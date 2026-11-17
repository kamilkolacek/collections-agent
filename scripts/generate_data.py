"""Generate the synthetic Lumina Streaming Co. AR dataset.

Everything here is fictional. Customer names, contacts and amounts are invented
for demo purposes. Re-running this script is deterministic (fixed seed), so the
committed CSVs in data/ always match what it produces.

Usage:
    python scripts/generate_data.py            # writes data/*.csv
    python scripts/generate_data.py --out tmp  # writes somewhere else
"""
from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

AS_OF = date(2026, 10, 31)
FIRST_INVOICE_MONTH = (2025, 10)  # Oct 2025 .. Oct 2026 = 13 monthly invoices
N_MONTHS = 13
SEED = 42

OWNERS = {
    "Priya Shah": "priya.shah@luminastreaming.example",
    "Marcus Lee": "marcus.lee@luminastreaming.example",
    "Dana Ortiz": "dana.ortiz@luminastreaming.example",
    "Tom Becker": "tom.becker@luminastreaming.example",
}

# Each profile drives a monthly invoice series and how late it gets paid.
#   start/end      : days late at month 0 and month 12 (linear in between)
#   stop_from      : invoices dated on/after this stay unpaid
#   force_open     : list of (year, month) invoices that stay unpaid
#   partial        : {(year, month): amount_paid} partial payments on unpaid invoices
#   disputes       : {(year, month): (reason, disputed_amount)}
PROFILES = [
    dict(id="C-1001", name="Brightline Ad Agency", seg="Enterprise", limit=600_000, terms=45, day=7,
         amt=150_000, start=2, end=3, owner="Priya Shah"),
    dict(id="C-1002", name="Harbor Hotels Group", seg="Mid-Market", limit=90_000, terms=30, day=22,
         amt=31_000, start=12, end=14, owner="Marcus Lee"),
    # EVAL-01: trends from ~15 to ~45 days late -> must be flagged as deteriorating
    dict(id="C-1003", name="Northwind Media Partners", seg="Enterprise", limit=650_000, terms=45, day=10,
         amt=185_000, start=15, end=45, owner="Priya Shah"),
    # EVAL-05: chronically ~55 days late but stable -> chronic, NOT deteriorating
    dict(id="C-1004", name="Cedar Valley Cable", seg="Mid-Market", limit=150_000, terms=30, day=25,
         amt=42_000, start=55, end=55, owner="Dana Ortiz"),
    # EVAL-04: 90+ days and over credit limit -> final notice + credit hold recommendation
    dict(id="C-1005", name="Polaris Fitness Studios", seg="SMB", limit=25_000, terms=30, day=15,
         amt=9_500, start=10, end=30, stop_from=date(2026, 6, 1), owner="Tom Becker"),
    # EVAL-02: only past-due invoice is disputed -> dispute handling, no dunning email
    dict(id="C-1006", name="Summit Airlines Inflight", seg="Enterprise", limit=500_000, terms=45, day=1,
         amt=120_000, start=3, end=3, owner="Marcus Lee",
         disputes={(2026, 7): ("Pricing - invoice billed at list rate, contract rate is 15% lower", 18_000)}),
    # EVAL-07: 61-90 days -> escalation tier
    dict(id="C-1007", name="Redwood Sports Bars", seg="SMB", limit=30_000, terms=30, day=20,
         amt=6_200, start=8, end=18, stop_from=date(2026, 7, 15), owner="Tom Becker"),
    # EVAL-03: one disputed invoice + one undisputed 31-60 invoice -> dun only the undisputed one
    dict(id="C-1008", name="Atlas Education Network", seg="Mid-Market", limit=120_000, terms=30, day=12,
         amt=28_000, start=30, end=36, owner="Dana Ortiz", force_open=[(2026, 8)],
         disputes={(2026, 9): ("Service credit - 3-day platform outage in September not credited", 8_400)}),
    dict(id="C-1009", name="Blue Fjord Distribution", seg="Enterprise", limit=400_000, terms=45, day=3,
         amt=88_000, start=-2, end=0, owner="Priya Shah"),
    # EVAL-06: SMB trending 5 -> 28 days late; only 1-30 bucket today but must be on watchlist
    dict(id="C-1010", name="Meridian Retail Displays", seg="SMB", limit=20_000, terms=30, day=8,
         amt=4_800, start=5, end=28, owner="Tom Becker"),
    dict(id="C-1011", name="Quantum Telecom", seg="Enterprise", limit=900_000, terms=45, day=15,
         amt=310_000, start=4, end=6, owner="Marcus Lee"),
    # EVAL-08: improving payer with one stranded 61-90 invoice -> escalation tier, NOT deteriorating
    dict(id="C-1012", name="Lakeside Cinemas", seg="Mid-Market", limit=80_000, terms=30, day=18,
         amt=15_500, start=50, end=22, owner="Dana Ortiz", force_open=[(2026, 7)]),
    # EVAL-09: small balance 90+ -> still final notice regardless of size
    dict(id="C-1013", name="Orchid Wellness Apps", seg="SMB", limit=5_000, terms=30, day=2,
         amt=900, start=5, end=10, stop_from=date(2026, 7, 1), owner="Tom Becker"),
    # EVAL-02b: every past-due invoice disputed -> dispute routing only
    dict(id="C-1014", name="Ironwood Gyms", seg="SMB", limit=25_000, terms=30, day=6,
         amt=5_500, start=5, end=5, owner="Tom Becker",
         disputes={(2026, 8): ("Service outage - streaming down at 4 locations for 2 weeks", 5_500),
                   (2026, 9): ("Service outage - streaming down at 4 locations for 2 weeks", 5_500)}),
    dict(id="C-1015", name="Sterling Cruise Lines", seg="Enterprise", limit=350_000, terms=45, day=12,
         amt=95_000, start=12, end=20, owner="Priya Shah"),
    dict(id="C-1016", name="Vantage Car Rentals", seg="Mid-Market", limit=70_000, terms=30, day=25,
         amt=22_000, start=0, end=2, owner="Marcus Lee"),
    # EVAL-10: drifting later but below the 10-day threshold -> NOT flagged
    dict(id="C-1017", name="Pinecrest Senior Living", seg="SMB", limit=15_000, terms=30, day=28,
         amt=3_900, start=18, end=25, owner="Dana Ortiz"),
    # EVAL-11: enterprise, stopped paying in June, partial payment, over limit -> final notice + hold
    dict(id="C-1018", name="Horizon Sports Network", seg="Enterprise", limit=400_000, terms=45, day=1,
         amt=140_000, start=20, end=35, stop_from=date(2026, 6, 1), owner="Marcus Lee",
         partial={(2026, 6): 60_000}),
    dict(id="C-1019", name="Golden Gate Podcasts", seg="SMB", limit=10_000, terms=30, day=14,
         amt=2_400, start=1, end=1, owner="Tom Becker"),
    dict(id="C-1020", name="Evergreen Transit Ads", seg="Mid-Market", limit=60_000, terms=30, day=9,
         amt=18_500, start=12, end=12, owner="Dana Ortiz"),
]


