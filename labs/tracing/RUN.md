# Live run: tracing lab (2026-11-21)

A real run of `done/`. The local part ran Jaeger 2.22.0 in Docker (on other host ports in our run; the README's commands use 4318 and 16686). The cloud part ran on ECS Express Mode in `ap-southeast-2`. Your IDs and timings will differ.

## Checkpoints

```text
$ uv run pytest labs/tracing -q
.......                                                                  [100%]
7 passed in 1.61s
```

## One real trace, in Jaeger

```text
$ docker run -d --name jaeger -p 16686:16686 -p 4318:4318 jaegertracing/jaeger:2.22.0
$ OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
    uv run uvicorn app:app --app-dir labs/tracing/done --port 8000 &
$ curl -sN localhost:8000/chat -H 'Content-Type: application/json' \
    -d '{"session_id": "demo-trace", "message": "Where is my refund for order 4512? Call me on 98765 43210 if needed."}' | grep done
data: {"type": "done", "request_id": "4cc389c81d62", "trace_id": "b38970eb2aab194ba8c5c17f8ad5597a", "model": "claude-haiku-5-5", "tokens_in": 488, "tokens_out": 150, "cost_usd": 0.000124, "ttft_ms": 738, "latency_ms": 1427}

$ uv run python labs/tracing/done/show_trace.py b38970eb2aab194ba8c5c17f8ad5597a
Trace b38970eb2aab194ba8c5c17f8ad5597a
POST /chat                             1427 ms   (starts at 0 ms)
     gen_ai.conversation.id = demo-trace
     shopkart.feature = chat
     shopkart.request_id = 4cc389c81d62
     shopkart.user.anon_id = a02ab51f8b0b
├─ execute_tool lookup_order                 0 ms   (starts at 0 ms)
│       gen_ai.operation.name = execute_tool
│       gen_ai.tool.name = lookup_order
│       shopkart.order_found = True
└─ chat claude-haiku-5-5                  1427 ms   (starts at 0 ms)
      · first_token at 738 ms
        gen_ai.input.messages = ..."}} </order> Customer: Where is my refund for order 4512? Call me on [phone] if needed.
        gen_ai.operation.name = chat
        gen_ai.output.messages = ...ort team if the amount hasn't reflected by the end of that window.
        gen_ai.provider.name = anthropic
        gen_ai.request.max_tokens = 300
        gen_ai.request.model = claude-haiku-5-5
        gen_ai.usage.input_tokens = 488
        gen_ai.usage.output_tokens = 150
        shopkart.cost_usd = 0.0001238
        shopkart.prompt.version = v1
        shopkart.provider_request_id = req_011ChFrocw5Y8xa6hm8VYUPJ
        shopkart.ttft_ms = 738
```

The phone number reached the trace as `[phone]`; the order ID and the refund reference stayed. The same request's metrics line (stdout):

```text
{"_aws": {"Timestamp": 1795254305643, "CloudWatchMetrics": [{"Namespace": "ShopKart/Copilot", "Dimensions": [["Service", "Model"]], "Metrics": [{"Name": "LatencyMs", "Unit": "Milliseconds"}, {"Name": "TTFTMs", "Unit": "Milliseconds"}, {"Name": "CostUSD", "Unit": "None"}, {"Name": "InputTokens", "Unit": "Count"}, {"Name": "OutputTokens", "Unit": "Count"}, {"Name": "Requests", "Unit": "Count"}, {"Name": "Errors", "Unit": "Count"}]}]}, "Service": "shopkart-copilot", "Model": "fake", "LatencyMs": 1662, "CostUSD": 4.56e-05, "InputTokens": 291, "OutputTokens": 33, "Requests": 1, "Errors": 0, "TTFTMs": 401, "event": "chat", "prompt_version": "v1", "error": null, "request_id": "3579e635ddaa", "trace_id": "8d6d2d621111c82932359d5e656757d3"}
```

(That one is from a fake-mode request a minute earlier; the shape is the same.)

## Deployed, with the dashboard

```text
$ export IMAGE=$REGISTRY/$REPO:tracing-$TAG
$ docker build --platform linux/amd64 --provenance=false -f labs/deploy/done/Dockerfile --build-arg APP_DIR=labs/tracing/done -t $IMAGE . && docker push $IMAGE
045510280991.dkr.ecr.ap-southeast-2.amazonaws.com/shopkart-copilot:tracing-0cb0212
$ aws ecs create-express-gateway-service ... (09:51:36)
https://sh-3a2927d24cce429eb40b83bfc959db85.ecs.ap-southeast-2.on.aws
# live at 09:56:54

$ for q in ...six questions...; do curl -sN $URL/chat ... | grep '"done"'; done
{"type": "done", "request_id": "97875a25fec1", "trace_id": "24d451883b3821ac673b37c5a5acaeca", "model": "claude-haiku-5-5", "tokens_in": 473, "tokens_out": 122, "cost_usd": 0.000108, "ttft_ms": 719, "latency_ms": 1304}
{"type": "done", "request_id": "22d0b4eef2a1", "trace_id": "0824d0801fabf964fed8013c44ba7f06", "model": "claude-haiku-5-5", "tokens_in": 390, "tokens_out": 118, "cost_usd": 9.8e-05, "ttft_ms": 502, "latency_ms": 1076}
{"type": "done", "request_id": "1ea9efbd2d6d", "trace_id": "dcf6ee33a3d1ec06ee7e82f4a7bf1add", "model": "claude-haiku-5-5", "tokens_in": 237, "tokens_out": 86, "cost_usd": 6.7e-05, "ttft_ms": 530, "latency_ms": 1023}
{"type": "done", "request_id": "be079ba1c92b", "trace_id": "4e94fa5bed0447cb92e4937a08016b36", "model": "claude-haiku-5-5", "tokens_in": 480, "tokens_out": 151, "cost_usd": 0.000123, "ttft_ms": 505, "latency_ms": 1251}
{"type": "done", "request_id": "0ff78a87973b", "trace_id": "8394ae2b10a68286512ff8b05f5e36fb", "model": "claude-haiku-5-5", "tokens_in": 384, "tokens_out": 72, "cost_usd": 7.4e-05, "ttft_ms": 514, "latency_ms": 888}
{"type": "done", "request_id": "2983cb00aab1", "trace_id": "5f075f96930aa4b7283147c12b87b8ac", "model": "claude-haiku-5-5", "tokens_in": 231, "tokens_out": 113, "cost_usd": 8e-05, "ttft_ms": 533, "latency_ms": 984}

$ LOG=$(aws logs describe-log-groups --log-group-name-prefix /aws/ecs/$CLUSTER/ --query 'logGroups[0].logGroupName' --output text); echo $LOG
/aws/ecs/shopkart/shopkart-copilot-6ff1
$ aws cloudwatch put-dashboard --dashboard-name shopkart-copilot --dashboard-body "$(sed "s|LOG_GROUP|$LOG|" labs/tracing/dashboard.json)"
{
    "DashboardValidationMessages": []
}
$ aws cloudwatch put-metric-alarm --alarm-name shopkart-ttft-p95 ...
$ aws cloudwatch list-metrics --namespace ShopKart/Copilot --query 'Metrics[].MetricName' --output text
CostUSD  Errors  InputTokens  LatencyMs  OutputTokens  Requests  TTFTMs
```

The metrics appeared about a minute after the requests. P95 for that minute, from the metric itself:

```text
$ aws cloudwatch get-metric-statistics --namespace ShopKart/Copilot --metric-name LatencyMs \
    --dimensions Name=Service,Value=shopkart-copilot Name=Model,Value=claude-haiku-5-5 \
    --start-time ... --end-time ... --period 60 --extended-statistics p95 --query 'Datapoints[].[Timestamp,ExtendedStatistics.p95]' --output text
2026-11-21T09:57:00+00:00	1294.284439875962
```

The dashboard's "slowest requests" table (Logs Insights):

```text
2026-11-21 09:57:02.277  97875a25fec1  24d451883b3821ac673b37c5a5acaeca  claude-haiku-5-5  v1  1304  719  1.083E-4
2026-11-21 09:57:07.524  be079ba1c92b  4e94fa5bed0447cb92e4937a08016b36  claude-haiku-5-5  v1  1251  505  1.235E-4
2026-11-21 09:57:03.954  22d0b4eef2a1  0824d0801fabf964fed8013c44ba7f06  claude-haiku-5-5  v1  1076  502  9.8E-5
2026-11-21 09:57:05.635  1ea9efbd2d6d  dcf6ee33a3d1ec06ee7e82f4a7bf1add  claude-haiku-5-5  v1  1023  530  6.67E-5
2026-11-21 09:57:10.636  2983cb00aab1  5f075f96930aa4b7283147c12b87b8ac  claude-haiku-5-5  v1  984   533  7.96E-5
```

The latency chart then showed answer P95 1,294 ms and first-token P95 about 720 ms for `claude-haiku-5-5`. The same service then ran the load-test lab, so the charts also show the fake-model traffic (`fake`, `lite`) from that lab.

`dashboard_png.py` output (run again after teardown against a short test log group, so the tables show test rows):

```text
$ uv run python labs/tracing/done/dashboard_png.py $LOG --minutes 120
chart: .shopkart/dashboard/1-latency-p95.png
chart: .shopkart/dashboard/2-requests-and-errors.png
chart: .shopkart/dashboard/3-cost.png
chart: .shopkart/dashboard/4-tokens.png

Slowest requests: open the trace by its ID
  @timestamp               request_id  trace_id  Model             prompt_version  LatencyMs  TTFTMs  CostUSD
  ...
Cost by prompt version and model
  prompt_version  Model             requests  cost_usd   avg_tokens_in  p95_ms
  ...
```

## Spend

- Anthropic: 7 calls on `claude-haiku-5-5` (1 local traced + 6 deployed), **$0.00068**. OpenAI: none.
- AWS: the service ran about 28 minutes across this lab and the load-test lab; a few custom metrics, one dashboard and one alarm for under an hour. Estimated a few cents.
