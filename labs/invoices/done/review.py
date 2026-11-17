"""Part 2, step 2: store every invoice, and a review queue for the ones the checks don't trust.

One SQLite table. Each row is one invoice with its provenance: the file and
its hash, the model, the prompt version, the extracted JSON, the reasons it
needs a person, and who approved it (the pipeline, or a person).

Two keys keep it safe to run twice:
  - sha256 of the file:              the same file twice is stored once
  - supplier GSTIN + invoice number: the same invoice as a PDF and a photo is held

The CLI, for the person doing the review:
    uv run python labs/invoices/done/review.py list
    uv run python labs/invoices/done/review.py show 4
    uv run python labs/invoices/done/review.py approve 4 --set total_inr=279104 --note "total misprinted, confirmed with supplier"
    uv run python labs/invoices/done/review.py reject 8 --note "wrong GST rate, asked for a corrected invoice"
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # the repo root, where shopkart/ lives
sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks import inr  # noqa: E402
from shopkart import budget  # noqa: E402

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id              INTEGER PRIMARY KEY,
    file            TEXT NOT NULL,
    sha256          TEXT NOT NULL UNIQUE,
    supplier_gstin  TEXT,
    invoice_number  TEXT,
    total_inr       REAL,
    status          TEXT NOT NULL,          -- approved | review | rejected | duplicate
    reasons         TEXT NOT NULL,          -- JSON list of "code: message"
    data            TEXT,                   -- the invoice as the model read it, as JSON (never edited)
    corrections     TEXT NOT NULL DEFAULT '{}',  -- what a person changed: labelled examples
    decided_by      TEXT,                   -- pipeline | person
    note            TEXT,
    model           TEXT,
    prompt_version  TEXT,
    cost_usd        REAL,
    created_at      TEXT NOT NULL,
    decided_at      TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS business_key ON invoices (supplier_gstin, invoice_number)
    WHERE status IN ('approved', 'review');  -- one live row per supplier invoice
"""


def default_db() -> Path:
    return budget.LEDGER_DIR / "invoices.db"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ReviewQueue:
    def __init__(self, path: Path | str | None = None):
        path = Path(path) if path else default_db()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def store(self, *, file: str, sha256: str, data: dict | None, reasons: list[str],
              model: str, prompt_version: str, cost_usd: float) -> tuple[int, str, bool]:
        """Route one invoice: no reasons -> approved by the pipeline; any reason -> review.

        Returns (id, status, new). Idempotent: a file already stored comes back
        as it is, with whatever a person already decided about it.
        """
        old = self.db.execute("SELECT id, status FROM invoices WHERE sha256 = ?", (sha256,)).fetchone()
        if old:
            return old["id"], old["status"], False

        data = data or {}
        gstin, number = data.get("supplier_gstin"), data.get("invoice_number")
        status = "review" if reasons else "approved"
        if gstin and number:
            dup = self.db.execute(
                "SELECT id, file FROM invoices WHERE supplier_gstin = ? AND invoice_number = ? "
                "AND status IN ('approved', 'review')", (gstin, number)).fetchone()
            if dup:
                status = "duplicate"
                reasons = [*reasons, f"duplicate: same supplier and invoice number as #{dup['id']} ({dup['file']})"]

        cur = self.db.execute(
            "INSERT INTO invoices (file, sha256, supplier_gstin, invoice_number, total_inr, status, reasons,"
            " data, decided_by, model, prompt_version, cost_usd, created_at, decided_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (file, sha256, gstin, number, data.get("total_inr"), status, json.dumps(reasons),
             json.dumps(data), "pipeline" if status == "approved" else None, model, prompt_version,
             cost_usd, _now(), _now() if status == "approved" else None))
        self.db.commit()
        return cur.lastrowid, status, True

    def rows(self, status: str | None = None) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM invoices", ()
        if status:
            sql, args = sql + " WHERE status = ?", (status,)
        return self.db.execute(sql + " ORDER BY id", args).fetchall()

    def get(self, invoice_id: int) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if row is None:
            raise KeyError(f"No invoice #{invoice_id}")
        return row

    def decide(self, invoice_id: int, approve: bool, note: str = "",
               fixes: dict[str, object] | None = None) -> sqlite3.Row:
        """A person approves (optionally correcting fields) or rejects one queued invoice."""
        row = self.get(invoice_id)
        if row["status"] not in ("review", "duplicate"):
            raise ValueError(f"#{invoice_id} is {row['status']}, not waiting for review")
        data = json.loads(row["data"] or "{}")
        corrections = {k: {"was": data.get(k), "now": v} for k, v in (fixes or {}).items()}
        final = {**data, **(fixes or {})}
        try:
            self.db.execute(
                "UPDATE invoices SET status = ?, corrections = ?, total_inr = ?, decided_by = 'person',"
                " note = ?, decided_at = ? WHERE id = ?",
                ("approved" if approve else "rejected", json.dumps(corrections),
                 final.get("total_inr"), note, _now(), invoice_id))
        except sqlite3.IntegrityError:
            raise ValueError(f"#{invoice_id} is a duplicate of an invoice already stored: reject one of them") from None
        self.db.commit()
        return self.get(invoice_id)

    @staticmethod
    def final(row: sqlite3.Row) -> dict:
        """The invoice as approved: the model's reading plus a person's corrections."""
        data = json.loads(row["data"] or "{}")
        data.update({k: c["now"] for k, c in json.loads(row["corrections"]).items()})
        return data


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _value(text: str) -> object:
    """--set total_inr=279104 -> 279104.0; --set supplier_gstin=27ABC... -> the string."""
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None if text.lower() == "null" else text


