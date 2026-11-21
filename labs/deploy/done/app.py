"""The ShopKart Copilot as a web service: FastAPI, streamed answers, ready for the cloud.

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

Run it locally:
    uv run uvicorn app:app --app-dir labs/deploy/done --port 8000
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

from shopkart import budget  # noqa: E402
from shopkart.llm import DEFAULT_MODELS, KEY_NAMES, LLM, _anthropic_usage, _openai_usage, call_cost_usd  # noqa: E402

# The ledger must live somewhere writable: /tmp on Lambda, a folder the app user owns in the image.
if os.environ.get("SHOPKART_STATE_DIR"):
    budget.LEDGER_DIR = Path(os.environ["SHOPKART_STATE_DIR"])

CLIENT_TIMEOUT_S = 30.0  # each wait for the provider (the SDK default is 10 minutes)
ANSWER_BUDGET_S = 60.0   # the whole answer, however slowly it trickles
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "300"))
FAKE_PRICE_MODEL = "claude-haiku-5-5"  # fake mode bills fake tokens at Haiku's price

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
    return response


# --------------------------------------------------------------------------
# Typed requests, and the context for one question
# --------------------------------------------------------------------------


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)


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


async def model_stream(llm: LLM, prompt: str) -> AsyncIterator[str | Usage]:
    """Async all the way down: while one customer waits, the server serves the others."""
    msgs = [{"role": "user", "content": prompt}]
    if llm.provider == "anthropic":
        args = llm._anthropic_args(msgs, SYSTEM, MAX_TOKENS, None, False)
        async with llm._client.messages.stream(**args) as stream:
            async for text in stream.text_stream:
                yield text
            final = await stream.get_final_message()
            request_id = stream.request_id
        usage = _anthropic_usage(final.usage)
    else:
        args = llm._openai_args(msgs, SYSTEM, MAX_TOKENS, None)
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


def sse(data: dict) -> str:
    """One server-sent event: a line starting with 'data: ', a little JSON, then a blank line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def answer_events(llm: LLM | None, req: ChatRequest, request_id: str) -> AsyncIterator[str]:
    start = time.monotonic()
    ttft = None
    usage = None
    stream = model_stream(llm, user_prompt(req.message)) if llm else fake_stream(user_prompt(req.message))
    try:
        async with asyncio.timeout(ANSWER_BUDGET_S):
            async for piece in stream:
                if isinstance(piece, Usage):
                    usage = piece
                    continue
                if ttft is None:
                    ttft = time.monotonic() - start
                yield sse({"type": "text", "text": piece})
    except (TimeoutError, anthropic.APIError, openai.APIError) as exc:
        # The 200 status went out with the first byte, so a failure is an EVENT, not a status code.
        kind = "timeout" if isinstance(exc, TimeoutError) else type(exc).__name__
        log_event("chat_error", request_id=request_id, session_id=req.session_id, error=kind,
                  latency_ms=round((time.monotonic() - start) * 1000))
        yield sse({"type": "error", "request_id": request_id,
                   "message": "Sorry, the Copilot couldn't finish this answer. Please try again."})
        return
    latency = time.monotonic() - start
    if usage.model != "fake":
        budget.record(usage.cost_usd)
    done = {"type": "done", "request_id": request_id, "model": usage.model, "tokens_in": usage.tokens_in,
            "tokens_out": usage.tokens_out, "cost_usd": round(usage.cost_usd, 6),
            "ttft_ms": round((ttft or latency) * 1000), "latency_ms": round(latency * 1000)}
    log_event("chat", session_id=req.session_id, provider_request_id=usage.provider_request_id,
              **{k: v for k, v in done.items() if k != "type"})
    yield sse(done)


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/chat")
async def chat(req: ChatRequest, request: Request):
    request_id = request.state.request_id
    try:
        budget.check()  # before the call: no model call once today's budget is spent
    except budget.BudgetExceeded:
        log_event("chat_blocked", request_id=request_id, reason="daily_budget")
        return JSONResponse(status_code=429, headers={"Retry-After": "3600"},
                            content={"error": "The Copilot's daily budget is used up.", "request_id": request_id})
    return StreamingResponse(
        answer_events(request.app.state.llm, req, request_id),
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
      if (ev.type === "done") s.textContent = ev.model + " · " + ev.ttft_ms + " ms to first token · $" + ev.cost_usd + " · " + ev.request_id;
      if (ev.type === "error") s.textContent = ev.message + " (" + ev.request_id + ")"; } } };
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
async def page() -> str:
    return PAGE
