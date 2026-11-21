# Live run: load-test lab (2026-11-21)

A real run of `done/` against ECS Express Mode in `ap-southeast-2` (0.25 vCPU, 0.5 GB, one task), from a machine outside Australia, so every request includes about 0.5 s of network and TLS. **Fake mode: no model calls, no LLM cost.** Your numbers will differ.

## Checkpoints

```text
$ uv run pytest labs/loadtest -q
........                                                                 [100%]
8 passed in 1.73s
```

## Deploy in fake mode with small caps

Our service was created for the tracing lab with `maxTaskCount=1`, so the update below didn't need `--scaling-target`.

```text
$ docker build ... --build-arg APP_DIR=labs/loadtest/done -t $REGISTRY/$REPO:loadtest-$TAG . && docker push ...
045510280991.dkr.ecr.ap-southeast-2.amazonaws.com/shopkart-copilot:loadtest-0cb0212
$ aws ecs update-express-gateway-service --service-arn ... --primary-container "{... LLM_PROVIDER=fake, USER_PER_MINUTE=10, USER_DAILY_INR=0.2, GLOBAL_DAILY_INR=2 ...}" --query 'service.status.statusCode' --output text
ACTIVE
# 09:59:18 update; new task started 10:00:22; rollout finished 10:09:02
$ curl -s $URL/budget
{"day":"2026-11-21","mode":"normal","spent_inr":0.0,"cap_inr":2.0,"used":"0%","users_today":0}
```

## Load-test it

```text
$ uv run python labs/loadtest/done/loadtest.py $URL --requests 100 --concurrency 10 --users 50
100 chats, 10 at a time, in 18.8 s (5.3 chats/s)
  ok 100 · limited (429) 0 · error events 0 · other failures 0  ->  error rate 0.0%
  first token  P50 580 ms   P95 1,064 ms
  full answer  P50 1,852 ms   P95 2,343 ms   max 2,359 ms
  modes: normal 100

$ uv run python labs/loadtest/done/loadtest.py $URL --requests 100 --concurrency 40 --users 50
100 chats, 40 at a time, in 6.0 s (16.7 chats/s)
  ok 100 · limited (429) 0 · error events 0 · other failures 0  ->  error rate 0.0%
  first token  P50 615 ms   P95 1,121 ms
  full answer  P50 1,888 ms   P95 2,324 ms   max 2,401 ms
  modes: normal 100

$ curl -s $URL/budget
{"day":"2026-11-21","mode":"normal","spent_inr":0.719,"cap_inr":2.0,"used":"36%","users_today":43}
```

Fake mode waits 0.4 s for the first word and about 1.3 s for the rest; the remaining ~0.5 s is the trip to Sydney. Going from 10 to 40 chats at a time barely moved P95: one async task holds them all while they wait.

We also ran 100 chats **100 at a time**: P95 first token rose to **1,684 ms** and P95 full answer to **2,972 ms**, with no errors (that run's 24 `429`s came from an early version of the script that reused the same user IDs in every run; the script now picks fresh IDs each run).

## Watch the caps trip

```text
$ uv run python labs/loadtest/done/loadtest.py $URL --requests 30 --concurrency 5 --users 1
30 chats, 5 at a time, in 4.8 s (6.3 chats/s)
  ok 10 · limited (429) 20 · error events 0 · other failures 0  ->  error rate 0.0%
  first token  P50 581 ms   P95 954 ms
  full answer  P50 1,855 ms   P95 2,226 ms   max 2,226 ms
  429 because: rate_limit 20
  modes: normal 10

$ curl -s $URL/budget
{"day":"2026-11-21","mode":"normal","spent_inr":1.541,"cap_inr":2.0,"used":"77%","users_today":115}

$ uv run python labs/loadtest/done/loadtest.py $URL --requests 200 --concurrency 20 --users 200
200 chats, 20 at a time, in 15.0 s (13.3 chats/s)
  ok 200 · limited (429) 0 · error events 0 · other failures 0  ->  error rate 0.0%
  first token  P50 578 ms   P95 948 ms
  full answer  P50 1,847 ms   P95 2,213 ms   max 2,275 ms
  modes: normal 93, degraded 57, lite 50

$ curl -s $URL/budget
{"day":"2026-11-21","mode":"lite","spent_inr":2.0683,"cap_inr":2.0,"used":"103%","users_today":239}

$ curl -sN $URL/chat -H 'Content-Type: application/json' -d '{"session_id": "late-night", "message": "Where is my refund for order 4512?"}'
data: {"type": "text", "text": "Order SK04512 is returned. Refund of ₹3,499 initiated on 2026-11-16 (ref ARN74418820551). The Copilot is busy right now. To talk to a person, reply 'agent' or open Help > Create a ticket."}

data: {"type": "done", "request_id": "ca1267f50a03", "trace_id": "880d245e5ef7f4d44b6800315a5e8ffb", "model": "lite", "mode": "lite", "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "ttft_ms": 0, "latency_ms": 1}

$ aws logs tail $LOG --since 30m --format short | grep -E 'budget_alert|"limited"' | head -2
2026-11-21T10:09:46 {"event": "limited", "request_id": "85e7b15bb9d4", "user": "user004", "reason": "rate_limit", "retry_after_s": 26}
2026-11-21T10:10:50 {"event": "budget_alert", "request_id": "3d7eb70c49cd", "day": "2026-11-21", "mode": "normal", "spent_inr": 1.6019, "cap_inr": 2.0, "used": "80%", "users_today": 140}
```

The spend stopped at 103% (requests already past the check when the cap was reached finish normally). Degraded answers in fake mode take as long as normal ones: fake mode doesn't shorten its canned text, while a real model would get half the `max_tokens`.

On the tracing lab's dashboard, the fake traffic shows as a requests-per-minute peak of about 330, and the cost line drops to zero once lite mode starts.

## Tear down

```text
$ bash labs/deploy/teardown.sh service      # 10:12:17 to 10:20:27
- deleting ECS Express service shopkart-copilot (the load balancer goes with it; takes a few minutes)
- deleting log group /aws/ecs/shopkart/shopkart-copilot-6ff1
- deleting task definitions of shopkart-shopkart-copilot
- deleting cluster shopkart
```

Then `teardown.sh all` at the end of the session (see the deploy lab's RUN.md): every line `none`.

## Spend

- LLM: **$0** (fake mode only).
- AWS: about 13 minutes of the service for this lab. Estimated about a cent.
