"""The ShopKart Copilot web service, traced, and now with COST CAPS (look for "LIMITS"):
  - per user: a rate limit (messages a minute) and a spend limit (rupees a day) -> 429 + Retry-After
  - a global daily cap with a ladder: alert at 80%, degrade at 90%, lite mode at 100%
  - GET /budget shows today's spend and the mode

From the tracing lab (look for "TRACING"):
  - every request is one trace: a request span, a lookup_order tool span, a chat model span
  - the model span carries the gen_ai.* attributes, cost, prompt version and time to first token
  - one JSON line per request in CloudWatch Embedded Metric Format, for the dashboard
  - the trace ID goes back to the browser in the done event and the X-Trace-ID header

    GET  /         a tiny chat page (open the live URL on your phone)
    GET  /health   {"status": "ok"} for the load balancer. Never calls the model.
    POST /chat     {"session_id": "...", "message": "..."}  ->  server-sent events:
                   data: {"type": "text", "text": "..."}       (many)
                   data: {"type": "done", "request_id": ..., "tokens_in": ..., "cost_usd": ...}
                   data: {"type": "error", "message": ..., "request_id": ...}   (instead of done)

Settings come from the environment, never from the image:
    LLM_PROVIDER         anthropic (default) | openai | fake (no model, no cost: for load tests)
    ANTHROPIC_API_KEY    on ECS: injected from Secrets Manager (the service holds only a reference)
    OPENAI_API_KEY       the same, for LLM_PROVIDER=openai
    <KEY>_SECRET_ID      on Lambda: the secret's name; the app reads it once at start-up
    MODEL, MAX_TOKENS, DAILY_BUDGET_USD, SHOPKART_STATE_DIR
    OTEL_EXPORTER_OTLP_ENDPOINT   where spans go (e.g. http://localhost:4318 for Jaeger). Unset: no export.
    PROMPT_VERSION       recorded on every model span (default v1)
    USER_PER_MINUTE, USER_DAILY_INR, GLOBAL_DAILY_INR   the limits (defaults 10, ₹20, ₹36,000)

Run it locally:
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uv run uvicorn app:app --app-dir labs/loadtest/done --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import anthropic
import openai
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from pydantic import BaseModel, Field


def _find_root() -> Path:
    """The folder with shopkart/ and data/: the repo root, or /app inside the image."""
    here = Path(__file__).resolve().parent
    for folder in (here, *here.parents):
        if (folder / "shopkart").is_dir() and (folder / "data").is_dir():
            return folder
    raise RuntimeError("Can't find the shopkart/ package and data/ folder")


ROOT = _find_root()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import telemetry  # noqa: E402  (TRACING: the gen-AI attribute names, redaction, the metrics line)
from limits import CostGuard  # noqa: E402  (LIMITS)

from shopkart import budget  # noqa: E402
from shopkart.llm import DEFAULT_MODELS, KEY_NAMES, LLM, _anthropic_usage, _openai_usage, call_cost_usd  # noqa: E402

# The ledger must live somewhere writable: /tmp on Lambda, a folder the app user owns in the image.
if os.environ.get("SHOPKART_STATE_DIR"):
    budget.LEDGER_DIR = Path(os.environ["SHOPKART_STATE_DIR"])

CLIENT_TIMEOUT_S = 30.0  # each wait for the provider (the SDK default is 10 minutes)
ANSWER_BUDGET_S = 60.0   # the whole answer, however slowly it trickles
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "300"))
FAKE_PRICE_MODEL = "claude-haiku-5-5"  # fake mode bills fake tokens at Haiku's price
PROMPT_VERSION = os.environ.get("PROMPT_VERSION", "v1")  # change the prompt -> change the version

SYSTEM = (
    "You are ShopKart's support Copilot, answering a customer in a chat window. "
    "ShopKart is an online store in India. Today is 2026-11-17.\n"
    "Policy: returns within 14 days of delivery (footwear 10 days; electronics 7 days, unopened unless "
    "faulty or damaged). Refunds go to the original payment method within 5 to 7 working days of pickup. "
    "Refunds above ₹5,000 need a human: say a teammate will confirm, never promise one.\n"
    "Use only the order details given. If something isn't there, say so and offer a human. "
    "Answer in at most three short sentences, in plain text."
)


# --------------------------------------------------------------------------
# Secrets and the model client, read once at start-up
# --------------------------------------------------------------------------


def load_secrets_from_aws() -> None:
    """Lambda has no 'secrets' setting like ECS. So for each <KEY>_SECRET_ID, read the secret once."""
    wanted = {k: os.environ[f"{k}_SECRET_ID"] for k in KEY_NAMES.values()
              if os.environ.get(f"{k}_SECRET_ID") and not os.environ.get(k)}
    if not wanted:
        return
    import boto3  # only needed on Lambda

    sm = boto3.client("secretsmanager")
    for key_name, secret_id in wanted.items():
        os.environ[key_name] = sm.get_secret_value(SecretId=secret_id)["SecretString"].strip()


def provider() -> str:
    return os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()


def make_llm() -> LLM | None:
    """The async client for the chosen provider. A missing key fails NOW, not on the first customer."""
    name = provider()
    if name == "fake":
        return None
    if name not in KEY_NAMES:
        raise RuntimeError(f"LLM_PROVIDER must be anthropic, openai or fake, not {name!r}")
    key = os.environ.get(KEY_NAMES[name], "").strip()
    if not key:
        raise RuntimeError(f"{KEY_NAMES[name]} is not set. On AWS it comes from Secrets Manager.")
    cls = anthropic.AsyncAnthropic if name == "anthropic" else openai.AsyncOpenAI
    client = cls(api_key=key, timeout=CLIENT_TIMEOUT_S, max_retries=1)
    # shopkart.llm.LLM builds the request arguments; we only swap in the ASYNC client.
    return LLM(name, os.environ.get("MODEL") or DEFAULT_MODELS[name], client=client)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_secrets_from_aws()
    app.state.llm = make_llm()
    app.state.tracer = telemetry.setup_tracing()  # TRACING
    app.state.guard = CostGuard.from_env()  # LIMITS: in memory, so one copy of the app
    log_event("startup", provider=provider(), model=app.state.llm.model if app.state.llm else "fake")
    yield


app = FastAPI(title="ShopKart Copilot", version="1.0", lifespan=lifespan)


# --------------------------------------------------------------------------
# A request ID on every request: in the response header and in every log line
# --------------------------------------------------------------------------


def log_event(event: str, **fields) -> None:
    """One JSON line per event on stdout. On AWS, stdout goes to CloudWatch Logs."""
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    if getattr(request.state, "trace_id", None):
        response.headers["X-Trace-ID"] = request.state.trace_id
    return response


# --------------------------------------------------------------------------
# Typed requests, and the context for one question
# --------------------------------------------------------------------------


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=64)  # LIMITS: who pays; default: the session

    @property
    def user(self) -> str:
        return self.user_id or self.session_id


ORDERS = {o["order_id"]: o for o in json.loads((ROOT / "data" / "orders.json").read_text(encoding="utf-8"))}


def find_order(message: str) -> dict | None:
    """'order 4512' or 'SK04512' -> the order, without names or addresses."""
    for digits in re.findall(r"\b(?:SK)?(\d{4,5})\b", message, flags=re.IGNORECASE):
        order = ORDERS.get(f"SK{int(digits):05d}")
        if order:
            keep = ("order_id", "status", "placed_on", "delivered_on", "items", "total_inr",
                    "payment_method", "refunds", "return")
            return {k: order.get(k) for k in keep}
    return None


def user_prompt(message: str) -> str:
    order = find_order(message)
    facts = json.dumps(order, ensure_ascii=False) if order else "No order number found in the message."
    return f"<order>\n{facts}\n</order>\n\nCustomer: {message}"


# --------------------------------------------------------------------------
# Streaming the answer: the model's pieces, then the usage
# --------------------------------------------------------------------------


@dataclass
class Usage:
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    provider_request_id: str | None = None


async def model_stream(llm: LLM, prompt: str, max_tokens: int = MAX_TOKENS) -> AsyncIterator[str | Usage]:
    """Async all the way down: while one customer waits, the server serves the others."""
    msgs = [{"role": "user", "content": prompt}]
    if llm.provider == "anthropic":
        args = llm._anthropic_args(msgs, SYSTEM, max_tokens, None, False)
        async with llm._client.messages.stream(**args) as stream:
            async for text in stream.text_stream:
                yield text
            final = await stream.get_final_message()
            request_id = stream.request_id
        usage = _anthropic_usage(final.usage)
    else:
        args = llm._openai_args(msgs, SYSTEM, max_tokens, None)
        async with llm._client.responses.stream(**args) as stream:
            async for event in stream:
                if event.type == "response.output_text.delta":
                    yield event.delta
            final = await stream.get_final_response()
            request_id = stream._response.headers.get("x-request-id")
        usage = _openai_usage(final.usage)
    cost = call_cost_usd(llm.model, usage["in"], usage["out"], usage["cache_read"], usage["cache_write"])
    yield Usage(llm.model, usage["in"], usage["out"], cost, request_id)  # the provider's own ID


async def fake_stream(prompt: str) -> AsyncIterator[str | Usage]:
    """No model and no cost: a canned answer at a model-like pace. For load tests."""
    await asyncio.sleep(float(os.environ.get("FAKE_TTFT_S", "0.4")))
    order = find_order(prompt)
    words = (f"Thanks for asking! Your order {order['order_id']} is {order['status']}. "
             if order else "Thanks for asking! ") + \
        "This is a test answer from fake mode, so no model was called and nothing was billed."
    for word in words.split(" "):
        yield word + " "
        await asyncio.sleep(float(os.environ.get("FAKE_WORD_S", "0.05")))
    tokens_in, tokens_out = (len(SYSTEM) + len(prompt)) // 4, len(words) // 4
    yield Usage("fake", tokens_in, tokens_out, call_cost_usd(FAKE_PRICE_MODEL, tokens_in, tokens_out, 0, 0))


async def lite_stream(prompt: str) -> AsyncIterator[str | Usage]:
    """LIMITS, lite mode: no model call. Order status straight from the database, or the FAQ."""
    order = find_order(prompt)
    if order:
        refund = next(iter(order.get("refunds") or []), None)
        text = f"Order {order['order_id']} is {order['status']}."
        if refund:
            text += f" Refund of ₹{refund['amount_inr']:,} {refund['status']} on {refund['date']} (ref {refund['reference']})."
    else:
        text = "Returns: 14 days from delivery (footwear 10, electronics 7). Refunds: 5 to 7 working days after pickup."
    yield text + " The Copilot is busy right now. To talk to a person, reply 'agent' or open Help > Create a ticket."
    yield Usage("lite", 0, 0, 0.0)


def sse(data: dict) -> str:
    """One server-sent event: a line starting with 'data: ', a little JSON, then a blank line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def answer_events(llm: LLM | None, req: ChatRequest, request_id: str,
                        tracer: trace.Tracer, root: trace.Span, guard: CostGuard, mode: str) -> AsyncIterator[str]:
    """TRACING: `root` is the request span. Children are made with an explicit parent, because an
    async generator can't safely keep a span 'current' across its yields."""
    parent = trace.set_span_in_context(root)
    trace_id = format(root.get_span_context().trace_id, "032x")
    start = time.monotonic()
    ttft = None
    usage = None
    error = None

    with tracer.start_span("execute_tool lookup_order", context=parent) as tool:
        tool.set_attributes({"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "lookup_order"})
        prompt = user_prompt(req.message)
        tool.set_attribute("shopkart.order_found", "No order number found" not in prompt)

    # LIMITS: the ladder decides how this request is answered.
    max_tokens = MAX_TOKENS // 2 if mode == "degraded" else MAX_TOKENS  # degraded: shorter answers
    model = "lite" if mode == "lite" else llm.model if llm else "fake"
    root.set_attribute("shopkart.budget_mode", mode)
    span = tracer.start_span(f"chat {model}", context=parent, kind=SpanKind.CLIENT)
    if telemetry.capture_content():  # opt-in, and redacted first
        span.set_attribute("gen_ai.input.messages", telemetry.redact(prompt))
    if mode == "lite":
        stream = lite_stream(prompt)
    else:
        stream = model_stream(llm, prompt, max_tokens) if llm else fake_stream(prompt)
    answer = []
    try:
        async with asyncio.timeout(ANSWER_BUDGET_S):
            async for piece in stream:
                if isinstance(piece, Usage):
                    usage = piece
                    continue
                if ttft is None:
                    ttft = time.monotonic() - start
                    span.add_event("first_token")
                answer.append(piece)
                yield sse({"type": "text", "text": piece})
    except (TimeoutError, anthropic.APIError, openai.APIError) as exc:
        # The 200 status went out with the first byte, so a failure is an EVENT, not a status code.
        error = "timeout" if isinstance(exc, TimeoutError) else type(exc).__name__
        span.set_attribute("error.type", error)
        span.set_status(Status(StatusCode.ERROR, error))
        root.set_status(Status(StatusCode.ERROR, error))
        yield sse({"type": "error", "request_id": request_id, "trace_id": trace_id,
                   "message": "Sorry, the Copilot couldn't finish this answer. Please try again."})
    finally:
        latency = time.monotonic() - start
        if usage:
            span.set_attributes(telemetry.llm_attributes(
                provider=llm.provider if llm else "fake", model=usage.model, prompt_version=PROMPT_VERSION,
                tokens_in=usage.tokens_in, tokens_out=usage.tokens_out, cost_usd=usage.cost_usd,
                ttft_ms=(ttft or latency) * 1000, max_tokens=max_tokens,
                provider_request_id=usage.provider_request_id))
            if telemetry.capture_content():
                span.set_attribute("gen_ai.output.messages", telemetry.redact("".join(answer)))
        span.end()
        # One line: a log entry AND the dashboard's metrics.
        print(telemetry.emf_line(
            model=model, prompt_version=PROMPT_VERSION, latency_ms=latency * 1000,
            ttft_ms=ttft * 1000 if ttft is not None else None, cost_usd=usage.cost_usd if usage else 0.0,
            tokens_in=usage.tokens_in if usage else 0, tokens_out=usage.tokens_out if usage else 0,
            error=error, request_id=request_id, trace_id=trace_id), flush=True)
        root.end()
    if error:
        return
    if usage.model not in ("fake", "lite"):
        budget.record(usage.cost_usd)
    if guard.record(req.user, usage.cost_usd) == "budget_alert":  # LIMITS: the real cost, after the call
        log_event("budget_alert", request_id=request_id, **guard.status())
    yield sse({"type": "done", "request_id": request_id, "trace_id": trace_id, "model": usage.model, "mode": mode,
               "tokens_in": usage.tokens_in, "tokens_out": usage.tokens_out,
               "cost_usd": round(usage.cost_usd, 6), "ttft_ms": round((ttft or latency) * 1000),
               "latency_ms": round(latency * 1000)})


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/budget")
async def budget_status(request: Request) -> dict:
    """LIMITS: today's spend against the global cap, and the current mode. (Protect this in production.)"""
    return request.app.state.guard.status()


@app.post("/chat")
async def chat(req: ChatRequest, request: Request):
    request_id = request.state.request_id
    try:
        budget.check()  # before the call: no model call once today's budget is spent
    except budget.BudgetExceeded:
        log_event("chat_blocked", request_id=request_id, reason="daily_budget")
        return JSONResponse(status_code=429, headers={"Retry-After": "3600"},
                            content={"error": "The Copilot's daily budget is used up.", "request_id": request_id})
    # LIMITS: check the user's limits and the global ladder BEFORE any model call, with a worst-case
    # estimate (the input, plus max_tokens out). The real cost is added after the call.
    guard: CostGuard = request.app.state.guard
    tokens_in_estimate = (len(SYSTEM) + len(user_prompt(req.message))) // 3
    estimate = call_cost_usd(FAKE_PRICE_MODEL if request.app.state.llm is None else request.app.state.llm.model,
                             tokens_in_estimate, MAX_TOKENS, 0, 0)
    verdict = guard.check(req.user, estimate)
    if not verdict.allowed:
        log_event("limited", request_id=request_id, user=req.user, reason=verdict.reason,
                  retry_after_s=verdict.retry_after_s)
        return JSONResponse(status_code=429, headers={"Retry-After": str(verdict.retry_after_s)}, content={
            "error": "You've reached your limit for now. Please try again later, or ask for a human.",
            "reason": verdict.reason, "retry_after_s": verdict.retry_after_s, "request_id": request_id})

    # TRACING: the request span. It ends when the stream ends, not when this function returns.
    tracer = request.app.state.tracer
    root = tracer.start_span("POST /chat", kind=SpanKind.SERVER,
                             attributes=telemetry.request_attributes(session_id=req.session_id, request_id=request_id))
    request.state.trace_id = format(root.get_span_context().trace_id, "032x")
    return StreamingResponse(
        answer_events(request.app.state.llm, req, request_id, tracer, root, guard, verdict.mode),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},  # no proxy buffering
    )


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ShopKart Copilot</title>
<style>body{font:16px system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem}
#a{white-space:pre-wrap;min-height:4rem;border:1px solid #ccc;border-radius:8px;padding:.75rem}
input{width:100%;font:inherit;padding:.5rem;box-sizing:border-box}small{color:#666}</style></head>
<body><h1>ShopKart Copilot</h1><form id="f"><input id="m" value="Where is my refund for order 4512?">
</form><p id="a"></p><small id="s"></small><script>
f.onsubmit = async (e) => { e.preventDefault(); a.textContent = ""; s.textContent = "";
  const r = await fetch("/chat", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({session_id: "web", message: m.value})});
  if (!r.ok) { a.textContent = "Error " + r.status; return; }
  const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "";
  for (;;) { const {value, done} = await rd.read(); if (done) break;
    buf += dec.decode(value, {stream: true}); const parts = buf.split("\\n\\n"); buf = parts.pop();
    for (const p of parts) { if (!p.startsWith("data: ")) continue; const ev = JSON.parse(p.slice(6));
      if (ev.type === "text") a.textContent += ev.text;
      if (ev.type === "done") s.textContent = ev.model + " · " + ev.ttft_ms + " ms to first token · $" + ev.cost_usd + " · trace " + ev.trace_id + " · " + ev.mode;
      if (ev.type === "error") s.textContent = ev.message + " (" + ev.request_id + ")"; } } };
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
async def page() -> str:
    return PAGE
