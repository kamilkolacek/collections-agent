"""Automated evals - every deterministic case in EVALS.md has a test here.

Run:  python -m unittest discover tests -v
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from collections_agent import audit, calc, engine, review_queue as rq
from collections_agent.data import DataError, load

ROOT = Path(__file__).resolve().parent.parent
AS_OF = date(2026, 10, 31)


def cust(analysis, cid):
    return next(c for c in analysis["customers"] if c["customer_id"] == cid)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = load(ROOT / "data")
        cls.a = engine.analyze(cls.ds, AS_OF, "TEST")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "review_queue").mkdir()
        (self.tmp / "analysis.json").write_text(json.dumps(self.a, default=str))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def good_draft(self, cid, **overrides):
        """Build a draft that passes every control, then apply overrides."""
        c = cust(self.a, cid)
        invs = [i for i in c["invoices"] if i["invoice_id"] in c["dunnable_invoice_ids"]]
        total = round(sum(i["open_amount"] for i in invs), 2)
        meta = {
            "customer_id": cid, "run_id": "TEST", "tier": c["tier"] or "friendly",
            "status": "PENDING_APPROVAL", "to": c["ar_contact_email"],
            "cc": c["account_owner_email"], "subject": "Past-due balance",
            "invoices": ", ".join(i["invoice_id"] for i in invs),
            "amount_requested": f"{total:.2f}", "drafted_by": "claude",
        }
        lines = "\n".join(f"- {i['invoice_id']}: ${i['open_amount']:,.2f}" for i in invs)
        body = f"\nHello,\n\nOur records show ${total:,.2f} past due:\n{lines}\n"
        if c["hold_recommended"]:
            body += "\nWithout payment we will need to place the account on credit hold.\n"
        body += "\nThank you,\nLumina AR\n"
        meta.update({k: v for k, v in overrides.items() if k != "body"})
        body = overrides.get("body", body)
        path = self.tmp / "review_queue" / f"{cid}.md"
        rq.write_draft(path, meta, body)
        return path


# ---------------------------------------------------------- risk & trend -----
class TestTrendEvals(Base):
    def test_eval01_15_to_45_days_late_is_flagged(self):
        c = cust(self.a, "C-1003")
        self.assertEqual(c["trend"]["status"], "DETERIORATING")
        self.assertIn("C-1003", self.a["watchlist"])

    def test_eval05_chronic_but_stable_is_not_deteriorating(self):
        c = cust(self.a, "C-1004")
        self.assertEqual(c["trend"]["status"], "CHRONIC_LATE")
        self.assertNotIn("C-1004", self.a["watchlist"])

    def test_eval06_small_bucket_but_deteriorating_is_on_watchlist(self):
        c = cust(self.a, "C-1010")
        self.assertEqual(c["tier"], "friendly")
        self.assertIn("C-1010", self.a["watchlist"])

    def test_eval08_improving_payer_not_flagged(self):
        c = cust(self.a, "C-1012")
        self.assertEqual(c["trend"]["status"], "IMPROVING")
        self.assertEqual(c["tier"], "escalation")
        self.assertNotIn("C-1012", self.a["watchlist"])

    def test_eval10_drift_below_threshold_not_flagged(self):
        c = cust(self.a, "C-1017")
        self.assertLess(c["trend"]["delta_days"], 10)
        self.assertNotEqual(c["trend"]["status"], "DETERIORATING")

    def test_eval11_stopped_paying_is_flagged_high_risk(self):
        c = cust(self.a, "C-1018")
        self.assertEqual(c["trend"]["status"], "DETERIORATING")
        self.assertIn("No payments received", c["trend"]["signal"])
        self.assertEqual(c["risk"]["band"], "High")
        self.assertTrue(c["hold_recommended"])
        jun = next(i for i in c["invoices"] if i["invoice_id"] == "INV-1018-202606")
        self.assertTrue(jun["partially_paid"])
        self.assertAlmostEqual(jun["open_amount"], jun["original_amount"] - 60_000, places=2)


# ------------------------------------------------------------- routing -------
class TestRoutingEvals(Base):
    def test_eval02_disputed_invoice_routes_to_dispute_not_dunning(self):
        c = cust(self.a, "C-1006")
        self.assertEqual(c["action"], "DISPUTE")
        self.assertIsNone(c["tier"])
        self.assertNotIn("C-1006", self.a["worklist"])
        self.assertIn("C-1006", [d["customer_id"] for d in self.a["dispute_queue"]])
        errs = rq.validate_draft(self.good_draft("C-1006", tier="escalation"), self.a)
        self.assertTrue(any("dispute-only" in e for e in errs))

    def test_eval02b_all_past_due_disputed_routes_to_dispute(self):
        self.assertEqual(cust(self.a, "C-1014")["action"], "DISPUTE")

    def test_eval03_mixed_customer_duns_only_undisputed(self):
        c = cust(self.a, "C-1008")
        self.assertEqual(c["action"], "DUN")
        self.assertEqual(c["dunnable_invoice_ids"], ["INV-1008-202608"])
        self.assertEqual(c["disputed_invoice_ids"], ["INV-1008-202609"])
        self.assertEqual(c["tier"], "firm")
        self.assertEqual(rq.validate_draft(self.good_draft("C-1008"), self.a), [])
        leaked = self.good_draft("C-1008", body="\nAlso INV-1008-202609 is open. $26,959.78 "
                                                "INV-1008-202608\n")
        self.assertTrue(any("disputed invoice" in e for e in rq.validate_draft(leaked, self.a)))

    def test_eval04_90_plus_over_limit_gets_final_and_hold(self):
        c = cust(self.a, "C-1005")
        self.assertEqual(c["tier"], "final")
        self.assertTrue(c["hold_recommended"])
        self.assertGreater(c["credit_utilization"], 1.0)

    def test_eval07_61_to_90_is_escalation_and_must_cc_owner(self):
        c = cust(self.a, "C-1007")
        self.assertEqual(c["tier"], "escalation")
        errs = rq.validate_draft(self.good_draft("C-1007", cc=""), self.a)
        self.assertTrue(any("must cc the account owner" in e for e in errs))

    def test_eval09_small_balance_90_plus_still_final(self):
        c = cust(self.a, "C-1013")
        self.assertLess(c["open_balance"], 5_000)
        self.assertEqual(c["tier"], "final")

    def test_eval12_nothing_past_due_gets_no_email(self):
        c = cust(self.a, "C-1009")
        self.assertEqual(c["action"], "NO_ACTION")
        errs = rq.validate_draft(self.good_draft("C-1009"), self.a)
        self.assertTrue(any("nothing past due" in e for e in errs))

    def test_tier_boundaries(self):
        cases = {0: None, 1: "friendly", 30: "friendly", 31: "firm", 60: "firm",
                 61: "escalation", 90: "escalation", 91: "final", 400: "final"}
        for dpd, tier in cases.items():
            self.assertEqual(calc.tier_for(dpd), tier, dpd)
        self.assertEqual(calc.bucket(0), "current")
        self.assertEqual(calc.bucket(-10), "current")
        self.assertEqual(calc.bucket(91), "90+")

    def test_worklist_priority_puts_90_plus_enterprise_first(self):
        self.assertEqual(self.a["worklist"][0], "C-1018")
        ranks = {cid: n for n, cid in enumerate(self.a["worklist"])}
        # a 1-day-late invoice must not outrank a 108-day-late one
        self.assertLess(ranks["C-1005"], ranks["C-1011"])


# -------------------------------------------------------- draft controls -----
class TestDraftControls(Base):
    def test_eval13_wrong_tier_fails(self):
        errs = rq.validate_draft(self.good_draft("C-1003", tier="friendly"), self.a)
        self.assertTrue(any("does not match computed tier" in e for e in errs))

    def test_eval14_amount_must_tie_out(self):
        errs = rq.validate_draft(self.good_draft("C-1003", amount_requested="999.00"), self.a)
        self.assertTrue(any("amount_requested" in e for e in errs))

    def test_eval15_unsupported_hold_threat_fails(self):
        c = cust(self.a, "C-1003")
        body = (f"\n${c['past_due_undisputed']:,.2f} for {', '.join(c['dunnable_invoice_ids'])}. "
                "We will put you on credit hold.\n")
        errs = rq.validate_draft(self.good_draft("C-1003", body=body), self.a)
        self.assertTrue(any("does not support" in e for e in errs))

    def test_eval16_hold_required_when_recommended(self):
        c = cust(self.a, "C-1005")
        body = f"\n${c['past_due_undisputed']:,.2f} for {', '.join(c['dunnable_invoice_ids'])}.\n"
        errs = rq.validate_draft(self.good_draft("C-1005", body=body), self.a)
        self.assertTrue(any("does not mention it" in e for e in errs))

    def test_eval17_legal_threats_blocked(self):
        c = cust(self.a, "C-1018")
        body = (f"\n${c['past_due_undisputed']:,.2f} for {', '.join(c['dunnable_invoice_ids'])}. "
                "Credit hold applies. We will refer this to a collection agency.\n")
        errs = rq.validate_draft(self.good_draft("C-1018", body=body), self.a)
        self.assertTrue(any("prohibited language" in e for e in errs))

    def test_sample_run_drafts_pass(self):
        run = ROOT / "examples" / "sample-run"
        analysis = rq.load_analysis(run)
        drafts = sorted((run / "review_queue").glob("*.md"))
        self.assertEqual(len(drafts), len(analysis["worklist"]))
        for p in drafts:
            self.assertEqual(rq.validate_draft(p, analysis), [], p.name)

    def test_good_drafts_pass_for_every_worklist_customer(self):
        for cid in self.a["worklist"]:
            self.assertEqual(rq.validate_draft(self.good_draft(cid), self.a), [], cid)


# ------------------------------------------------------ approval & audit -----
class TestApprovalAndAudit(Base):
    def test_eval18_cannot_approve_failing_draft(self):
        self.good_draft("C-1003", tier="friendly")
        with self.assertRaises(ValueError):
            rq.approve(self.tmp, self.a, "C-1003", "Jordan Blake")
        self.assertFalse((self.tmp / "approved").exists())

    def test_eval19_drafter_cannot_self_approve(self):
        self.good_draft("C-1003")
        with self.assertRaises(ValueError):
            rq.approve(self.tmp, self.a, "C-1003", "claude")

    def test_approve_happy_path_logs_and_copies(self):
        self.good_draft("C-1003")
        rq.approve(self.tmp, self.a, "C-1003", "Jordan Blake")
        meta, _ = rq.parse_draft(self.tmp / "review_queue" / "C-1003.md")
        self.assertEqual(meta["status"], "APPROVED")
        self.assertEqual(meta["approved_by"], "Jordan Blake")
        self.assertTrue((self.tmp / "approved" / "C-1003.md").exists())
        events = [json.loads(l)["event"] for l in (self.tmp / "audit_log.jsonl").read_text().splitlines()]
        self.assertIn("draft_approved", events)

    def test_eval20_audit_log_detects_tampering(self):
        for i in range(3):
            audit.log(self.tmp, "test_event", actor="tester", n=i)
        self.assertTrue(audit.verify(self.tmp)[0])
        p = self.tmp / "audit_log.jsonl"
        p.write_text(p.read_text().replace('"n": 1', '"n": 99'))
        self.assertFalse(audit.verify(self.tmp)[0])

    def test_eval21_no_send_capability_in_codebase(self):
        pattern = re.compile(r"smtplib|sendmail|send_message|requests\.post|urllib\.request")
        for py in (ROOT / "collections_agent").glob("*.py"):
            self.assertIsNone(pattern.search(py.read_text()), py.name)


# ---------------------------------------------------------------- metrics -----
class TestMetrics(Base):
    def test_eval22_dso_math(self):
        p = self.a["portfolio"]
        self.assertAlmostEqual(p["dso"], round(p["total_ar"] / p["sales_last_90d"] * 90, 1), places=1)
        self.assertAlmostEqual(p["average_days_delinquent"], round(p["dso"] - p["best_possible_dso"], 1),
                               places=1)
        self.assertAlmostEqual(sum(p["aging"].values()), p["total_ar"], places=1)

    def test_eval23_cash_at_risk_definition(self):
        p = self.a["portfolio"]
        high = sum(c["past_due_undisputed"] for c in self.a["customers"] if c["risk"]["band"] == "High")
        disp = sum(c["disputed_balance"] for c in self.a["customers"])
        self.assertAlmostEqual(p["cash_at_risk"]["total"], round(high + disp, 2), places=2)

    def test_open_ar_ties_to_input_file(self):
        with open(ROOT / "data" / "ar_aging.csv") as f:
            total = sum(float(r["open_amount"]) for r in csv.DictReader(f))
        self.assertAlmostEqual(self.a["portfolio"]["total_ar"], round(total, 2), places=2)


# ------------------------------------------------------------- bad data ------
class TestDataValidation(unittest.TestCase):
    def _copy(self):
        tmp = Path(tempfile.mkdtemp())
        for f in (ROOT / "data").glob("*.csv"):
            shutil.copy(f, tmp / f.name)
        return tmp

    def test_eval24_open_amount_above_original_rejected(self):
        tmp = self._copy()
        p = tmp / "ar_aging.csv"
        with open(p) as fh:
            rows = list(csv.DictReader(fh))
        rows[0]["open_amount"] = str(float(rows[0]["original_amount"]) + 100)
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
        with self.assertRaises(DataError):
            load(tmp)
        shutil.rmtree(tmp)

    def test_eval25_dispute_on_unknown_invoice_rejected(self):
        tmp = self._copy()
        p = tmp / "disputes.csv"
        p.write_text(p.read_text() + 'DSP-999,C-1001,INV-DOES-NOT-EXIST,2026-10-01,x,100.00,Open,Priya Shah\n')
        with self.assertRaises(DataError):
            load(tmp)
        shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
