"""Tracing and metrics for the Copilot: OpenTelemetry spans with the gen-AI names, plus one
metrics line per request for the CloudWatch dashboard.

    tracer = setup_tracing()            # spans go to OTEL_EXPORTER_OTLP_ENDPOINT, if it's set
    span.set_attributes(llm_attributes(...))
    print(emf_line(...))                # CloudWatch turns this log line into metrics

Names follow the OpenTelemetry semantic conventions for generative AI (still marked
"in development", so they can change). There's no standard name for cost, prompt version
or time to first token yet, so those are ours, under "shopkart.".
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

SERVICE = "shopkart-copilot"
METRICS_NAMESPACE = "ShopKart/Copilot"


def setup_tracing(exporter: SpanExporter | None = None) -> trace.Tracer:
    """One tracer for the app. Spans are sent in batches, in the background, never in the answer's way."""
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE}))
    if exporter is None and os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter()  # reads OTEL_EXPORTER_OTLP_ENDPOINT, adds /v1/traces
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider.get_tracer("shopkart.copilot")


# --------------------------------------------------------------------------
# What every model call records
# --------------------------------------------------------------------------


def llm_attributes(*, provider: str, model: str, prompt_version: str, tokens_in: int, tokens_out: int,
                   cost_usd: float, ttft_ms: float, max_tokens: int,
                   provider_request_id: str | None = None) -> dict:
    """The span attributes for one model call: standard gen_ai.* names where they exist."""
    # TODO 1: return a dict with the standard names where they exist:
    #   gen_ai.operation.name ("chat"), gen_ai.provider.name, gen_ai.request.model,
    #   gen_ai.request.max_tokens, gen_ai.usage.input_tokens, gen_ai.usage.output_tokens
    # and our own names where there's no standard yet:
    #   shopkart.prompt.version, shopkart.cost_usd (rounded to 8 places), shopkart.ttft_ms (whole ms),
    #   shopkart.provider_request_id (only when there is one)
    return {}


def request_attributes(*, session_id: str, request_id: str, feature: str = "chat") -> dict:
    """Labels for the whole trace: the conversation, the feature, and an ANONYMOUS user ID."""
    return {
        "gen_ai.conversation.id": session_id,
        "shopkart.feature": feature,
        "shopkart.user.anon_id": hashlib.sha256(session_id.encode()).hexdigest()[:12],
        "shopkart.request_id": request_id,
    }


# --------------------------------------------------------------------------
# Redact before anything is written
# --------------------------------------------------------------------------

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\d)")


def redact(text: str) -> str:
    """Mask emails, card numbers and Indian phone numbers. Cards first: they're the longest."""
    # TODO 2: replace each match of _EMAIL, _CARD and _PHONE (in that order) with
    #         [email], [card] and [phone]. Order IDs like SK04512 must survive.
    return text


def capture_content() -> bool:
    """Prompts and answers go into traces only when you opt in (the OTel convention)."""
    return os.environ.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "").lower() == "true"


# --------------------------------------------------------------------------
# One metrics line per request: CloudWatch Embedded Metric Format (EMF)
# --------------------------------------------------------------------------

METRICS = [("LatencyMs", "Milliseconds"), ("TTFTMs", "Milliseconds"), ("CostUSD", "None"),
           ("InputTokens", "Count"), ("OutputTokens", "Count"), ("Requests", "Count"), ("Errors", "Count")]


def emf_line(*, model: str, prompt_version: str, latency_ms: float, ttft_ms: float | None, cost_usd: float,
             tokens_in: int, tokens_out: int, error: str | None, request_id: str, trace_id: str) -> str:
    """A JSON log line that is ALSO a set of metrics. CloudWatch Logs reads the _aws block and
    records each named number as a metric, per Service and Model. The other fields (request ID,
    trace ID, prompt version) stay searchable in the log."""
    # TODO 3: add the "_aws" block that turns this line into metrics:
    #   "_aws": {"Timestamp": <now in ms>, "CloudWatchMetrics": [{
    #       "Namespace": METRICS_NAMESPACE, "Dimensions": [["Service", "Model"]],
    #       "Metrics": [{"Name": name, "Unit": unit} for each (name, unit) in METRICS that has a value]}]}
    # and the numbers themselves: LatencyMs, TTFTMs (only if there was a first token), CostUSD,
    # InputTokens, OutputTokens, Requests (always 1) and Errors (1 if error, else 0).
    return json.dumps({"Service": SERVICE, "Model": model, "event": "chat", "prompt_version": prompt_version,
                       "error": error, "request_id": request_id, "trace_id": trace_id})
