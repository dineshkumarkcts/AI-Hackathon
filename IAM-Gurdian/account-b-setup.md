# IAM Guardian — Account B (Sasi) Complete Setup Guide
# Based on architecture: Account B = "Automation runs here"
# Account B owns: Lambda · STS temp credentials · S3 storage · Policy analyser · Findings & alerts

==========================================================
WHAT ACCOUNT B DOES (from your diagram)
==========================================================

1. IAM Guardian Lambda         → calls sts:AssumeRole into Account A
2. STS temporary credentials   → short-lived access key, secret, token
3. S3 / storage                → stores JSON dumps per role, versioned
4. Policy analyser engine      → detect *, wildcards, privilege escalation
5. Findings & alerts           → Security Hub / SNS / S3 report

==========================================================
PRE-REQUISITES (get these from Dinesh first)
==========================================================

Before starting Account B setup, you need from Account A (Dinesh):
  - Account A ID  (12-digit, e.g. 111122223333)
  - ARN of the ReadOnly cross-account role in Account A
    e.g. arn:aws:iam::111122223333:role/IAMGuardianReadOnlyRole

==========================================================
STEP 1 — CREATE THE LAMBDA EXECUTION ROLE (Account B)
==========================================================

This is the IAM role that the Lambda function will use.

1. AWS Console → IAM → Roles → Create role
2. Trusted entity type: AWS Service → Lambda
3. Role name: IAMGuardianLambdaRole
4. Skip managed policies for now → Create role
5. Open the role → Add permissions → Create inline policy → JSON tab

Paste this policy (replace ACCOUNT_A_ID with Dinesh's account ID):

{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AssumeRoleInAccountA",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::ACCOUNT_A_ID:role/IAMGuardianReadOnlyRole"
    },
    {
      "Sid": "WriteToS3",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::iam-guardian-data-ACCOUNT_B_ID",
        "arn:aws:s3:::iam-guardian-data-ACCOUNT_B_ID/*"
      ]
    },
    {
      "Sid": "PublishSNS",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "arn:aws:sns:us-east-1:ACCOUNT_B_ID:IAMGuardianAlerts"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    },
    {
      "Sid": "ReadSSMParams",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParametersByPath"
      ],
      "Resource": "arn:aws:ssm:*:*:parameter/iam-guardian/*"
    }
  ]
}

6. Name the policy: IAMGuardianLambdaPolicy → Create policy
7. Note the role ARN — you'll need it when creating the Lambda

==========================================================
STEP 2 — CREATE S3 BUCKET FOR IAM DATA STORAGE
==========================================================

1. AWS Console → S3 → Create bucket
2. Bucket name: iam-guardian-data-[YOUR_ACCOUNT_B_ID]
   (e.g. iam-guardian-data-444455556666)
   NOTE: bucket names must be globally unique

3. Region: us-east-1  (or your preferred region — keep consistent)
4. Block all public access: ON (keep this checked)
5. Versioning: ENABLE  (matches "versioned" in your diagram)
6. Encryption: SSE-S3 (default)
7. Create bucket

Bucket structure that Lambda will write to:
  iam-guardian-data-[id]/
  ├── scans/
  │   └── [ACCOUNT_A_ID]/
  │       └── [timestamp]/
  │           ├── roles.json
  │           ├── managed_policies.json
  │           └── findings.json
  └── reports/
      └── [timestamp]-report.json

==========================================================
STEP 3 — CREATE SNS TOPIC FOR ALERTS
==========================================================

1. AWS Console → SNS → Topics → Create topic
2. Type: Standard
3. Name: IAMGuardianAlerts
4. Create topic
5. Note the Topic ARN (e.g. arn:aws:sns:us-east-1:444455556666:IAMGuardianAlerts)

Subscribe your email:
6. Click the topic → Create subscription
7. Protocol: Email
8. Endpoint: [your email address]
9. Create subscription
10. Check your email and click "Confirm subscription"

