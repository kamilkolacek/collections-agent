---
description: Ranked collections worklist with a rationale and next step for each account
---

1. If `output/runs/LATEST` does not exist, run `python -m collections_agent analyze` first.
2. Read `analysis.json` for the latest run.
3. Present the worklist in Python's rank order as a table: rank, customer, segment, tier,
   past due (undisputed), oldest days past due, risk band, trend.
4. Under the table, for each account, write **one or two sentences**: why it ranks where it does
   (cite the risk components that drive it) and the concrete next step (who does what, by when).
5. Close with "**Would reorder:**": any account you would move, and why (for example, relationship
   value, a deteriorating trend not yet reflected in aging). This is advisory; do not change the
   deterministic rank.

Copy every number from `analysis.json`. Do not compute anything yourself.
