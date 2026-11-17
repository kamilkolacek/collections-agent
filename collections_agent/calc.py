"""Deterministic math: aging buckets, days-late trends, DSO, risk score inputs,
cash-at-risk. No judgment lives here - only arithmetic that can be unit-tested."""
from __future__ import annotations

from datetime import date, timedelta
from statistics import mean

from . import config as C


# ----------------------------------------------------------------- aging -----
def days_past_due(due: date, as_of: date) -> int:
    return (as_of - due).days


def bucket(dpd: int) -> str:
    for label, lo, hi in C.BUCKETS:
        if (lo is None or dpd >= lo) and (hi is None or dpd <= hi):
            return label
    raise ValueError(dpd)


def tier_for(dpd: int) -> str | None:
    for tier, lo, hi, _ in C.TIERS:
        if dpd >= lo and (hi is None or dpd <= hi):
            return tier
    return None


def tier_name(tier: str | None) -> str:
    return next((name for t, _, _, name in C.TIERS if t == tier), "No action")


def aging_summary(invoices: list[dict]) -> dict[str, float]:
    out = {label: 0.0 for label, _, _ in C.BUCKETS}
    for inv in invoices:
        out[inv["bucket"]] += inv["open_amount"]
    return {k: round(v, 2) for k, v in out.items()}


# ----------------------------------------------------------------- trend -----
def _slope(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mx, my = mean(xs), mean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return 0.0 if den == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def payment_trend(history: list[dict], as_of: date, open_past_due_dpd: list[int] | None = None) -> dict:
    """Compare days late on payments received in the last 90 days with the
    9 months before that. Uses paid_date windows so the measure reflects how
    the customer is paying *now*.

    A customer who has stopped paying has no recent payments to measure, which
    is itself the strongest deterioration signal. In that case the oldest open
    (undisputed) past-due item stands in for "recent days late"."""
    open_past_due_dpd = open_past_due_dpd or []
    recent_start = as_of - timedelta(days=C.TREND_RECENT_WINDOW_DAYS)
    lookback_start = as_of - timedelta(days=C.TREND_LOOKBACK_DAYS)
    pts = sorted(
        ((h["paid_date"], (h["paid_date"] - h["due_date"]).days)
         for h in history if lookback_start < h["paid_date"] <= as_of),
    )
    recent = [dl for pd, dl in pts if pd > recent_start]
    base = [dl for pd, dl in pts if pd <= recent_start]

    res = {
        "payments_12m": len(pts),
        "avg_days_late_12m": round(mean(dl for _, dl in pts), 1) if pts else None,
        "recent_avg_days_late": round(mean(recent), 1) if recent else None,
        "baseline_avg_days_late": round(mean(base), 1) if base else None,
        "delta_days": None,
        "signal": None,
        "slope_days_per_month": round(_slope([(p - pts[0][0]).days / 30.4 for p, _ in pts],
                                             [dl for _, dl in pts]), 2) if len(pts) > 1 else 0.0,
        "days_late_by_payment": [{"paid_date": p.isoformat(), "days_late": dl} for p, dl in pts],
    }
    if len(base) < C.TREND_MIN_BASELINE_PAYMENTS:
        res["status"] = "INSUFFICIENT_HISTORY"
        return res

    if not recent:
        oldest = max(open_past_due_dpd, default=0)
        delta = oldest - mean(base)
        if open_past_due_dpd and delta >= C.DETERIORATING_DELTA_DAYS:
            res.update(status="DETERIORATING", delta_days=round(delta, 1),
                       signal=f"No payments received in {C.TREND_RECENT_WINDOW_DAYS} days; "
                              f"oldest open item is {oldest} days past due vs "
                              f"{mean(base):.0f}-day historical average")
        else:
            res["status"] = "INSUFFICIENT_HISTORY"
        return res

    delta = mean(recent) - mean(base)
    res["delta_days"] = round(delta, 1)
    if delta >= C.DETERIORATING_DELTA_DAYS:
        res["status"] = "DETERIORATING"
        res["signal"] = (f"Paying {mean(recent):.0f} days late in the last {C.TREND_RECENT_WINDOW_DAYS} "
                         f"days vs {mean(base):.0f} days before that")
    elif delta <= C.IMPROVING_DELTA_DAYS:
        res["status"] = "IMPROVING"
    elif mean(recent) >= C.CHRONIC_LATE_DAYS:
        res["status"] = "CHRONIC_LATE"
    else:
        res["status"] = "STABLE"
    return res


# ------------------------------------------------------------------ risk -----
def risk_score(*, open_balance: float, balance_61_plus: float, max_dpd: int,
               trend_delta: float | None, utilization: float,
               recent_avg_days_late: float | None, has_open_dispute: bool) -> dict:
    W = C.RISK_WEIGHTS
    comp = {
        "aging_severity": W["aging_severity"] * (balance_61_plus / open_balance if open_balance else 0),
        "max_days_past_due": W["max_days_past_due"] * min(max(max_dpd, 0), 120) / 120,
        "trend": W["trend"] * min(max(trend_delta or 0, 0), 30) / 30,
        "credit_utilization": W["credit_utilization"] * min(utilization, 1.5) / 1.5,
        "chronic_lateness": W["chronic_lateness"] * min(max(recent_avg_days_late or 0, 0), 60) / 60,
        "open_dispute": W["open_dispute"] if has_open_dispute else 0,
    }
    comp = {k: round(v, 1) for k, v in comp.items()}
    score = round(sum(comp.values()), 1)
    band = next(b for b, floor in C.RISK_BANDS if score >= floor)
    return {"score": score, "band": band, "components": comp}


# ------------------------------------------------------------------- DSO -----
def _month_end(y: int, m: int) -> date:
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return nxt - timedelta(days=1)


def ar_balance_at(all_invoices: list[dict], d: date) -> float:
    """AR outstanding at date d, rebuilt from invoice + payment dates."""
    total = 0.0
    for inv in all_invoices:
        if inv["invoice_date"] > d:
            continue
        if inv["paid_date"] is None:
            # still open at as-of; partial payments are treated as received before d
            total += inv["open_amount"]
        elif inv["paid_date"] > d:
            total += inv["amount"]
    return total


def sales_between(all_invoices: list[dict], start: date, end: date) -> float:
    return sum(inv["amount"] for inv in all_invoices if start < inv["invoice_date"] <= end)


def dso(ar: float, sales: float, days: int) -> float | None:
    return round(ar / sales * days, 1) if sales else None


def dso_trend(all_invoices: list[dict], as_of: date, months: int) -> list[dict]:
    out = []
    y, m = as_of.year, as_of.month
    for _ in range(months):
        me = _month_end(y, m) if (y, m) != (as_of.year, as_of.month) else as_of
        ar = ar_balance_at(all_invoices, me)
        sales = sales_between(all_invoices, me - timedelta(days=C.DSO_SALES_WINDOW_DAYS), me)
        out.append({"period_end": me.isoformat(), "ar_balance": round(ar, 2),
                    "sales_90d": round(sales, 2), "dso": dso(ar, sales, C.DSO_SALES_WINDOW_DAYS)})
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(out))
