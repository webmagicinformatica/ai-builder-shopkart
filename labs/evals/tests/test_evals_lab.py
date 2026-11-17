"""The eval lab's checkpoints, with fake servers (no key, no network, no cost).

Against the finished answer:   uv run pytest labs/evals -q
Against your copy:             LAB=start uv run pytest labs/evals -q
"""

import importlib
import json
import os
import sys
from pathlib import Path

import httpx2
import pytest

from shopkart import budget
from tests.fakes import FakeServer, anthropic_message, openai_response

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")
NAMES = ("cases", "copilot", "checks", "cache", "judge", "run_evals", "calibrate", "report")


def _load():
    """Import the lab's modules from start/ or done/ (they import each other by plain name)."""
    for name in NAMES:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(FOLDER))
    try:
        return {name: importlib.import_module(name) for name in NAMES}
    finally:
        sys.path.remove(str(FOLDER))


M = _load()
cases, checks, cache, judge = M["cases"], M["checks"], M["cache"], M["judge"]
run_evals, calibrate, report, copilot = M["run_evals"], M["calibrate"], M["report"], M["copilot"]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")


def fake_llm(server: FakeServer, tmp_path: Path):
    from shopkart.llm import LLM

    http = httpx2.Client(transport=httpx2.MockTransport(server))
    llm = LLM(server.provider, http_client=http, sleep=lambda s: None)
    return cache.CachedLLM(llm, cache_dir=tmp_path / "eval-cache")


def reply_json(text: str, handover: bool = False) -> str:
    return json.dumps({"reply": text, "handover": handover})


CASE_14 = {"id": "t-1", "category": "everyday", "question": "How many days to return?",
           "expected": ["14 days", "from delivery"], "must_not": ["30 days"], "must_handover": False}
CASE_GIFT = {"id": "t-2", "category": "must_handover", "question": "Can I return a gift?",
             "expected": ["not covered by policy", "hand over"],
             "must_not": ["gifts can be returned within 14 days"], "must_handover": True}


# ---- Part 1: test set, code checks, runner ---------------------------------

def test_todo1_the_frozen_50_have_the_golden_mix():
    got = cases.load_cases()
    assert len(got) == 50 and len({c["id"] for c in got}) == 50
    mix = {cat: sum(c["category"] == cat for c in got) for cat in cases.CATEGORIES}
    assert mix == {"everyday": 30, "hard": 12, "must_handover": 8}
    assert [c["id"] for c in cases.load_cases(limit=3)] == ["g-001", "g-005", "g-009"]
    with pytest.raises(KeyError):
        cases.load_cases(ids=["g-999"])


def test_todo2_days_check_wants_the_right_window():
    shoes = {"expected": ["10 days", "from delivery"]}
    assert checks.check_days(shoes, "Footwear can be returned within 10 days of delivery.").passed is True
    assert checks.check_days(shoes, "Shoes: ten-day window.").passed is True
    assert checks.check_days(shoes, "Joote 10 din ke andar return ho sakte hain.").passed is True
    bad = checks.check_days(shoes, "You have 14 days to return it.")
    assert bad.passed is False and "10 days" in bad.note
    assert checks.check_days({"expected": ["7 days"]}, "Refund in 7 working days.").passed is False
    assert checks.check_days({"expected": ["48 hours"]}, "anything").passed is None


def test_todo3_handover_check_fails_both_ways():
    assert checks.check_handover(CASE_GIFT, True).passed is True
    miss = checks.check_handover(CASE_GIFT, False)
    assert miss.passed is False and "should hand over" in miss.note
    extra = checks.check_handover(CASE_14, True)
    assert extra.passed is False and "should answer" in extra.note


def test_must_not_one_word_phrases_only_count_at_the_start():
    case = {"must_not": ["yes", "30 days"]}
    assert checks.check_must_not(case, "Yes, you can return it.").passed is False
    assert checks.check_must_not(case, "No. If yes was the answer before, the rule changed.").passed is True
    assert checks.check_must_not(case, "We used to allow 30 days.").passed is False


def test_todo4_made_up_amounts_are_caught():
    allowed = checks.allowed_amounts("Refunds above ₹5,000 need a human. Delivery ₹49.", "my order",
                                     {"total_inr": 1299})
    assert checks.check_amounts("Your ₹1,299 refund is under ₹5,000.", allowed).passed is True
    bad = checks.check_amounts("We'll add ₹1,500 as a goodwill credit.", allowed)
    assert bad.passed is False and "₹1,500" in bad.note
    assert checks.check_amounts("No money mentioned.", allowed).passed is None
    assert checks.amounts_in("Rs. 499 or 2,999 rupees or INR 10,000") == {499, 2999, 10000}


def test_todo5_runner_writes_results_and_the_rerun_is_free(tmp_path):
    two = [cases.load_cases(ids=["g-001"])[0], cases.load_cases(ids=["g-129"])[0]]
    server = FakeServer("anthropic", [
        anthropic_message(reply_json("You can return most items within 14 days of delivery.")),
        anthropic_message(reply_json("Gift returns aren't in our policy, so a colleague will take over.", True)),
    ])
    llm = fake_llm(server, tmp_path)
    out = tmp_path / "results.jsonl"
    rows = run_evals.run(llm, two, out, echo=lambda *a: None)
    assert server.calls == 2 and [r["code_pass"] for r in rows] == [True, True]
    saved = [json.loads(x) for x in out.read_text().splitlines()]
    assert saved[1]["handover"] is True and {c["name"] for c in saved[0]["checks"]} == {
        "days", "handover", "must_not", "amounts"}
    # the policies go in a cached system prompt
    assert server.requests[0]["system"][0]["cache_control"] == {"type": "ephemeral"}

    again = FakeServer("anthropic", [])  # no replies: any call would fail
    rows2 = run_evals.run(fake_llm(again, tmp_path), two, out, echo=lambda *a: None)
    assert again.calls == 0 and all(r["cached"] and r["cost_usd"] == 0 for r in rows2)
    assert [r["reply"] for r in rows2] == [r["reply"] for r in rows]


