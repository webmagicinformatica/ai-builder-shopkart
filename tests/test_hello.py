"""Run both hello scripts with a fake client: no key, no network, no cost."""

from types import SimpleNamespace

import pytest

import hello_anthropic
import hello_openai
from shopkart import budget

USAGE = SimpleNamespace(input_tokens=20, output_tokens=15)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")


def fake_anthropic(**_):
    text = SimpleNamespace(type="text", text="Namaste, welcome to ShopKart!")
    create = lambda **kw: SimpleNamespace(content=[text], usage=USAGE)  # noqa: E731
    return SimpleNamespace(messages=SimpleNamespace(create=create))


def fake_openai(**_):
    create = lambda **kw: SimpleNamespace(  # noqa: E731
        output_text="Namaste, welcome to ShopKart!", usage=USAGE
    )
    return SimpleNamespace(responses=SimpleNamespace(create=create))


@pytest.mark.parametrize(
    "script, attr, fake, model",
    [
        (hello_anthropic, "Anthropic", fake_anthropic, "claude-haiku-5-5"),
        (hello_openai, "OpenAI", fake_openai, "gpt-6-luna"),
    ],
)
def test_prints_cost_and_records_it(script, attr, fake, model, monkeypatch, capsys):
    sdk = script.anthropic if attr == "Anthropic" else script.openai
    monkeypatch.setattr(sdk, attr, fake)
    script.main()
    out = capsys.readouterr().out
    assert f"Model:   {model}" in out
    assert "Tokens:  20 in, 15 out" in out
    assert "Cost:    $0.000095  (₹0.01)" in out  # 20 x $1/M + 15 x $5/M
    assert budget.spent_today() == pytest.approx(0.000095)


def test_missing_key_exits_with_hint(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(SystemExit) as exc:
        hello_anthropic.main()
    assert exc.value.code == 1
    assert "Codespaces" in capsys.readouterr().err


def test_budget_blocks_before_the_call(monkeypatch, capsys):
    budget.record(0.01)
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.000001")
    monkeypatch.setattr(hello_openai.openai, "OpenAI", lambda **_: pytest.fail("called"))
    with pytest.raises(SystemExit) as exc:
        hello_openai.main()
    assert exc.value.code == 2
    assert "Call blocked." in capsys.readouterr().err
