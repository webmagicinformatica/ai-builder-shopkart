"""A daily spending cap that lives in your own code.

The provider's spend limit is your outer wall, but it reacts with a delay.
This is the inner wall: before every call we check today's spend, and after
every call we record what it cost.

Today's spend is kept in a small JSON file, .shopkart/spend-YYYY-MM-DD.json
(gitignored). A new day means a new file, so the budget resets every day.
"""

import json
import os
from datetime import date
from pathlib import Path

DEFAULT_DAILY_BUDGET_USD = 0.50
LEDGER_DIR = Path(__file__).resolve().parent.parent / ".shopkart"


class BudgetExceeded(Exception):
    """Raised before a call when today's spend has reached the budget."""

    def __init__(self, spent: float, budget: float):
        self.spent = spent
        self.budget = budget
        super().__init__(
            f"Budget reached: spent ${spent:.6f} of ${budget:.6f} today. Call blocked."
        )


def daily_budget_usd() -> float:
    """The daily budget: DAILY_BUDGET_USD if set, otherwise $0.50."""
    raw = os.environ.get("DAILY_BUDGET_USD", "").strip()
    return float(raw) if raw else DEFAULT_DAILY_BUDGET_USD


def _ledger_path(today: date | None, ledger_dir: Path | None) -> Path:
    today = today or date.today()
    return (ledger_dir or LEDGER_DIR) / f"spend-{today.isoformat()}.json"


def spent_today(today: date | None = None, ledger_dir: Path | None = None) -> float:
    """Dollars spent so far today (0 if there's no ledger yet)."""
    path = _ledger_path(today, ledger_dir)
    if not path.exists():
        return 0.0
    return float(json.loads(path.read_text())["spent_usd"])


def check(today: date | None = None, ledger_dir: Path | None = None) -> None:
    """Call BEFORE every API call. Raises BudgetExceeded at or over the budget."""
    spent = spent_today(today, ledger_dir)
    budget = daily_budget_usd()
    if spent >= budget:
        raise BudgetExceeded(spent, budget)


def record(cost: float, today: date | None = None, ledger_dir: Path | None = None) -> float:
    """Call AFTER every API call. Adds its cost to today's total and returns the total."""
    path = _ledger_path(today, ledger_dir)
    data = {"spent_usd": 0.0, "calls": 0}
    if path.exists():
        data = json.loads(path.read_text())
    data["spent_usd"] = float(data["spent_usd"]) + cost
    data["calls"] = int(data.get("calls", 0)) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)
    return data["spent_usd"]
