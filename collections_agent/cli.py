"""Command-line entry point:  python -m collections_agent <command>

  analyze    Run the deterministic analysis, write a new run folder
  customer   Print one customer's full detail (JSON) from a run
  validate   Check every draft in the review queue against the controls
  status     Show the review queue
  approve    Approve a draft   (human only - interactive terminal required)
  reject     Reject a draft    (human only - interactive terminal required)
  verify-log Check the run's audit log hash chain
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

from . import audit, engine, review_queue as rq
from .data import DataError, load

ROOT = Path.cwd()


def _runs_dir(out: str) -> Path:
    return Path(out) / "runs"


def _resolve_run(out: str, run: str) -> Path:
    runs = _runs_dir(out)
    if run == "latest":
        ptr = runs / "LATEST"
        if not ptr.exists():
            sys.exit("No runs yet. Run: python -m collections_agent analyze")
        run = ptr.read_text().strip()
    path = runs / run
    if not (path / "analysis.json").exists():
        sys.exit(f"Run not found: {path}")
    return path


def _default_as_of(data_dir: Path) -> date:
    with open(data_dir / "ar_aging.csv") as f:
        row = next(csv.DictReader(f), None)
    if row and row.get("as_of_date"):
        return date.fromisoformat(row["as_of_date"])
    return date.today()


def _fmt(x: float) -> str:
    return f"${x:,.0f}"


# ------------------------------------------------------------- commands -------
def cmd_analyze(a) -> None:
    data_dir = Path(a.data)
    try:
        ds = load(data_dir)
    except DataError as e:
        sys.exit(f"DATA ERROR: {e}")
    as_of = date.fromisoformat(a.as_of) if a.as_of else _default_as_of(data_dir)
    run_id = f"{as_of.isoformat()}_{datetime.now().strftime('%H%M%S')}"
    run_dir = _runs_dir(a.out) / run_id
    (run_dir / "review_queue").mkdir(parents=True, exist_ok=True)

    audit.log(run_dir, "run_started", as_of=as_of.isoformat(), data_dir=str(data_dir),
              input_hashes=ds.file_hashes)
    res = engine.analyze(ds, as_of, run_id)
    (run_dir / "analysis.json").write_text(json.dumps(res, indent=2, default=str))

    # flat CSVs for people who live in Excel
    by_id = {c["customer_id"]: c for c in res["customers"]}
    with open(run_dir / "worklist.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "customer_id", "customer_name", "segment", "tier", "past_due_undisputed",
                    "max_days_past_due", "risk_score", "risk_band", "trend", "hold_recommended",
                    "account_owner"])
        for cid in res["worklist"]:
            c = by_id[cid]
            w.writerow([c["priority_rank"], cid, c["customer_name"], c["segment"], c["tier"],
                        c["past_due_undisputed"], c["max_days_past_due_undisputed"],
                        c["risk"]["score"], c["risk"]["band"], c["trend"]["status"],
                        c["hold_recommended"], c["account_owner"]])
    with open(run_dir / "dispute_queue.csv", "w", newline="") as f:
        rows = res["dispute_queue"]
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    (_runs_dir(a.out) / "LATEST").write_text(run_id)
    p = res["portfolio"]
    audit.log(run_dir, "analysis_complete", total_ar=p["total_ar"], dso=p["dso"],
              cash_at_risk=p["cash_at_risk"]["total"], counts=p["counts"])

    print(f"Run {run_id}  (as of {as_of})  ->  {run_dir}")
    print(f"  Total AR {_fmt(p['total_ar'])} | past due {_fmt(p['past_due'])} "
          f"({p['pct_past_due']:.0%}) | DSO {p['dso']} (best possible {p['best_possible_dso']}, "
          f"ADD {p['average_days_delinquent']})")
    print(f"  Cash at risk {_fmt(p['cash_at_risk']['total'])} | expected loss "
          f"{_fmt(p['expected_loss_reserve_method'])}")
    c = p["counts"]
    print(f"  Worklist {c['dun']} | disputes {c['dispute_only']} dispute-only | "
          f"deteriorating {c['deteriorating']} | hold recommended {c['hold_recommended']}")
    print("\n  Rank  Customer                     Tier         Past due     Risk   Trend")
    for cid in res["worklist"]:
        x = by_id[cid]
        print(f"  {x['priority_rank']:>4}  {x['customer_name'][:27]:<27}  {x['tier']:<11} "
              f"{_fmt(x['past_due_undisputed']):>11}  {x['risk']['score']:>5}  {x['trend']['status']}")


def cmd_customer(a) -> None:
    res = rq.load_analysis(_resolve_run(a.out, a.run))
    c = next((c for c in res["customers"] if c["customer_id"] == a.customer_id), None)
    if not c:
        sys.exit(f"Unknown customer {a.customer_id}")
    print(json.dumps(c, indent=2, default=str))


def cmd_validate(a) -> None:
    run_dir = _resolve_run(a.out, a.run)
    s = rq.validate_queue(run_dir, rq.load_analysis(run_dir))
    print(f"{s['passed']}/{s['drafts']} drafts pass all controls")
    for cid, errs in s["failed"].items():
        print(f"  FAIL {cid}")
        for e in errs:
            print(f"     - {e}")
    if s["worklist_without_draft"]:
        print(f"  Worklist customers with no draft yet: {', '.join(s['worklist_without_draft'])}")
    sys.exit(1 if s["failed"] else 0)


def cmd_status(a) -> None:
    run_dir = _resolve_run(a.out, a.run)
    q = run_dir / "review_queue"
    drafts = sorted(q.glob("*.md"))
    if not drafts:
        print("Review queue is empty.")
        return
    for p in drafts:
        meta, _ = rq.parse_draft(p)
        who = meta.get("approved_by") or meta.get("rejected_by") or ""
        print(f"  {p.stem:<8} {meta.get('tier', ''):<11} {meta.get('status', ''):<17} "
              f"${float(meta.get('amount_requested', 0)):>12,.2f}  {who}")


def _require_human(action: str) -> None:
    if not sys.stdin.isatty():
        sys.exit(f"'{action}' must be run by a person in an interactive terminal. "
                 "Agents cannot approve or reject drafts.")


def cmd_approve(a) -> None:
    _require_human("approve")
    run_dir = _resolve_run(a.out, a.run)
    analysis = rq.load_analysis(run_dir)
    meta, body = rq.parse_draft(run_dir / "review_queue" / f"{a.customer_id}.md")
    print(f"\nTo: {meta['to']}\nCc: {meta.get('cc', '')}\nSubject: {meta['subject']}\n{body}")
    if input(f"Type {a.customer_id} to approve this draft: ").strip() != a.customer_id:
        sys.exit("Not approved.")
    try:
        path = rq.approve(run_dir, analysis, a.customer_id, a.by)
    except (ValueError, FileNotFoundError) as e:
        sys.exit(str(e))
    print(f"Approved. Copy saved to {run_dir / 'approved' / path.name} - send it from your mail client.")


def cmd_reject(a) -> None:
    _require_human("reject")
    run_dir = _resolve_run(a.out, a.run)
    try:
        rq.reject(run_dir, rq.load_analysis(run_dir), a.customer_id, a.by, a.reason)
    except (ValueError, FileNotFoundError) as e:
        sys.exit(str(e))
    print(f"Rejected {a.customer_id}: {a.reason}")


def cmd_verify_log(a) -> None:
    ok, msg = audit.verify(_resolve_run(a.out, a.run))
    print(("OK: " if ok else "TAMPERED: ") + msg)
    sys.exit(0 if ok else 1)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="collections_agent", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="output", help="output folder (default: output)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("analyze")
    s.add_argument("--data", default="data")
    s.add_argument("--as-of", help="YYYY-MM-DD (default: as_of_date in ar_aging.csv)")
    s.set_defaults(fn=cmd_analyze)

    s = sub.add_parser("customer")
    s.add_argument("customer_id")
    s.add_argument("--run", default="latest")
    s.set_defaults(fn=cmd_customer)

    for name, fn in [("validate", cmd_validate), ("status", cmd_status), ("verify-log", cmd_verify_log)]:
        s = sub.add_parser(name)
        s.add_argument("--run", default="latest")
        s.set_defaults(fn=fn)

    s = sub.add_parser("approve")
    s.add_argument("customer_id")
    s.add_argument("--by", required=True, help="your name (recorded in the audit log)")
    s.add_argument("--run", default="latest")
    s.set_defaults(fn=cmd_approve)

    s = sub.add_parser("reject")
    s.add_argument("customer_id")
    s.add_argument("--by", required=True)
    s.add_argument("--reason", required=True)
    s.add_argument("--run", default="latest")
    s.set_defaults(fn=cmd_reject)

    a = ap.parse_args(argv)
    a.fn(a)
