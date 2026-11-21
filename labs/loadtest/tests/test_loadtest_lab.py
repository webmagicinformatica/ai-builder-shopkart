"""The loadtest lab's checkpoints: limits with a fake clock, a load test against the app in memory.
No key, no network, no cost.

Against the finished answer:   uv run pytest labs/loadtest -q
Against your copy:             LAB=start uv run pytest labs/loadtest -q
"""

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

import httpx2
import pytest

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")
INR = 88.0  # shopkart.pricing.USD_TO_INR


def load(name: str):
    for shared in ("telemetry", "limits"):  # each lab folder has its own copies
        sys.modules.pop(shared, None)
    spec = importlib.util.spec_from_file_location(f"loadtest_{FOLDER.name}_{name}", FOLDER / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.setattr("shopkart.budget.LEDGER_DIR", tmp_path)
    monkeypatch.setenv("DAILY_BUDGET_USD", "1")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("FAKE_TTFT_S", "0")
    monkeypatch.setenv("FAKE_WORD_S", "0")
    for name in ("USER_PER_MINUTE", "USER_DAILY_INR", "GLOBAL_DAILY_INR", "OTEL_EXPORTER_OTLP_ENDPOINT",
                 "SHOPKART_STATE_DIR"):
        monkeypatch.delenv(name, raising=False)


class Clock:
    def __init__(self, t: float = 1_795_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def guard(**kw):
    limits = load("limits")
    clock = Clock()
    return limits.CostGuard(clock=clock, **kw), clock


# ---- TODO 1: the per-user rate limit ------------------------------------------------


def test_rate_limit_counts_requests_per_minute():
    g, clock = guard(user_per_minute=3, user_daily_usd=1, global_daily_usd=10)
    assert all(g.check("asha", 0.0001).allowed for _ in range(3))
    v = g.check("asha", 0.0001)
    assert not v.allowed and v.reason == "rate_limit" and 1 <= v.retry_after_s <= 61
    assert g.check("ravi", 0.0001).allowed  # other users are not affected
    clock.t += 61
    assert g.check("asha", 0.0001).allowed  # a minute later, allowed again


# ---- TODO 2: the per-user spend limit (worst case before, real cost after) ------------


def test_spend_limit_uses_the_worst_case_before_and_the_real_cost_after():
    g, _ = guard(user_per_minute=100, user_daily_usd=20 / INR, global_daily_usd=1000)
    assert g.check("seller-7", 15 / INR).allowed
    g.record("seller-7", 15 / INR)                      # a huge catalogue message: ₹15
    v = g.check("seller-7", 10 / INR)                   # the next one could cost ₹10: over ₹20
    assert not v.allowed and v.reason == "user_daily_spend" and v.retry_after_s > 0
    assert g.check("seller-7", 1 / INR).allowed         # a small one still fits


# ---- TODO 3: the global ladder: alert, degrade, lite -----------------------------------


def test_global_cap_is_a_ladder_not_a_cliff():
    g, clock = guard(user_per_minute=1000, user_daily_usd=1000, global_daily_usd=100 / INR)
    assert g.record("u", 79 / INR) is None and g.mode() == "normal"
    assert g.record("u", 1 / INR) == "budget_alert"      # 80%: alert, once
    assert g.record("u", 1 / INR) is None and g.mode() == "normal"
    g.record("u", 9 / INR)
    assert g.mode() == "degraded"                       # 90%
    assert g.check("u", 0.0).mode == "degraded"
    g.record("u", 10 / INR)
    assert g.mode() == "lite" and g.check("u", 0.0).allowed  # 100%: still answers, without the model
    clock.t += 86_400                                    # a new day starts from zero
    assert g.mode() == "normal" and g.status()["spent_inr"] == 0


def test_limits_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("USER_PER_MINUTE", "4")
    monkeypatch.setenv("GLOBAL_DAILY_INR", "880")
    g = load("limits").CostGuard.from_env()
    assert g.user_per_minute == 4 and g.global_daily_usd == pytest.approx(10.0)
    assert g.user_daily_usd == pytest.approx(20 / INR)  # default ₹20


# ---- the app: 429s and modes, end to end -------------------------------------------------


def run_load(monkeypatch, requests, users, concurrency=5, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    app_mod = load("app")
    lt = load("loadtest")

    async def go():
        async with app_mod.app.router.lifespan_context(app_mod.app):
            transport = httpx2.ASGITransport(app=app_mod.app)
            report = await lt.run("http://copilot", requests, concurrency, users, transport=transport)
            async with httpx2.AsyncClient(transport=transport) as c:
                status = (await c.get("http://copilot/budget")).json()
            return report, status

    report, status = asyncio.run(go())
    return lt, report, status


def test_load_test_reports_latency_and_outcomes(monkeypatch, capsys):
    lt, report, status = run_load(monkeypatch, 30, users=30)
    assert report.outcomes()["ok"] == 30
    text = lt.summary(report, 5)
    assert "P95" in text and "error rate 0.0%" in text
    assert status["mode"] == "normal" and status["spent_inr"] > 0


def test_a_script_on_one_account_gets_429s(monkeypatch, capsys):
    _, report, _ = run_load(monkeypatch, 12, users=1, USER_PER_MINUTE=5)
    out = report.outcomes()
    assert out["ok"] == 5 and out["429"] == 7


def test_the_global_cap_trips_into_lite_mode(monkeypatch, capsys):
    # each fake chat costs about ₹0.004, so a ₹0.05 cap trips within ~12 chats
    _, report, status = run_load(monkeypatch, 40, users=40, concurrency=1, GLOBAL_DAILY_INR="0.05")
    modes = report.modes()
    assert modes["normal"] > 0 and modes["lite"] > 0
    assert status["mode"] == "lite"
    alerts = [json.loads(line) for line in capsys.readouterr().out.splitlines() if '"budget_alert"' in line]
    assert len(alerts) == 1  # the team is told once


def test_percentile_nearest_rank():
    lt = load("loadtest")
    values = [1.0] * 90 + [10.0] * 10
    assert lt.percentile(values, 50) == 1.0
    assert lt.percentile(values, 95) == 10.0  # the slow tail the average hides
    assert sum(values) / len(values) == pytest.approx(1.9)
