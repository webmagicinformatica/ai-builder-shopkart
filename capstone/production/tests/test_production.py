"""The production capstone's tests. No key, no network, no AWS, no cost: a fake embedder,
a fake reranker, a fake Claude (a mock HTTP transport), spans kept in memory.

    uv run pytest capstone/production -q
"""

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.fakes import FakeServer, anthropic_message

PROJECT = Path(__file__).resolve().parents[1]
SOLUTION = PROJECT / "solution"
ROOT = PROJECT.parents[1]
# Plain module names that other labs' tests may have loaded from their own folders.
SHARED = ("parse", "chunker", "index", "ingest", "ask", "hybrid", "measure", "assistant", "telemetry", "limits",
          "fake_llm", "loadtest")


def load(name: str, path: Path):
    for shared in SHARED:
        sys.modules.pop(shared, None)
    spec = importlib.util.spec_from_file_location(f"production_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeEmbedder:
    name = "fake-embedder"

    def _vec(self, text):
        v = np.zeros(384, dtype=np.float32)
        for word in re.findall(r"\w+", text.lower()):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % 384] += 1
        return v / (np.linalg.norm(v) or 1)

    def passages(self, texts):
        return np.array([self._vec(t) for t in texts])

    def query(self, text):
        return self._vec(text)


