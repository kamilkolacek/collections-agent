"""Load and validate the four input files. Fails loudly on bad data rather than
guessing - a collections run on a broken aging report should not happen."""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REQUIRED = {
    "customer_master.csv": ["customer_id", "customer_name", "segment", "credit_limit",
                            "payment_terms_days", "account_owner", "account_owner_email",
                            "ar_contact_email"],
    "ar_aging.csv": ["customer_id", "invoice_id", "invoice_date", "due_date",
                     "original_amount", "open_amount"],
    "payment_history.csv": ["customer_id", "invoice_id", "invoice_date", "due_date",
                            "invoice_amount", "paid_date", "paid_amount"],
    "disputes.csv": ["dispute_id", "customer_id", "invoice_id", "reason",
                     "disputed_amount", "status"],
}


class DataError(ValueError):
    pass


@dataclass
class Dataset:
    customers: dict[str, dict]
    open_invoices: list[dict]
    history: list[dict]
    disputes: list[dict]
    file_hashes: dict[str, str] = field(default_factory=dict)

    @property
    def open_dispute_invoice_ids(self) -> set[str]:
        return {d["invoice_id"] for d in self.disputes if d["status"].lower() == "open"}


def _read(path: Path) -> list[dict]:
    if not path.exists():
        raise DataError(f"Missing input file: {path}")
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    missing = [c for c in REQUIRED[path.name] if rows and c not in rows[0]]
    if missing:
        raise DataError(f"{path.name} is missing columns: {missing}")
    return rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(data_dir: str | Path) -> Dataset:
    d = Path(data_dir)
    cust_rows = _read(d / "customer_master.csv")
    customers = {}
    for r in cust_rows:
        r["credit_limit"] = float(r["credit_limit"])
        r["payment_terms_days"] = int(r["payment_terms_days"])
        customers[r["customer_id"]] = r

    open_inv = _read(d / "ar_aging.csv")
    for r in open_inv:
        r["invoice_date"] = date.fromisoformat(r["invoice_date"])
        r["due_date"] = date.fromisoformat(r["due_date"])
        r["original_amount"] = float(r["original_amount"])
        r["open_amount"] = float(r["open_amount"])
        if r["customer_id"] not in customers:
            raise DataError(f"ar_aging.csv: {r['invoice_id']} has unknown customer {r['customer_id']}")
        if r["open_amount"] > r["original_amount"] + 0.005:
            raise DataError(f"ar_aging.csv: {r['invoice_id']} open amount exceeds original amount")

    hist = _read(d / "payment_history.csv")
    for r in hist:
        for k in ("invoice_date", "due_date", "paid_date"):
            r[k] = date.fromisoformat(r[k])
        r["invoice_amount"] = float(r["invoice_amount"])
        r["paid_amount"] = float(r["paid_amount"])

    disputes = _read(d / "disputes.csv")
    open_ids = {r["invoice_id"] for r in open_inv}
    for r in disputes:
        r["disputed_amount"] = float(r["disputed_amount"])
        if r["status"].lower() == "open" and r["invoice_id"] not in open_ids:
            raise DataError(f"disputes.csv: {r['dispute_id']} references {r['invoice_id']}, "
                            "which is not on the open AR aging")

    ids = [r["invoice_id"] for r in open_inv]
    if len(ids) != len(set(ids)):
        raise DataError("ar_aging.csv contains duplicate invoice_ids")

    hashes = {name: _sha256(d / name) for name in REQUIRED}
    return Dataset(customers, open_inv, hist, disputes, hashes)
