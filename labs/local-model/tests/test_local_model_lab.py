"""The local-model lab's checkpoints. No Ollama, no key, no network.

Against the finished answer:   uv run pytest labs/local-model -q
Against your copy:             LAB=start uv run pytest labs/local-model -q
"""

import importlib.util
import os
import sys
from pathlib import Path

import httpx2
import pytest

from shopkart import budget
from tests.fakes import FakeServer, openai_response

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")

spec = importlib.util.spec_from_file_location(f"local_model_compare_{FOLDER.name}", FOLDER / "compare.py")
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setattr(compare, "CACHE", tmp_path / "cache")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")


def test_twenty_golden_questions_from_every_category():
    qs = compare.load_questions()
    assert len(qs) == 20
    assert {q["category"] for q in qs} == {"everyday", "hard", "must_handover"}
    assert sum(q["check"]["verdict"] == "handover" for q in qs) == sum(q["must_handover"] for q in qs)


def test_prompt_has_the_cited_policy_and_the_order():
    q = next(q for q in compare.load_questions() if q["id"] == "g-061")
    p = compare.prompt_for(q)
    assert "footwear §1" in p and "10 days" in p
    assert "SK48493" in p and "2026-11-08" in p and q["question"] in p


@pytest.mark.parametrize("qid,text,ok", [
    ("g-001", "VERDICT: info\nANSWER: You have 14 days from delivery.", True),
    ("g-001", "VERDICT: info\nANSWER: You have 30 days.", False),
    ("g-001", "VERDICT: handover\nANSWER: A colleague will help, within 14 days.", False),
    ("g-067", "VERDICT: no\nANSWER: Opened headphones can be returned only if faulty.", True),
    ("g-067", "VERDICT: yes\nANSWER: Sure, unless faulty.", False),
    ("g-143", "VERDICT: handover\nANSWER: I'll pass this to a colleague.", True),
    ("g-143", "VERDICT: handover\nANSWER: Your refund has been processed.", False),
])
def test_simple_code_checks(qid, text, ok):
    q = next(q for q in compare.load_questions() if q["id"] == qid)
    assert compare.check(q, text)[0] is ok


def test_local_model_is_the_same_client_on_a_local_address():
    server = FakeServer("openai", [openai_response("VERDICT: info\nANSWER: 14 days.", 900, 12)])
    seen = []
    transport = httpx2.MockTransport(lambda req: seen.append(str(req.url)) or server(req))
    llm = compare.local_llm("shopkart-local", http_client=httpx2.Client(transport=transport))
    r = llm.complete("hi", system=compare.SYSTEM)
    assert seen == ["http://localhost:11434/v1/responses"]
    assert server.requests[0]["model"] == "shopkart-local"
    assert r.cost_usd == 0.0 and r.input_tokens == 900


def test_local_cost_is_the_machine_not_the_tokens():
    rows = [{"ok": True, "latency_s": 36.0, "out": 40, "cost_usd": 0.0}] * 10   # 6 minutes for 10 answers
    s = compare.summary(rows, local=True)
    assert s["correct"] == 10 and s["cost_usd"] == 0.0
    assert s["per_1000_usd"] == pytest.approx(0.18 * 36 * 1000 / 3600)        # $1.80 of Codespace time
    api = compare.summary([{"ok": True, "latency_s": 1.0, "out": 40, "cost_usd": 0.0002}] * 10, local=False)
    assert api["per_1000_usd"] == pytest.approx(0.2)
