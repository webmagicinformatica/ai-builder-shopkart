# Capstone: put your project into production

**AI Builder · dabeer.ai**

Take the document assistant (capstone 1) or the action agent (capstone 2) and run it in production on AWS: a live HTTPS URL, a trace for every request, a dashboard, per-user limits and a daily cost cap, a load test, and a README that says what broke and how you fixed it.

A project that works on your laptop shows you can build. A project with a URL, a dashboard and a cost cap shows you can *ship*, and that you know what it costs and how it fails. That's the question every hiring manager asks after "does it work?"

You've done every step in the Production module's lessons and its cloud labs, on the simple Copilot. This time it's your own project, and it's heavier. Expect things to break that didn't break in the labs. Writing them down is part of the grade.

## The goal

Anyone with the link can use your project from a phone. You can show:

1. **where every second and every cent of one request went** (a trace),
2. **how the service is doing right now** (a dashboard, two alarms),
3. **what stops the worst day** (per-user limits, a daily cap that degrades, never surprises), and
4. **how much it can take** (a load test, and the size you chose from it).

## Which project?

| | Document assistant (capstone 1) | Action agent (capstone 2) |
| --- | --- | --- |
| The hard part in production | CPU and memory: the local embedder and reranker run inside the container | State: refunds, approvals and the audit trail must survive a redeploy |
| What changes | Task size, threads, baking the models into the image | Files on local disk vanish when a task is replaced: move them to a table (DynamoDB, as in the remote MCP server lab) |
| Recommended for | most people | people who did the remote MCP server lab |

The model solution deploys the **document assistant**.

## What you build on

| You need | Where you did it |
| --- | --- |
| Typed requests, `/health`, a request ID everywhere, timeouts, streaming events | Lesson: *A real backend* · Lab: deploy, Part 1 (`labs/deploy`) |
| A chat page that shows what's happening, keys only on the server | Lesson: *A simple front end people will actually use* |
| A slim, non-root image with no secrets in it, built from the repo root | Lesson: *Packaging with Docker* · Lab: deploy |
| ECR, Secrets Manager, ECS Express Mode (or Lambda), teardown | Lessons: *Deploying to the cloud*, Parts 1 and 2 · Lab: deploy, Parts 1 and 2 |
| Spans with `gen_ai.*` attributes, redaction, the EMF metrics line, the dashboard | Lesson: *Observability* · Lab: tracing (`labs/tracing`) |
| Per-user limits, the daily cap with its ladder, the load tester | Lesson: *Running costs in production* · Lab: load test (`labs/loadtest`) |

## Requirements

1. **A live HTTPS URL** on AWS: ECS Express Mode or Lambda with a function URL. Your project's own image (slim, non-root, no `.env` inside), tagged with the git commit, pushed to ECR. The API key in Secrets Manager; the service settings hold only its ARN.
2. **A real service.** Typed requests (an empty message gets 422, with no model call), `GET /health` that never calls a model, a request ID in every response and log line, a timeout on every wait, and a polite error event, never a stack trace.
3. **Tracing.** One request is one trace. A span per step (for the document assistant: retrieve, model call, grounding check; for the agent: each tool call and each model call). The model span has the model, tokens, cost, prompt version and the provider's request ID. No customer text in traces unless you opt in, and then redacted.
4. **A dashboard and two alarms.** P95 latency (not the average), requests and errors, cost over time, and the slowest requests with their trace IDs. One alarm for slow, one for expensive, each with a description that says what to check first.
5. **Cost control in the app.** Per user: a rate limit and a daily spend limit, answered with `429` and `Retry-After`. For the whole app: a daily cap with a ladder (alert at 80%, degrade at 90%, a no-model "lite" mode at 100%) and a hard stop just above it. Checked **before** any model call. If you run more than one task, say how the cap holds across them.
6. **A load test, in fake mode.** Your app with the model replaced by a fake (no key, no cost, everything else real). The error rate and P95 at three concurrency levels, and the task size and scaling setting you chose **from those numbers**. Then trip every limit on purpose.
7. **Offline tests** for the service: no key, no network, no AWS.
8. **A README** with how to deploy it, your settings and why, and **"What broke and how I fixed it"**: at least three real problems, each with the symptom, the cause, the fix, and a number from before and after.

