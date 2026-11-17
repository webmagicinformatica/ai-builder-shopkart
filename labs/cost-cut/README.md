# Lab: cut a workload's cost in half with caching and a smaller model

The ShopKart Copilot answers every question with the large model and a long policy prompt. Measure what that costs, then cut it with three levers: prompt caching, routing easy questions to the small model, and a local cache for exact repeats.
**Checkpoint:** a before/after table that is at least 50% cheaper, with no drop in quality.

```text
labs/cost-cut/
  policies.md         the policy sheet: the long, stable system prompt (about 2,150 tokens on Claude)
  answer_key.json     key facts per question type, for the quality spot check
  start/cost_cut.py   your copy, with TODO 1-4
  done/cost_cut.py    the finished answer
  tests/              the checkpoints, with fake servers (no key, no cost)
```

The workload is `data/workload.jsonl`: 200 real-looking questions with easy/hard labels and many repeats. The lab runs the **first 20** (`--limit 20`), so one full run costs about $0.16 on Claude. That fits the $0.50 daily budget, but watch it: `--limit 200` costs ten times as much.

| | Anthropic (default) | OpenAI (`--provider openai`) |
| --- | --- | --- |
| Large model | `claude-sonnet-5-5`: $2 in, $10 out | `gpt-6.2-sol`: $2 in, $10 out |
| Small model | `claude-haiku-5-5`: $0.10 in, $0.50 out | `gpt-6-luna`: $0.10 in, $0.50 out |
| Cache read | Sonnet 0.05x, Haiku 0.1x of input | Sol 0.05x, Luna 0.1x of input |
| Cache write | 1.25x of input (5-minute cache) | free, automatic above 1,024 tokens |

Prices per million tokens, checked November 2026 (`shopkart/pricing.py`). Check the pricing pages before you trust them.

## Steps

1. **Baseline.** Every question goes to the large model with the policy sheet as the system prompt. Note the cost, the input tokens (about 2,150 per call, the same policy text every time) and the time.
   ```bash
   uv run python labs/cost-cut/start/cost_cut.py baseline
   ```
2. **Prompt caching (TODO 1).** In `answer()`, pass `cache_system=cache`. The policy sheet is the stable prefix; the question comes last. Re-run and watch the `write` and `read` columns: the first call writes about 2,150 tokens to the cache (at 1.25x), and every later call reads them (at 0.05x).
   ```bash
   uv run python labs/cost-cut/start/cost_cut.py cache
   ```
   On OpenAI there's nothing to switch on: it caches prompts of 1,024+ tokens by itself, and `read` shows its `cached_tokens`. It is best-effort, so check the numbers.
3. **Routing (TODO 2).** In `route()`, ask the small model for one word, `easy`, `hard` or `unsure`, with the `Route` schema. Easy questions go to the small model; hard and unsure ones go to the large model. When the router isn't sure, go big.
   ```bash
   uv run python labs/cost-cut/start/cost_cut.py route
   ```
4. **A local response cache (TODO 3).** In `ResponseCache`, make the key the cleaned-up question (lower case, no punctuation, single spaces), and never cache a question with an order number: it's personal. Exact repeats now cost $0 and skip the model. In production this would be Redis; clear it whenever a policy changes.
   ```bash
   uv run python labs/cost-cut/start/cost_cut.py final
   ```
5. **The table (TODO 4).** Write `saving()`, then compare all four runs, with a quick quality check: did each answer keep its key facts (`answer_key.json`), compared with the baseline? Then read the answers side by side yourself.
   ```bash
   uv run python labs/cost-cut/start/cost_cut.py table
   uv run python labs/cost-cut/start/cost_cut.py spot
   ```
6. **Checkpoint:**
   ```bash
   LAB=start uv run pytest labs/cost-cut -q
   ```

Each step saves its run in `.shopkart/cost-cut/<provider>/`. Running a step again **replays** it for $0; add `--fresh` to call the API again.

## What to notice

- Caching alone cut about 70%: the policy text was most of the bill. What's left is mostly output tokens.
- Routing adds a call per question, so it is a little slower, but most questions now run on a model that costs a twentieth as much.
- The cache only works while it's warm: about 5 minutes without use on Claude. Run the steps one after another.
- Run the router on your own questions before you trust it: in our run it sent the "₹799 to Kochi" question (labelled hard) to the small model, which still got it right. A wrong refund answer costs more than the cents you save.

## Batch API (not run here)

For work nobody is waiting for, like tagging yesterday's chats every night, both providers have a batch API at **half price**, with results within 24 hours (often within an hour). Match results back by your own ID, never by position. On Claude the batch discount stacks with prompt caching. `table` prints what the final run would cost as a batch. Never use it for a customer in the chat.

The real output of a live run is in [RUN.md](RUN.md).