class FakeReranker:
    """Share of the question's longer words found in the chunk: 0 when nothing matches."""

    def scores(self, question, texts):
        words = {w for w in re.findall(r"\w+", question.lower()) if len(w) > 3}
        return [len(words & set(re.findall(r"\w+", t.lower()))) / (len(words) or 1) for t in texts]


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.setattr("shopkart.budget.LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setenv("DAILY_BUDGET_USD", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("SHOPKART_STATE_DIR", str(tmp_path))  # the answer cache: fresh for every test
    for name in ("USER_PER_MINUTE", "USER_DAILY_INR", "GLOBAL_DAILY_INR", "OTEL_EXPORTER_OTLP_ENDPOINT",
                 "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "SEARCH_THREADS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="module")
def index_path(tmp_path_factory):
    """The real policies, chunked and indexed with the fake embedder."""
    ingest = load("ingest", ROOT / "labs" / "rag" / "done" / "ingest.py")
    path = tmp_path_factory.mktemp("idx") / "index.sqlite"
    ingest.PARSED_DIR = path.parent / "parsed"
    ingest.build(index_path=path, embedder=FakeEmbedder(), log=lambda *a: None)
    return path


def start(monkeypatch, index_path, replies=(), *, llm=None, threads=None):
    """The app with the real policies, fake models, and spans kept in memory."""
    mod = load("app", SOLUTION / "app.py")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    server = FakeServer("anthropic", list(replies))
    monkeypatch.setattr(mod.telemetry, "setup_tracing", lambda: provider.get_tracer("test"))
    monkeypatch.setattr(mod, "make_llm", lambda: llm or server.llm())
    monkeypatch.setattr(mod, "match_threads_to_cpu_quota", lambda: threads or 1)

    def make_bot(llm, cache_dir):
        idx = mod.assistant.Index(index_path, embedder=FakeEmbedder())
        return mod.assistant.DocAssistant(llm, index=idx, reranker=FakeReranker(), cache_dir=cache_dir)

    monkeypatch.setattr(mod, "make_bot", make_bot)
    client = TestClient(mod.app)
    client.__enter__()
    return mod, client, server, exporter


def events(body: str) -> list[dict]:
    return [json.loads(c[6:]) for c in body.split("\n\n") if c.startswith("data: ")]


def answer_json(answer, labels, answerable=True):
    return anthropic_message(json.dumps({"answerable": answerable, "answer": answer, "citations": labels}),
                             input_tokens=1800, output_tokens=120)


RETURN_Q = {"session_id": "s1", "message": "How many days do I have to return a product?"}
RETURN_LABEL = "returns-and-refunds § 2.1"


# ---- the service -----------------------------------------------------------------

def test_health_never_searches_or_calls(monkeypatch, index_path):
    mod, client, server, exporter = start(monkeypatch, index_path)
    assert client.get("/health").json() == {"status": "ok"}
    assert server.calls == 0 and exporter.get_finished_spans() == ()


def test_a_checked_answer_with_its_sources_and_one_trace(monkeypatch, index_path, capsys):
    mod, client, server, exporter = start(
        monkeypatch, index_path, [answer_json(f"You have 14 days from delivery [{RETURN_LABEL}].", [RETURN_LABEL])])
    r = client.post("/chat", json=RETURN_Q)
    ev = events(r.text)
    assert [e["type"] for e in ev] == ["status", "text", "done"]
    assert ev[1]["text"] == f"You have 14 days from delivery [{RETURN_LABEL}]."
    done = ev[2]
    assert done["kind"] == "answer" and done["sources"][0]["label"] == RETURN_LABEL and done["cost_usd"] > 0
    assert r.headers["x-trace-id"] == done["trace_id"]

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert set(spans) == {"POST /chat", "retrieve hybrid+rerank", "chat claude-haiku-5-5", "grounding_check"}
    assert len({s.context.trace_id for s in spans.values()}) == 1  # one request, one trace
    chat = spans["chat claude-haiku-5-5"].attributes
    assert chat["gen_ai.usage.input_tokens"] == 1800 and chat["shopkart.prompt.version"] == "doc-v1"
    assert spans["grounding_check"].attributes["shopkart.check.passed"] is True
    assert spans["retrieve hybrid+rerank"].attributes["shopkart.retrieval.best_score"] > 0.01

    emf = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{"_aws"')]
    assert emf and emf[0]["Model"] == "claude-haiku-5-5" and emf[0]["CostUSD"] > 0 and emf[0]["InputTokens"] == 1800


def test_the_floor_hands_over_without_a_model_call(monkeypatch, index_path):
    mod, client, server, exporter = start(monkeypatch, index_path)
    ev = events(client.post("/chat", json={"session_id": "s2", "message": "Zxqv blorptastic wibbles?"}).text)
    assert ev[-1]["kind"] == "handover" and "no model call" in ev[-1]["reason"] and ev[-1]["cost_usd"] == 0
    assert ev[1]["text"] == mod.ask.HANDOVER_TEXT and server.calls == 0
    assert "chat claude-haiku-5-5" not in {s.name for s in exporter.get_finished_spans()}


def test_a_failed_check_never_reaches_the_customer(monkeypatch, index_path, capsys):
    made_up = f"You have 30 days from delivery [{RETURN_LABEL}]."
    mod, client, server, exporter = start(monkeypatch, index_path, [answer_json(made_up, [RETURN_LABEL])])
    ev = events(client.post("/chat", json=RETURN_Q).text)
    assert ev[1]["text"] == mod.ask.HANDOVER_TEXT and "30" not in ev[1]["text"]
    assert ev[-1]["kind"] == "handover" and "number 30" in ev[-1]["reason"]
    check = next(s for s in exporter.get_finished_spans() if s.name == "grounding_check")
    assert check.attributes["shopkart.check.passed"] is False
    assert '"event": "check_failed"' in capsys.readouterr().out  # kept in the log for us


def test_the_same_question_twice_is_paid_once(monkeypatch, index_path):
    mod, client, server, exporter = start(
        monkeypatch, index_path, [answer_json(f"You have 14 days from delivery [{RETURN_LABEL}].", [RETURN_LABEL])])
    first = events(client.post("/chat", json=RETURN_Q).text)[-1]
    again = events(client.post("/chat", json=RETURN_Q).text)[-1]
    assert first["cached"] is False and again["cached"] is True and again["cost_usd"] == 0
    assert server.calls == 1


def test_one_user_over_the_rate_limit_gets_429_others_dont(monkeypatch, index_path):
    monkeypatch.setenv("USER_PER_MINUTE", "2")
    mod, client, server, exporter = start(monkeypatch, index_path)
    ask = {"session_id": "s3", "user_id": "script", "message": "Zxqv blorptastic wibbles?"}
    codes = [client.post("/chat", json=ask).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    r = client.post("/chat", json=ask)
    assert r.json()["reason"] == "rate_limit" and int(r.headers["retry-after"]) > 0
    assert client.post("/chat", json={**ask, "user_id": "someone-else"}).status_code == 200


def test_the_ladder_ends_in_lite_mode_with_no_model_call(monkeypatch, index_path):
    monkeypatch.setenv("GLOBAL_DAILY_INR", "0.02")  # about one answer's worth
    mod, client, server, exporter = start(
        monkeypatch, index_path, [answer_json(f"You have 14 days from delivery [{RETURN_LABEL}].", [RETURN_LABEL])])
    client.post("/chat", json=RETURN_Q)
    assert client.get("/budget").json()["mode"] == "lite"
    ev = events(client.post("/chat", json={**RETURN_Q, "user_id": "late-night"}).text)
    assert ev[-1]["mode"] == "lite" and ev[-1]["cost_usd"] == 0 and RETURN_LABEL in ev[1]["text"]
    assert server.calls == 1  # only the first question reached the model


def test_fake_mode_answers_pass_the_real_check(monkeypatch, index_path):
    fake = load("fake_llm", SOLUTION / "fake_llm.py").FakeDocLLM(latency_s=0)
    mod, client, server, exporter = start(monkeypatch, index_path, llm=fake)
    done = events(client.post("/chat", json=RETURN_Q).text)[-1]
    assert done["kind"] == "answer" and done["model"] == "fake" and done["cost_usd"] > 0  # pretend cost
    assert server.calls == 0


# ---- sizing and the image ---------------------------------------------------------

def test_cpu_quota_reads_the_cgroup(tmp_path):
    mod = load("app", SOLUTION / "app.py")
    (tmp_path / "cpu.max").write_text("100000 100000\n")
    assert mod.cpu_quota(tmp_path) == 1
    (tmp_path / "cpu.max").write_text("50000 100000\n")
    assert mod.cpu_quota(tmp_path) == 1  # half a CPU still needs one thread
    (tmp_path / "cpu.max").write_text("max 100000\n")
    assert mod.cpu_quota(tmp_path) is None
    v1 = tmp_path / "v1"
    (v1 / "cpu").mkdir(parents=True)
    (v1 / "cpu" / "cpu.cfs_quota_us").write_text("200000")
    (v1 / "cpu" / "cpu.cfs_period_us").write_text("100000")
    assert mod.cpu_quota(v1) == 2


def test_the_image_recipe():
    docker = (SOLUTION / "Dockerfile").read_text()
    ignore = (SOLUTION / "Dockerfile.dockerignore").read_text().split()
    assert "FROM python:3.12-slim" in docker and "USER app" in docker
    assert "--only-group serve" not in docker.replace("Not --only-group serve", "")  # needs the RAG libraries
    assert "uv sync --frozen" in docker and "ingest.py" in docker
    assert ".shopkart/models" in docker and "HF_HUB_OFFLINE=1" in docker  # nothing downloads at start-up
    assert ".env" in ignore and ".shopkart" in ignore


def test_the_service_settings_add_up():
    env = dict(line.split("=", 1) for line in (SOLUTION / "service.env").read_text().splitlines()
               if "=" in line and not line.startswith("#"))
    assert int(env["MEMORY"]) >= 2048 and int(env["CPU"]) >= 1024
    assert env["SCALE_METRIC"] == "AVERAGE_CPU"
    total_inr = float(env["GLOBAL_DAILY_INR"]) * int(env["MAX_TASKS"])
    assert total_inr == 88  # the daily cap is ₹88 (about $1) across every task
    per_task_usd = float(env["GLOBAL_DAILY_INR"]) / 88
    assert per_task_usd < float(env["DAILY_BUDGET_USD"]) < per_task_usd * 1.2  # hard stop just above the ladder
    assert "KEY" not in (SOLUTION / "service.env").read_text().replace("API key", "")


def test_the_load_test_asks_policy_questions():
    lt = load("loadtest_docs", SOLUTION / "loadtest_docs.py")
    assert len(lt.loadtest.QUESTIONS) == 25 and "Do you offer a student discount?" in lt.loadtest.QUESTIONS
