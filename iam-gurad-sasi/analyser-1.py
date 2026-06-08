"""
IAM Guardian - AI Analysis Agent
Uses Claude to classify IAM policies as RED / AMBER / GREEN
Supports parallel batch analysis with rate-limit-aware retry.
"""

import json
import os
import asyncio
import anthropic
from dotenv import load_dotenv

load_dotenv()

async_client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
sync_client  = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── Concurrency config ─────────────────────────────────────────────
# 50 RPM limit → safe to run 10 truly concurrent calls with retries.
# Raise BATCH_SIZE only after upgrading your Anthropic billing tier.
BATCH_SIZE   = 10   # concurrent in-flight Claude calls
MAX_RETRIES  = 5    # retry attempts on 429
RETRY_DELAY  = 12   # seconds to wait after a 429 (60s / 5 calls buffer)

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
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())
    result["original"] = policy
    return result


def _error_result(policy: dict, reason: str) -> dict:
    return {
        "classification": "AMBER",
        "justification": f"{reason}. Manual review required.",
        "risk_factors": ["Automated analysis failed — review manually"],
        "suggested_policy": policy.get("document", {}),
        "original": policy,
    }


# ── Async single-policy analysis with retry ────────────────────────

async def _analyse_policy_async(
    policy: dict,
    semaphore: asyncio.Semaphore,
    index: int,
    total: int,
) -> dict:
    async with semaphore:
        name = policy.get("policy_name", "unknown")
        print(f"  [{index}/{total}] Analysing: {name}")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                message = await async_client.messages.create(
                    model="claude-sonnet-4-5",
                    max_tokens=1500,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": build_prompt(policy)}],
                )
                return _parse_response(message.content[0].text, policy)

            except anthropic.RateLimitError:
                if attempt < MAX_RETRIES:
                    wait = RETRY_DELAY * attempt   # 12s, 24s, 36s …
                    print(f"  [429] Rate limit hit for {name}. Waiting {wait}s (attempt {attempt}/{MAX_RETRIES})...")
                    await asyncio.sleep(wait)
                else:
                    print(f"  [429] Giving up on {name} after {MAX_RETRIES} attempts.")
                    return _error_result(policy, "Rate limit exceeded after retries")

            except json.JSONDecodeError as e:
                print(f"  JSON parse error for {name}: {e}")
                return _error_result(policy, "JSON parse error")

            except Exception as e:
                print(f"  Analysis error for {name}: {e}")
                return _error_result(policy, f"Analysis error: {str(e)}")


# ── Public API ─────────────────────────────────────────────────────

def analyse_policy(policy: dict) -> dict:
    """Synchronous single-policy analysis (backward compat)."""
    try:
        message = sync_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(policy)}],
        )
        return _parse_response(message.content[0].text, policy)
    except Exception as e:
        print(f"Analysis error for policy {policy.get('policy_name')}: {e}")
        return _error_result(policy, f"Analysis error: {str(e)}")


def analyse_all_policies(policies: list, batch_size: int = BATCH_SIZE) -> list:
    """
    Analyse all policies in parallel with rate-limit-safe retries.

    With 50 RPM limit and batch_size=10:
      - 60 IAMs → ~6 rounds of 10 concurrent calls
      - 429s are caught and retried with backoff automatically
      - Expected total time: ~60-90 seconds vs ~3 minutes sequential
    """
    total = len(policies)
    print(f"Analysing {total} policies (batch_size={batch_size}, max_retries={MAX_RETRIES})...")

    async def run_all():
        semaphore = asyncio.Semaphore(batch_size)
        tasks = [
            _analyse_policy_async(policy, semaphore, i + 1, total)
            for i, policy in enumerate(policies)
        ]
        return await asyncio.gather(*tasks)

    results = asyncio.run(run_all())

    red   = sum(1 for r in results if r["classification"] == "RED")
    amber = sum(1 for r in results if r["classification"] == "AMBER")
    green = sum(1 for r in results if r["classification"] == "GREEN")
    print(f"Analysis complete: {red} RED, {amber} AMBER, {green} GREEN")

    return list(results)
