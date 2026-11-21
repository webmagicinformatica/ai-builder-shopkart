"""The document assistant from capstone 1, as a production web service.

Almost nothing here is new. It wires three things together:
  - capstone/doc-assistant/solution   hybrid search + rerank, the score floor, the JSON answer,
                                       the grounding check per passage, the disk cache
  - labs/loadtest/done/telemetry.py    traces with gen_ai.* attributes, redaction, the EMF metrics line
  - labs/loadtest/done/limits.py       per-user limits and the global daily cap with its ladder
and the deploy lab's habits: typed requests, /health, a request ID everywhere, keys only from
the environment, a timeout on every wait.

    GET  /         a small page: ask a question, see the answer with its sources
    GET  /health   {"status": "ok"}: for the load balancer. Never searches, never calls the model.
    GET  /budget   today's spend against the cap, and the mode (protect this in a real product)
    POST /chat     {"session_id": "...", "message": "...", "user_id": "..."}  ->  server-sent events:
                   data: {"type": "status", "text": "Searching the policies"}
                   data: {"type": "text", "text": "<the CHECKED answer, all at once>"}
                   data: {"type": "done", "kind": "answer" | "handover", "sources": [...], ...}

Why the answer isn't streamed word by word: nothing reaches the customer before the grounding
check has passed, and the check needs the whole answer. So the page shows a status line while
we search and answer, then the checked answer in one piece.

One request is one trace:
    POST /chat
      ├─ retrieve hybrid+rerank        best score, k, how long the CPU took
      ├─ chat claude-haiku-5-5         tokens, cost, prompt version, the provider's request ID
      └─ grounding_check               passed or not, and why

Settings (environment only, never in the image; see service.env):
    LLM_PROVIDER         anthropic (default) | openai | fake (no model, no cost: for load tests)
    ANTHROPIC_API_KEY    on ECS, injected from Secrets Manager. OPENAI_API_KEY for openai.
    MODEL                default: the provider's small model
    DAILY_BUDGET_USD     the hard stop (shopkart.budget), just above the ladder's 100%
    USER_PER_MINUTE, USER_DAILY_INR, GLOBAL_DAILY_INR   the limits and the cap with its ladder
    PROMPT_VERSION       on every model span (default doc-v1)
    OTEL_EXPORTER_OTLP_ENDPOINT   where spans go. Unset: no export (the metrics line still prints).
    SHOPKART_STATE_DIR   a writable folder for the spend ledger and the answer cache

Run it locally (needs the index: uv run python labs/rag/done/ingest.py):
    LLM_PROVIDER=fake uv run uvicorn app:app --app-dir capstone/production/solution --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from pydantic import BaseModel, Field


def _find_root() -> Path:
    """The folder with shopkart/ and data/: the repo root, or /app inside the image."""
    here = Path(__file__).resolve().parent
    for folder in (here, *here.parents):
        if (folder / "shopkart").is_dir() and (folder / "labs").is_dir():
            return folder
    raise RuntimeError("Can't find the shopkart/ package and the labs/ folder")


ROOT = _find_root()
for p in (ROOT, ROOT / "labs" / "rag" / "done", ROOT / "labs" / "rag-hybrid" / "done",
          ROOT / "labs" / "loadtest" / "done", ROOT / "capstone" / "doc-assistant" / "solution",
          Path(__file__).resolve().parent):
    sys.path.insert(0, str(p))  # the last one wins: this folder first

import ask  # noqa: E402  (the RAG lab: the prompt, the JSON answer, the cache, the handover text)
import assistant  # noqa: E402  (capstone 1: DocAssistant, the floor, the check per passage)
import hybrid  # noqa: E402  (the hybrid-search lab: BM25 + vectors, the reranker)
import telemetry  # noqa: E402  (the tracing lab: gen_ai.* attributes, redaction, the metrics line)
from limits import CostGuard  # noqa: E402  (the load-test lab: per-user limits, the daily cap)
from fake_llm import FakeDocLLM  # noqa: E402

from shopkart import budget  # noqa: E402
from shopkart import llm as shopkart_llm  # noqa: E402
from shopkart.llm import LLM, LLMError, call_cost_usd  # noqa: E402

if os.environ.get("SHOPKART_STATE_DIR"):  # the image's code folder is read-only for the app user
    budget.LEDGER_DIR = Path(os.environ["SHOPKART_STATE_DIR"])
    shopkart_llm.CALL_LOG = budget.LEDGER_DIR / "calls.csv"

ANSWER_BUDGET_S = 60.0  # the whole request: search, model (30 s per wait inside), check
MAX_TOKENS_OUT = 400    # ask.cached_complete asks for at most this many
PROMPT_VERSION = os.environ.get("PROMPT_VERSION", "doc-v1")
# The guard checks BEFORE retrieval, so it can't count this request's prompt yet. A worst case
# instead: five long chunks in, the full answer out. Measured: the longest prompts are ~1,900 tokens.
WORST_CASE_TOKENS_IN = 2_500
# The reranker is the CPU-heavy step. Measured on the 50 policy questions (one CPU): reranking the
# top 10 instead of 20 kept hit@1 36/50, hit@5 49/50 and the floor's 6 of 10 "I don't know"
# questions exactly the same, and halved the time (median 1,495 -> 709 ms).
hybrid.RERANK_CANDIDATES = int(os.environ.get("RERANK_CANDIDATES", "10"))


def log_event(event: str, **fields) -> None:
    """One JSON line per event on stdout. On AWS, stdout goes to CloudWatch Logs."""
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def provider() -> str:
    return os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()


def make_llm():
    """The model client. A missing key fails NOW, at start-up, not on the first customer."""
    if provider() == "fake":
        return FakeDocLLM()
    return LLM(provider(), os.environ.get("MODEL") or None, timeout=30.0, max_attempts=2, max_total_s=40.0)


def state_dir() -> Path:
    return Path(os.environ.get("SHOPKART_STATE_DIR") or ROOT / ".shopkart")


def cpu_quota(cgroup: Path = Path("/sys/fs/cgroup")) -> int | None:
    """How many CPUs the container may really use: its cgroup quota, rounded up. None if unlimited."""
    try:
        if (cgroup / "cpu.max").exists():  # cgroup v2: "100000 100000" or "max 100000"
            quota, period = (cgroup / "cpu.max").read_text().split()
        else:  # cgroup v1
            quota = (cgroup / "cpu" / "cpu.cfs_quota_us").read_text().strip()
            period = (cgroup / "cpu" / "cpu.cfs_period_us").read_text().strip()
    except (OSError, ValueError):
        return None
    if quota in ("max", "-1"):
        return None
    return max(1, -(-int(quota) // int(period)))


def match_threads_to_cpu_quota() -> int:
    """What broke: the local models start one thread per CPU they can SEE. A container limited to
    1 CPU on a 32-core host sees 32, so ONNX ran 32 threads on one CPU's worth of time, and a
    search took 20 s instead of 0.6 s. The labs' code counts CPUs with os.sched_getaffinity(),
    so we narrow that to the real quota (or SEARCH_THREADS) before any model loads."""
    want = int(os.environ.get("SEARCH_THREADS", "0")) or cpu_quota()
    cpus = sorted(os.sched_getaffinity(0))
    if want and want < len(cpus):
        os.sched_setaffinity(0, cpus[:want])
    return len(os.sched_getaffinity(0))


@asynccontextmanager
async def lifespan(app: FastAPI):
    threads = match_threads_to_cpu_quota()
    llm = make_llm()
    # What broke: the index and the reranker use SQLite and ONNX objects that must stay on the
    # thread that made them. So retrieval gets ONE thread of its own, made here, and every search
    # runs on it. One at a time is also right for the CPU: a 1 vCPU task can't rerank two at once
    # any faster.
    app.state.search_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="search")
    loop = asyncio.get_running_loop()
    cache = None if provider() == "fake" else state_dir() / "cache" / "answers"
    app.state.bot = await loop.run_in_executor(app.state.search_pool, lambda: _warm(make_bot(llm, cache)))
    app.state.tracer = telemetry.setup_tracing()
    app.state.guard = CostGuard.from_env()
    log_event("startup", provider=provider(), model=llm.model, chunks=len(app.state.bot.index.chunks), threads=threads,
              floor=app.state.bot.min_score, prompt_version=PROMPT_VERSION)
    yield
    app.state.search_pool.shutdown(wait=False)


def make_bot(llm, cache_dir: Path | None) -> assistant.DocAssistant:
    """Capstone 1's assistant, unchanged: the real index and the local reranker (tests swap in fakes)."""
    return assistant.DocAssistant(llm, cache_dir=cache_dir)


