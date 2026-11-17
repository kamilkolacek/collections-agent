---
description: DSO, Best Possible DSO, ADD, cash-at-risk, expected loss and the 6-month DSO trend
---

1. If no run exists, run `python -m collections_agent analyze`.
2. From `analysis.json` → `portfolio`, present:
   - Total AR, current, past due, % past due, aging by bucket
   - **DSO** (AR ÷ last-90-day sales × 90), **Best Possible DSO** (current AR only) and
     **Average Days Delinquent** (DSO − BPDSO, the part collections can fix)
   - **Cash at risk** = past-due AR on High-risk accounts + all disputed balances, with each part
   - **Expected loss** (reserve-rate method; rates are in `policy.RESERVE_RATES`)
   - DSO trend for the last 6 month-ends as a small table
3. Write 3–4 sentences of commentary: what moved DSO, which accounts drive cash at risk (name the
   top 3 by `past_due_undisputed` among High-risk accounts plus the largest dispute), and what
   collecting the top 3 worklist accounts would do to past-due AR.
4. If the user wants a chart, build it from these numbers only.

All figures come from `analysis.json`. Do not recompute them.
