---
description: Review-queue status, draft validation results and audit-log integrity
---

Run these and summarize the results in a short table:

1. `python -m collections_agent status`: each draft's tier, status and approver
2. `python -m collections_agent validate`: control pass/fail per draft
3. `python -m collections_agent verify-log`: audit-log hash-chain check

Then list what is waiting on a human: drafts pending approval, holds needing a controller decision,
disputes needing an owner. You cannot approve, reject or send anything. Say so if asked.