def _warm(bot: assistant.DocAssistant) -> assistant.DocAssistant:
    """Load both local models at start-up: the first customer shouldn't wait for them."""
    bot.retrieve("How many days do I have to return a product?")
    return bot


app = FastAPI(title="ShopKart Policy Assistant", version="1.0", lifespan=lifespan)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    if getattr(request.state, "trace_id", None):
        response.headers["X-Trace-ID"] = request.state.trace_id
    return response


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=1000)
    user_id: str | None = Field(default=None, max_length=64)  # who pays; default: the session

    @property
    def user(self) -> str:
        return self.user_id or self.session_id


def sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


LITE_TEXT = ("Our assistant is resting for today, so here is the closest section of our policies: "
             "{title} ({label}). To talk to a person, reply 'agent' or open Help > Create a ticket.")


async def answer_events(request: Request, req: ChatRequest, mode: str, root: trace.Span):
    """Search, answer, check, each in its own span. Children get an explicit parent, because
    an async generator can't keep a span 'current' across its yields."""
    app_state = request.app.state
    bot: assistant.DocAssistant = app_state.bot
    tracer: trace.Tracer = app_state.tracer
    guard: CostGuard = app_state.guard
    request_id = request.state.request_id
    parent = trace.set_span_in_context(root)
    trace_id = format(root.get_span_context().trace_id, "032x")
    loop = asyncio.get_running_loop()
    start = time.monotonic()
    k = 3 if mode == "degraded" else bot.k  # degraded: fewer chunks, a shorter (cheaper) prompt
    reply: ask.Reply | None = None
    error = None
    model_name = "none"

    yield sse({"type": "status", "text": "Searching the policies"})
    try:
        async with asyncio.timeout(ANSWER_BUDGET_S):
            with tracer.start_span("retrieve hybrid+rerank", context=parent) as span:
                t0 = time.monotonic()
                hits = await loop.run_in_executor(
                    app_state.search_pool, lambda: bot.search.search(req.message, "rerank", k=k))
                best = hits[0][1] if hits else 0.0
                span.set_attributes({"shopkart.retrieval.k": k, "shopkart.retrieval.best_score": round(best, 4),
                                     "shopkart.retrieval.ms": round((time.monotonic() - t0) * 1000),
                                     "shopkart.retrieval.top_section": ask.label(hits[0][0]) if hits else ""})

            if mode == "lite" and hits and best >= bot.min_score:
                # LIMITS, lite mode: no model call. Retrieval is local and free, so point to the section.
                c = hits[0][0]
                reply = ask.Reply(req.message, "handover", LITE_TEXT.format(title=c["section_title"], label=ask.label(c)),
                                  reason="lite mode: today's cap is reached, no model call", hits=hits)
            else:
                reply = await answer_traced(bot, req.message, hits, tracer, parent, loop)
                if reply.result is not None:
                    model_name = reply.result.model
    except TimeoutError:
        error = "timeout"
    except budget.BudgetExceeded:
        error = "daily_budget"
    except LLMError as exc:
        error = exc.kind
    finally:
        latency = time.monotonic() - start
        cost = reply.cost_usd if reply else 0.0
        result = reply.result if reply else None
        if error:
            root.set_status(Status(StatusCode.ERROR, error))
        if reply:
            root.set_attributes({"shopkart.reply.kind": reply.kind, "shopkart.reply.reason": reply.reason[:200],
                                 "shopkart.budget_mode": mode})
        print(telemetry.emf_line(
            model=model_name, prompt_version=PROMPT_VERSION, latency_ms=latency * 1000,
            ttft_ms=None if error else latency * 1000, cost_usd=cost,
            tokens_in=result.input_tokens if result and not reply.cached else 0,
            tokens_out=result.output_tokens if result and not reply.cached else 0,
            error=error, request_id=request_id, trace_id=trace_id), flush=True)
        root.end()

    if error or reply is None:
        yield sse({"type": "error", "request_id": request_id, "trace_id": trace_id,
                   "message": "Sorry, I couldn't finish this answer. Please try again, or reply 'agent'."})
        return
    # The real cost was recorded by shopkart.llm already (budget.record, after every paid call).
    # The guard adds it to this user's and today's totals. Fake mode counts its pretend cost here
    # too, so the caps fill up like real spend in a load test.
    if guard.record(req.user, cost) == "budget_alert":
        log_event("budget_alert", request_id=request_id, **guard.status())
    log_event("reply", request_id=request_id, trace_id=trace_id, kind=reply.kind, reason=reply.reason[:200],
              cited=reply.cited, cached=reply.cached, mode=mode, latency_ms=round(latency * 1000))
    yield sse({"type": "text", "text": customer_text(reply, mode)})
    sources = [{"label": ask.label(bot.index.by_id[cid]), "title": bot.index.by_id[cid]["heading_path"],
                "source": bot.index.by_id[cid]["source"]} for cid in reply.cited]
    yield sse({"type": "done", "request_id": request_id, "trace_id": trace_id, "kind": reply.kind,
               "reason": reply.reason, "sources": sources, "mode": mode, "model": model_name,
               "cached": reply.cached, "cost_usd": round(cost, 6), "latency_ms": round(latency * 1000)})


