---
description: Full collections run — analyze AR, draft emails for approval, validate, write the run report
argument-hint: "[--as-of YYYY-MM-DD]"
---

Run the complete collections workflow. Follow CLAUDE.md hard rules throughout.

1. **Analyze.** Run `python -m collections_agent analyze $ARGUMENTS`. If it prints `DATA ERROR`,
   stop and report the problem. Do not fix the data.
2. **Read** `output/runs/<run_id>/analysis.json` (the run id is in `output/runs/LATEST`).
   Use `python -m collections_agent customer <ID>` for any account you need in detail.
3. **Draft** one email per customer in `worklist` (in rank order), following
   `templates/email-tone-guide.md` and the draft format in CLAUDE.md. Save each to
   `output/runs/<run_id>/review_queue/<customer_id>.md` with `status: PENDING_APPROVAL` and
   `drafted_by: claude`. Do **not** draft for `DISPUTE` or `NO_ACTION` customers.
4. **Validate.** Run `python -m collections_agent validate`. Fix every failure and re-run until all
   drafts pass. Never weaken a control to get a pass. If a control seems wrong, note it in the report.
5. **Report.** Write `output/runs/<run_id>/run_report.md` using `templates/run-report.md`.
   Every number must come from `analysis.json`.
6. **Verify** the audit log: `python -m collections_agent verify-log`.
7. **Summarize** for the user in under 10 lines: headline metrics, the top 3 accounts, the holds
   needing a controller decision, and the approval command:
   `python -m collections_agent approve <ID> --by "Your Name"` (to be run by a person in a terminal).
