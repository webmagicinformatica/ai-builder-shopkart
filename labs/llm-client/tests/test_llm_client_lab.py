"""The lab's checkpoints, with fake servers (no key, no network, no cost).

Against the finished answer:   uv run pytest labs/llm-client -q
Against your copy:             LAB=start uv run pytest labs/llm-client -q
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import httpx2
import pytest

from shopkart import budget
from tests.fakes import FakeServer, anthropic_message, anthropic_stream, error_body, openai_response

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")


def _load(name: str):
    sys.path.insert(0, str(FOLDER))
    try:
        spec = importlib.util.spec_from_file_location(f"llm_client_lab_{FOLDER.name}_{name}", FOLDER / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(FOLDER))


client = _load("llm_client")
triage = _load("triage")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr(client, "CALL_LOG", tmp_path / "calls.csv", raising=False)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")


def make(server: FakeServer, **kw):
    http = httpx2.Client(transport=httpx2.MockTransport(server))
    return client.LLM(server.provider, http_client=http, sleep=lambda s: None, **kw)


# ---- Part 1: typed and streaming --------------------------------------

def test_part1_complete_returns_text_tokens_and_cost():
    r = make(FakeServer("anthropic", [anthropic_message("Namaste!", 20, 15)])).complete("hi")
    assert r.text == "Namaste!" and (r.input_tokens, r.output_tokens) == (20, 15)
    assert r.cost_usd == pytest.approx(0.0000095) and r.cost_inr > 0
    assert budget.spent_today() == pytest.approx(0.0000095)


def test_part1_twenty_messages_classified_zero_crashes():
    """Checkpoint: 20 messages, each one a valid Triage."""
    messages = json.loads((LAB / "messages.json").read_text())
    assert len(messages) == 20
    reply = '{"intent":"where_is_order","order_id":"SK48213","urgency":"high","summary":"Late order"}'
    server = FakeServer("anthropic", [anthropic_message(reply) for _ in messages])
    llm = make(server)
    for m in messages:
        assert isinstance(llm.complete(m, schema=triage.Triage).parsed, triage.Triage)
    assert server.calls == 20


def test_part1_bad_order_id_gets_one_retry():
    bad = '{"intent":"refund","order_id":"48213","urgency":"normal","summary":"x"}'
    good = bad.replace('"48213"', '"SK48213"')
    server = FakeServer("anthropic", [anthropic_message(bad), anthropic_message(good)])
    assert make(server).complete("hi", schema=triage.Triage).parsed.order_id == "SK48213"
    assert server.calls == 2


def test_part1_stream_assembles_the_answer():
    pieces = ["Your refund ", "was approved ", "on Monday."]
    out = list(make(FakeServer("anthropic", [("stream", anthropic_stream(pieces))])).stream("refund?"))
    assert out[:-1] == pieces
    assert out[-1].text == "Your refund was approved on Monday." and out[-1].output_tokens == 12


# ---- Part 2: retries and error handling --------------------------------

def test_part2_survives_injected_failures():
    """Checkpoint: 429, 529 and a 500, then success. The answer still arrives."""
    server = FakeServer("anthropic", [429, 529, 500, anthropic_message("ok")])
    r = make(server).complete("hi")
    assert r.text == "ok" and r.attempts == 4


def test_part2_never_retries_a_400():
    server = FakeServer("anthropic", [400])
    with pytest.raises(client.LLMError):
        make(server).complete("hi")
    assert server.calls == 1


def test_part2_never_retries_a_spend_limit():
    body = error_body("openai", 429, "insufficient_quota", "insufficient_quota", "You exceeded your current quota")
    server = FakeServer("openai", [("error", 429, body)])
    with pytest.raises(client.SpendLimitReached):
        make(server).complete("hi")
    assert server.calls == 1


def test_part2_honours_retry_after():
    waits = []
    body = error_body("anthropic", 429, "rate_limit_error")
    server = FakeServer("anthropic", [("error", 429, body, {"retry-after": "2"}), anthropic_message("ok")])
    llm = make(server)
    llm._sleep = waits.append
    llm.complete("hi")
    assert waits == [2.0]


def test_part2_falls_back_when_retries_run_out():
    backup = make(FakeServer("openai", [openai_response("from the fallback")]))
    r = make(FakeServer("anthropic", [529, 529]), max_attempts=2, fallback=backup).complete("hi")
    assert r.text == "from the fallback"
