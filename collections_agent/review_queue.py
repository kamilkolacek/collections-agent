"""Human-in-the-loop review queue.

Claude writes drafts to  output/runs/<run_id>/review_queue/<customer_id>.md
with status PENDING_APPROVAL. This module:
  * validates every draft against analysis.json (deterministic guardrails)
  * lets a human approve or reject a draft (interactive terminal only)

There is deliberately NO send function anywhere in this repo. Approved drafts
are copied to approved/ for a person to send from their own mail client.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import audit

REQUIRED_FIELDS = ["customer_id", "run_id", "tier", "status", "to", "subject", "invoices",
                   "amount_requested"]
VALID_STATUSES = {"PENDING_APPROVAL", "APPROVED", "REJECTED"}
PROHIBITED_PHRASES = ["legal action", "lawsuit", "attorney", "collection agency",
                      "collections agency", "credit bureau", "sue ", "litigation"]


# ------------------------------------------------------------- parsing -------
def parse_draft(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path.name}: missing front matter block")
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, m.group(2)


def write_draft(path: Path, meta: dict, body: str) -> None:
    head = "\n".join(f"{k}: {v}" for k, v in meta.items())
    path.write_text(f"---\n{head}\n---\n{body}")


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _split(v: str) -> list[str]:
    return [s.strip() for s in v.split(",") if s.strip()]


# ---------------------------------------------------------- validation -------
def validate_draft(path: Path, analysis: dict) -> list[str]:
    """Return a list of control failures for one draft (empty list = pass)."""
    errors: list[str] = []
    try:
        meta, body = parse_draft(path)
    except ValueError as e:
        return [str(e)]

    cid = meta.get("customer_id") or path.stem
    cust = next((c for c in analysis["customers"] if c["customer_id"] == cid), None)
    if cust is None:
        return [f"unknown customer {cid}"]

    # C1: only DUN customers get collection emails (checked first - it overrides everything)
    if cust["action"] == "DISPUTE":
        errors.append("customer is dispute-only: route to dispute handling, do not send a dunning email")
    elif cust["action"] == "NO_ACTION":
        errors.append("customer has nothing past due: no collection email allowed")

    missing = [f for f in REQUIRED_FIELDS if not meta.get(f)]
    if missing:
        return errors + [f"missing field '{f}'" for f in missing]

    if meta["run_id"] != analysis["run_id"]:
        errors.append(f"run_id {meta['run_id']} does not match analysis run {analysis['run_id']}")

    # C2: tone tier must match the deterministic tier
    if cust["tier"] and meta["tier"] != cust["tier"]:
        errors.append(f"tier '{meta['tier']}' does not match computed tier '{cust['tier']}'")

    # C3: only undisputed past-due invoices may be requested
    listed = _split(meta["invoices"])
    bad = [i for i in listed if i not in cust["dunnable_invoice_ids"]]
    if bad:
        errors.append(f"invoices not eligible for dunning: {bad}")

    # C4: disputed invoice numbers must not appear anywhere in the email
    full_text = path.read_text()
    leaked = [i for i in cust["disputed_invoice_ids"] if i in full_text]
    if leaked:
        errors.append(f"disputed invoice(s) referenced in draft: {leaked}")

    # C5: amount requested must tie to the listed invoices, and appear in the body
    inv_amounts = {i["invoice_id"]: i["open_amount"] for i in cust["invoices"]}
    expected = round(sum(inv_amounts.get(i, 0) for i in listed), 2)
    try:
        requested = round(float(meta["amount_requested"].replace(",", "").replace("$", "")), 2)
    except ValueError:
        requested = None
    if requested is None or abs(requested - expected) > 0.01:
        errors.append(f"amount_requested {meta['amount_requested']} != sum of listed invoices {expected:.2f}")
    elif _money(expected) not in body:
        errors.append(f"body does not state the amount requested ({_money(expected)})")

    # C6: every listed invoice number must appear in the body
    missing_in_body = [i for i in listed if i not in body]
    if missing_in_body:
        errors.append(f"listed invoices not mentioned in body: {missing_in_body}")

    # C7: recipients
    if meta["to"] != cust["ar_contact_email"]:
        errors.append(f"'to' must be the customer AR contact {cust['ar_contact_email']}")
    if meta["tier"] in ("escalation", "final") and cust["account_owner_email"] not in meta.get("cc", ""):
        errors.append(f"tier '{meta['tier']}' must cc the account owner {cust['account_owner_email']}")

    # C8: hold language must match the hold recommendation
    mentions_hold = re.search(r"\bhold\b", body, re.I) is not None
    if cust["hold_recommended"] and not mentions_hold:
        errors.append("credit hold is recommended but the draft does not mention it")
    if not cust["hold_recommended"] and mentions_hold:
        errors.append("draft threatens a credit hold that policy does not support")

    # C9: legal / third-party threats are a human decision, never in an agent draft
    found = [p for p in PROHIBITED_PHRASES if p in body.lower()]
    if found:
        errors.append(f"prohibited language (legal escalation is a human decision): {found}")

    # C10: status discipline
    if meta["status"] not in VALID_STATUSES:
        errors.append(f"invalid status {meta['status']}")
    if meta["status"] == "APPROVED" and not meta.get("approved_by"):
        errors.append("status APPROVED without approved_by")
    if meta["status"] == "APPROVED" and meta.get("drafted_by", "").lower() == meta.get("approved_by", "").lower():
        errors.append("drafter cannot approve their own draft")

    return errors


def validate_queue(run_dir: Path, analysis: dict, log: bool = True) -> dict:
    q = Path(run_dir) / "review_queue"
    drafts = sorted(q.glob("*.md")) if q.exists() else []
    results = {p.stem: validate_draft(p, analysis) for p in drafts}
    drafted = set(results)
    missing = [cid for cid in analysis["worklist"] if cid not in drafted]
    summary = {
        "drafts": len(drafts),
        "passed": sum(not e for e in results.values()),
        "failed": {k: v for k, v in results.items() if v},
        "worklist_without_draft": missing,
    }
    if log:
        audit.log(run_dir, "queue_validated", passed=summary["passed"],
                  failed=list(summary["failed"]), missing=missing)
    return summary


# -------------------------------------------------- approve / reject ---------
def _set_status(run_dir: Path, analysis: dict, customer_id: str, status: str,
                by: str, reason: str | None = None) -> Path:
    path = Path(run_dir) / "review_queue" / f"{customer_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"No draft for {customer_id} in {path.parent}")
    meta, body = parse_draft(path)
    if meta.get("status") != "PENDING_APPROVAL":
        raise ValueError(f"{customer_id} is {meta.get('status')}, not PENDING_APPROVAL")

    if status == "APPROVED":
        errs = validate_draft(path, analysis)
        if errs:
            audit.log(run_dir, "approval_blocked", actor=by, customer_id=customer_id, errors=errs)
            raise ValueError("Draft fails controls, cannot approve:\n  - " + "\n  - ".join(errs))
        if meta.get("drafted_by", "").lower() == by.lower():
            raise ValueError("The drafter cannot approve their own draft")

    meta["status"] = status
    key = "approved" if status == "APPROVED" else "rejected"
    meta[f"{key}_by"] = by
    meta[f"{key}_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if reason:
        meta["rejection_reason"] = reason
    write_draft(path, meta, body)

    if status == "APPROVED":
        dest = Path(run_dir) / "approved"
        dest.mkdir(exist_ok=True)
        shutil.copy(path, dest / path.name)

    audit.log(run_dir, f"draft_{key}", actor=by, customer_id=customer_id,
              tier=meta["tier"], amount_requested=meta["amount_requested"], reason=reason)
    return path


def approve(run_dir: Path, analysis: dict, customer_id: str, by: str) -> Path:
    return _set_status(run_dir, analysis, customer_id, "APPROVED", by)


def reject(run_dir: Path, analysis: dict, customer_id: str, by: str, reason: str) -> Path:
    return _set_status(run_dir, analysis, customer_id, "REJECTED", by, reason)


def load_analysis(run_dir: Path) -> dict:
    return json.loads((Path(run_dir) / "analysis.json").read_text())
