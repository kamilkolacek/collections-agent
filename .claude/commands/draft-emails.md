---
description: Draft (or redraft) collection emails into the review queue — never sends
argument-hint: "[customer IDs, e.g. C-1003 C-1005 — default: whole worklist]"
---

Draft collection emails for: $ARGUMENTS (if empty, every customer in `worklist`).

1. Use the latest run (`output/runs/LATEST`). If none exists, run `python -m collections_agent analyze`.
2. For each customer, run `python -m collections_agent customer <ID>` and check `action`.
   - `DISPUTE` or `NO_ACTION`: **do not draft.** Explain why in one line.
   - `DUN`: draft using the tier in `tier` and `templates/email-tone-guide.md`.
3. Write each draft to `output/runs/<run_id>/review_queue/<ID>.md` in the CLAUDE.md format,
   `status: PENDING_APPROVAL`, `drafted_by: claude`. If a draft is already `APPROVED` or
   `REJECTED`, do not overwrite it. Tell the user instead.
4. Run `python -m collections_agent validate`, then fix and re-run until it passes.
5. Show the user each draft's subject line and the validation result. Remind them that a person
   approves drafts with `python -m collections_agent approve <ID> --by "Name"` and sends them
   from their own mail client.