def test_a_changed_prompt_is_not_served_from_the_cache(tmp_path, monkeypatch):
    case = cases.load_cases(ids=["g-001"])
    server = FakeServer("anthropic", [anthropic_message(reply_json("14 days from delivery.")),
                                      anthropic_message(reply_json("14 days from delivery."))])
    llm = fake_llm(server, tmp_path)
    run_evals.run(llm, case, tmp_path / "r.jsonl", echo=lambda *a: None)
    monkeypatch.setattr(copilot, "system_prompt", lambda: "a new prompt version")
    run_evals.run(llm, case, tmp_path / "r.jsonl", echo=lambda *a: None)
    assert server.calls == 2


def test_runner_on_openai(tmp_path):
    server = FakeServer("openai", [openai_response(reply_json("Within 14 days of delivery."))])
    rows = run_evals.run(fake_llm(server, tmp_path), cases.load_cases(limit=1), tmp_path / "o.jsonl",
                         echo=lambda *a: None)
    assert rows[0]["provider"] == "openai" and rows[0]["code_pass"] is True


def test_estimate_counts_the_prompt_cache():
    e = run_evals.estimate("claude-haiku-5-5", cases.load_cases(), 50)
    assert 0 < e["total"] < e["worst"] and e["copilot_calls"] == 50 and e["judge_calls"] == 50
    assert run_evals.estimate("claude-haiku-5-5", cases.load_cases(), 20)["judge"] < e["judge"]


# ---- Part 2: judge, calibration, report ------------------------------------

def verdict_json(reason="Says 14 days, as the policy does.", g="pass", f="pass", a="pass") -> str:
    return json.dumps({"reason": reason, "grounded": g, "follows_policy": f, "answers_question": a})


def test_todo6_judge_returns_a_typed_verdict(tmp_path):
    v = judge.JudgeVerdict.model_validate_json(verdict_json(f="fail"))
    assert (v.score, v.verdict) == (2, "fail")
    assert judge.JudgeVerdict.model_validate_json(verdict_json()).verdict == "pass"
    assert list(judge.JudgeVerdict.model_fields)[0] == "reason"  # reason first, then the checks
    with pytest.raises(Exception):
        judge.JudgeVerdict.model_validate_json(verdict_json(g="7/10"))

    row = {"id": "g-001", "category": "everyday", "question": "q", "reply": "14 days.", "handover": False}
    server = FakeServer("anthropic", [anthropic_message(verdict_json(f="fail"))])
    out = judge.judge_rows(fake_llm(server, tmp_path), [row], echo=lambda *a: None)
    assert out[0]["judge"]["verdict"] == "fail" and out[0]["judge"]["score"] == 2
    sent = server.requests[0]
    assert "Length earns no points" in sent["system"][0]["text"]
    assert "<copilot_answer" in sent["messages"][0]["content"]  # the answer is data, in tags


def test_todo7_calibration_counts_caught_failures_not_just_agreement():
    rows = [{"id": i, "reply": "r", "judge": {"verdict": j, "reason": "x"}}
            for i, j in [("a", "pass"), ("b", "pass"), ("c", "fail"), ("d", "pass"), ("e", "fail")]]
    labels = [{"id": i, "label": h} for i, h in [("a", "pass"), ("b", "fail"), ("c", "fail"),
                                                  ("d", "pass"), ("e", "pass")]]
    c = calibrate.compare(labels, rows)
    assert (c["n"], c["agree"], c["human_fails"], c["caught"], c["false_alarms"], c["lazy_agree"]) == (5, 3, 2, 1, 1, 3)


def test_todo8_report_by_category_and_failures(tmp_path):
    def row(i, cat, code, verdict=None):
        r = {"id": i, "category": cat, "question": "q", "reply": "a", "handover": False,
             "provider": "anthropic", "model": "claude-haiku-5-5", "prompt_version": "v1", "cost_usd": 0.0,
             "code_pass": code, "checks": [{"name": "handover", "passed": code, "note": "" if code else "bad"}]}
        if verdict:
            r["judge"] = {"verdict": verdict, "score": 3 if verdict == "pass" else 2, "reason": "because",
                          "grounded": "pass", "follows_policy": verdict, "answers_question": "pass",
                          "model": "claude-haiku-5-5", "cost_usd": 0.0}
        return r

    rows = [row("a", "everyday", True, "pass"), row("b", "everyday", True, "fail"),
            row("c", "hard", False, "pass"), row("d", "must_handover", True)]
    d = report.build(rows)
    cats = {c["category"]: c for c in d["by_cat"]}
    assert cats["everyday"]["overall"] == "1/2 (50%)" and cats["hard"]["code"] == "0/1 (0%)"
    assert cats["all"]["overall"] == "2/4 (50%)" and cats["must_handover"]["judge"] == "-"
    assert [f["id"] for f in d["failures"]] == ["b", "c"]
    md, page = report.to_markdown(d), report.to_html(d)
    assert "| everyday | 2 | 2/2 (100%) | 1/2 (50%) | 1/2 (50%) |" in md
    assert "<table>" in page and "prefers-color-scheme: dark" in page