def month_iter():
    y, m = FIRST_INVOICE_MONTH
    for _ in range(N_MONTHS):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def slug(name: str) -> str:
    return "".join(c for c in name.lower().replace(" ", "-") if c.isalnum() or c == "-")


def build(out: Path) -> None:
    rng = random.Random(SEED)
    out.mkdir(parents=True, exist_ok=True)

    customers, history, aging, disputes = [], [], [], []
    dispute_seq = 1

    for p in PROFILES:
        domain = slug(p["name"]) + ".example"
        customers.append({
            "customer_id": p["id"],
            "customer_name": p["name"],
            "segment": p["seg"],
            "credit_limit": p["limit"],
            "payment_terms_days": p["terms"],
            "account_owner": p["owner"],
            "account_owner_email": OWNERS[p["owner"]],
            "ar_contact_email": f"ap@{domain}",
            "currency": "USD",
        })

        cust_num = p["id"].split("-")[1]
        for i, (y, m) in enumerate(month_iter()):
            inv_date = date(y, m, p["day"])
            due = inv_date + timedelta(days=p["terms"])
            inv_id = f"INV-{cust_num}-{y}{m:02d}"
            # small variation in monthly billing so amounts aren't identical
            amount = round(p["amt"] * rng.uniform(0.94, 1.06), 2) if p["amt"] > 1000 else float(p["amt"])

            late = p["start"] + (p["end"] - p["start"]) * i / (N_MONTHS - 1) + rng.randint(-2, 2)
            late = round(late)
            paid = due + timedelta(days=late)

            disputed = (y, m) in p.get("disputes", {})
            unpaid = (
                disputed
                or (p.get("stop_from") and inv_date >= p["stop_from"])
                or (y, m) in p.get("force_open", [])
                or paid > AS_OF
            )

            if unpaid:
                paid_partial = p.get("partial", {}).get((y, m), 0.0)
                aging.append({
                    "as_of_date": AS_OF.isoformat(),
                    "customer_id": p["id"],
                    "invoice_id": inv_id,
                    "invoice_date": inv_date.isoformat(),
                    "due_date": due.isoformat(),
                    "original_amount": f"{amount:.2f}",
                    "open_amount": f"{amount - paid_partial:.2f}",
                    "currency": "USD",
                })
                if disputed:
                    reason, amt = p["disputes"][(y, m)]
                    disputes.append({
                        "dispute_id": f"DSP-{dispute_seq:03d}",
                        "customer_id": p["id"],
                        "invoice_id": inv_id,
                        "opened_date": (due + timedelta(days=5)).isoformat(),
                        "reason": reason,
                        "disputed_amount": f"{min(amt, amount):.2f}",
                        "status": "Open",
                        "dispute_owner": p["owner"],
                    })
                    dispute_seq += 1
            else:
                history.append({
                    "customer_id": p["id"],
                    "invoice_id": inv_id,
                    "invoice_date": inv_date.isoformat(),
                    "due_date": due.isoformat(),
                    "invoice_amount": f"{amount:.2f}",
                    "paid_date": paid.isoformat(),
                    "paid_amount": f"{amount:.2f}",
                })

    def write(name, rows):
        with open(out / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    write("customer_master.csv", customers)
    write("payment_history.csv", sorted(history, key=lambda r: (r["customer_id"], r["invoice_date"])))
    write("ar_aging.csv", sorted(aging, key=lambda r: (r["customer_id"], r["invoice_date"])))
    write("disputes.csv", disputes)
    print(f"Wrote {len(customers)} customers, {len(history)} paid invoices, "
          f"{len(aging)} open invoices, {len(disputes)} disputes to {out}/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data"))
    build(Path(ap.parse_args().out))
