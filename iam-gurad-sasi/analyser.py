"""
IAM Guardian - AI Analysis Agent
Uses Claude to classify IAM policies as RED / AMBER / GREEN
Supports parallel batch analysis for large policy sets.
"""

import json
import os
import asyncio
import anthropic
from dotenv import load_dotenv

load_dotenv()

# Async client for concurrent requests
async_client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Sync client kept for any legacy direct calls
sync_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── Concurrency config ─────────────────────────────────────────────
# Anthropic default rate limit is ~50 RPM on claude-sonnet-4-5.
# BATCH_SIZE controls how many Claude calls fire simultaneously.
# Keep at 20 to stay safe; raise if you have a higher tier.
BATCH_SIZE = 20

SYSTEM_PROMPT = """You are a senior AWS cloud security expert specialising in IAM policy analysis.
Your job is to analyse AWS IAM policies and classify them by security risk.
Always respond with valid JSON only. No markdown, no explanation outside the JSON."""


def build_prompt(policy: dict) -> str:
    return f"""Analyse this AWS IAM policy and respond ONLY with a valid JSON object.

Policy details:
{json.dumps(policy, indent=2, default=str)}

Classification rules:
- RED   = Critical risk. Has wildcard Action (*) or Resource (*), dormant role unused for 90+ days 
          with broad permissions, or allows privilege escalation
- AMBER = Moderate risk. Broad service-level permissions (e.g. s3:* or ec2:*), unused for 30-90 days,
          missing MFA conditions on sensitive actions, overly permissive resource scope
- GREEN = Low risk. Scoped to specific resource ARNs, actively used within 30 days, 
          follows least-privilege principle

Respond with ONLY this JSON structure:
{{
  "classification": "RED",
  "justification": "Clear 2-3 sentence explanation of why this risk level was assigned",
  "risk_factors": [
    "Specific issue 1 found in this policy",
    "Specific issue 2 found in this policy"
  ],
  "suggested_policy": {{
    "Version": "2012-10-17",
    "Statement": [
      {{
        "Effect": "Allow",
        "Action": ["specific:action1", "specific:action2"],
        "Resource": "arn:aws:service:region:account:specific-resource"
      }}
    ]
  }}
}}"""


def _parse_response(raw: str, policy: dict) -> dict:
    """Strip markdown fences and parse Claude's JSON response."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())
    result["original"] = policy
    return result


# ── Async single-policy analysis ───────────────────────────────────

async def _analyse_policy_async(policy: dict, semaphore: asyncio.Semaphore, index: int, total: int) -> dict:
    """Analyse a single policy asynchronously, respecting the semaphore limit."""
    async with semaphore:
        print(f"  [{index}/{total}] Analysing: {policy.get('policy_name', 'unknown')}")
        try:
            message = await async_client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1500,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_prompt(policy)}],
            )
            return _parse_response(message.content[0].text, policy)

        except json.JSONDecodeError as e:
            print(f"  JSON parse error for {policy.get('policy_name')}: {e}")
            return {
                "classification": "AMBER",
                "justification": "Policy could not be automatically analysed. Manual review required.",
                "risk_factors": ["Automated analysis failed — review manually"],
                "suggested_policy": policy.get("document", {}),
                "original": policy,
            }
        except Exception as e:
            print(f"  Analysis error for {policy.get('policy_name')}: {e}")
            return {
                "classification": "AMBER",
                "justification": f"Analysis error: {str(e)}. Manual review required.",
                "risk_factors": ["Automated analysis error"],
                "suggested_policy": policy.get("document", {}),
                "original": policy,
            }


# ── Public API ─────────────────────────────────────────────────────

def analyse_policy(policy: dict) -> dict:
    """Synchronous single-policy analysis (kept for backward compatibility)."""
    try:
        message = sync_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(policy)}],
        )
        return _parse_response(message.content[0].text, policy)
    except json.JSONDecodeError as e:
        print(f"JSON parse error for policy {policy.get('policy_name')}: {e}")
        return {
            "classification": "AMBER",
            "justification": "Policy could not be automatically analysed. Manual review required.",
            "risk_factors": ["Automated analysis failed — review manually"],
            "suggested_policy": policy.get("document", {}),
            "original": policy,
        }
    except Exception as e:
        print(f"Analysis error for policy {policy.get('policy_name')}: {e}")
        return {
            "classification": "AMBER",
            "justification": f"Analysis error: {str(e)}. Manual review required.",
            "risk_factors": ["Automated analysis error"],
            "suggested_policy": policy.get("document", {}),
            "original": policy,
        }


def analyse_all_policies(policies: list, batch_size: int = BATCH_SIZE) -> list:
    """
    Analyse all policies in parallel batches.

    - Up to `batch_size` Claude API calls fire simultaneously.
    - Results are returned in the same order as the input list.
    - For 60 IAMs with batch_size=20: 3 rounds instead of 60 sequential calls.
    """
    total = len(policies)
    print(f"Analysing {total} policies (parallel batch_size={batch_size})...")

    async def run_all():
        semaphore = asyncio.Semaphore(batch_size)
        tasks = [
            _analyse_policy_async(policy, semaphore, i + 1, total)
            for i, policy in enumerate(policies)
        ]
        # gather preserves order and runs up to `batch_size` concurrently
        return await asyncio.gather(*tasks)

    results = asyncio.run(run_all())

    red   = sum(1 for r in results if r["classification"] == "RED")
    amber = sum(1 for r in results if r["classification"] == "AMBER")
    green = sum(1 for r in results if r["classification"] == "GREEN")
    print(f"Analysis complete: {red} RED, {amber} AMBER, {green} GREEN")

    return list(results)
