Now let me fetch the `notifier.py` to understand the current SMTP implementation:I have enough from the README to give you a complete guide. Here's everything you need:

---

## Step 1 — Set Up AWS SES (Free Tier)

### 1.1 Verify your sender email address

1. Go to **AWS Console → Amazon SES → Verified identities**
2. Click **Create identity** → choose **Email address**
3. Enter the email you'll send *from* (e.g. `middleware-agent@yourdomain.com`)
4. AWS sends a verification link — click it

> **Free tier note:** In the SES *sandbox* (default), you can only send **to** verified emails too. Verify your admin email the same way. To send to anyone, you'd request production access, but for this monitoring project sandbox is fine.

### 1.2 Create an IAM user for SES sending

1. Go to **IAM → Users → Create user** (e.g. `ses-middleware-agent`)
2. Attach this inline policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ses:SendEmail",
      "Resource": "*"
    }
  ]
}
```

3. Go to the user → **Security credentials → Create access key** → choose **Application running outside AWS**
4. Save the `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`

> If you're running on EC2, skip IAM user keys — attach the policy to the EC2 instance role instead.

---

## Step 2 — Replace SMTP with AWS SES in the project

The project uses `notifier.py` with `smtplib`. You have two options:

### Option A — Use SES SMTP endpoint (easiest, minimal code change)

SES exposes an SMTP interface. Just swap your SMTP settings — **no Python code changes needed**.

In your `.env`:
```
SMTP_PASSWORD=your_ses_smtp_password   # generated below
```

In `config/settings.yaml`:
```yaml
email:
  smtp_host: email-smtp.us-east-1.amazonaws.com   # change region if needed
  smtp_port: 587
  smtp_user: YOUR_SES_SMTP_USERNAME                # generated below
  from_addr: middleware-agent@yourdomain.com
  admin_addrs:
    - admin@yourdomain.com
  use_tls: true
```

**To get SES SMTP credentials:**
1. Go to **SES → SMTP settings → Create SMTP credentials**
2. It creates an IAM user and gives you a **SMTP username** and **SMTP password** (different from IAM access keys — don't confuse them)
3. Copy those into the config above

This is the recommended path — zero code changes.

---

### Option B — Use boto3 SES SDK (more native AWS)

If you prefer using `boto3` directly (no SMTP), replace `agent/notifier.py` with this:

```python
import boto3
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

class EmailNotifier:
    def __init__(self, cfg: dict):
        self.enabled = cfg.get("enabled", True)
        self.from_addr = cfg["from_addr"]
        self.admin_addrs = cfg["admin_addrs"]
        region = cfg.get("ses_region", "us-east-1")
        self.client = boto3.client("ses", region_name=region)

    def send(self, subject: str, body: str) -> bool:
        if not self.enabled:
            return True
        try:
            self.client.send_email(
                Source=self.from_addr,
                Destination={"ToAddresses": self.admin_addrs},
                Message={
                    "Subject": {"Data": subject},
                    "Body": {"Text": {"Data": body}},
                },
            )
            logger.info("Email sent via SES: %s", subject)
            return True
        except Exception as e:
            logger.error("SES send failed: %s", e)
            return False
```

Then update `config/settings.yaml` to add:
```yaml
email:
  ses_region: us-east-1
  from_addr: middleware-agent@yourdomain.com
  admin_addrs:
    - admin@yourdomain.com
  enabled: true
```

And install the dependency (already present if you're using boto3 for Bedrock):
```bash
pip install boto3
```

---

## Step 3 — Update `.env`

For **Option A** (SMTP):
```
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=your_bedrock_key
AWS_REGION=us-east-1
SMTP_PASSWORD=your_ses_smtp_password
```

For **Option B** (boto3 SDK): the same IAM credentials used for Bedrock can be reused — just make sure the IAM policy includes both `bedrock:InvokeModel` and `ses:SendEmail`.

---

## Quick Summary

| | Option A (SES SMTP) | Option B (boto3 SDK) |
|---|---|---|
| Code changes | None | Replace `notifier.py` |
| Credentials | Separate SES SMTP creds | Reuse existing IAM keys |
| Best for | Minimal effort | Cleaner AWS-native setup |

**Recommendation:** Go with **Option A** first — it works with the existing code, and you're already in the AWS ecosystem. Switch to Option B later if you want a unified IAM credential setup (one set of keys for both Bedrock and SES).