def customer_text(reply: ask.Reply, mode: str) -> str:
    """Only a checked answer, the lite-mode pointer, or the polite handover. A failed check keeps
    the model's text in reply.text for the log; the customer gets the handover."""
    if reply.kind == "answer" or mode == "lite" and reply.reason.startswith("lite mode"):
        return reply.text
    return ask.HANDOVER_TEXT


async def answer_traced(bot, question, hits, tracer, parent, loop) -> ask.Reply:
    """assistant.answer(), split into spans: the floor, the model call, the check."""
    reply = ask.Reply(question, "handover", ask.HANDOVER_TEXT, hits=hits)
    if not hits or hits[0][1] < bot.min_score:
        best = f"{hits[0][1]:.3f}" if hits else "none"
        reply.reason = f"best chunk scores {best}, below the floor of {bot.min_score}: no model call"
        return reply

    llm = bot.llm
    with tracer.start_span(f"chat {llm.model}", context=parent, kind=SpanKind.CLIENT) as span:
        prompt = ask.build_prompt(question, hits)
        if telemetry.capture_content():
            span.set_attribute("gen_ai.input.messages", telemetry.redact(prompt))
        # The model call is network I/O: it runs on the default pool, many at once.
        result, cached = await loop.run_in_executor(
            None, lambda: ask.cached_complete(llm, ask.SYSTEM, prompt, cache_dir=bot.cache_dir))
        span.set_attributes(telemetry.llm_attributes(
            provider=result.provider, model=result.model, prompt_version=PROMPT_VERSION,
            tokens_in=result.input_tokens, tokens_out=result.output_tokens,
            cost_usd=0.0 if cached else result.cost_usd, ttft_ms=result.latency_s * 1000,
            max_tokens=MAX_TOKENS_OUT, provider_request_id=result.request_id))
        span.set_attribute("shopkart.cache_hit", cached)
    reply.result, reply.cached = result, cached
    out: ask.Answer = result.parsed  # type: ignore[assignment]
    if not out.answerable or not out.answer.strip():
        reply.reason = "the model says the sources don't cover it (answerable = false)"
        return reply

    with tracer.start_span("grounding_check", context=parent) as span:
        problems, cited = assistant.check_passages(out.answer, hits, question)
        span.set_attributes({"shopkart.check.passed": not problems, "shopkart.check.problems": len(problems)})
        if problems:
            span.set_attribute("shopkart.check.first_problem", problems[0][:200])
    if problems:
        reply.reason = "check failed: " + "; ".join(problems)
        reply.text = out.answer  # kept for the log, NOT shown to the customer
        log_event("check_failed", question=telemetry.redact(question), answer=telemetry.redact(out.answer),
                  problems=problems)
        return reply
    reply.kind, reply.text, reply.cited = "answer", out.answer, cited
    return reply


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/budget")
async def budget_status(request: Request) -> dict:
    return request.app.state.guard.status()


