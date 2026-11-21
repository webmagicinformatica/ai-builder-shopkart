"""A small async load test for the Copilot: many chats at once, then P50/P95 latency and errors.

    uv run python labs/loadtest/done/loadtest.py $URL --requests 200 --concurrency 20 --users 50

Each request is one chat (POST /chat) read to the end, like a browser would. We measure the
time to first token (the first text event) and the full answer, and count the outcomes:
    ok       the answer finished with a done event
    error    the stream ended with an error event (the status was already 200)
    429      a limit said no (rate, user spend), with a Retry-After header
    other    anything else: 5xx, timeouts, refused connections

Point it at an app in FAKE mode (LLM_PROVIDER=fake): the load test then costs no tokens.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import sys
import time
from collections import Counter
from dataclasses import dataclass, field

import httpx2

QUESTIONS = [
    "Where is my refund for order 4512?",
    "Can I still return my shoes from order 48213?",
    "How long do refunds take to reach my card?",
    "My blender from order 4512 arrived damaged, what now?",
]


@dataclass
class Result:
    outcome: str                  # ok | error | 429 | other
    ttft_s: float | None = None
    total_s: float | None = None
    mode: str | None = None       # normal | degraded | lite (from the done event)
    detail: str = ""


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)
    wall_s: float = 0.0

    def outcomes(self) -> Counter:
        return Counter(r.outcome for r in self.results)

    def modes(self) -> Counter:
        return Counter(r.mode for r in self.results if r.mode)


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile: the value that p% of requests beat or match."""
    if not values:
        return None
    # TODO 4: sort the values, and return the one at rank ceil(p / 100 * n) (counting from 1).
    #         With 90 requests at 1 s and 10 at 10 s, P50 is 1 s and P95 is 10 s.
    return sum(values) / len(values)  # the average: exactly what hides the slow tail


async def one_chat(client: httpx2.AsyncClient, url: str, user: str, question: str) -> Result:
    start = time.monotonic()
    ttft = None
    try:
        body = {"session_id": f"lt-{user}", "user_id": user, "message": question}
        async with client.stream("POST", f"{url}/chat", json=body) as r:
            if r.status_code == 429:
                await r.aread()
                return Result("429", detail=r.json().get("reason", "?"))  # rate_limit or user_daily_spend
            if r.status_code != 200:
                return Result("other", detail=f"HTTP {r.status_code}")
            last = None
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if event["type"] == "text" and ttft is None:
                    ttft = time.monotonic() - start
                last = event
            total = time.monotonic() - start
            if last and last["type"] == "done":
                return Result("ok", ttft, total, last.get("mode", "normal"))
            return Result("error", ttft, total, detail=(last or {}).get("message", "no done event"))
    except httpx2.HTTPError as exc:
        return Result("other", detail=type(exc).__name__)


async def run(url: str, requests: int, concurrency: int, users: int, *,
              transport: httpx2.AsyncBaseTransport | None = None, seed: int | None = None) -> Report:
    rng = random.Random(seed)
    first = rng.randrange(10_000)  # a fresh set of user IDs each run, unless you fix the seed
    jobs = [(f"user{first + rng.randrange(users):05d}", rng.choice(QUESTIONS)) for _ in range(requests)]
    gate = asyncio.Semaphore(concurrency)  # at most this many chats at once
    report = Report()
    limits = httpx2.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx2.AsyncClient(timeout=70, limits=limits, transport=transport) as client:

        async def worker(user: str, question: str) -> None:
            async with gate:
                report.results.append(await one_chat(client, url, user, question))

        start = time.monotonic()
        await asyncio.gather(*(worker(u, q) for u, q in jobs))
        report.wall_s = time.monotonic() - start
    return report


def summary(report: Report, concurrency: int) -> str:
    oks = [r for r in report.results if r.outcome == "ok"]
    n = len(report.results)
    out = report.outcomes()
    ms = lambda v: "-" if v is None else f"{v * 1000:,.0f} ms"  # noqa: E731
    failed = out["error"] + out["other"]
    lines = [
        f"{n} chats, {concurrency} at a time, in {report.wall_s:.1f} s ({n / report.wall_s:.1f} chats/s)",
        f"  ok {out['ok']} · limited (429) {out['429']} · error events {out['error']} · other failures {out['other']}"
        f"  ->  error rate {failed / n:.1%}",
        f"  first token  P50 {ms(percentile([r.ttft_s for r in oks], 50))}   P95 {ms(percentile([r.ttft_s for r in oks], 95))}",
        f"  full answer  P50 {ms(percentile([r.total_s for r in oks], 50))}   P95 {ms(percentile([r.total_s for r in oks], 95))}"
        f"   max {ms(max((r.total_s for r in oks), default=None))}",
    ]
    limited = Counter(r.detail for r in report.results if r.outcome == "429")
    if limited:
        lines.append("  429 because: " + ", ".join(f"{d} {c}" for d, c in limited.most_common()))
    if report.modes():
        lines.append("  modes: " + ", ".join(f"{m} {c}" for m, c in report.modes().most_common()))
    other = Counter(r.detail for r in report.results if r.outcome == "other")
    if other:
        lines.append("  other: " + ", ".join(f"{d} x{c}" for d, c in other.most_common(3)))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Load-test the ShopKart Copilot")
    p.add_argument("url", help="the app's base URL, e.g. https://....ecs.ap-southeast-2.on.aws")
    p.add_argument("--requests", type=int, default=100)
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--users", type=int, default=50, help="how many different user IDs to spread chats over")
    args = p.parse_args(argv)
    report = asyncio.run(run(args.url.rstrip("/"), args.requests, args.concurrency, args.users))
    print(summary(report, args.concurrency))
    return 0


if __name__ == "__main__":
    sys.exit(main())
