# What broke and how I fixed it

The model solution's own log, in the order things went wrong. Numbers marked *local* come from the image running in Docker on our machine with a CPU and memory limit (`docker run --cpus 1 --memory 2g ...`), fake model mode unless it says Haiku. Numbers marked *cloud* come from the real AWS runs of the cloud labs (`labs/deploy`, `labs/tracing`, `labs/loadtest`, RUN.md in each), on the same account type you'll use: a free-plan account in `ap-southeast-2`.

## 1. The lab's task size killed the app (local)

The labs ran the Copilot on 0.25 vCPU and 0.5 GB. That app only called a model. Ours also loads two local models, the embedder and the reranker, and holds the index in memory: about **600 MB** once it's up.

On 0.25 vCPU and 0.5 GB it passed the health check, answered **one** question in 5.9 s, and was killed on the second: `OOMKilled=true`. On ECS that's a task that starts, serves a little, dies and starts again, while the load balancer keeps sending it customers.

| Task size (local, fake model, 1 s pretend wait) | Healthy after | One question | Memory used |
| --- | --- | --- | --- |
| 0.25 vCPU, 0.5 GB | 18 s | 5.9 s, then **OOM-killed** | over 512 MB |
| 0.25 vCPU, 2 GB | 18 s | 5.3 to 6.5 s | 598 MB |
| 0.5 vCPU, 1 GB | 9 s | 3.0 to 3.5 s | 598 MB of 1 GB |
| **1 vCPU, 2 GB** (chosen) | **5 s** | **about 2.0 s** | 598 MB |

**Fix:** 1 vCPU and 2 GB (`service.env`). 0.5 vCPU and 1 GB works, but leaves 40% memory headroom and a slower answer.

## 2. 32 threads on one CPU: 21 seconds a question (local)

The first image, limited to 1 CPU, took **34 s** to become healthy and **21 s** per question. The labs' code gives ONNX one thread per CPU it can *see*, with `os.sched_getaffinity()`. A container limited to one CPU on a 32-core machine still sees 32. So 32 threads shared one CPU's worth of time, and spent it waiting for each other.

**Fix:** at start-up, `match_threads_to_cpu_quota()` reads the container's real CPU quota from the cgroup and narrows the visible CPUs to match (or to `SEARCH_THREADS`). Same image, same limit: healthy in **5 s**, **2.8 s** a question (with a 1 s pretend model wait). The `startup` log line now prints `threads`, so you can see it on AWS too.

## 3. Search on the wrong thread (local)

Search is CPU work, so it can't run on the event loop. The obvious move, FastAPI's thread pool, fails: the index's SQLite connection belongs to the thread that opened it.

```text
ProgrammingError SQLite objects created in a thread can only be used in that same thread.
```

**Fix:** one search thread, made at start-up (`ThreadPoolExecutor(max_workers=1)`). The assistant is built on it, warmed up on it (so the first customer doesn't load the models), and every search runs on it. One at a time is also the right speed for one CPU. The model call is network waiting, so it runs on the normal pool, many at once.

## 4. The reranker was doing twice the work it needed (local, measured)

The reranker reads the top 20 hybrid results for every question. On one CPU, over the 50 policy questions:

| Reranker reads | hit@1 | hit@5 | "I don't know" caught by the floor | median | P95 |
| --- | --- | --- | --- | --- | --- |
| 20 | 36/50 | 49/50 | 6/10 | 1,495 ms | 3,070 ms |
| **10** | **36/50** | **49/50** | **6/10** | **709 ms** | **990 ms** |

Same quality, half the CPU. **Fix:** `RERANK_CANDIDATES=10`. (Lowest best score of an answerable question: 0.020 either way, so capstone 1's floor of 0.01 still holds.)

## 5. "Scale on requests, not CPU" was wrong for this app (local)

The labs' rule came from an app that only waits for the model. Ours searches first, on the CPU. The load-test lab's tester, with policy questions, on 1 vCPU:

| At a time | Chats a second | P95 answer | Errors |
| --- | --- | --- | --- |
| 1 | 0.6 | 2.1 s | 0 |
| 5 | 1.5 | 3.8 s | 0 |
| 10 | 1.4 | 8.3 s | 0 |

Throughput stops at about 1.5 chats a second; after that, extra chats just queue for the search thread. **Fix:** scale on `AVERAGE_CPU` (target 60%), one to two tasks.

## 6. Two tasks, two caps (design)

The limits live in each task's memory. With two tasks, a ₹88 daily cap becomes ₹176. **Fix:** each task enforces its share: `GLOBAL_DAILY_INR=44` with `MAX_TASKS=2`, and the hard stop `DAILY_BUDGET_USD=0.55` sits just above it. A test checks the arithmetic. The real fix for more tasks is a shared counter (Redis or Valkey), same logic.

## 7. Things the cloud labs hit first (cloud)

- **A brand-new account** can't create the first Express service: `Unable to assume the service linked role`. `aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com`, once.
- **About 5 minutes** from create to the first `/health`, and **about 10 minutes** for a rolling update. Plan your evening around it.
- **Lambda's cold start** was 8.0 s the first time, with an image a third the size of ours and no models to load. That's why this project runs on ECS, with one task always warm.
- **The ladder overshoots a little:** the load-test lab's spend stopped at **103%** of the cap, ours at **106%** locally. Requests that passed the check before the cap was reached still finish.
- **A load-test script that reused user IDs** produced 429s that weren't real. The tester now picks fresh IDs each run.

## What I didn't fix

- The answer isn't streamed word by word. The grounding check needs the whole answer, so the page shows "Searching the policies…" and then the checked answer in one piece. On Haiku that's about 2 to 3 s.
- `user_id` comes from the request body, so a script can change it to dodge the per-user limits. The global cap still holds. Real sign-in (a token the app checks) is the fix, and a stretch goal.
- Traces go to Jaeger locally. On AWS the trace ID is in every log line and on the dashboard, but there's no trace backend: X-Ray or a collector is the next step.
