"""The tracing lab's checkpoints: spans in memory, no collector, no key, no cost.

Against the finished answer:   uv run pytest labs/tracing -q
Against your copy:             LAB=start uv run pytest labs/tracing -q
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from shopkart.llm import LLM
from tests.fakes import FakeServer, anthropic_stream

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")


def load(name: str):
    sys.modules.pop("telemetry", None)  # each lab folder has its own telemetry.py
    spec = importlib.util.spec_from_file_location(f"tracing_{FOLDER.name}_{name}", FOLDER / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.setattr("shopkart.budget.LEDGER_DIR", tmp_path)
    monkeypatch.setenv("DAILY_BUDGET_USD", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", raising=False)
    monkeypatch.delenv("SHOPKART_STATE_DIR", raising=False)


@pytest.fixture
def telemetry():
    return load("telemetry")


def traced_app(replies, monkeypatch, capsys=None):
    """The app with a fake Claude and an in-memory span exporter."""
    mod = load("app")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(mod.telemetry, "setup_tracing", lambda: provider.get_tracer("test"))
    tc = TestClient(mod.app)
    tc.__enter__()
    fake = FakeServer("anthropic", replies)
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(fake))
    tc.app.state.llm = LLM("anthropic", client=anthropic.AsyncAnthropic(api_key="sk-fake", http_client=http, max_retries=0))
    return tc, exporter


def events(body: str) -> list[dict]:
    return [json.loads(c[6:]) for c in body.split("\n\n") if c.startswith("data: ")]


ASK = {"session_id": "conv-42", "message": "Where is my refund for order 4512? Mail me at asha@example.com"}


# ---- TODO 1: the gen-AI attribute names ------------------------------------------


def test_llm_attributes_use_the_standard_names(telemetry):
    attrs = telemetry.llm_attributes(provider="anthropic", model="claude-haiku-5-5", prompt_version="v7",
                                     tokens_in=3700, tokens_out=120, cost_usd=0.00043, ttft_ms=612.4,
                                     max_tokens=300, provider_request_id="req_123")
    assert attrs["gen_ai.provider.name"] == "anthropic"
    assert attrs["gen_ai.request.model"] == "claude-haiku-5-5"
    assert attrs["gen_ai.usage.input_tokens"] == 3700
    assert attrs["gen_ai.usage.output_tokens"] == 120
    assert attrs["gen_ai.operation.name"] == "chat"
    # no standard names for these yet, so they're ours:
    assert attrs["shopkart.prompt.version"] == "v7"
    assert attrs["shopkart.cost_usd"] == pytest.approx(0.00043)
    assert attrs["shopkart.ttft_ms"] == 612
    assert attrs["shopkart.provider_request_id"] == "req_123"


# ---- TODO 2: redact before anything is written ------------------------------------


def test_redact_masks_personal_data_but_keeps_order_ids(telemetry):
    text = ("Order SK04512, ref ARN74418820551. Mail asha.k@example.com, call +91 98765 43210 "
            "or 9876543210, card 4111 1111 1111 1111.")
    out = telemetry.redact(text)
    assert "asha.k@example.com" not in out and "[email]" in out
    assert "98765 43210" not in out and "9876543210" not in out and out.count("[phone]") == 2
    assert "4111" not in out and "[card]" in out
    assert "SK04512" in out and "ARN74418820551" in out


# ---- TODO 3: one metrics line per request (CloudWatch EMF) ---------------------------


def test_emf_line_is_a_log_line_and_metrics(telemetry):
    line = json.loads(telemetry.emf_line(model="claude-haiku-5-5", prompt_version="v1", latency_ms=1400.2,
                                         ttft_ms=610.0, cost_usd=0.000124, tokens_in=488, tokens_out=150,
                                         error=None, request_id="r1", trace_id="t1"))
    spec = line["_aws"]["CloudWatchMetrics"][0]
    assert spec["Namespace"] == "ShopKart/Copilot"
    assert spec["Dimensions"] == [["Service", "Model"]]
    names = {m["Name"] for m in spec["Metrics"]}
    assert {"LatencyMs", "TTFTMs", "CostUSD", "Requests", "Errors"} <= names
    for name in names:  # every metric named in _aws has its number in the line
        assert isinstance(line[name], (int, float))
    assert line["Model"] == "claude-haiku-5-5" and line["Errors"] == 0
    assert line["trace_id"] == "t1" and line["request_id"] == "r1"


# ---- the app: one trace per request ---------------------------------------------------


def test_one_request_is_one_trace_with_nested_spans(monkeypatch, capsys):
    tc, exporter = traced_app([("stream", anthropic_stream(["Your refund ", "is on its way."]))], monkeypatch)
    r = tc.post("/chat", json=ASK)
    done = events(r.text)[-1]
    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert set(spans) == {"POST /chat", "execute_tool lookup_order", "chat claude-haiku-5-5"}
    root = spans["POST /chat"]
    assert len({s.context.trace_id for s in spans.values()}) == 1
    assert spans["chat claude-haiku-5-5"].parent.span_id == root.context.span_id
    assert spans["execute_tool lookup_order"].parent.span_id == root.context.span_id
    # the trace ID goes back to the browser
    assert done["trace_id"] == format(root.context.trace_id, "032x") == r.headers["x-trace-id"]
    assert root.attributes["gen_ai.conversation.id"] == "conv-42"
    assert root.attributes["shopkart.request_id"] == r.headers["x-request-id"]
    chat = spans["chat claude-haiku-5-5"]
    assert chat.attributes["gen_ai.usage.output_tokens"] == 12
    assert chat.attributes["shopkart.cost_usd"] > 0
    assert any(e.name == "first_token" for e in chat.events)
    # no prompt text in the trace unless you opt in
    assert "gen_ai.input.messages" not in chat.attributes
    # and one EMF line on stdout with the same trace ID
    emf = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{"_aws"')]
    assert emf and emf[-1]["trace_id"] == done["trace_id"]


def test_content_capture_is_opt_in_and_redacted(monkeypatch):
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    tc, exporter = traced_app([("stream", anthropic_stream(["Done."]))], monkeypatch)
    tc.post("/chat", json=ASK)
    chat = next(s for s in exporter.get_finished_spans() if s.name.startswith("chat "))
    sent = chat.attributes["gen_ai.input.messages"]
    assert "SK04512" in sent and "asha@example.com" not in sent and "[email]" in sent


def test_a_failed_call_is_an_error_span(monkeypatch, capsys):
    tc, exporter = traced_app([("stream", anthropic_stream(["Your ", "x"], error_after=1))], monkeypatch)
    evs = events(tc.post("/chat", json=ASK).text)
    assert evs[-1]["type"] == "error"
    spans = {s.name: s for s in exporter.get_finished_spans()}
    chat = spans["chat claude-haiku-5-5"]
    assert chat.status.status_code == StatusCode.ERROR and chat.attributes["error.type"]
    assert spans["POST /chat"].status.status_code == StatusCode.ERROR
    emf = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{"_aws"')]
    assert emf[-1]["Errors"] == 1


def test_dashboard_has_p95_errors_and_cost():
    body = (LAB / "dashboard.json").read_text()
    for needle in ("'p95'", "Errors", "CostUSD", "TTFTMs", "LOG_GROUP"):
        assert needle in body
    json.loads(body)
