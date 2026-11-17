"""Part 2, last step: measure. Field by field, against data/invoices/expected.json.

Both sides are normalised first, so "SFI-2611-077" and "sfi 2611 077" match,
and amounts match within 50 paise. We score the model's own reading, before
any person's corrections.

Three numbers:
  - field accuracy, per field: where to work next
  - straight-through: how many invoices needed nobody
  - wrong values that slipped through: wrong fields on auto-approved invoices.
    That's the one that costs money.

Run:  uv run python labs/invoices/done/score.py [--model claude-haiku-5-5]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks import state_code  # noqa: E402
from review import ReviewQueue  # noqa: E402
from shopkart import data  # noqa: E402

TEXT = ["supplier_name", "supplier_gstin", "buyer_gstin", "invoice_number", "invoice_date"]
AMOUNTS = ["taxable_value_inr", "cgst_inr", "sgst_inr", "igst_inr", "total_inr"]
FIELDS = [*TEXT, "place_of_supply", *AMOUNTS, "line_items"]
LINE_FIELDS = ["qty", "unit_price_inr", "taxable_value_inr", "gst_rate_pct"]


def norm_text(v: object) -> str | None:
    return re.sub(r"[^a-z0-9]", "", str(v).casefold()) or None if v is not None else None


def same_amount(a: object, b: object) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= 0.5


def field_ok(name: str, got: dict, want: dict) -> bool:
    g, w = got.get(name), want.get(name)
    if name in TEXT:
        return norm_text(g) == norm_text(w)
    if name == "place_of_supply":
        return state_code(g) == state_code(w)
    if name in AMOUNTS:
        if name in ("cgst_inr", "sgst_inr", "igst_inr"):  # not printed = 0
            g, w = g or 0, w or 0
        return same_amount(g, w)
    if name == "line_items":  # every line, every number
        g, w = g or [], w or []
        return len(g) == len(w) and all(
            same_amount(gl.get(k), wl.get(k)) for gl, wl in zip(g, w) for k in LINE_FIELDS)
    raise KeyError(name)


def flag_codes(reasons: list[str]) -> set[str]:
    return {r.split(":", 1)[0] for r in reasons}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Field accuracy against expected.json.")
    parser.add_argument("--db", default=None)
    parser.add_argument("--model", default=None, help="only rows read by this model")
    args = parser.parse_args(argv)

    expected = {e["file"]: e for e in data.load_invoice_expected()}
    rows = [r for r in ReviewQueue(args.db).rows()
            if r["file"] in expected and (args.model is None or r["model"] == args.model)]
    if not rows:
        print("Nothing to score yet: run pipeline.py first.")
        return 1

    right = {f: 0 for f in FIELDS}
    slipped, straight, flags_as_expected = [], 0, 0
    print(f"{'file':<34}{'fields':>8}  flags (expected)")
    for row in rows:
        want = expected[row["file"]]
        got = json.loads(row["data"] or "{}")
        wrong = [f for f in FIELDS if not field_ok(f, got, want)]
        for f in FIELDS:
            right[f] += f not in wrong
        auto = row["decided_by"] == "pipeline"
        straight += auto
        if auto and wrong:
            slipped.append((row["file"], wrong))
        flags = flag_codes(json.loads(row["reasons"])) - {"duplicate"}
        want_flags = set(want.get("expected_validation_errors", []))
        flags_as_expected += flags == want_flags
        mark = "" if not wrong else "  wrong: " + ", ".join(wrong)
        print(f"{row['file']:<34}{len(FIELDS) - len(wrong):>4}/{len(FIELDS):<3}  "
              f"{', '.join(sorted(flags)) or '-'} ({', '.join(sorted(want_flags)) or '-'}){mark}")

    n = len(rows)
    print(f"\nField accuracy, {n} invoices:")
    for f in FIELDS:
        print(f"  {f:<20}{100 * right[f] / n:>5.0f}%")
    total = sum(right.values()) / (n * len(FIELDS))
    print(f"  {'all fields':<20}{100 * total:>5.0f}%")
    print(f"\nStraight through: {straight} of {n}")
    print(f"Flags as expected: {flags_as_expected} of {n}")
    print(f"Wrong values that slipped past every check: {sum(len(w) for _, w in slipped)}"
          + "".join(f"\n  {file}: {', '.join(w)}" for file, w in slipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
