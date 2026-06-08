The problem is clear. In `analyser.py`, `analyse_all_policies()` calls `analyse_policy()` in a simple `for` loop — fully sequential. Here's the fix: **parallel batched execution using `asyncio` + `asyncio.gather`**, with a concurrency limiter so you don't hammer the Anthropic API rate limits.

Here's the updated `analyser.py`:Here's exactly what changed and why it's fast now:

**Root cause:** `analyse_all_policies()` had a plain `for` loop — policy 2 couldn't start until policy 1's Claude API call (typically 2–4 seconds) fully returned. 60 IAMs × ~3s = ~3 minutes.

**The fix — 3 key changes in `analyser.py`:**

**1. Async client**
```python
async_client = anthropic.AsyncAnthropic(...)
```
The Anthropic SDK ships `AsyncAnthropic` specifically for this. Swapped in alongside the existing sync client (kept for `analyse_policy()` backward compat).

**2. Semaphore-controlled concurrency**
```python
semaphore = asyncio.Semaphore(BATCH_SIZE)  # default: 20
async with semaphore:
    await async_client.messages.create(...)
```
The semaphore ensures at most 20 Claude calls are in-flight simultaneously — preventing rate limit errors (Anthropic's default is ~50 RPM on Sonnet).

**3. `asyncio.gather` replaces the for loop**
```python
tasks = [_analyse_policy_async(policy, semaphore, i+1, total) for i, policy in enumerate(policies)]
return await asyncio.gather(*tasks)
```
All 60 tasks are created instantly; `gather` + the semaphore means they run 20-at-a-time. Results come back in the original order.

**Expected speedup for 60 IAMs:**

| Before | After (batch_size=20) |
|---|---|
| ~60 sequential calls | ~3 rounds of 20 parallel calls |
| ~3 minutes | ~15–20 seconds |

**No changes needed** in `main.py` — `analyse_all_policies()` signature is identical. Just replace `backend/agent/analyser.py` on your EC2 and restart uvicorn. If you're on a higher Anthropic API tier, you can bump `BATCH_SIZE = 20` up to 40 or 50 in the file.
