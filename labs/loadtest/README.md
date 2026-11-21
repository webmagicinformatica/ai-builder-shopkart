# Lab: load-test it and set a daily cost cap

Hit the deployed Copilot with many chats at once and read **P95 latency** and the **error rate**. Then cap the cost in the app itself, as in the running-costs lesson: per-user limits (requests a minute, rupees a day) and a **global daily cap with a ladder**: alert at 80%, degrade at 90%, lite mode at 100%. Then watch it trip.

The load test runs in **fake mode** (`LLM_PROVIDER=fake`): the app streams a canned answer at a model-like pace and counts fake tokens at Haiku's price, so the caps fill up like real spend. **No model is called and nothing is billed.** Never load-test, or trip a limit, with real model calls.

```text
labs/loadtest/
  start/limits.py      the cost guard: TODO 1–3
  start/loadtest.py    the async load tester: TODO 4 (P95)
  start/app.py         the traced app, now with the guard (given: look for "LIMITS")
  done/                the finished answer
  tests/               the checkpoints (a fake clock, the app in memory: no network, no cost)
```

## 1. The guard (`start/limits.py`)

- **TODO 1, the rate limit.** Per user, `USER_PER_MINUTE` requests in any 60 seconds (default 10). It stops floods and scripts. Over it: `429` with a `Retry-After` header.
- **TODO 2, the spend limit.** Per user, `USER_DAILY_INR` a day (default ₹20). Before the call, check with the **worst case**: the input tokens plus `max_tokens` out. After the call, add the **real** cost. It catches what a rate limit misses: one huge message a minute.
- **TODO 3, the ladder.** The whole app's spend today against `GLOBAL_DAILY_INR` (default ₹36,000). Below 90%: normal (at 80% the team gets one `budget_alert` log line). From 90%: **degraded**, the small model and shorter answers. From 100%: **lite**, no new model calls: order status straight from the data, the FAQ, and a way to reach a human.

In `app.py` the guard runs **before** the stream starts, so a refused request costs nothing. `GET /budget` shows today's spend and the mode. The counters live in memory, so they're exact for **one** copy of the app; with more copies, keep them in a shared store such as Redis, with the same logic. That's why this lab runs the service with `maxTaskCount=1`.

## 2. The load tester (`start/loadtest.py`)

It runs N chats, C at a time, spread over U user IDs, reads each stream to the end like a browser, and prints the outcomes, P50/P95 time to first token and full answer, and the modes it saw.

**TODO 4, `percentile()`.** Nearest rank: sort, then take the value at rank ⌈p/100 × n⌉. With 90 requests at 1 s and 10 at 10 s, the average is 1.9 s but P95 is 10 s: one customer in ten waited ten seconds.

```bash
LAB=start uv run pytest labs/loadtest -q
```

## 3. Deploy in fake mode, with small caps

Build the image from this lab and deploy it as in the deploy lab (or update the tracing lab's service). Fake mode needs no secret. Rupee caps this small make the ladder visible in a few hundred chats: each fake chat counts about ₹0.004.

```bash
source labs/deploy/aws-vars.sh
export IMAGE=$REGISTRY/$REPO:loadtest-$TAG
docker build --platform linux/amd64 --provenance=false -f labs/deploy/done/Dockerfile \
  --build-arg APP_DIR=labs/loadtest/start -t $IMAGE . && docker push $IMAGE
aws ecs update-express-gateway-service \
  --service-arn arn:aws:ecs:$AWS_REGION:$ACCOUNT:service/$CLUSTER/$SERVICE \
  --scaling-target minTaskCount=1,maxTaskCount=1 \
  --primary-container "{
      \"image\": \"$IMAGE\", \"containerPort\": 8000,
      \"environment\": [{\"name\": \"LLM_PROVIDER\", \"value\": \"fake\"},
                        {\"name\": \"USER_PER_MINUTE\", \"value\": \"10\"},
                        {\"name\": \"USER_DAILY_INR\", \"value\": \"0.2\"},
                        {\"name\": \"GLOBAL_DAILY_INR\", \"value\": \"2\"}]
    }"
curl -s $URL/budget          # wait for the new task: about 10 minutes in our run
```

(No service yet? Use `create-express-gateway-service` from the deploy lab with this image, this environment and `--scaling-target minTaskCount=1,maxTaskCount=1`.)

## 4. Load-test it

```bash
L="uv run python labs/loadtest/start/loadtest.py"
$L $URL --requests 100 --concurrency 10 --users 50       # a normal hour
$L $URL --requests 100 --concurrency 40 --users 50       # busier
curl -s $URL/budget
```

Read three numbers: the **error rate**, **P95 time to first token** (what the customer feels) and **P95 full answer**. On a 0.25 vCPU task in fake mode, they stayed flat from 10 to 40 chats at a time: the app is waiting, not working. Set the scaling target from runs like these, not from CPU.

## 5. Watch the caps trip

```bash
$L $URL --requests 30 --concurrency 5 --users 1          # one account, a script
$L $URL --requests 200 --concurrency 20 --users 200      # a busy evening, many accounts
curl -s $URL/budget
curl -sN $URL/chat -H 'Content-Type: application/json' -d '{"session_id": "late-night", "message": "Where is my refund for order 4512?"}'
LOG=$(aws logs describe-log-groups --log-group-name-prefix /aws/ecs/$CLUSTER/ --query 'logGroups[0].logGroupName' --output text)
aws logs tail $LOG --since 30m --format short | grep budget_alert
```

- The script gets 10 answers, then `429 because: rate_limit`.
- Many new accounts slip under the per-user limits, so the **global** spend climbs: `budget_alert` at 80%, then `degraded`, then `lite`. In lite mode, the order question is answered straight from the data, with no model call and no cost.
- The worst day got slower, not more expensive. A person decides whether to raise the cap; never automatically.

The tracing lab's dashboard shows the same run: requests per minute climbing, and the cost line falling flat once lite mode starts.

## 6. Tear down

```bash
bash labs/deploy/teardown.sh all
```

## Checkpoint

```bash
LAB=start uv run pytest labs/loadtest -q      # your copy
uv run pytest labs/loadtest -q                # the answer
```

- [ ] A load-test report with an error rate and P95 for first token and full answer
- [ ] One account over its rate limit gets 429s with `Retry-After`; other users don't notice
- [ ] The global cap steps through alert, degraded and lite, and `/budget` shows it
- [ ] No real model call was made during the load test

The real output of a live run is in [RUN.md](RUN.md).
