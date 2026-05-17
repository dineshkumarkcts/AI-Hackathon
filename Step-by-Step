Here's the complete step-by-step walkthrough, including a plain-English explanation of that "Note" you asked about.

---

## Phase 1 — Prerequisites

Before you do anything, confirm these two things in your sandbox account:

Your logged-in AWS user must have permissions to create IAM resources and CloudFormation stacks. In a sandbox account this is usually pre-granted, but if the deployment fails with an "Access Denied" error, that's the reason.

Make sure the **region is set to US East (N. Virginia)** — that is `us-east-1`. The template is hardcoded for that region.

---

## Phase 2 — Download the template

Click the download button above to save `iam-hackathon-cft.yaml` to your computer (Desktop or Downloads folder is fine).

---

## Phase 3 — Open CloudFormation

1. Go to [console.aws.amazon.com](https://console.aws.amazon.com) and log in.
2. In the **top-right corner**, click the region name and select **US East (N. Virginia)**.
3. In the search bar at the top, type `CloudFormation` and click it.
4. In the left sidebar, click **Stacks**.

---

## Phase 4 — Create the Stack

1. Click the orange **"Create stack"** button → choose **"With new resources (standard)"**.
2. Under "Specify template", select **"Upload a template file"**.
3. Click **"Choose file"** and select the `iam-hackathon-cft.yaml` you downloaded.
4. Click **Next**.
5. For **Stack name**, type `hackathon-iam` (no spaces).
6. Under **Parameters**, you'll see `HackathonTag`, `TrustedAccountId`, `SandboxBucketName` — leave them all as the defaults.
7. Click **Next**, then **Next** again on the Configure Stack Options page (nothing to change there).

---

## Phase 5 — The CAPABILITY_NAMED_IAM checkbox (this is the "Note" explained)

On the final **Review** page, scroll to the very bottom. You will see a yellow/orange acknowledgement box that says something like:

> *"AWS CloudFormation might create IAM resources with custom names."*

**This is the `CAPABILITY_NAMED_IAM` requirement.** AWS forces you to explicitly tick this checkbox any time a CloudFormation template creates IAM roles or policies with custom names (which ours does — every role and policy has a specific name like `RED-Role-01-WildcardAdmin`). AWS does this as a safety measure so you can't accidentally create powerful IAM resources without realising it.

**What to do:** Tick the checkbox next to the acknowledgement statement. If you skip this, the Deploy button stays greyed out and the stack will not create.

---

## Phase 6 — Submit and Monitor

1. Click **"Submit"** (or "Create stack" depending on your console version).
2. You'll land on the **Events** tab. Watch the status — it will cycle through `CREATE_IN_PROGRESS` and finish with `CREATE_COMPLETE` in about 2–3 minutes.
3. Click the **Resources** tab to see all 50 policies and 51 roles listed.

**To verify in IAM:** Go to the IAM service → Roles → search `RED-` or `GREEN-` to see them.

---

## Cleanup (important for sandbox)

When you're done with the hackathon, delete everything in one click — no need to delete 50 policies manually:

1. In CloudFormation → Stacks → select `hackathon-iam`.
2. Click **Actions → Delete stack**.
3. Confirm. CloudFormation removes all 50 policies and 51 roles automatically.

> Since your sandbox expires in 3 hours, the resources will be destroyed anyway when the account expires — but deleting the stack cleanly first is good practice and avoids any partial-state issues.
