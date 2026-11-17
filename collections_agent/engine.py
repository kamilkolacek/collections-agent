"""Turn a Dataset into a fully-scored collections analysis.

Output is a plain dict (saved as analysis.json) that Claude reads to write
risk narratives, prioritization rationale and email drafts. Every number
Claude quotes must come from this file."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from . import calc, config as C
from .data import Dataset


def _policy_snapshot() -> dict:
    return {k: getattr(C, k) for k in dir(C) if k.isupper()}


def analyze(ds: Dataset, as_of: date, run_id: str) -> dict:
    disputed_ids = ds.open_dispute_invoice_ids
    disputes_by_inv = {d["invoice_id"]: d for d in ds.disputes if d["status"].lower() == "open"}

    inv_by_cust: dict[str, list[dict]] = defaultdict(list)
    for inv in ds.open_invoices:
        dpd = calc.days_past_due(inv["due_date"], as_of)
        inv_by_cust[inv["customer_id"]].append({
            "invoice_id": inv["invoice_id"],
            "invoice_date": inv["invoice_date"].isoformat(),
            "due_date": inv["due_date"].isoformat(),
            "original_amount": inv["original_amount"],
            "open_amount": inv["open_amount"],
            "partially_paid": inv["open_amount"] < inv["original_amount"] - 0.005,
            "days_past_due": dpd,
            "bucket": calc.bucket(dpd),
            "disputed": inv["invoice_id"] in disputed_ids,
            "dispute": disputes_by_inv.get(inv["invoice_id"]),
        })

    hist_by_cust: dict[str, list[dict]] = defaultdict(list)
    for h in ds.history:
        hist_by_cust[h["customer_id"]].append(h)

    customers = []
    for cid, cust in sorted(ds.customers.items()):
        invs = sorted(inv_by_cust.get(cid, []), key=lambda i: -i["days_past_due"])
        open_bal = sum(i["open_amount"] for i in invs)
        past_due = [i for i in invs if i["days_past_due"] > 0]
        dunnable = [i for i in past_due if not i["disputed"]]
        disputed = [i for i in invs if i["disputed"]]
        bal_61 = sum(i["open_amount"] for i in invs if i["days_past_due"] >= 61 and not i["disputed"])
        max_dpd = max((i["days_past_due"] for i in dunnable), default=0)
        util = open_bal / cust["credit_limit"] if cust["credit_limit"] else 0.0
        trend = calc.payment_trend(hist_by_cust.get(cid, []), as_of,
                                   [i["days_past_due"] for i in dunnable])

        if dunnable:
            action = "DUN"
        elif disputed:
            action = "DISPUTE"
        else:
            action = "NO_ACTION"
        tier = calc.tier_for(max_dpd) if action == "DUN" else None

        hold, hold_reason = False, None
        if tier == "final":
            hold, hold_reason = True, f"Oldest undisputed item is {max_dpd} days past due (90+)"
        elif util > C.HOLD_UTILIZATION and max_dpd >= C.HOLD_MIN_DAYS_PAST_DUE:
            hold, hold_reason = True, (f"Open AR is {util:.0%} of credit limit with an item "
                                       f"{max_dpd} days past due")

        risk = calc.risk_score(
            open_balance=open_bal, balance_61_plus=bal_61, max_dpd=max_dpd,
            trend_delta=trend["delta_days"], utilization=util,
            recent_avg_days_late=trend["recent_avg_days_late"], has_open_dispute=bool(disputed),
        )
        past_due_undisputed = sum(i["open_amount"] for i in dunnable)

        customers.append({
            "customer_id": cid,
            "customer_name": cust["customer_name"],
            "segment": cust["segment"],
            "payment_terms_days": cust["payment_terms_days"],
            "credit_limit": cust["credit_limit"],
            "account_owner": cust["account_owner"],
            "account_owner_email": cust["account_owner_email"],
            "ar_contact_email": cust["ar_contact_email"],
            "open_balance": round(open_bal, 2),
            "past_due_undisputed": round(past_due_undisputed, 2),
            "disputed_balance": round(sum(i["open_amount"] for i in disputed), 2),
            "credit_utilization": round(util, 3),
            "aging": calc.aging_summary(invs),
            "max_days_past_due_undisputed": max_dpd,
            "action": action,
            "tier": tier,
            "tier_name": calc.tier_name(tier),
            "hold_recommended": hold,
            "hold_reason": hold_reason,
            "dunnable_invoice_ids": [i["invoice_id"] for i in dunnable],
            "disputed_invoice_ids": [i["invoice_id"] for i in disputed],
            "invoices": invs,
            "trend": trend,
            "risk": risk,
            # expected loss on undisputed past-due items, scaled up by risk score
            "priority_value": round(sum(i["open_amount"] * C.RESERVE_RATES[i["bucket"]] for i in dunnable)
                                    * (1 + risk["score"] / 100), 2),
        })

    # Priority: dunning worklist ranked by risk-weighted expected loss
    worklist = sorted((c for c in customers if c["action"] == "DUN"),
                      key=lambda c: (-c["priority_value"], -c["max_days_past_due_undisputed"]))
    for rank, c in enumerate(worklist, 1):
        c["priority_rank"] = rank

    # --- portfolio metrics ----------------------------------------------------
    all_invs = [i for c in customers for i in c["invoices"]]
    total_ar = sum(i["open_amount"] for i in all_invs)
    aging = calc.aging_summary(all_invs)

    unified = [{"invoice_date": h["invoice_date"], "amount": h["invoice_amount"],
                "paid_date": h["paid_date"], "open_amount": 0.0} for h in ds.history]
    unified += [{"invoice_date": i["invoice_date"], "amount": i["original_amount"],
                 "paid_date": None, "open_amount": i["open_amount"]} for i in ds.open_invoices]
    sales_90 = calc.sales_between(unified, as_of - timedelta(days=C.DSO_SALES_WINDOW_DAYS), as_of)
    dso = calc.dso(total_ar, sales_90, C.DSO_SALES_WINDOW_DAYS)
    bpdso = calc.dso(aging["current"], sales_90, C.DSO_SALES_WINDOW_DAYS)

    high_risk_pd = sum(c["past_due_undisputed"] for c in customers if c["risk"]["band"] == "High")
    disputed_total = sum(c["disputed_balance"] for c in customers)
    expected_loss = sum(i["open_amount"] * C.RESERVE_RATES[i["bucket"]] for i in all_invs)

    portfolio = {
        "total_ar": round(total_ar, 2),
        "current": aging["current"],
        "past_due": round(total_ar - aging["current"], 2),
        "pct_past_due": round((total_ar - aging["current"]) / total_ar, 4) if total_ar else 0,
        "aging": aging,
        "sales_last_90d": round(sales_90, 2),
        "dso": dso,
        "best_possible_dso": bpdso,
        "average_days_delinquent": round(dso - bpdso, 1) if dso is not None and bpdso is not None else None,
        "dso_trend": calc.dso_trend(unified, as_of, C.DSO_TREND_MONTHS),
        "cash_at_risk": {
            "high_risk_past_due": round(high_risk_pd, 2),
            "disputed": round(disputed_total, 2),
            "total": round(high_risk_pd + disputed_total, 2),
        },
        "expected_loss_reserve_method": round(expected_loss, 2),
        "counts": {
            "customers": len(customers),
            "dun": sum(c["action"] == "DUN" for c in customers),
            "dispute_only": sum(c["action"] == "DISPUTE" for c in customers),
            "no_action": sum(c["action"] == "NO_ACTION" for c in customers),
            "deteriorating": sum(c["trend"]["status"] == "DETERIORATING" for c in customers),
            "hold_recommended": sum(c["hold_recommended"] for c in customers),
            "by_tier": {t: sum(c["tier"] == t for c in customers) for t, *_ in C.TIERS},
        },
    }

    return {
        "run_id": run_id,
        "as_of": as_of.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_hashes": ds.file_hashes,
        "policy": _policy_snapshot(),
        "portfolio": portfolio,
        "worklist": [c["customer_id"] for c in worklist],
        "watchlist": [c["customer_id"] for c in customers if c["trend"]["status"] == "DETERIORATING"],
        "dispute_queue": [
            {"customer_id": c["customer_id"], "customer_name": c["customer_name"], **i["dispute"],
             "open_amount": i["open_amount"], "days_past_due": i["days_past_due"]}
            for c in customers for i in c["invoices"] if i["disputed"]
        ],
        "customers": customers,
    }
