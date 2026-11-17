from datetime import date

import pytest

from shopkart import budget

MONDAY = date(2026, 11, 16)
TUESDAY = date(2026, 11, 17)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.01")
    return tmp_path


def test_default_budget(monkeypatch):
    monkeypatch.delenv("DAILY_BUDGET_USD", raising=False)
    assert budget.daily_budget_usd() == 0.50


def test_fresh_day_allows_a_call(ledger):
    budget.check(today=MONDAY, ledger_dir=ledger)
    assert budget.spent_today(today=MONDAY, ledger_dir=ledger) == 0


def test_record_adds_up(ledger):
    budget.record(0.003, today=MONDAY, ledger_dir=ledger)
    total = budget.record(0.002, today=MONDAY, ledger_dir=ledger)
    assert total == pytest.approx(0.005)
    assert budget.spent_today(today=MONDAY, ledger_dir=ledger) == pytest.approx(0.005)


def test_under_budget_is_allowed(ledger):
    budget.record(0.009, today=MONDAY, ledger_dir=ledger)
    budget.check(today=MONDAY, ledger_dir=ledger)  # no exception


def test_blocks_at_the_limit(ledger):
    budget.record(0.01, today=MONDAY, ledger_dir=ledger)
    with pytest.raises(budget.BudgetExceeded) as exc:
        budget.check(today=MONDAY, ledger_dir=ledger)
    assert str(exc.value) == (
        "Budget reached: spent $0.010000 of $0.010000 today. Call blocked."
    )


def test_blocks_over_the_limit(ledger):
    budget.record(0.02, today=MONDAY, ledger_dir=ledger)
    with pytest.raises(budget.BudgetExceeded):
        budget.check(today=MONDAY, ledger_dir=ledger)


def test_resets_the_next_day(ledger):
    budget.record(0.05, today=MONDAY, ledger_dir=ledger)
    budget.check(today=TUESDAY, ledger_dir=ledger)  # new day, new file
    assert budget.spent_today(today=TUESDAY, ledger_dir=ledger) == 0
    assert (ledger / "spend-2026-11-16.json").exists()