@app.post("/chat")
async def chat(req: ChatRequest, request: Request):
    request_id = request.state.request_id
    try:
        budget.check()  # the hard stop, just above the ladder's 100%
    except budget.BudgetExceeded:
        log_event("chat_blocked", request_id=request_id, reason="daily_budget")
        return JSONResponse(status_code=429, headers={"Retry-After": "3600"},
                            content={"error": "The assistant's daily budget is used up.", "request_id": request_id})
    guard: CostGuard = request.app.state.guard
    llm = request.app.state.bot.llm
    estimate = call_cost_usd(getattr(llm, "price_model", llm.model), WORST_CASE_TOKENS_IN, MAX_TOKENS_OUT, 0, 0)
    verdict = guard.check(req.user, estimate)  # BEFORE any work: a refused request costs nothing
    if not verdict.allowed:
        log_event("limited", request_id=request_id, user=req.user, reason=verdict.reason,
                  retry_after_s=verdict.retry_after_s)
        return JSONResponse(status_code=429, headers={"Retry-After": str(verdict.retry_after_s)}, content={
            "error": "You've reached your limit for now. Please try again later, or ask for a person.",
            "reason": verdict.reason, "retry_after_s": verdict.retry_after_s, "request_id": request_id})

    root = request.app.state.tracer.start_span(
        "POST /chat", kind=SpanKind.SERVER,
        attributes=telemetry.request_attributes(session_id=req.session_id, request_id=request_id, feature="policy_qa"))
    request.state.trace_id = format(root.get_span_context().trace_id, "032x")
    return StreamingResponse(answer_events(request, req, verdict.mode, root), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ShopKart Policy Assistant</title>
<style>body{font:16px system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem}
#a{white-space:pre-wrap;min-height:4rem;border:1px solid #ccc;border-radius:8px;padding:.75rem}
input{width:100%;font:inherit;padding:.5rem;box-sizing:border-box}small{color:#666}li{color:#444}</style></head>
<body><h1>ShopKart Policy Assistant</h1><form id="f"><input id="m" value="How many days do I have to return a product?">
</form><p id="a"></p><ul id="src"></ul><small id="s"></small><script>
f.onsubmit = async (e) => { e.preventDefault(); a.textContent = ""; s.textContent = ""; src.innerHTML = "";
  const r = await fetch("/chat", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({session_id: "web", message: m.value})});
  if (!r.ok) { a.textContent = r.status === 429 ? "You've reached your limit for now." : "Error " + r.status; return; }
  const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "";
  for (;;) { const {value, done} = await rd.read(); if (done) break;
    buf += dec.decode(value, {stream: true}); const parts = buf.split("\\n\\n"); buf = parts.pop();
    for (const p of parts) { if (!p.startsWith("data: ")) continue; const ev = JSON.parse(p.slice(6));
      if (ev.type === "status") a.textContent = ev.text + "…";
      if (ev.type === "text") a.textContent = ev.text;
      if (ev.type === "done") { for (const x of ev.sources) { const li = document.createElement("li");
          li.textContent = x.label + ": " + x.title; src.appendChild(li); }
        s.textContent = ev.kind + " · " + ev.latency_ms + " ms · $" + ev.cost_usd + " · trace " + ev.trace_id; }
      if (ev.type === "error") s.textContent = ev.message + " (" + ev.request_id + ")"; } } };
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
async def page() -> str:
    return PAGE
