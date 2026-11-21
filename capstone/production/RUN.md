# Run of the model solution (2026-11-21, local Docker)

The model solution was built and measured **in local Docker, with CPU and memory limits**, not on AWS: the course's AWS account was busy with other recordings. Every command it uses on AWS is a cloud lab's command that *was* run live; those real cloud numbers are in [labs/deploy/RUN.md](../../labs/deploy/RUN.md), [labs/tracing/RUN.md](../../labs/tracing/RUN.md) and [labs/loadtest/RUN.md](../../labs/loadtest/RUN.md). Your project should be deployed for real: that's the point of it.

Output below is what the commands printed, except where `...` marks lines left out; container names and ports are simplified.

## Tests

```text
$ uv run pytest capstone/production -q
............                                                             [100%]
12 passed in 2.50s
```

## The image

```text
$ docker build -f capstone/production/solution/Dockerfile -t shopkart-docs .
...
$ docker images shopkart-docs --format '{{.Size}}'
1.01GB
$ docker history shopkart-docs --format '{{.Size}}\t{{.CreatedBy}}'
...
159MB	COPY /app/.shopkart/models /app/.shopkart/models     # the embedder and the reranker, baked in
606kB	COPY /app/.shopkart/rag/index.sqlite ...              # 126 chunks
402MB	COPY /app/.venv /app/.venv                            # incl. ONNX Runtime
```

The deploy lab's image was 353 MB. The local models and ONNX Runtime are the difference.

## Live, on Haiku, with Jaeger (1 vCPU, 2 GB)

```text
$ docker run -d --name jaeger --network sk-net -p 16686:16686 jaegertracing/jaeger:2.22.0
$ docker run -d --network sk-net --cpus 1 --memory 2g -p 8000:8000 -e LLM_PROVIDER=anthropic -e ANTHROPIC_API_KEY \
    -e DAILY_BUDGET_USD=0.01 -e OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318 \
    -e OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true shopkart-docs
{"event": "startup", "provider": "anthropic", "model": "claude-haiku-5-5", "chunks": 126, "threads": 1, "floor": 0.01, "prompt_version": "doc-v1"}

$ curl -sN localhost:8000/chat -H 'Content-Type: application/json' -d '{"session_id": "live-1", "message": "How much does express delivery cost?"}'
data: {"type": "status", "text": "Searching the policies"}
data: {"type": "text", "text": "Express delivery costs ₹99 extra on top of the standard delivery charge [shipping-and-delivery § 2]. Express delivery in metro cities arrives the next day, and in other cities in 2–3 days [shipping-and-delivery § 2]."}
data: {"type": "done", "request_id": "0a03706b1592", "trace_id": "3c890de95f7d5ffb3edea5204425aa9d", "kind": "answer", "reason": "", "sources": [{"label": "shipping-and-delivery § 2", "title": "Shipping and Delivery Policy > 2. Delivery times", "source": "data/policies/pdf/shipping-and-delivery.pdf"}], "mode": "normal", "model": "claude-haiku-5-5", "cached": false, "cost_usd": 0.000247, "latency_ms": 2063}
```

Four questions in all:

| Question | Result | Time | Cost |
| --- | --- | --- | --- |
| How many days do I have to return a product? | answer, 3 sources | 2,976 ms | $0.000268 |
| Do you sell refurbished phones? | handover: best chunk 0.007, below the floor, **no model call** | 644 ms | $0 |
| How much does express delivery cost? | answer, 1 source | 2,063 ms | $0.000247 |
| How many days do I have to return a product? (again) | the same answer, **from the cache** | 982 ms | $0 |

The trace of the express-delivery question:

