"""shopkart.llm against fake servers: typed results, streaming, retries, no network."""

from typing import Literal

import pytest
from pydantic import BaseModel, Field, field_validator

from shopkart import budget, llm as llm_mod
from shopkart.llm import LLM, LLMError, Result, SchemaError, SpendLimitReached, StreamInterrupted
from tests.fakes import (FakeServer, anthropic_message, anthropic_stream, error_body,
                         openai_response, openai_stream)

PROVIDERS = ["anthropic", "openai"]


def answer(provider: str, text: str, **kw):
    return anthropic_message(text, **kw) if provider == "anthropic" else openai_response(text, **kw)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr(llm_mod, "CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")


class Triage(BaseModel):
    intent: Literal["where_is_order", "refund", "cancel", "product", "other"]
    order_id: str | None = Field(description="null if not given")
    urgency: Literal["low", "normal", "high"]
    summary: str = Field(description="one line, always in English")

    @field_validator("order_id")
    @classmethod
    def looks_like_sk(cls, v):
        if v is not None and not (v.startswith("SK") and len(v) == 7 and v[2:].isdigit()):
            raise ValueError("order_id must look like SK followed by 5 digits")
        return v


GOOD = '{"intent":"where_is_order","order_id":"SK48213","urgency":"high","summary":"Order late, needed Saturday"}'
BAD_ID = GOOD.replace("SK48213", "48213")


# ---- typed results ------------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_complete_returns_a_typed_result(provider):
    server = FakeServer(provider, [answer(provider, "Namaste!", input_tokens=20, output_tokens=15)])
    result = server.llm().complete("hi")
    assert isinstance(result, Result)
    assert result.text == "Namaste!"
    assert (result.input_tokens, result.output_tokens) == (20, 15)
    assert result.cost_usd == pytest.approx(0.0000095)  # 20 x $0.10/M + 15 x $0.50/M
    assert result.cost_inr == pytest.approx(0.0000095 * 88)
    assert result.attempts == 1 and result.stop_reason == "end"
    assert budget.spent_today() == pytest.approx(0.0000095)  # budget.record() ran
    assert (budget.LEDGER_DIR / "calls.csv").read_text().count("\n") == 2  # header + 1 row


@pytest.mark.parametrize("provider", PROVIDERS)
def test_schema_gives_a_pydantic_object_and_sends_the_schema(provider):
    server = FakeServer(provider, [answer(provider, GOOD)])
    result = server.llm().complete("Order SK48213 hasn't arrived", schema=Triage)
    assert isinstance(result.parsed, Triage)
    assert result.parsed.order_id == "SK48213" and result.parsed.urgency == "high"
    sent = server.requests[0]
    fmt = sent["output_config"]["format"] if provider == "anthropic" else sent["text"]["format"]
    assert fmt["type"] == "json_schema"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_invalid_json_is_retried_once_with_the_error(provider):
    server = FakeServer(provider, [answer(provider, BAD_ID), answer(provider, GOOD)])
    result = server.llm().complete("hi", schema=Triage)
    assert result.parsed.order_id == "SK48213"
    assert server.calls == 2
    assert "SK followed by 5 digits" in str(server.requests[1])
    assert budget.spent_today() > 0  # both calls were paid and recorded


@pytest.mark.parametrize("provider", PROVIDERS)
def test_still_invalid_after_one_retry_raises_schema_error(provider):
    server = FakeServer(provider, [answer(provider, BAD_ID), answer(provider, BAD_ID)])
    with pytest.raises(SchemaError):
        server.llm().complete("hi", schema=Triage)
    assert server.calls == 2  # one retry, not a loop


def test_budget_blocks_before_any_call(monkeypatch):
    budget.record(0.01)
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.000001")
    server = FakeServer("anthropic", [])
    with pytest.raises(budget.BudgetExceeded):
        server.llm().complete("hi")
    assert server.calls == 0


# ---- streaming ----------------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_stream_yields_pieces_then_a_result(provider):
    pieces = ["Your refund ", "was approved ", "on Monday."]
    body = anthropic_stream(pieces) if provider == "anthropic" else openai_stream(pieces)
    out = list(FakeServer(provider, [("stream", body)]).llm().stream("refund?"))
    assert out[:-1] == pieces
    result = out[-1]
    assert isinstance(result, Result)
    assert result.text == "".join(pieces)
    assert result.output_tokens == 12 and result.ttft_s is not None
    assert budget.spent_today() == pytest.approx(result.cost_usd)


