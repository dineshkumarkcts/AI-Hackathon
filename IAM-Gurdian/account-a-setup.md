# IAM Guardian — Account A (Dinesh) Complete Setup Guide
# Based on architecture: Account A = "IAM roles & policies live here"
# Account A owns: ReadOnly cross-account role · AWS IAM API · IAM data collected

==========================================================
WHAT ACCOUNT A DOES (from your diagram)
==========================================================

1. ReadOnly cross-account role   → Trusted by Account B (Sasi's Lambda)
2. AWS IAM API                   → list_roles, list_policies, get_policy_version
3. IAM data collected            → Roles, inline + managed policies, trust docs

Account A does NOT run any compute (no Lambda, no EC2 for this flow).
It simply exposes a cross-account role that Account B's Lambda assumes
via sts:AssumeRole to read IAM data.

==========================================================
PRE-REQUISITES (get these from Sasi first)
==========================================================

Before starting, get from Account B (Sasi):
  - Account B ID   (12-digit, e.g. 444455556666)
  - Lambda role ARN from Account B
    e.g. arn:aws:iam::444455556666:role/IAMGuardianLambdaRole

You need these to write the trust policy in Step 1.

==========================================================
STEP 1 — CREATE THE READONLY CROSS-ACCOUNT ROLE
==========================================================

This is THE critical step for Account A.
This role is what Account B's Lambda assumes via sts:AssumeRole.

--- 1a. Go to IAM ---

AWS Console → IAM → Roles → Create role

--- 1b. Set trusted entity ---

1. Trusted entity type: AWS account
2. Select: Another AWS account
3. Account ID: [Sasi's Account B ID, e.g. 444455556666]
4. Do NOT check "Require MFA" for now (Lambda can't provide MFA)
5. Click Next

--- 1c. Attach permissions ---

6. Search and select: ReadOnlyAccess  (AWS managed policy)
   NOTE: This is broader than needed. Replace it in Step 1e below
         with a least-privilege inline policy instead.
7. Click Next

--- 1d. Name and create ---

8. Role name: IAMGuardianReadOnlyRole
9. Description: Allows IAM Guardian Lambda in Account B to read IAM policies
10. Create role

--- 1e. IMPORTANT — Replace ReadOnlyAccess with least-privilege policy ---

The AWS ReadOnlyAccess managed policy is too broad for production.
Replace it with a tight inline policy:

1. Open the role: IAMGuardianReadOnlyRole
2. Permissions tab → Add permissions → Create inline policy → JSON tab
3. Paste this policy:

{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "IAMReadOnly",
      "Effect": "Allow",
      "Action": [
        "iam:ListPolicies",
        "iam:GetPolicy",
        "iam:GetPolicyVersion",
        "iam:ListPolicyVersions",
        "iam:ListRoles",
        "iam:GetRole",
        "iam:ListRolePolicies",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:ListUsers",
        "iam:GetUser",
        "iam:ListUserPolicies",
        "iam:GetUserPolicy",
        "iam:ListAttachedUserPolicies",
        "iam:ListGroups",
        "iam:GetGroup",
        "iam:ListGroupPolicies",
        "iam:GetGroupPolicy",
        "iam:ListAttachedGroupPolicies"
      ],
      "Resource": "*"
    },
    {
      "Sid": "STSCallerIdentity",
      "Effect": "Allow",
      "Action": "sts:GetCallerIdentity",
      "Resource": "*"
    }
  ]
}

4. Policy name: IAMGuardianReadPolicy
5. Create policy

6. NOW remove the broad ReadOnlyAccess managed policy:
   Permissions tab → ReadOnlyAccess → Remove → Confirm

--- 1f. Tighten the trust policy ---

The default trust policy created in step 1b trusts the entire Account B.
Tighten it so ONLY Sasi's specific Lambda role can assume it:

1. Open role: IAMGuardianReadOnlyRole
2. Trust relationships tab → Edit trust policy
3. Replace the entire JSON with this
   (replace ACCOUNT_B_ID with Sasi's actual account ID):

{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowIAMGuardianLambda",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::ACCOUNT_B_ID:role/IAMGuardianLambdaRole"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "IAMGuardianHackathon2024"
        }
      }
    }
  ]
}

4. Update policy

IMPORTANT: Note the ExternalId value "IAMGuardianHackathon2024"
           You must tell Sasi to add this same ExternalId in the
           Lambda's sts.assume_role() call. This prevents
           confused deputy attacks.

--- 1g. Note the Role ARN ---

After creating, copy the Role ARN from the role summary page.
It looks like: arn:aws:iam::111122223333:role/IAMGuardianReadOnlyRole

Send this ARN to Sasi so she can put it in SSM Parameter Store.

==========================================================
STEP 2 — VERIFY THE ROLE WORKS (OPTIONAL BUT RECOMMENDED)
==========================================================