def _line(row: sqlite3.Row) -> str:
    total = inr(row["total_inr"]) if row["total_inr"] is not None else "-"
    who = f" by {row['decided_by']}" if row["decided_by"] else ""
    return f"#{row['id']:<3}{row['file']:<34}{total:>15}  {row['status']}{who}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ShopKart's invoice review queue.")
    parser.add_argument("--db", default=None, help="default: .shopkart/invoices.db")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="invoices and their status (default: waiting for review)")
    ls.add_argument("--all", action="store_true")
    show = sub.add_parser("show", help="one invoice: fields and reasons")
    show.add_argument("id", type=int)
    for name in ("approve", "reject"):
        p = sub.add_parser(name)
        p.add_argument("id", type=int)
        p.add_argument("--note", default="")
        if name == "approve":
            p.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE",
                           help="correct a field before approving (saved as a correction)")
    args = parser.parse_args(argv)
    queue = ReviewQueue(args.db)

    if args.cmd == "list":
        rows = queue.rows() if args.all else [*queue.rows("review"), *queue.rows("duplicate")]
        for row in rows:
            print(_line(row))
            if row["status"] in ("review", "duplicate"):
                for reason in json.loads(row["reasons"]):
                    print(f"     - {reason}")
        waiting = len(queue.rows("review")) + len(queue.rows("duplicate"))
        print(f"\n{waiting} waiting for review" + ("" if args.all else " (--all shows every invoice)"))
        return 0

    try:
        if args.cmd == "show":
            row = queue.get(args.id)
            print(_line(row))
            for reason in json.loads(row["reasons"]):
                print(f"  - {reason}")
            print(json.dumps(queue.final(row), indent=2, ensure_ascii=False))
            print(f"model {row['model']} · prompt {row['prompt_version']} · sha256 {row['sha256'][:12]}…")
            return 0
        fixes = {}
        for item in getattr(args, "set", []):
            key, _, value = item.partition("=")
            fixes[key] = _value(value)
        row = queue.decide(args.id, args.cmd == "approve", args.note, fixes)
    except (KeyError, ValueError) as err:
        print(err.args[0], file=sys.stderr)
        return 1
    print(_line(row) + (f" · note: {row['note']}" if row["note"] else ""))
    for key, change in json.loads(row["corrections"]).items():
        print(f"  corrected {key}: {change['was']} -> {change['now']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
