"""The CI lab's checkpoints, with fake servers (no key, no network, no cost).

Against the finished answer:   uv run pytest labs/evals-ci -q
Against your copy:             LAB=start uv run pytest labs/evals-ci -q
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import httpx2
import pytest

from shopkart import budget
from tests.fakes import FakeServer, anthropic_message

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")
REPO = LAB.parents[1]
EVAL_NAMES = ("cases", "copilot", "checks", "cache", "judge", "run_evals", "calibrate", "report")


def _load_gate():
    for name in EVAL_NAMES:  # ci_gate uses the finished eval suite from labs/evals/done
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(f"ci_gate_{FOLDER.name}", FOLDER / "ci_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setattr(gate, "OUT", tmp_path / "out")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)


def row(i, cat, code=True, verdict="pass", handover=False):
    return {"id": i, "category": cat, "question": "q", "reply": "a", "handover": handover, "code_pass": code,
            "checks": [], "judge": {"verdict": verdict, "reason": "r", "cost_usd": 0.0}}


GOOD = [row(f"e{i}", "everyday") for i in range(7)] + [row("h1", "hard", code=False), row("m1", "must_handover",
                                                                                          handover=True)]


def test_the_slice_is_10_cases_from_the_50():
    ids = gate.slice_ids()
    fifty = json.loads((REPO / "labs/evals/eval-50.json").read_text())["ids"]
    assert len(ids) == 10 and set(ids) <= {i for v in fifty.values() for i in v}


def test_todo1_no_key_skips_cleanly(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert gate.main([]) == 0
    assert "skipped" in summary.read_text() and "Actions" in summary.read_text()


def test_todo2_threshold_and_hard_rule():
    d = gate.decide(GOOD, 0.7)
    assert (d["passed"], d["cases"], d["blocked"]) == (8, 9, False)
    assert gate.decide(GOOD, 0.9)["blocked"] is True
    missed = GOOD[:-1] + [row("m1", "must_handover", handover=False)]
    d = gate.decide(missed, 0.1)  # the hard rule blocks even when the rate is fine
    assert d["blocked"] and any("m1" in r for r in d["reasons"])
    judged_out = GOOD[:-2] + [row("x", "everyday", verdict="fail"), row("y", "everyday", verdict="fail")]
    assert gate.decide(judged_out, 0.8)["blocked"] is True


def test_failed_calls_are_an_error_not_a_verdict():
    broken = [dict(r, error="connection: Connection error.", code_pass=False) for r in GOOD]
    d = gate.decide(broken, 0.7)
    assert d["blocked"] and d["error"]
    assert "ERROR" in gate.summary_markdown(broken, d, "anthropic claude-haiku-5-5", 0.0)


def test_todo3_full_run_with_fakes_writes_the_job_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    ids = gate.slice_ids()
    handover_ids = {"g-129", "g-138"}
    answers = [anthropic_message(json.dumps({"reply": "A colleague will take over." if i in handover_ids
                                             else "Within 14 days of delivery, 10 days for footwear.",
                                             "handover": i in handover_ids})) for i in ids]
    verdicts = [anthropic_message(json.dumps({"reason": "fine", "grounded": "pass", "follows_policy": "pass",
                                              "answers_question": "pass"})) for _ in ids]
    server = FakeServer("anthropic", answers + verdicts)

    real_llm = gate.LLM

    def fake(provider=None, model=None, **kw):
        return real_llm(provider, model, http_client=httpx2.Client(transport=httpx2.MockTransport(server)),
                        sleep=lambda s: None)

    monkeypatch.setattr(gate, "LLM", fake)
    monkeypatch.setattr(sys.modules[gate.CachedLLM.__module__], "CACHE_DIR", tmp_path / "cache")
    code = gate.main(["--threshold", "0.5"])
    text = summary.read_text()
    assert server.calls == 20 and "| must_handover | 2 | 2 |" in text
    assert code == 0 and text.startswith("## Evals: passed")


def test_the_workflow_runs_on_pull_requests_and_skips_without_the_secret():
    wf = (REPO / ".github/workflows/evals.yml").read_text()
    assert "pull_request:" in wf and "secrets.ANTHROPIC_API_KEY" in wf
    assert "GITHUB_STEP_SUMMARY" in wf and "steps.key.outputs.ok == 'true'" in wf
    assert "ci_gate.py" in wf and 'DAILY_BUDGET_USD: "0.05"' in wf
    assert wf == (LAB / "done" / "evals.yml").read_text()  # the lab's copy and the live one match