==========================================================
STEP 4 — STORE CONFIG IN SSM PARAMETER STORE
==========================================================

This avoids hardcoding Account A's details in Lambda code.

AWS Console → Systems Manager → Parameter Store → Create parameter

Create these 4 parameters:

  Name:  /iam-guardian/account_a_id
  Type:  String
  Value: [Dinesh's 12-digit account ID]

  Name:  /iam-guardian/account_a_role_arn
  Type:  String
  Value: arn:aws:iam::[ACCOUNT_A_ID]:role/IAMGuardianReadOnlyRole

  Name:  /iam-guardian/s3_bucket
  Type:  String
  Value: iam-guardian-data-[YOUR_ACCOUNT_B_ID]

  Name:  /iam-guardian/sns_topic_arn
  Type:  String
  Value: arn:aws:sns:us-east-1:[ACCOUNT_B_ID]:IAMGuardianAlerts

==========================================================
STEP 5 — CREATE THE LAMBDA FUNCTION
==========================================================

--- 5a. Create the function ---

1. AWS Console → Lambda → Create function
2. Author from scratch
3. Function name: IAMGuardianLambda
4. Runtime: Python 3.12
5. Architecture: x86_64
6. Execution role: Use existing role → IAMGuardianLambdaRole
7. Create function

--- 5b. Configure settings ---

After creation, go to Configuration tab:
  General configuration:
    Memory: 512 MB
    Timeout: 5 minutes (300 seconds)
    (IAM API calls across accounts can be slow for large environments)

--- 5c. Paste the Lambda code ---

In the Code tab, replace the default code with this:

```python
"""
IAM Guardian Lambda — Account B
Assumes role into Account A, collects IAM data,
analyses for risks, stores in S3, publishes findings to SNS.
"""
import json
import boto3
import os
from datetime import datetime, timezone

def lambda_handler(event, context):
    region = os.environ.get("AWS_REGION", "us-east-1")
    ssm = boto3.client("ssm", region_name=region)

    # Load config from SSM
    def get_param(name):
        return ssm.get_parameter(Name=name)["Parameter"]["Value"]

    account_a_id   = get_param("/iam-guardian/account_a_id")
    role_arn       = get_param("/iam-guardian/account_a_role_arn")
    s3_bucket      = get_param("/iam-guardian/s3_bucket")
    sns_topic_arn  = get_param("/iam-guardian/sns_topic_arn")

    # ── STEP 1: Assume role into Account A ──────────────────
    print(f"Assuming role: {role_arn}")
    sts = boto3.client("sts", region_name=region)
    assumed = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName="IAMGuardianSession",
        DurationSeconds=900  # 15 min — enough to collect all policies
    )
    creds = assumed["Credentials"]
    print(f"STS credentials obtained, expire: {creds['Expiration']}")

    # ── STEP 2: Build IAM client using temp credentials ─────
    iam = boto3.client(
        "iam",
        region_name=region,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"]
    )

    # ── STEP 3: Collect IAM data from Account A ─────────────
    print("Collecting IAM data from Account A...")
    roles = collect_roles(iam)
    managed_policies = collect_managed_policies(iam)
    print(f"Collected {len(roles)} roles, {len(managed_policies)} managed policies")

    # ── STEP 4: Analyse for risks ────────────────────────────
    print("Analysing policies for risks...")
    findings = analyse_policies(roles, managed_policies)
    print(f"Found {len(findings)} risk findings")

    # ── STEP 5: Store in S3 (versioned JSON dumps) ───────────
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base_key = f"scans/{account_a_id}/{timestamp}"

    s3 = boto3.client("s3", region_name=region)
    s3.put_object(
        Bucket=s3_bucket,
        Key=f"{base_key}/roles.json",
        Body=json.dumps(roles, indent=2, default=str),
        ContentType="application/json"
    )
    s3.put_object(
        Bucket=s3_bucket,
        Key=f"{base_key}/managed_policies.json",
        Body=json.dumps(managed_policies, indent=2, default=str),
        ContentType="application/json"
    )
    s3.put_object(
        Bucket=s3_bucket,
        Key=f"{base_key}/findings.json",
        Body=json.dumps(findings, indent=2, default=str),
        ContentType="application/json"
    )
    print(f"Stored results in s3://{s3_bucket}/{base_key}/")

    # ── STEP 6: Publish critical findings to SNS ─────────────
    red_findings = [f for f in findings if f["risk_level"] == "red"]
    if red_findings:
        sns = boto3.client("sns", region_name=region)
        message = format_sns_message(account_a_id, red_findings, s3_bucket, base_key)
        sns.publish(
            TopicArn=sns_topic_arn,
            Subject=f"IAM Guardian ALERT: {len(red_findings)} Critical findings in {account_a_id}",
            Message=message
        )
        print(f"Published {len(red_findings)} critical findings to SNS")

    # ── Summary ───────────────────────────────────────────────
    summary = {
        "red":   len([f for f in findings if f["risk_level"] == "red"]),
        "amber": len([f for f in findings if f["risk_level"] == "amber"]),
        "green": len([f for f in findings if f["risk_level"] == "green"]),
    }
    return {
        "statusCode": 200,
        "account_a_id": account_a_id,
        "timestamp": timestamp,
        "policies_scanned": len(roles) + len(managed_policies),
        "findings": len(findings),
        "summary": summary,
        "s3_path": f"s3://{s3_bucket}/{base_key}/"
    }


def collect_roles(iam):
    """Collect all roles with their inline and attached managed policies"""
    roles = []
    paginator = iam.get_paginator("list_roles")
    for page in paginator.paginate():
        for role in page["Roles"]:
            role_data = {
                "RoleName": role["RoleName"],
                "RoleId": role["RoleId"],
                "Arn": role["Arn"],
                "CreateDate": role["CreateDate"].isoformat(),
                "AssumeRolePolicyDocument": role.get("AssumeRolePolicyDocument", {}),
                "InlinePolicies": [],
                "AttachedManagedPolicies": []
            }

            # Inline policies
            try:
                inline = iam.list_role_policies(RoleName=role["RoleName"])
                for policy_name in inline.get("PolicyNames", []):
                    doc = iam.get_role_policy(
                        RoleName=role["RoleName"],
                        PolicyName=policy_name
                    )
                    role_data["InlinePolicies"].append({
                        "PolicyName": policy_name,
                        "Document": doc["PolicyDocument"]
                    })
            except Exception as e:
                print(f"Error fetching inline policies for {role['RoleName']}: {e}")

            # Attached managed policies
            try:
                attached = iam.list_attached_role_policies(RoleName=role["RoleName"])
                role_data["AttachedManagedPolicies"] = [
                    {"PolicyName": p["PolicyName"], "PolicyArn": p["PolicyArn"]}
                    for p in attached.get("AttachedPolicies", [])
                ]
            except Exception as e:
                print(f"Error fetching attached policies for {role['RoleName']}: {e}")

            roles.append(role_data)
    return roles


def collect_managed_policies(iam):
    """Collect all customer-managed policies with their documents"""
    policies = []
    paginator = iam.get_paginator("list_policies")
    for page in paginator.paginate(Scope="Local"):
        for policy in page["Policies"]:
            policy_data = {
                "PolicyName": policy["PolicyName"],
                "PolicyId": policy["PolicyId"],
                "Arn": policy["Arn"],
                "AttachmentCount": policy["AttachmentCount"],
                "CreateDate": policy["CreateDate"].isoformat(),
                "UpdateDate": policy.get("UpdateDate", policy["CreateDate"]).isoformat(),
                "Document": None
            }
            try:
                version = iam.get_policy_version(
                    PolicyArn=policy["Arn"],
                    VersionId=policy.get("DefaultVersionId", "v1")
                )
                policy_data["Document"] = version["PolicyVersion"]["Document"]
            except Exception as e:
                print(f"Error fetching policy version for {policy['PolicyName']}: {e}")
            policies.append(policy_data)
    return policies


def analyse_policies(roles, managed_policies):
    """
    Rule-based policy analyser — detects wildcards, privilege escalation,
    orphaned roles, missing conditions.
    Mirrors what your diagram calls: detect *, wildcards, privilege escalation
    """
    findings = []

    # Analyse managed policies
    for policy in managed_policies:
        doc = policy.get("Document") or {}
        statements = doc.get("Statement", [])
        if isinstance(statements, dict):
            statements = [statements]

        risks, risk_level, score = check_statements(statements)

        # Extra check: orphaned policy (no attachments)
        if policy.get("AttachmentCount", 0) == 0:
            risks.append("Policy has zero attachments — orphaned, increases attack surface")
            if risk_level == "green":
                risk_level = "amber"
                score = max(score, 4)

        findings.append({
            "resource_type": "ManagedPolicy",
            "resource_name": policy["PolicyName"],
            "resource_arn": policy["Arn"],
            "risk_level": risk_level,
            "risk_score": score,
            "risks": risks,
            "attachment_count": policy.get("AttachmentCount", 0)
        })

    # Analyse role inline policies
    for role in roles:
        for inline in role.get("InlinePolicies", []):
            doc = inline.get("Document") or {}
            statements = doc.get("Statement", [])
            if isinstance(statements, dict):
                statements = [statements]

            risks, risk_level, score = check_statements(statements)

            findings.append({
                "resource_type": "InlinePolicy",
                "resource_name": f"{role['RoleName']} → {inline['PolicyName']}",
                "resource_arn": role["Arn"],
                "risk_level": risk_level,
                "risk_score": score,
                "risks": risks
            })

        # Check trust policy for overly broad trust
        trust = role.get("AssumeRolePolicyDocument", {})
        trust_risks = check_trust_policy(trust, role["RoleName"])
        if trust_risks:
            findings.append({
                "resource_type": "TrustPolicy",
                "resource_name": f"{role['RoleName']} (trust policy)",
                "resource_arn": role["Arn"],
                "risk_level": "red",
                "risk_score": 8,
                "risks": trust_risks
            })

    return findings


def check_statements(statements):
    """Evaluate a list of policy statements for risk patterns"""
    risks = []
    risk_level = "green"
    score = 1

    for stmt in statements:
        if not isinstance(stmt, dict):
            continue
        if stmt.get("Effect") != "Allow":
            continue

        actions = stmt.get("Action", [])
        resources = stmt.get("Resource", [])
        conditions = stmt.get("Condition", {})

        if isinstance(actions, str):
            actions = [actions]
        if isinstance(resources, str):
            resources = [resources]

        # RED: Full wildcard
        if "*" in actions and "*" in resources:
            risks.append("CRITICAL: Action=* with Resource=* — grants full admin access to everything")
            risk_level = "red"
            score = max(score, 10)

        # RED: Action wildcard on all resources
        elif "*" in actions:
            risks.append("CRITICAL: Action=* allows any action (wildcard). Scope to specific actions.")
            risk_level = "red"
            score = max(score, 9)

        # RED: Resource wildcard with sensitive services
        elif "*" in resources:
            sensitive = [a for a in actions if any(
                svc in a.lower() for svc in ["iam:", "sts:", "kms:", "secretsmanager:", "s3:", "ec2:"]
            )]
            if sensitive:
                risks.append(f"HIGH: Resource=* with sensitive actions: {', '.join(sensitive[:3])}")
                risk_level = "red"
                score = max(score, 8)
            else:
                risks.append("MODERATE: Resource=* — scope to specific ARNs")
                if risk_level == "green":
                    risk_level = "amber"
                score = max(score, 5)

        # AMBER: Service-level wildcards (e.g. s3:*)
        service_wildcards = [a for a in actions if a.endswith(":*")]
        if service_wildcards:
            risks.append(f"MODERATE: Service-level wildcards found: {', '.join(service_wildcards[:3])}")
            if risk_level == "green":
                risk_level = "amber"
            score = max(score, 5)

        # AMBER: Privilege escalation actions
        escalation_actions = [
            "iam:CreateAccessKey", "iam:CreateLoginProfile", "iam:UpdateLoginProfile",
            "iam:AttachUserPolicy", "iam:AttachRolePolicy", "iam:PutUserPolicy",
            "iam:PutRolePolicy", "iam:CreatePolicy", "iam:SetDefaultPolicyVersion",
            "sts:AssumeRole", "iam:PassRole", "iam:CreateRole"
        ]
        found_escalation = [a for a in actions if a in escalation_actions]
        if found_escalation:
            risks.append(f"MODERATE: Privilege escalation actions present: {', '.join(found_escalation[:3])}")
            if risk_level == "green":
                risk_level = "amber"
            score = max(score, 6)

        # AMBER: No MFA condition for human-facing actions
        if not conditions and any("iam:" in a or "sts:" in a for a in actions):
            risks.append("LOW: No MFA condition on IAM/STS actions. Add aws:MultiFactorAuthPresent condition.")
            if risk_level == "green":
                risk_level = "amber"
            score = max(score, 4)

    if not risks:
        risks.append("No significant risks detected in policy statements")

    return risks, risk_level, score


def check_trust_policy(trust_doc, role_name):
    """Check AssumeRolePolicyDocument for overly broad trust"""
    risks = []
    statements = trust_doc.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]

    for stmt in statements:
        if not isinstance(stmt, dict):
            continue
        principal = stmt.get("Principal", {})

        # Trust everyone (*)
        if principal == "*" or (isinstance(principal, dict) and principal.get("AWS") == "*"):
            risks.append(f"CRITICAL: Role {role_name} trusts ALL AWS principals (*). Extremely dangerous.")

        # Trust all of an account without conditions
        if isinstance(principal, dict):
            aws_principals = principal.get("AWS", [])
            if isinstance(aws_principals, str):
                aws_principals = [aws_principals]
            for p in aws_principals:
                if p.endswith(":root") and not stmt.get("Condition"):
                    risks.append(f"HIGH: Trust allows entire account root ({p}) without conditions.")

    return risks


def format_sns_message(account_id, red_findings, s3_bucket, s3_prefix):
    """Format a readable SNS alert message"""
    lines = [
        "=" * 60,
        "IAM GUARDIAN — CRITICAL FINDINGS ALERT",
        "=" * 60,
        f"Account scanned : {account_id}",
        f"Critical findings: {len(red_findings)}",
        f"S3 report        : s3://{s3_bucket}/{s3_prefix}/findings.json",
        "",
        "CRITICAL POLICIES:",
        "-" * 40
    ]
    for i, f in enumerate(red_findings[:10], 1):  # Max 10 in SMS
        lines.append(f"{i}. {f['resource_name']}")
        lines.append(f"   ARN: {f['resource_arn']}")
        lines.append(f"   Risk: {f['risks'][0] if f['risks'] else 'N/A'}")
        lines.append("")
    lines += [
        "-" * 40,
        "Login to AWS Console and review immediately.",
        "IAM Guardian | Amex GBT AI Hackathon 2024"
    ]
    return "\n".join(lines)
```

8. Click Deploy to save the code

==========================================================
STEP 6 — SET ENVIRONMENT VARIABLE IN LAMBDA
==========================================================

Lambda console → Configuration → Environment variables → Edit

Add:
  Key:   AWS_DEFAULT_REGION
  Value: us-east-1

Save

==========================================================
STEP 7 — TEST THE LAMBDA MANUALLY
==========================================================

1. Lambda console → Test tab
2. Event name: TestScan
3. Event JSON: {}  (Lambda reads config from SSM, no input needed)
4. Click Test

Expected output:
{
  "statusCode": 200,
  "account_a_id": "111122223333",
  "timestamp": "20240522-143021",
  "policies_scanned": 47,
  "findings": 12,
  "summary": { "red": 3, "amber": 6, "green": 3 },
  "s3_path": "s3://iam-guardian-data-444455556666/scans/..."
}

If you see "AccessDenied on sts:AssumeRole":
  → Dinesh has not yet added the trust relationship in Account A (Step 8 below)

If you see "AccessDenied on ssm:GetParameter":
  → Lambda role is missing SSM permissions (re-check Step 1)

If you see "AccessDenied on s3:PutObject":
  → Bucket name in SSM doesn't match actual bucket name

==========================================================
STEP 8 — TELL DINESH WHAT TO DO IN ACCOUNT A
==========================================================

For sts:AssumeRole to work, Dinesh must create this role in Account A:

Role name: IAMGuardianReadOnlyRole
Trusted entity (trust policy):
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::[ACCOUNT_B_ID]:role/IAMGuardianLambdaRole"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}

Permissions policy (attach to the role):
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "iam:ListPolicies",
        "iam:GetPolicy",
        "iam:GetPolicyVersion",
        "iam:ListRoles",
        "iam:ListRolePolicies",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "sts:GetCallerIdentity",
      "Resource": "*"
    }
  ]
}