## Acceptance criteria

| | Criterion |
| --- | --- |
| 1 | The URL answers over HTTPS: `/health` is 200, and one real question gets a real answer |
| 2 | No secret in the image or the service settings (`docker run --entrypoint ls ... -a /app`, and the service shows only an ARN) |
| 3 | One request is one trace with at least three spans; the model span has tokens, cost and prompt version |
| 4 | The dashboard shows P95 latency and cost **from the deployed service**, and both alarms exist |
| 5 | Load test in fake mode: **0% errors** at 10 chats at a time, P95 reported at three levels |
| 6 | One user over the limit gets `429` while others don't; the global cap reaches lite mode, and lite answers cost **$0** |
| 7 | Model spend for the whole project at most **$0.10**; AWS spend at most **$1** |
| 8 | At the end, `bash labs/deploy/leftovers.sh` prints `none` on every line |

## Rubric (100 points)

| Area | Points | Full marks | Half marks |
| --- | --- | --- | --- |
| Deployment | 20 | Live URL, slim non-root image, secret by reference, task size chosen from measurements | Works, but copied the lab's size, or the key is in an env file |
| Observability | 20 | One trace per request with a span per step, the dashboard on P95 and cost, two alarms that say what to check | Logs only, or averages only |
| Cost control | 20 | Per-user limits, the ladder and a hard stop, all before the call; the multi-task cap explained | A cap that only blocks, or checks after the call |
| Load test and sizing | 15 | Three levels, error rate and P95, and a scaling decision that follows from them; every limit tripped | One run, no decision |
| "What broke" | 15 | Three or more real problems, each with cause, fix, and numbers before and after | "Everything worked" |
| Engineering | 10 | Offline tests, deploy steps in scripts or files (not typed by hand), clean teardown | Works only from your terminal history |

A project at 80 or more is portfolio-ready.

## Suggested plan (about 8 hours, over two sessions)

AWS is slow to change: about 5 minutes to create a service and about 10 to roll out an update. Do everything you can locally first.

1. **Hour 1, make it a service.** Wrap your project in the deploy lab's FastAPI app: typed requests, `/health`, request IDs, fake mode. Run it with uvicorn.
2. **Hour 2, the image.** Build it, then run it **with the limits you'll deploy**: `docker run --cpus 1 --memory 2g ...`. Time the start-up and one request. Try a smaller size too.
3. **Hour 3, tracing.** Spans for each step, Jaeger in your Codespace, one trace printed with `show_trace.py`.
4. **Hours 4–5, limits and tests.** The guard from the load-test lab, before every call. Offline tests for the answer, the handover, a 429 and lite mode.
5. **Hour 6, deploy.** Secret, image, service, then the dashboard and alarms. Ask five real questions. Check the trace ID from the browser in the logs.
6. **Hour 7, load test.** Fake mode, three levels, choose the size and scaling. Trip every limit.
7. **Hour 8, write it up and tear down.** "What broke", the numbers, a screen recording of the live URL, then `teardown.sh all` and `leftovers.sh`.

## Common traps

- **Testing on your laptop's full CPU.** A container limited to one CPU behaves very differently. Run the image locally with `--cpus` and `--memory` before you deploy.
- **Copying the lab's task size.** 0.25 vCPU and 0.5 GB was right for an app that only calls a model. Measure yours.
- **Load-testing with real model calls,** or tripping a limit with them. Use fake mode: the caps fill with pretend spend, and nothing is billed.
- **Limits in memory with more than one task.** Each task counts its own spend, so two tasks double the cap. Give each task its share, or use a shared store.
- **Averages on the dashboard.** The average hides the customer who waited ten seconds. Use P95.
- **Leaving it running.** The load balancer is billed by the hour, busy or idle. Deploy for a session, record your demo, tear down.
- **A per-user limit keyed on something the client sends.** A script can change it. Say so, and let the global cap catch it.

