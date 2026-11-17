"""Watch the client handle real and injected errors, safely and almost for free.

Run:  uv run python labs/llm-client/demo_errors.py [--provider openai] [--only rate-limit]

Four scenes:
  bad-model    a model name that doesn't exist: a real 4xx error, stopped at once
  timeout      a 0.01 s timeout: every attempt times out, retries run out, the fallback answers
  rate-limit   a fake 429 and a fake overloaded error, injected by a mock transport,
               then the real API answers on attempt three
  spend-limit  a fake spending-limit error: looks like a rate limit, but never retried

The fake errors never reach the provider. The transport answers them itself,
then passes the next request through to the real API.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import httpx2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repo root, where shopkart/ lives

from shopkart.llm import LLM, LLMError  # noqa: E402

QUESTION = "In one short sentence: how many days does a ShopKart customer have to return a kurta?"
SYSTEM = "You are ShopKart's support assistant. The return window is 14 days (footwear 10)."


class FlakyTransport(httpx2.BaseTransport):
    """Answers the first requests with fake errors, then forwards to the real API."""

    def __init__(self, fakes: list[tuple[int, dict, dict]]):
        self.fakes = list(fakes)
        self.real = httpx2.HTTPTransport()

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        if self.fakes:
            status, body, headers = self.fakes.pop(0)
            return httpx2.Response(status, json=body, headers=headers, request=request)
        return self.real.handle_request(request)


def fake_error(provider: str, kind: str) -> tuple[int, dict, dict]:
    """A provider-shaped error body, like the real ones."""
    if provider == "anthropic":
        status, err_type, message = {
            "rate_limit": (429, "rate_limit_error", "Number of request tokens has exceeded your per-minute rate limit"),
            "overloaded": (529, "overloaded_error", "Overloaded"),
            "spend_limit": (400, "invalid_request_error",
                            "You have reached your specified workspace API usage limits."),
        }[kind]
        return status, {"type": "error", "error": {"type": err_type, "message": message}}, {"request-id": f"req_fake_{kind}"}
    status, err_type, code, message = {
        "rate_limit": (429, "requests", "rate_limit_exceeded", "Rate limit reached for requests"),
        "overloaded": (503, "server_error", None, "The server is overloaded. Please retry."),
        "spend_limit": (429, "insufficient_quota", "project_spend_limit_exceeded",
                        "You have exceeded your project's spend limit."),
    }[kind]
    return status, {"error": {"type": err_type, "code": code, "message": message, "param": None}}, {"x-request-id": f"req_fake_{kind}"}


def scene(title: str) -> None:
    print(f"\n=== {title} " + "=" * (60 - len(title)), flush=True)
    time.sleep(0.05)


def ask(llm: LLM) -> None:
    try:
        result = llm.complete(QUESTION, system=SYSTEM, max_tokens=60)
        print(f"Answer: {result.text}")
        print(f"        {result.summary()}")
    except LLMError as exc:
        print(f"Stopped: {exc}")
        print(f"         attempts={exc.attempts} retryable={exc.retryable}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    parser.add_argument("--only", choices=["bad-model", "timeout", "rate-limit", "spend-limit"])
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s] %(message)s", stream=sys.stdout)
    provider = args.provider or LLM().provider
    run = lambda name: args.only in (None, name)  # noqa: E731

    if run("bad-model"):
        scene("1. A model that doesn't exist")
        ask(LLM(provider, model="no-such-model-2026"))

    if run("timeout"):
        scene("2. A 0.01 second timeout, with a fallback")
        ask(LLM(provider, timeout=0.01, max_attempts=3, fallback=LLM(provider)))

    if run("rate-limit"):
        scene("3. Fake 429, then fake overloaded, then the real API")
        flaky = FlakyTransport([fake_error(provider, "rate_limit"), fake_error(provider, "overloaded")])
        ask(LLM(provider, http_client=httpx2.Client(transport=flaky)))

    if run("spend-limit"):
        scene("4. Fake spending limit")
        flaky = FlakyTransport([fake_error(provider, "spend_limit")])
        ask(LLM(provider, http_client=httpx2.Client(transport=flaky)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
