"""Append-only, hash-chained audit log (one JSONL file per run).

Each entry stores the SHA-256 of the previous entry, so any edit or deletion
of an earlier line breaks the chain and `verify()` reports it."""
from __future__ import annotations

import getpass
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


def _hash(entry: dict) -> str:
    return hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()


def _last_hash(path: Path) -> str:
    if not path.exists():
        return GENESIS
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    return json.loads(lines[-1])["entry_hash"] if lines else GENESIS


def log(run_dir: Path, event: str, actor: str | None = None, **details) -> dict:
    path = Path(run_dir) / "audit_log.jsonl"
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        "actor": actor or getpass.getuser(),
        "details": details,
        "prev_hash": _last_hash(path),
    }
    entry["entry_hash"] = _hash(entry)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def verify(run_dir: Path) -> tuple[bool, str]:
    path = Path(run_dir) / "audit_log.jsonl"
    if not path.exists():
        return False, "no audit log"
    prev = GENESIS
    for n, line in enumerate(path.read_text().splitlines(), 1):
        e = json.loads(line)
        stored = e.pop("entry_hash")
        if e["prev_hash"] != prev or _hash(e) != stored:
            return False, f"chain broken at line {n}"
        prev = stored
    return True, f"{n} entries, chain intact"
