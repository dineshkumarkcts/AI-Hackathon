10 steps for Account B — estimated 45 minutes total
Step 1 — IAM Lambda Execution Role (IAMGuardianLambdaRole)
Give it permissions to: sts:AssumeRole into Account A, write to S3, publish to SNS, read SSM params, write CloudWatch logs.
Step 2 — S3 Bucket (iam-guardian-data-[your-account-id])
Enable versioning — matches the "JSON dumps per role, versioned" box in your diagram. Private, SSE-S3 encrypted.
Step 3 — SNS Topic (IAMGuardianAlerts)
Subscribe your email. SNS only fires when RED findings are detected.
Step 4 — SSM Parameters
Store Account A's ID and role ARN here so nothing is hardcoded in Lambda.
Step 5 — Lambda Function (IAMGuardianLambda, Python 3.12, 512MB, 5min timeout)
The full code is in the guide — it handles all 4 boxes from your diagram in one function: assume role → collect IAM → analyse → store → alert.
Step 6–7 — Configure & Test
One test run to verify the sts:AssumeRole handshake with Dinesh's account works.
Step 8 — Coordinate with Dinesh
He needs to create IAMGuardianReadOnlyRole in Account A with a trust policy that allows your Lambda role ARN to assume it. The exact JSON is in the guide to hand to him.
Step 9 — EventBridge Schedule
Daily at 8AM UTC normally. Use rate(5 minutes) for the live hackathon demo.
Step 10 — Verify
Check S3 for findings.json and your email for SNS alerts on red findings.
