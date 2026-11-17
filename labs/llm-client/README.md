# Lab: a typed, streaming, retrying LLM client

Build the ShopKart Copilot's own LLM client: one class for Claude and OpenAI that returns a typed result, streams to the terminal and survives a bad day.
Every later lab imports the finished version, `shopkart/llm.py`.

```text
labs/llm-client/
  start/llm_client.py   your copy, with TODO 1–6
  start/triage.py       classifies the 20 messages (Part 1 checkpoint)
  done/                 the finished answer (re-exports shopkart/llm.py)
  messages.json         20 real-looking ShopKart messages, some in Hinglish
  demo_errors.py        real and injected errors, safely
  tests/                the checkpoints, with fake servers
```

Runs on Anthropic by default. For OpenAI add `--provider openai` (or set `LLM_PROVIDER=openai`).

## Part 1: typed and streaming

1. **TODO 1, one call.** In `_complete_once`, call `messages.create` (or `responses.create`) and build a `Result`: text, tokens in and out, cost in $ and ₹, latency. `_finish` already runs `budget.record()` and writes the cost log.
   ```bash
   uv run python labs/llm-client/start/llm_client.py "When will my order arrive?"
   ```
2. **TODO 2, a schema.** `complete(..., schema=Triage)` sends the schema to the API (already done in `_anthropic_args` / `_openai_args`), then validates the JSON with Pydantic. If it fails, retry once with the error message, then raise `SchemaError` so a human can review it.
3. **TODO 3, streaming.** In `_stream_once`, yield each text piece as it arrives, then the same `Result`. Usage arrives at the end. Note the time to first token.
   ```bash
   uv run python labs/llm-client/start/llm_client.py "What is your return window?" --stream
   ```
4. **Checkpoint:** 20 messages classified, 0 crashes.
   ```bash
   uv run python labs/llm-client/start/triage.py
   ```

## Part 2: retries and error handling

5. **TODO 4, sort the errors.** Retry: 429, 529 overloaded, 5xx, timeouts. Stop: 400, auth errors, and spend limits. Read the error type and code in the body, not just the status: OpenAI's spend limit is a 429 with code `insufficient_quota` or `project_spend_limit_exceeded`, and Anthropic answers 400 at a workspace limit.
6. **TODO 5, how long to wait.** Exponential backoff (1 s, 2 s, 4 s, capped at 8 s) with jitter, and `retry-after` wins when the server sends it. Cap the total time too.
7. **TODO 6, the retry loop.** Check the budget before every attempt (each one is a paid call), log every retry. The SDK's own retries are off (`max_retries=0`), so three tries never become nine.
8. Watch it work:
   ```bash
   uv run python labs/llm-client/demo_errors.py
   ```
9. **Checkpoint:** a test that injects failures and still passes.
   ```bash
   LAB=start uv run pytest labs/llm-client -q
   ```

Every call is logged to `.shopkart/calls.csv` (time, model, tokens, $, ₹, latency, attempts).
The real output of a live run is in [RUN.md](RUN.md).

## Using the finished client in later labs

```python
from shopkart.llm import LLM

llm = LLM()                                 # claude-haiku-5-5, or LLM("openai") for gpt-6-luna
result = llm.complete("Where is SK48213?", system="...", schema=Triage)
result.parsed, result.cost_inr, result.latency_s

for piece in llm.stream("Explain the return policy"):
    ...                                     # str pieces, then one Result
```

```bash
uv run python -m shopkart.llm "question" [--stream] [--provider openai]
```
