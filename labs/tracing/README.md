# Lab: add tracing and a cost dashboard

Every request leaves a **trace**: one timeline with a span for the request, the order lookup and the model call. The model span records the model, prompt version, tokens in and out, cost, latency, time to first token, errors and both request IDs, with the **OpenTelemetry gen-AI names**. You see one real trace in **Jaeger**, running in your Codespace, then deploy and build a **CloudWatch dashboard** for P95 latency, errors and cost.

```text
labs/tracing/
  start/telemetry.py     span attributes, redaction, the metrics line: TODO 1–3
  start/app.py           the deploy lab's app, now traced (given: look for "TRACING")
  start/show_trace.py    prints a trace from Jaeger as a tree
  start/dashboard_png.py draws the dashboard's charts as PNGs and prints its tables
  done/                  the finished answer
  dashboard.json         the CloudWatch dashboard (4 charts, 2 tables)
  tests/                 the checkpoints (spans in memory: no collector, no key, no AWS)
```

## 1. What a model span records (`start/telemetry.py`)

- **TODO 1, `llm_attributes()`.** Standard names where they exist: `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.request.max_tokens`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`. There's no standard for cost, prompt version or time to first token yet, so those are ours: `shopkart.cost_usd`, `shopkart.prompt.version`, `shopkart.ttft_ms`, and `shopkart.provider_request_id` (the ID the provider's support asks for).
- **TODO 2, `redact()`.** Mask emails, card numbers and Indian phone numbers before anything is written. Order IDs and refund references stay.
- **TODO 3, `emf_line()`.** One JSON log line per request that is also a set of metrics: CloudWatch's *Embedded Metric Format*. The `_aws` block names the metrics (`LatencyMs`, `TTFTMs`, `CostUSD`, tokens, `Requests`, `Errors`) per `Service` and `Model`; the request ID, trace ID and prompt version stay in the line, searchable.

The gen-AI conventions are still marked *in development*, so names can change. Using them now still means any tool can read your numbers.

In `app.py`, each request opens a `POST /chat` span (with the conversation ID, the feature and an anonymous user ID). Inside it: `execute_tool lookup_order` and `chat claude-haiku-5-5`, which gets a `first_token` event. The spans are made with an explicit parent, because an async generator can't keep a span "current" across its `yield`s. Spans go out in batches, in the background. The trace ID goes back to the browser in the `done` event and an `X-Trace-ID` header.

```bash
LAB=start uv run pytest labs/tracing -q
```

## 2. One real trace in Jaeger (in the Codespace)

```bash
docker run -d --name jaeger -p 16686:16686 -p 4318:4318 jaegertracing/jaeger:2.22.0
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uv run uvicorn app:app --app-dir labs/tracing/start --port 8000 &
curl -sN localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"session_id": "demo-trace", "message": "Where is my refund for order 4512? Call me on 98765 43210 if needed."}' | tail -2
uv run python labs/tracing/start/show_trace.py <trace_id from the done event>
```

Open the **Ports** tab, then port 16686, for the Jaeger UI: service `shopkart-copilot`, *Find Traces*, and click the trace. The longest bar is where the time went.

Prompts and answers are **not** in the trace unless you opt in, and then they're redacted first:

```bash
kill %1
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
  uv run uvicorn app:app --app-dir labs/tracing/start --port 8000 &
# ask again: gen_ai.input.messages shows "Call me on [phone]"
```

## 3. Deploy it, and build the dashboard

Deploy the traced app as in the deploy lab, Part 1 (steps 3–6). If you tore everything down, recreate the repository, the secret, the roles and the cluster first. Only the image changes:

```bash
source labs/deploy/aws-vars.sh
export IMAGE=$REGISTRY/$REPO:tracing-$TAG
docker build --platform linux/amd64 --provenance=false -f labs/deploy/done/Dockerfile \
  --build-arg APP_DIR=labs/tracing/start -t $IMAGE . && docker push $IMAGE
# then create-express-gateway-service exactly as before, with "PROMPT_VERSION": "v1" in environment
```

Ask it a few questions (each costs about $0.0001):

```bash
for q in "Where is my refund for order 4512?" "Can I still return my shoes from order 48213?" "Can I return opened earphones?"; do
  curl -sN $URL/chat -H 'Content-Type: application/json' -d "{\"session_id\": \"dash-$RANDOM\", \"message\": \"$q\"}" | grep '"done"'
done
```

On AWS, stdout goes to CloudWatch Logs, and CloudWatch turns each EMF line into metrics. No agent, no collector. Now the dashboard and one alert:

```bash
LOG=$(aws logs describe-log-groups --log-group-name-prefix /aws/ecs/$CLUSTER/ --query 'logGroups[0].logGroupName' --output text)
aws cloudwatch put-dashboard --dashboard-name shopkart-copilot --dashboard-body "$(sed "s|LOG_GROUP|$LOG|" labs/tracing/dashboard.json)"
aws cloudwatch put-metric-alarm --alarm-name shopkart-ttft-p95 \
  --alarm-description "P95 time to first token above 3 s for 10 minutes. Check: the slowest traces on the dashboard, then the provider's status page." \
  --namespace ShopKart/Copilot --metric-name TTFTMs --dimensions Name=Service,Value=shopkart-copilot Name=Model,Value=claude-haiku-5-5 \
  --extended-statistic p95 --period 300 --evaluation-periods 2 --threshold 3000 --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching
```

The dashboard: P95 latency for the full answer and the first token (not the average), requests and errors, cost per minute, tokens, the 10 slowest requests with their trace IDs, and cost by prompt version and model. Metrics appear a minute or two after the requests. To see it without the AWS console:

```bash
uv run python labs/tracing/start/dashboard_png.py $LOG --minutes 30      # charts in .shopkart/dashboard/, open them in VS Code
```

Real metrics come from the deployed app. The real trace comes from Jaeger in your Codespace: a trace backend on AWS (X-Ray, or a collector next to the app) is the next step for production, and the trace ID in every log line already joins the two.

## 4. Tear down

Keep the service if you go straight on to the load-test lab. Otherwise:

```bash
bash labs/deploy/teardown.sh all      # also deletes the dashboard and the alarm
docker rm -f jaeger
```

Custom metrics can't be deleted; they stop costing anything once no new data arrives.

## Checkpoint

```bash
LAB=start uv run pytest labs/tracing -q      # your copy
uv run pytest labs/tracing -q                # the answer
```

- [ ] One request is one trace: `POST /chat` with `execute_tool lookup_order` and `chat claude-haiku-5-5` inside, the same trace ID in the browser, the trace and the log line
- [ ] The model span has the gen-AI attributes, cost, prompt version and the `first_token` event
- [ ] No prompt text in traces unless you opt in, and a phone number shows as `[phone]` when you do
- [ ] The dashboard shows P95 latency, errors and cost from the deployed app

The real output of a live run is in [RUN.md](RUN.md).
