"""The cost lab's checkpoints, with fake servers (no key, no network, no cost).

Against the finished answer:   uv run pytest labs/cost-cut -q
Against your copy:             LAB=start uv run pytest labs/cost-cut -q
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from shopkart import budget
from shopkart.llm import call_cost_usd
from tests.fakes import FakeServer, anthropic_message, openai_response

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")

spec = importlib.util.spec_from_file_location(f"cost_cut_{FOLDER.name}", FOLDER / "cost_cut.py")
lab = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = lab  # pydantic models need their module registered
spec.loader.exec_module(lab)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")


def cached_message(text, read=0, write=0, fresh=20, out=30):
    msg = anthropic_message(text, fresh, out)
    msg["usage"].update(cache_read_input_tokens=read, cache_creation_input_tokens=write)
    return msg


def route_reply(level):
    return anthropic_message(json.dumps({"level": level}), 120, 5)


QUESTIONS = [
    {"id": "w-1", "question": "how long can i return stuff", "difficulty": "easy", "cluster": "return-window"},
    {"id": "w-2", "question": "opened earbuds return possible?", "difficulty": "hard", "cluster": "opened-headphones"},
    {"id": "w-3", "question": "How long can I return stuff?", "difficulty": "easy", "cluster": "return-window"},
]


# ---- the models and their prices -----------------------------------------

def test_large_model_has_a_price_and_cheap_cache_reads():
    # Sonnet 5.5: $2 in, $10 out, cache read 0.05x ($0.10/M), cache write 1.25x ($2.50/M).
    assert call_cost_usd("claude-sonnet-5-5", 1_000_000, 0) == pytest.approx(2.00)
    assert call_cost_usd("claude-sonnet-5-5", 0, 1_000_000) == pytest.approx(10.00)
    assert call_cost_usd("claude-sonnet-5-5", 0, 0, cache_read=1_000_000) == pytest.approx(0.10)
    assert call_cost_usd("claude-sonnet-5-5", 0, 0, cache_write=1_000_000) == pytest.approx(2.50)
    assert call_cost_usd("claude-haiku-5-5", 0, 0, cache_read=1_000_000) == pytest.approx(0.01)


def test_sonnet_turns_thinking_off_with_between_tools():
    server = FakeServer("anthropic", [anthropic_message("ok")])
    server.llm(model="claude-sonnet-5-5").complete("hi")
    assert server.requests[0]["thinking"] == {"type": "between_tools"}


def test_sol_uses_its_lowest_reasoning_setting():
    server = FakeServer("openai", [openai_response("ok")])
    server.llm(model="gpt-6.2-sol").complete("hi")
    assert server.requests[0]["reasoning"] == {"effort": "low"}


# ---- step 2: prompt caching ------------------------------------------------

def test_cache_step_marks_the_policy_prompt_for_caching():
    server = FakeServer("anthropic", [cached_message("14 days.", write=2150)])
    r = lab.answer(server.llm(model="claude-sonnet-5-5"), "how long can i return stuff", cache=True)
    system = server.requests[0]["system"]
    assert isinstance(system, list) and system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[0]["text"] == lab.SYSTEM            # the whole policy sheet is the cached prefix
    assert server.requests[0]["messages"][-1]["content"] == "how long can i return stuff"  # question last
    assert r.cache_write_tokens == 2150


def test_baseline_sends_a_plain_system_prompt():
    server = FakeServer("anthropic", [anthropic_message("14 days.")])
    lab.answer(server.llm(model="claude-sonnet-5-5"), "q", cache=False)
    assert server.requests[0]["system"] == lab.SYSTEM


# ---- step 3: routing ----------------------------------------------------------

@pytest.mark.parametrize("level, expected", [("easy", "easy"), ("hard", "hard"), ("unsure", "hard")])
def test_router_sends_unsure_questions_to_the_large_model(level, expected):
    server = FakeServer("anthropic", [route_reply(level)])
    got, result = lab.route(server.llm(), "opened earbuds return possible?")
    assert got == expected and result.cost_usd > 0


def test_router_falls_back_to_hard_when_the_answer_is_not_valid():
    server = FakeServer("anthropic", [anthropic_message("no idea"), anthropic_message("still no")])
    assert lab.route(server.llm(), "?")[0] == "hard"


# ---- step 4: the local response cache ---------------------------------------

def test_response_cache_key_ignores_case_and_punctuation():
    k = lab.ResponseCache.key
    assert k("How long can I return stuff?") == k("how long can i  return stuff")
    assert k("Is delivery free for ₹799?") != k("Is delivery free for ₹499?")


def test_personal_questions_are_never_cached():
    cache = lab.ResponseCache()
    cache.put("Where is SK48213?", "Out for delivery")
    assert cache.get("Where is SK48213?") is None
    cache.put("What time do you deliver?", "9 am to 9 pm")
    assert cache.get("what time do you deliver") == "9 am to 9 pm"


def test_final_step_serves_repeats_from_the_cache_for_free():
    small = FakeServer("anthropic", [route_reply("easy"), cached_message("14 days from delivery.", write=2000),
                                     route_reply("hard")])
    large = FakeServer("anthropic", [cached_message("Only if faulty.", write=2000)])
    clients = {"small": small.llm(model="claude-haiku-5-5"), "large": large.llm(model="claude-sonnet-5-5")}
    rec = lab.run_step("final", "anthropic", QUESTIONS, clients=clients, out=lambda *a: None)
    paths = [r["path"] for r in rec["rows"]]
    assert paths == ["haiku", "sonnet", "cache"]
    assert rec["rows"][2]["cost"] == 0 and rec["rows"][2]["answer"] == "14 days from delivery."
    assert small.calls == 3 and large.calls == 1   # the repeat made no call at all


# ---- step 5: the table ---------------------------------------------------------

def test_saving_is_measured_against_the_baseline():
    assert lab.saving(0.10, 0.04) == pytest.approx(0.60)
    assert lab.saving(0.10, 0.10) == pytest.approx(0.0)


def test_key_fact_check():
    assert lab.key_facts_ok("refund-time", "Refunds take 5 to 7 working days.")
    assert lab.key_facts_ok("footwear-window", "You have 10 days from delivery.")
    assert not lab.key_facts_ok("footwear-window", "You have 7 days.")


def test_openai_reports_its_automatic_cache():
    server = FakeServer("openai", [openai_response("14 days.", 1412, 20)])
    reply = server.replies[0]
    reply["usage"]["input_tokens_details"]["cached_tokens"] = 1280
    r = lab.answer(server.llm(model="gpt-6.2-sol"), "q", cache=True)
    assert r.cache_read_tokens == 1280 and r.input_tokens == 132
    assert "cache_control" not in json.dumps(server.requests[0])  # nothing to switch on