Once Dinesh creates this role, re-run the Lambda test in Step 7.

==========================================================
STEP 9 — SCHEDULE AUTOMATED SCANS WITH EVENTBRIDGE
==========================================================

1. AWS Console → EventBridge → Rules → Create rule
2. Name: IAMGuardianDailySchedule
3. Rule type: Schedule
4. Schedule pattern: Cron expression
   Cron: 0 8 * * ? *   (runs every day at 8 AM UTC)
5. Target: Lambda function → IAMGuardianLambda
6. Create rule

For hackathon demo — use a 5-minute schedule to show it working live:
   Rate expression: rate(5 minutes)
   (Remember to delete/disable this after the demo!)

==========================================================
STEP 10 — VERIFY FINDINGS IN S3 + EMAIL ALERTS
==========================================================

After a successful Lambda run:

1. S3 console → iam-guardian-data-[ACCOUNT_B_ID] → scans/
   You should see folders like: scans/111122223333/20240522-143021/
   Download findings.json — it contains all risk findings with RAG levels

2. Check your email for SNS alerts
   (only sent if red findings exist)

3. View Lambda logs:
   CloudWatch → Log groups → /aws/lambda/IAMGuardianLambda
   Filter by "Found" to see finding counts per run

==========================================================
QUICK REFERENCE — RESOURCES CREATED IN ACCOUNT B
==========================================================

IAM Role      : IAMGuardianLambdaRole
Lambda        : IAMGuardianLambda  (Python 3.12, 512MB, 5min timeout)
S3 Bucket     : iam-guardian-data-[ACCOUNT_B_ID]  (versioned, private)
SNS Topic     : IAMGuardianAlerts  (email subscription)
SSM Params    : /iam-guardian/account_a_id
                /iam-guardian/account_a_role_arn
                /iam-guardian/s3_bucket
                /iam-guardian/sns_topic_arn
EventBridge   : IAMGuardianDailySchedule

==========================================================
ESTIMATED TIME TO COMPLETE
==========================================================

Step 1  Create Lambda execution role    :  5 min
Step 2  Create S3 bucket               :  3 min
Step 3  Create SNS topic + subscribe   :  3 min
Step 4  Store SSM parameters           :  5 min
Step 5  Create Lambda + paste code     : 10 min
Step 6  Set env variable               :  1 min
Step 7  Test Lambda                    :  5 min
Step 8  Coordinate with Dinesh (Acct A):  5 min
Step 9  EventBridge schedule           :  3 min
Step 10 Verify outputs                 :  5 min

TOTAL                                  : ~45 minutes