Test that the trust relationship is correct before telling Sasi.
Run this from AWS CloudShell in Account A (no EC2 needed):

1. AWS Console → CloudShell (top right icon, looks like >_)

2. Run this command (replace with Sasi's Account B ID):

aws sts assume-role \
  --role-arn arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/IAMGuardianReadOnlyRole \
  --role-session-name TestSession \
  --external-id IAMGuardianHackathon2024

If successful, you'll see:
{
    "Credentials": {
        "AccessKeyId": "ASIA...",
        "SecretAccessKey": "...",
        "SessionToken": "...",
        "Expiration": "..."
    }
}

This confirms the role and trust policy are correctly configured.

3. Also verify IAM read access works using the temp credentials:

# Export the credentials from the output above
export AWS_ACCESS_KEY_ID=ASIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_SESSION_TOKEN=...

# Test IAM list
aws iam list-policies --scope Local --max-items 5

# Should return a list of your customer-managed policies
# If you see AccessDenied, re-check the inline policy in Step 1e

# Clear credentials when done
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

==========================================================
STEP 3 — UPDATE SASI'S LAMBDA WITH THE EXTERNALID
==========================================================

Because you added an ExternalId condition in Step 1f,
tell Sasi to update the assume_role call in her Lambda code.

Find this line in the Lambda:
    assumed = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName="IAMGuardianSession",
        DurationSeconds=900
    )

Change it to:
    assumed = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName="IAMGuardianSession",
        DurationSeconds=900,
        ExternalId="IAMGuardianHackathon2024"
    )

==========================================================
STEP 4 — WHAT TO SEND SASI (ACCOUNT B HANDOVER CHECKLIST)
==========================================================

Send Sasi all of the following:

  [ ] Account A ID       : [your 12-digit account ID]
  [ ] Role ARN           : arn:aws:iam::[ACCOUNT_A_ID]:role/IAMGuardianReadOnlyRole
  [ ] ExternalId         : IAMGuardianHackathon2024
  [ ] Region             : us-east-1  (or whichever region you used)

She needs to:
  1. Add the Role ARN to SSM: /iam-guardian/account_a_role_arn
  2. Add the ExternalId to her Lambda assume_role call
  3. Re-test the Lambda

==========================================================
STEP 5 — VERIFY END-TO-END FROM ACCOUNT A SIDE
==========================================================

After Sasi runs her Lambda test, verify from Account A:

1. Check CloudTrail to confirm the assume-role event was logged:

   AWS Console → CloudTrail → Event history
   Filter by: Event name = AssumeRole
   You should see an event from principal:
     arn:aws:iam::ACCOUNT_B_ID:role/IAMGuardianLambdaRole

2. This confirms Account B successfully assumed the role
   and Account A's IAM data was read.

==========================================================
QUICK REFERENCE — RESOURCES CREATED IN ACCOUNT A
==========================================================

IAM Role      : IAMGuardianReadOnlyRole
  Trust       : arn:aws:iam::ACCOUNT_B_ID:role/IAMGuardianLambdaRole
  ExternalId  : IAMGuardianHackathon2024
  Permissions : IAMGuardianReadPolicy (inline — least privilege IAM read)

That is ALL Account A needs. No Lambda, no EC2, no S3, no SNS.
Account A is purely a passive data source.

==========================================================
ESTIMATED TIME TO COMPLETE
==========================================================

Step 1a-d  Create role with trusted entity       :  5 min
Step 1e    Replace with least-privilege policy   :  5 min
Step 1f    Tighten trust policy with ExternalId  :  3 min
Step 1g    Note and share Role ARN with Sasi     :  1 min
Step 2     Verify role via CloudShell            :  5 min
Step 3     Tell Sasi to add ExternalId to Lambda :  2 min
Step 4     Send handover checklist to Sasi       :  2 min
Step 5     Verify CloudTrail after Sasi's test   :  3 min

TOTAL                                            : ~26 minutes

==========================================================
TROUBLESHOOTING
==========================================================

Problem: Sasi sees "AccessDenied" on sts:AssumeRole
  Fix 1: Check the trust policy Principal ARN matches her Lambda role ARN exactly
  Fix 2: Check ExternalId matches exactly (case-sensitive)
  Fix 3: Ensure the role was saved — re-open and confirm trust policy JSON

Problem: Sasi sees "AccessDenied" on iam:ListPolicies
  Fix: Verify Step 1e inline policy was saved and ReadOnlyAccess was removed
       Open the role → Permissions tab → confirm only IAMGuardianReadPolicy is listed

Problem: Trust policy shows entire account instead of specific role
  Fix: Redo Step 1f — the default trust policy after "Another AWS account"
       trusts the whole account root. You must manually replace it.

Problem: CloudTrail shows no AssumeRole events
  Fix: CloudTrail may take 15 minutes to show events. Also check
       you are looking at the correct region.
