---
description: Dispute-handling recommendations — disputed invoices are never dunned
---

1. If no run exists, run `python -m collections_agent analyze`.
2. From `analysis.json` → `dispute_queue`, list each open dispute: customer, invoice, reason,
   disputed amount vs invoice open amount, days past due, dispute owner, date opened.
3. For each, recommend the next step for the **dispute owner** (not AR dunning). For example:
   - Partial dispute (disputed amount < invoice): ask for a short-pay of the undisputed portion
     and resolve the rest separately.
   - Service-credit / outage claim: confirm with Operations, then issue a credit memo if valid.
   - Pricing claim: pull the contract rate and rebill if Lumina billed incorrectly.
4. Flag disputes open for more than 30 days as aging disputes that need a decision.
5. Do **not** draft customer emails here. Dispute communication belongs to the dispute owner.
