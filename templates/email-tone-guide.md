# Email tone guide

The tier comes from `analysis.json` and is never changed in a draft. This guide sets how each
tier *sounds*. All tiers are professional, specific, and short (under 200 words). We are writing
to a customer we want to keep.

## Every email includes

- Each invoice number with its open amount, and the total requested (`$12,345.67` format)
- One clear ask with a date (payment, or a remittance date / payment plan by a date)
- An easy out: "If payment has already been sent, please share the remittance details."
- An invitation to raise any billing question (but **never** name disputed invoices)
- Signature:

  ```
  Lumina Streaming Co. — Accounts Receivable
  ar@luminastreaming.example
  ```

## Never

- Legal threats or third parties (legal action, attorney, collection agency, credit bureau)
- Guilt, sarcasm, ALL CAPS, exclamation marks, or "FINAL WARNING"-style subject lines
- Interest or late fees (not in the synthetic contracts)
- Any number not copied from `analysis.json`
- A credit hold, unless `hold_recommended` is true

## Tier 1: `friendly`: 1–30 days past due

**Goal:** a nudge. Assume an oversight.
**Tone:** warm, brief, no pressure.
**Subject:** `Friendly reminder: invoice <ID> — <Customer>`
**Ask:** confirm payment status or a scheduled payment date within 5 business days.
**Tip:** for a large Enterprise account one day late, keep it especially light. It is almost
always timing.

## Tier 2: `firm`: 31–60 days past due

**Goal:** get a committed payment date.
**Tone:** direct and courteous. State the facts and the days overdue.
**Subject:** `Past-due balance of <$total> — <Customer>`
**Ask:** payment, or a confirmed payment date, within 5 business days. Offer a call.
**Tip:** if `trend.status` is `DETERIORATING`, you may note gently that recent payments have been
later than usual. Never quote the internal risk score.

## Tier 3: `escalation`: 61–90 days past due

**Goal:** move the conversation up a level on both sides.
**Tone:** serious and collaborative. This is a business problem to solve together.
**Recipients:** `to` the customer AP contact, `cc` the Lumina account owner (required).
**Subject:** `Action needed: <$total> past due — <Customer>`
**Ask:** ask that their finance leader (Controller/CFO) join a call this week. Propose a payment
plan if helpful.
**Tip:** for an `IMPROVING` payer with one stranded old invoice, say so. It is often a missed or
misapplied payment, so ask them to check.

## Tier 4: `final`: 91+ days past due

**Goal:** last attempt before an internal credit decision.
**Tone:** formal, calm, unambiguous. No drama.
**Recipients:** `to` AP contact, `cc` the account owner (required).
**Subject:** `Final notice: <$total> past due — <Customer>`
**Ask:** full payment or an agreed payment plan within 10 business days.
**Hold language** (`hold_recommended` is true): explain that without payment or an agreed plan,
the account *may be placed on credit hold*, which could affect new orders/services. This is a
possible consequence, not a decision. The controller decides.
**Tip:** for Enterprise accounts, ask for an executive-level call. The relationship matters as
much as the cash.
