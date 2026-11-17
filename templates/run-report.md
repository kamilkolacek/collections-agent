# Collections run report: {as_of}

Run `{run_id}` · prepared by the collections agent · **all drafts await human approval**

## 1. Executive summary
3–5 sentences: total AR, % past due, DSO vs Best Possible DSO, cash at risk, what changed and the
single most important action this week.

| Metric | Value |
|---|---|
| Total AR | |
| Past due (% of AR) | |
| DSO / Best Possible DSO / ADD | |
| Cash at risk (high-risk past due + disputed) | |
| Expected loss (reserve method) | |
| DSO trend (6 months) | |

## 2. Priority worklist
Table: rank, customer, tier, past due, risk band, trend. Then one or two sentences per account:
why it ranks there and the concrete next step. Say so if you would reorder anything, and why.
Python's rank stands; your view is advisory.

## 3. Deteriorating customers (watchlist)
For each: the signal (from `trend.signal`), what it likely means, and a recommended action
(for example, a call from the account owner or a credit-limit review).

## 4. Disputes: route to dispute owners, no dunning
For each dispute: owner, reason, amount, days open, recommended next step (for example, request
a short-pay of the undisputed portion, or issue a credit memo if the claim is valid).

## 5. Credit-hold recommendations (decision required: Controller)
For each `hold_recommended` customer: the reason, the exposure, and the recommendation. Clearly
a recommendation, not an action.

## 6. Policy flags
Anywhere the deterministic output looks wrong or incomplete (for example, a deteriorating
customer still in the friendly tier). Recommend, don't override.

## 7. Review queue and controls
- Drafts written: N · passed validation: N · failed: N
- Audit log: `python -m collections_agent verify-log` result
- To approve: `python -m collections_agent approve <ID> --by "Your Name"`
