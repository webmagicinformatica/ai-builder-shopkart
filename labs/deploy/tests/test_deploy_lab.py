"""The deploy lab's checkpoints: no key, no network, no AWS, no cost.

Against the finished answer:   uv run pytest labs/deploy -q
Against your copy:             LAB=start uv run pytest labs/deploy -q
"""

import importlib.util
import json
import os
import re
import sys
import types
from pathlib import Path

import anthropic
import httpx2
import openai
import pytest
from fastapi.testclient import TestClient

from shopkart.llm import LLM
from tests.fakes import FakeServer, anthropic_stream, openai_stream

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")


def load_app():
    spec = importlib.util.spec_from_file_location(f"deploy_{FOLDER.name}_app", FOLDER / "app.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.setattr("shopkart.budget.LEDGER_DIR", tmp_path)
    monkeypatch.setenv("DAILY_BUDGET_USD", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.setenv("FAKE_TTFT_S", "0")
    monkeypatch.setenv("FAKE_WORD_S", "0")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("SHOPKART_STATE_DIR", raising=False)


def client_with(fake: FakeServer | None, monkeypatch, provider: str = "anthropic"):
    """The app, with its model client pointed at a fake provider server."""
    monkeypatch.setenv("LLM_PROVIDER", provider if fake else "fake")
    mod = load_app()
    tc = TestClient(mod.app)
    tc.__enter__()  # runs the start-up (lifespan)
    if fake is not None:
        http = httpx2.AsyncClient(transport=httpx2.MockTransport(fake))
        cls = anthropic.AsyncAnthropic if provider == "anthropic" else openai.AsyncOpenAI
        tc.app.state.llm = LLM(provider, client=cls(api_key="sk-fake", http_client=http, max_retries=0))
    return mod, tc


def events(body: str) -> list[dict]:
    """Parse server-sent events: 'data: {...}' lines separated by blank lines."""
    return [json.loads(chunk[6:]) for chunk in body.split("\n\n") if chunk.startswith("data: ")]


ASK = {"session_id": "test-1", "message": "Where is my refund for order 4512?"}


# ---- TODO 1: the health check -------------------------------------------------


def test_health_is_cheap_and_ok(monkeypatch):
    fake = FakeServer("anthropic", [])
    _, tc = client_with(fake, monkeypatch)
    r = tc.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert r.headers["x-request-id"]
    assert fake.calls == 0  # never calls the model


# ---- the app (given): typed input, streaming, request IDs, failures ------------


def test_empty_message_is_422_before_any_model_call(monkeypatch):
    fake = FakeServer("anthropic", [])
    _, tc = client_with(fake, monkeypatch)
    r = tc.post("/chat", json={"session_id": "s", "message": ""})
    assert r.status_code == 422
    assert fake.calls == 0


@pytest.mark.parametrize("provider,stream", [("anthropic", anthropic_stream), ("openai", openai_stream)])
def test_chat_streams_text_then_done(monkeypatch, provider, stream):
    fake = FakeServer(provider, [("stream", stream(["Your refund ", "was started ", "on 16 November."]))])
    mod, tc = client_with(fake, monkeypatch, provider)
    r = tc.post("/chat", json=ASK)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    evs = events(r.text)
    assert "".join(e["text"] for e in evs if e["type"] == "text") == "Your refund was started on 16 November."
    done = evs[-1]
    assert done["type"] == "done"
    assert done["request_id"] == r.headers["x-request-id"]
    assert done["cost_usd"] > 0 and done["tokens_out"] > 0
    # the order was looked up and put in the prompt, without the customer's name
    sent = json.dumps(fake.requests[0], ensure_ascii=False)
    assert "SK04512" in sent and "Aditya" not in sent


def test_failure_mid_stream_is_an_error_event(monkeypatch):
    fake = FakeServer("anthropic", [("stream", anthropic_stream(["Your refund ", "was", "x"], error_after=1))])
    _, tc = client_with(fake, monkeypatch)
    r = tc.post("/chat", json=ASK)
    assert r.status_code == 200  # the status went out with the first byte
    evs = events(r.text)
    assert evs[0] == {"type": "text", "text": "Your refund "}
    assert evs[-1]["type"] == "error" and evs[-1]["request_id"] == r.headers["x-request-id"]


def test_daily_budget_blocks_with_429(monkeypatch):
    from shopkart import budget

    fake = FakeServer("anthropic", [])
    _, tc = client_with(fake, monkeypatch)
    budget.record(0.02)
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.01")
    r = tc.post("/chat", json=ASK)
    assert r.status_code == 429 and r.headers["retry-after"]
    assert fake.calls == 0


def test_missing_key_fails_at_startup(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    mod = load_app()
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        with TestClient(mod.app):
            pass


def test_fake_mode_streams_without_a_model(monkeypatch):
    _, tc = client_with(None, monkeypatch)
    evs = events(tc.post("/chat", json=ASK).text)
    assert evs[-1]["type"] == "done" and evs[-1]["model"] == "fake"
    assert "SK04512" in "".join(e.get("text", "") for e in evs)


def test_lambda_reads_the_key_from_secrets_manager(monkeypatch):
    asked = []

    class FakeSecrets:
        def get_secret_value(self, SecretId):
            asked.append(SecretId)
            return {"SecretString": "sk-from-secrets-manager\n"}

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda name: FakeSecrets()))
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("ANTHROPIC_API_KEY_SECRET_ID", "shopkart/anthropic-api-key")
    mod = load_app()
    mod.load_secrets_from_aws()
    assert asked == ["shopkart/anthropic-api-key"]
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-from-secrets-manager"


# ---- TODO 2-6: the Dockerfile and what it leaves out ---------------------------


def dockerfile() -> str:
    return (FOLDER / "Dockerfile").read_text()


def instructions() -> list[str]:
    return [line.strip() for line in dockerfile().splitlines() if line.strip() and not line.strip().startswith("#")]


def test_slim_base_image():
    froms = [line for line in instructions() if line.startswith("FROM")]
    assert froms and all("python:3.12-slim" in f for f in froms)


def test_packages_installed_from_the_lock_before_the_code():
    lines = instructions()
    sync = next(i for i, line in enumerate(lines) if line.startswith("RUN") and "uv sync" in line)
    assert "--frozen" in lines[sync]
    lock_copy = next(i for i, line in enumerate(lines) if line.startswith("COPY") and "uv.lock" in line)
    code_copy = next(i for i, line in enumerate(lines) if line.startswith("COPY") and "shopkart/" in line)
    assert lock_copy < sync < code_copy


def test_runs_as_a_user_that_is_not_root():
    users = [line for line in instructions() if line.startswith("USER")]
    assert users and users[-1].split()[1] not in ("root", "0")


def test_listens_on_all_interfaces_port_8000():
    cmd = [line for line in instructions() if line.startswith("CMD")][-1]
    assert "0.0.0.0" in cmd and "8000" in cmd


def test_lambda_web_adapter_for_part_2():
    assert re.search(r"^COPY --from=public\.ecr\.aws/awsguru/aws-lambda-adapter:\S+ /lambda-adapter "
                     r"/opt/extensions/lambda-adapter", dockerfile(), re.MULTILINE)


def test_env_file_never_reaches_the_image():
    ignored = (FOLDER / "Dockerfile.dockerignore").read_text().split()
    assert ".env" in ignored and ".venv" in ignored and ".git" in ignored
