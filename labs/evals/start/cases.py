"""The test set: 50 frozen cases from the golden set, plus the orders they talk about.

    cases = load_cases()            # the 50 in eval-50.json, in file order
    cases = load_cases(limit=10)    # a slice, for a quick try
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]  # the repo root, where shopkart/ and data/ live
sys.path.insert(0, str(ROOT))

from shopkart import data  # noqa: E402  (the shared loaders for data/)

LAB = Path(__file__).resolve().parents[1]
GOLDEN = data.GOLDEN_DIR / "golden-150.jsonl"
EVAL_SET = LAB / "eval-50.json"

CATEGORIES = ("everyday", "hard", "must_handover")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """One JSON object per line; blank lines are skipped."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def eval_ids(path: Path = EVAL_SET) -> list[str]:
    """The frozen IDs, everyday first, then hard, then must-hand-over."""
    ids = json.loads(path.read_text(encoding="utf-8"))["ids"]
    return [i for cat in CATEGORIES for i in ids.get(cat, [])]


def load_cases(limit: int | None = None, ids: list[str] | None = None,
               golden: Path = GOLDEN, eval_set: Path = EVAL_SET) -> list[dict[str, Any]]:
    """The eval cases, each a golden-set row: id, category, question, expected, must_not, ..."""
    # TODO 1: load the test set.
    #   - read every golden case (read_jsonl) and index them by "id"
    #   - take the IDs you want: `ids` if given, else eval_ids(eval_set) (the frozen 50)
    #   - raise KeyError if an ID isn't in the golden set (a typo must not shrink the set silently)
    #   - return the cases in that order, cut to `limit` if given
    raise NotImplementedError("TODO 1: load_cases")


def load_orders() -> dict[str, dict[str, Any]]:
    """Every order, by ID (SK48213 -> its record)."""
    return {o["order_id"]: o for o in data.load_orders()}


def load_policies() -> str:
    """Every current policy (not the archive), one after another, each tagged with its doc_id."""
    return "\n\n".join(
        f'<policy doc_id="{d.doc_id}" version="{d.meta.get("version", "?")}">\n{d.text.strip()}\n</policy>'
        for d in data.load_policies() if d.status == "current")