```text
$ uv run python labs/tracing/done/show_trace.py 3c890de95f7d5ffb3edea5204425aa9d
Trace 3c890de95f7d5ffb3edea5204425aa9d
POST /chat                             2063 ms   (starts at 0 ms)
     gen_ai.conversation.id = live-1
     shopkart.budget_mode = normal
     shopkart.feature = policy_qa
     shopkart.reply.kind = answer
     shopkart.request_id = 0a03706b1592
     shopkart.user.anon_id = b76bcdde9d20
├─ retrieve hybrid+rerank                  593 ms   (starts at 1 ms)
│       shopkart.retrieval.best_score = 0.7984
│       shopkart.retrieval.k = 5
│       shopkart.retrieval.top_section = shipping-and-delivery § 2
├─ chat claude-haiku-5-5                  1469 ms   (starts at 593 ms)
│       gen_ai.input.messages = ...ree COD deliveries in 6 months. Customer question: How much does express delivery cost?
│       gen_ai.request.model = claude-haiku-5-5
│       gen_ai.usage.input_tokens = 1879
│       gen_ai.usage.output_tokens = 119
│       shopkart.cache_hit = False
│       shopkart.cost_usd = 0.0002474
│       shopkart.prompt.version = doc-v1
│       shopkart.provider_request_id = req_011ChFwmE8uj2f81dLUwmtcd
└─ grounding_check                           0 ms   (starts at 2063 ms)
        shopkart.check.passed = True
        shopkart.check.problems = 0
```

Search was 0.6 s of the 2.1 s; the model was the rest. The check costs nothing.

## Load test, fake mode (1 vCPU, 2 GB)

Real search, real checks, a pretend model that waits 1 s. No model calls, no cost.

```text
$ L="uv run python capstone/production/solution/loadtest_docs.py http://localhost:8000"
$ $L --requests 40 --concurrency 1 --users 40
40 chats, 1 at a time, in 66.3 s (0.6 chats/s)
  ok 40 · limited (429) 0 · error events 0 · other failures 0  ->  error rate 0.0%
  full answer  P50 1,635 ms   P95 2,061 ms   max 2,220 ms
$ $L --requests 40 --concurrency 5 --users 40
40 chats, 5 at a time, in 26.2 s (1.5 chats/s)
  ok 40 · limited (429) 0 · error events 0 · other failures 0  ->  error rate 0.0%
  full answer  P50 3,299 ms   P95 3,844 ms   max 4,493 ms
$ $L --requests 60 --concurrency 10 --users 60
60 chats, 10 at a time, in 41.4 s (1.4 chats/s)
  ok 60 · limited (429) 0 · error events 0 · other failures 0  ->  error rate 0.0%
  full answer  P50 6,685 ms   P95 8,262 ms   max 8,979 ms
```

(The tester's "first token" line equals the full answer here: the checked answer arrives in one piece.)

## The caps trip (fake mode, small caps)

```text
$ docker run ... -e LLM_PROVIDER=fake -e USER_PER_MINUTE=10 -e USER_DAILY_INR=0.2 -e GLOBAL_DAILY_INR=0.5 shopkart-docs
$ $L --requests 30 --concurrency 5 --users 1
30 chats, 5 at a time, in 7.9 s (3.8 chats/s)
  ok 10 · limited (429) 20 · error events 0 · other failures 0  ->  error rate 0.0%
  429 because: rate_limit 20
$ $L --requests 60 --concurrency 5 --users 60
60 chats, 5 at a time, in 42.1 s (1.4 chats/s)
  ok 60 · limited (429) 0 · error events 0 · other failures 0  ->  error rate 0.0%
  modes: normal 44, lite 10, degraded 6
$ curl -s localhost:8000/budget
{"day":"2026-11-21","mode":"lite","spent_inr":0.5323,"cap_inr":0.5,"used":"106%","users_today":39}
$ curl -sN localhost:8000/chat -H 'Content-Type: application/json' -d '{"session_id": "late-night", "message": "How many days do I have to return a product?"}'
data: {"type": "text", "text": "Our assistant is resting for today, so here is the closest section of our policies: Return window (returns-and-refunds § 2.1). To talk to a person, reply 'agent' or open Help > Create a ticket."}
data: {"type": "done", ..., "kind": "handover", "reason": "lite mode: today's cap is reached, no model call", "mode": "lite", "model": "none", "cost_usd": 0.0, "latency_ms": 983}
$ docker logs ... | grep budget_alert
{"event": "budget_alert", "request_id": "6629f514608e", "day": "2026-11-21", "mode": "normal", "spent_inr": 0.4064, "cap_inr": 0.5, "used": "81%", "users_today": 31}
```

## Spend

- Anthropic: 2 calls on `claude-haiku-5-5`, **$0.000515**. OpenAI: none.
- AWS: none for this run. The cloud labs' runs cost a few cents in all (their RUN.md files).
