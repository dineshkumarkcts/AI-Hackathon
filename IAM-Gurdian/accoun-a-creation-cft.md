Account A is much simpler — only one IAM role with a trust policy and an inline permissions policy. Let me build the CFT now.Zero errors, zero warnings. Clean pass.Here's the Account A CFT — passed cfn-lint with **zero errors and zero warnings**.

Account A is intentionally minimal. As the guide states: *no Lambda, no S3, no SNS — purely a passive data source.* The entire stack is one IAM role.

---

**Parameters to fill before uploading:**

| Parameter | What to fill |
|---|---|
| `AccountAId` | Your own 12-digit Account A ID |
| `AccountBId` | Sasi's Account B ID (12 digits) |
| `AccountBLambdaRoleArn` | From Account B stack Output → `LambdaRoleArn` |
| `ExternalId` | Keep default `IAMGuardianHackathon2024` unless you change it in Account B too |
| `CrossAccountRoleName` / `InlinePolicyName` | Optional — keep defaults |

---

**What gets created:**
- One IAM Role: `IAMGuardianReadOnlyRole`
  - **Trust policy** — locked to Account B's specific Lambda role ARN + `ExternalId` condition (confused-deputy protection)
  - **Inline policy** — least-privilege, covers only the 15 IAM read actions the Lambda actually needs (roles, users, groups, policies) plus `sts:GetCallerIdentity`

---

**After stack creation — share these 3 Outputs with Sasi (Account B):**
1. `CrossAccountRoleArn` → goes into SSM `/iam-guardian/account_a_role_arn`
2. `AccountAId` → goes into SSM `/iam-guardian/account_a_id`
3. `ExternalIdValue` → Sasi adds `ExternalId="IAMGuardianHackathon2024"` to the Lambda's `sts.assume_role()` call
