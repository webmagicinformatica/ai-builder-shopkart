"""Where refunds and the audit trail live: .shopkart/capstone-action-agent/ (gitignored).

    refunds.json   every refund: issued at once (small, inside policy) or pending approval
    audit.jsonl    one line per event, append only, each line chained to the one before

The chain: every row stores the hash of the row before it. Edit or delete an old
line and `verify()` points at the first line that no longer fits.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from shopkart import budget

APPROVAL_EXPIRES = timedelta(hours=48)  # an approval request that waits longer is re-checked from scratch


def store_dir() -> Path:
    return budget.LEDGER_DIR / "capstone-action-agent"


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


# ---------------------------------------------------------------- refunds


def load() -> list[dict]:
    path = store_dir() / "refunds.json"
    return json.loads(path.read_text()) if path.exists() else []


def save(rows: list[dict]) -> None:
    path = store_dir() / "refunds.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def issued_on(order_id: str) -> int:
    return sum(r["amount_inr"] for r in load() if r["order_id"] == order_id and r["status"] == "issued")


def open_request(order_id: str) -> dict | None:
    return next((r for r in load() if r["order_id"] == order_id and r["status"] == "pending"), None)


def requests_by(customer_id: str) -> int:
    return sum(1 for r in load() if r["customer_id"] == customer_id and r["status"] != "rejected")


def auto_today() -> int:
    today = date.today().isoformat()
    return sum(r["amount_inr"] for r in load()
               if r["approved_by"] == "auto" and r["created"][:10] == today)


def add(row: dict) -> dict:
    rows = load()
    n = sum(r["order_id"] == row["order_id"] for r in rows) + 1
    row = {"id": f"{'AP' if row['status'] == 'pending' else 'RF'}-{row['order_id'][2:]}-{n}",
           "created": now().isoformat(), **row}
    rows.append(row)
    save(rows)
    return row


def update(row_id: str, **changes: Any) -> dict:
    rows = load()
    row = next(r for r in rows if r["id"] == row_id)
    row.update(changes)
    save(rows)
    return row


def get(row_id: str) -> dict | None:
    return next((r for r in load() if r["id"] == row_id), None)


# ---------------------------------------------------------------- audit trail


def _hash(row: dict) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def audit(event: str, **details: Any) -> dict:
    """Append one event. Who, what, why, the decision and the result."""
    path = store_dir() / "audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text().splitlines() if path.exists() else []
    prev = json.loads(lines[-1])["hash"] if lines else "start"
    row = {"time": now().isoformat(), "event": event, **details, "prev": prev}
    row["hash"] = _hash(row)
    with path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def read_audit() -> list[dict]:
    path = store_dir() / "audit.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def verify() -> tuple[bool, str]:
    """Walk the chain. Returns (ok, message)."""
    prev = "start"
    rows = read_audit()
    for n, row in enumerate(rows, 1):
        body = {k: v for k, v in row.items() if k != "hash"}
        if row.get("prev") != prev or _hash(body) != row.get("hash"):
            return False, f"line {n} was changed or a line before it was removed"
        prev = row["hash"]
    return True, f"{len(rows)} lines, chain intact"