def test_stream_retries_before_the_first_piece():
    server = FakeServer("anthropic", [529, ("stream", anthropic_stream(["ok"]))])
    out = list(server.llm().stream("hi"))
    assert out[0] == "ok" and out[-1].attempts == 2


def test_stream_error_after_text_keeps_the_partial_answer():
    body = anthropic_stream(["Your refund ", "was approved ", "on Monday."], error_after=2)
    server = FakeServer("anthropic", [("stream", body)])
    shown = []
    with pytest.raises(StreamInterrupted) as exc:
        for piece in server.llm().stream("refund?"):
            shown.append(piece)
    assert exc.value.partial_text == "Your refund was approved "
    assert exc.value.kind == "overloaded"
    assert server.calls == 1  # never re-sent once the user is reading


# ---- retries ------------------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_retries_429_then_succeeds(provider):
    server = FakeServer(provider, [429, 429, answer(provider, "ok")])
    result = server.llm().complete("hi")
    assert result.text == "ok" and result.attempts == 3 and server.calls == 3
    last_row = (budget.LEDGER_DIR / "calls.csv").read_text().strip().splitlines()[-1].split(",")
    assert last_row[-2:] == ["3", "ok"]  # the cost log shows the retries


def test_retries_529_overloaded():
    server = FakeServer("anthropic", [529, answer("anthropic", "ok")])
    assert server.llm().complete("hi").attempts == 2


def test_honours_retry_after():
    waits = []
    body = error_body("anthropic", 429, "rate_limit_error")
    server = FakeServer("anthropic", [("error", 429, body, {"retry-after": "3"}), answer("anthropic", "ok")])
    llm = server.llm()
    llm._sleep = waits.append
    llm.complete("hi")
    assert waits == [3.0]


def test_backoff_doubles_with_jitter():
    waits = []
    server = FakeServer("anthropic", [500, 500, 500, answer("anthropic", "ok")])
    llm = server.llm()
    llm._sleep = waits.append
    llm.complete("hi")
    for wait, base in zip(waits, [1, 2, 4]):
        assert 0.5 * base <= wait <= 1.5 * base


def test_gives_up_after_max_attempts():
    server = FakeServer("anthropic", [529] * 4)
    with pytest.raises(LLMError) as exc:
        server.llm(max_attempts=4).complete("hi")
    assert server.calls == 4 and exc.value.retryable and exc.value.status == 529


@pytest.mark.parametrize("provider", PROVIDERS)
def test_400_is_never_retried(provider):
    server = FakeServer(provider, [400])
    with pytest.raises(LLMError) as exc:
        server.llm().complete("hi")
    assert server.calls == 1 and exc.value.kind == "bad_request" and not exc.value.retryable


def test_auth_error_is_never_retried():
    server = FakeServer("openai", [401])
    with pytest.raises(LLMError) as exc:
        server.llm().complete("hi")
    assert server.calls == 1 and exc.value.kind == "auth"


@pytest.mark.parametrize("code", ["insufficient_quota", "project_spend_limit_exceeded"])
def test_openai_429_spend_limit_is_not_retried(code):
    body = error_body("openai", 429, "insufficient_quota", code, "You exceeded your current quota")
    server = FakeServer("openai", [("error", 429, body)])
    with pytest.raises(SpendLimitReached):
        server.llm().complete("hi")
    assert server.calls == 1


def test_anthropic_400_workspace_limit_is_not_retried():
    body = error_body("anthropic", 400, "invalid_request_error",
                      message="You have reached your specified workspace API usage limits.")
    server = FakeServer("anthropic", [("error", 400, body)])
    with pytest.raises(SpendLimitReached):
        server.llm().complete("hi")
    assert server.calls == 1


def test_fallback_after_retries_run_out():
    big = FakeServer("anthropic", [529, 529])
    small = FakeServer("openai", [openai_response("from the fallback")])
    result = big.llm(max_attempts=2, fallback=small.llm()).complete("hi")
    assert result.text == "from the fallback" and result.provider == "openai"


def test_no_fallback_for_a_bad_request():
    small = FakeServer("openai", [])
    with pytest.raises(LLMError):
        FakeServer("anthropic", [400]).llm(fallback=small.llm()).complete("hi")
    assert small.calls == 0


def test_cli_prints_answer_and_cost(monkeypatch, capsys):
    server = FakeServer("anthropic", [anthropic_message("We deliver in 3-5 days.")])
    monkeypatch.setattr(llm_mod, "LLM", lambda *a, **kw: server.llm())
    assert llm_mod.main(["When will it arrive?"]) == 0
    out = capsys.readouterr().out
    assert "We deliver in 3-5 days." in out and "claude-haiku-5-5" in out and "₹" in out
