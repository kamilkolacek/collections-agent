---
description: Customers whose payment behavior is deteriorating, with a risk narrative for each
---

1. If no run exists, run `python -m collections_agent analyze`.
2. From `analysis.json`, take every customer in `watchlist` (trend status `DETERIORATING`).
3. For each, write a short narrative (3–4 sentences):
   - **Signal:** quote `trend.signal`, plus the baseline vs recent days late, or "stopped paying".
   - **Exposure:** open balance, past due, credit utilization, current tier.
   - **Read:** what this likely means (cash-flow stress, a process change at the customer,
     a billing issue). Label it as a hypothesis.
   - **Recommended action:** for example, an account owner call, a credit-limit review, tightened
     terms on renewal, or moving up a tier at next review. Recommendations only.
4. Also list customers that are `CHRONIC_LATE` or `IMPROVING`, in one line each, so the reader
   sees the contrast: late but stable is a different problem from getting worse.