## Stretch goals

- Real sign-in: the app checks a token, and the per-user limits use the user it proves.
- Shared counters in Redis or Valkey, so the cap holds exactly across any number of tasks.
- Traces on AWS: X-Ray, or an OpenTelemetry collector next to the app.
- Deploy from GitHub Actions with OIDC (no long-lived AWS keys), on every merge to main.
- The same service on OpenAI (`LLM_PROVIDER=openai`), compared on the dashboard by model.
- A Lambda version, and a table: cold start, cost at your traffic, limits.

## What to submit

1. A link to your repo, with the production code in its own folder.
2. Your README: how to deploy it, your settings and why, and **"What broke and how I fixed it"**.
3. Proof it ran: a 2-minute screen recording of the live URL (one answer, one "I don't know" or approval), one trace printed, and a dashboard screenshot.
4. The load-test output, and the limits tripping.
5. Your costs: model spend from the logs, and your AWS bill for the project.
6. The output of `leftovers.sh`, all `none`.

## Region, cost and teardown

- **One region on the free plan.** A free-plan AWS account works in one region you pick at sign-up; ours is **Sydney, `ap-southeast-2`**. From India, that adds about half a second of network to every request. Say so in your README. When you upgrade, deploy near your users (for ShopKart, Mumbai, `ap-south-1`).
- **What costs money while it's up:** the task (by vCPU and GB per hour) and the load balancer (by the hour). The cloud labs ran a 0.25 vCPU task and a load balancer for a few US cents an hour; a 1 vCPU task costs more. Check the current Fargate and load balancer pricing pages for your region before you size up.
- **Set a budget alert** of $3 on the account before you start.
- **Tear down at the end of every session:** `bash labs/deploy/teardown.sh all`, then `bash labs/deploy/leftovers.sh`. Custom metrics can't be deleted, but they stop costing anything once no new data arrives.

---

## The model solution

`solution/` puts the document assistant into production, reusing the labs' code: capstone 1's `DocAssistant`, the tracing lab's `telemetry.py`, the load-test lab's `limits.py` and load tester, and the deploy lab's teardown. Try the project yourself first.

```text
capstone/production/
  solution/
    app.py            the service: search → floor → model → check, each in a span; limits before any work
    fake_llm.py       fake mode: real search and checks, a pretend model, pretend cost
    Dockerfile        + Dockerfile.dockerignore: the index and both local models baked in
    service.env       the settings: task size, scaling, limits, the cap, and why
    deploy.sh         build, push, create or update the ECS Express service
    observe.sh        the dashboard and two alarms (latency P95, cost per hour)
    loadtest_docs.py  the load-test lab's tester, with policy questions
    WHAT-BROKE.md     what broke and how it was fixed, with numbers
  tests/              offline tests (fake embedder, fake reranker, fake Claude, spans in memory)
  RUN.md              the real output: tests, the image, a live Haiku run with its trace, the load test
```

```bash
uv run python labs/rag/done/ingest.py                                       # the index, once (free)
LLM_PROVIDER=fake uv run uvicorn app:app --app-dir capstone/production/solution --port 8000
docker build -f capstone/production/solution/Dockerfile -t shopkart-docs .
docker run --rm --cpus 1 --memory 2g -p 8000:8000 -e LLM_PROVIDER=fake shopkart-docs
uv run python capstone/production/solution/loadtest_docs.py http://localhost:8000 --requests 40 --concurrency 5
bash capstone/production/solution/deploy.sh && bash capstone/production/solution/observe.sh   # on AWS
uv run pytest capstone/production -q
```

The model solution was measured in local Docker with CPU and memory limits; the AWS steps are the cloud labs' commands, whose live numbers are in their RUN.md files. What broke, and the numbers, are in [WHAT-BROKE.md](solution/WHAT-BROKE.md) and [RUN.md](RUN.md).
