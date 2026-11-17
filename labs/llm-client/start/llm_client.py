"""Lab: a typed, streaming, retrying LLM client. YOUR copy, with TODOs.

Part 1 (typed and streaming):   TODO 1, 2, 3
Part 2 (retries and errors):    TODO 4, 5, 6

Run the tests against your copy:   LAB=start uv run pytest labs/llm-client -q
Try it:   uv run python labs/llm-client/start/llm_client.py "Where is my order?" --stream

The finished answer is shopkart/llm.py (labs/llm-client/done/ imports it).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Literal

import anthropic
import openai
from pydantic import BaseModel, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # the repo root, where shopkart/ lives

from shopkart import budget  # noqa: E402
from shopkart.pricing import PRICES_PER_MILLION_USD, cost_usd, usd_to_inr  # noqa: E402

log = logging.getLogger("shopkart.llm")

Provider = Literal["anthropic", "openai"]

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-5-5",
    "openai": "gpt-6-luna",
}
KEY_NAMES: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

# Prompt caching: cached reads cost about a tenth of normal input, and on
# Claude a cache write costs about a quarter more (see the caching lesson).
CACHE_READ_FACTOR = 0.10
CACHE_WRITE_FACTOR = 1.25

CALL_LOG = budget.LEDGER_DIR / "calls.csv"


# --------------------------------------------------------------------------
# What a call returns
# --------------------------------------------------------------------------


@dataclass
class Result:
    """One finished call: the answer, what it cost and how long it took."""

    text: str
    parsed: BaseModel | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cost_inr: float
    latency_s: float
    model: str
    provider: str
    stop_reason: str = "end"  # "end", "max_tokens", "refusal" or the provider's own value
    attempts: int = 1
    ttft_s: float | None = None  # time to first token (streaming only)
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    request_id: str | None = None

    def summary(self) -> str:
        line = (
            f"{self.model} · {self.input_tokens} in / {self.output_tokens} out · "
            f"${self.cost_usd:.6f} (₹{self.cost_inr:.4f}) · {self.latency_s:.2f}s"
        )
        if self.ttft_s is not None:
            line += f" (first token {self.ttft_s:.2f}s)"
        if self.attempts > 1:
            line += f" · {self.attempts} attempts"
        return line


# --------------------------------------------------------------------------
# Errors: which ones are worth retrying?
# --------------------------------------------------------------------------


class LLMError(Exception):
    """A call that failed for good. `retryable` says whether retrying could have helped."""

    def __init__(self, message: str, *, kind: str, status: int | None = None,
                 code: str | None = None, request_id: str | None = None,
                 attempts: int = 1, retryable: bool = False):
        self.kind = kind
        self.status = status
        self.code = code
        self.request_id = request_id
        self.attempts = attempts
        self.retryable = retryable
        super().__init__(message)


class SpendLimitReached(LLMError):
    """The provider's spending limit is hit. Waiting won't fix it: raise the limit."""


class StreamInterrupted(LLMError):
    """The stream failed after text was already shown. `partial_text` is what arrived."""

    def __init__(self, message: str, *, partial_text: str, **kw: Any):
        self.partial_text = partial_text
        super().__init__(message, **kw)


class SchemaError(LLMError):
    """The answer still didn't match the schema after one retry: send it to a human."""

    def __init__(self, message: str, *, text: str, **kw: Any):
        self.text = text
        super().__init__(message, kind="schema", **kw)


SPEND_LIMIT_CODES = {
    # OpenAI: a 429 that looks like a rate limit, but waiting won't help.
    "insufficient_quota",
    "project_spend_limit_exceeded",
    # Anthropic: newer SDKs name these error types.
    "enforced_spend_limit_reached",
    "contract_spend_limit_reached",
    "linked_organization_spend_limit_reached",
}
RETRYABLE_TYPES = {"overloaded_error", "rate_limit_error", "api_error", "timeout_error"}


@dataclass
class Verdict:
    retry: bool
    kind: str  # rate_limit, overloaded, server, timeout, connection, spend_limit, bad_request, auth, ...
    status: int | None = None
    code: str | None = None
    message: str = ""
    request_id: str | None = None
    retry_after: float | None = None

    def label(self) -> str:
        """e.g. "429 rate_limit" or "400 spend_limit (insufficient_quota)"."""
        text = f"{self.status} {self.kind}" if self.status else self.kind
        if self.code and self.code != self.kind and self.code != f"{self.kind}_error":
            text += f" ({self.code})"
        return text


def _error_details(exc: Exception) -> tuple[str | None, str | None, str]:
    """(type, code, message) from an SDK error body. Read the body, not just the status."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        body = body["error"]  # Anthropic wraps it: {"type": "error", "error": {...}}
    if not isinstance(body, dict):
        body = {}
    err_type = body.get("type") or None
    code = body.get("code") or getattr(exc, "code", None) or None
    message = str(body.get("message") or getattr(exc, "message", None) or exc)
    return err_type, code, message


def _retry_after(exc: Exception) -> float | None:
    """Seconds the server asked us to wait (retry-after-ms or retry-after), if any."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    if ms := headers.get("retry-after-ms"):
        try:
            return float(ms) / 1000
        except ValueError:
            pass
    value = headers.get("retry-after")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        try:  # an HTTP date
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError):
            return None


def classify(exc: Exception) -> Verdict:
    """Sort an error into one of two piles: retry, or stop."""
    if isinstance(exc, (anthropic.APITimeoutError, openai.APITimeoutError)):
        return Verdict(True, "timeout", message="no answer in time")
    if isinstance(exc, (anthropic.APIConnectionError, openai.APIConnectionError)):
        return Verdict(True, "connection", message=str(exc))
    if not isinstance(exc, (anthropic.APIStatusError, openai.APIStatusError)):
        return Verdict(False, "unknown", message=repr(exc))

    status = exc.status_code
    err_type, code, message = _error_details(exc)
    request_id = getattr(exc, "request_id", None)
    v = Verdict(False, "client_error", status, code or err_type, message, request_id, _retry_after(exc))

    # TODO 4: sort the error. Set v.retry and v.kind, then return v.
    #   - Spend limits FIRST, and never retry them: `code` or `err_type` in
    #     SPEND_LIMIT_CODES (OpenAI's 429 insufficient_quota), or a 400/402 whose
    #     message mentions "usage limit" (Anthropic at a workspace limit).  kind="spend_limit"
    #   - 429 -> retry, "rate_limit".   529 or err_type "overloaded_error" -> retry, "overloaded"
    #   - 408 -> retry, "timeout".      5xx or err_type in RETRYABLE_TYPES -> retry, "server"
    #   - 401/403 -> "auth".  400 -> "bad_request".  404 -> "not_found".  Nothing else retries.
    return v


def _to_error(v: Verdict, attempts: int) -> LLMError:
    cls = SpendLimitReached if v.kind == "spend_limit" else LLMError
    msg = f"{v.label()}: {v.message}"
    if v.request_id:
        msg += f" (request {v.request_id})"
    return cls(msg, kind=v.kind, status=v.status, code=v.code,
               request_id=v.request_id, attempts=attempts, retryable=v.retry)


# --------------------------------------------------------------------------
# Cost
# --------------------------------------------------------------------------


def call_cost_usd(model: str, input_tokens: int, output_tokens: int,
                  cache_read: int = 0, cache_write: int = 0) -> float:
    """Dollars for one call. `input_tokens` are the uncached ones."""
    cost = cost_usd(model, input_tokens, output_tokens)
    if cache_read or cache_write:
        price_in = PRICES_PER_MILLION_USD[model][0]
        cost += (cache_read * CACHE_READ_FACTOR + cache_write * CACHE_WRITE_FACTOR) * price_in / 1e6
    return cost


def log_call(result: Result, outcome: str = "ok", path: Path | None = None) -> None:
    """Append one row to the cost log CSV (.shopkart/calls.csv, gitignored)."""
    path = path or CALL_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "provider", "model", "input_tokens", "output_tokens",
                        "cost_usd", "cost_inr", "latency_s", "attempts", "outcome"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), result.provider, result.model,
                    result.input_tokens, result.output_tokens, f"{result.cost_usd:.6f}",
                    f"{result.cost_inr:.4f}", f"{result.latency_s:.2f}", result.attempts, outcome])


# --------------------------------------------------------------------------
# The client
# --------------------------------------------------------------------------

Messages = str | list[dict[str, Any]]


def _as_messages(messages: Messages) -> list[dict[str, Any]]:
    if isinstance(messages, str):
        return [{"role": "user", "content": messages}]
    return list(messages)


class LLM:
    """One client for Claude and OpenAI, with the same calls and the same Result."""

    def __init__(
        self,
        provider: Provider | None = None,
        model: str | None = None,
        *,
        timeout: float = 30.0,
        max_attempts: int = 4,
        base_delay: float = 1.0,
        max_delay: float = 8.0,
        max_total_s: float = 60.0,
        fallback: LLM | None = None,
        client: Any = None,
        http_client: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        provider = provider or os.environ.get("LLM_PROVIDER", "anthropic")  # type: ignore[assignment]
        if provider not in DEFAULT_MODELS:
            raise ValueError(f"provider must be 'anthropic' or 'openai', not {provider!r}")
        self.provider: str = provider
        self.model = model or DEFAULT_MODELS[provider]
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_total_s = max_total_s
        self.fallback = fallback
        self._sleep = sleep
        self._client = client or self._make_client(http_client)

    def _make_client(self, http_client: Any) -> Any:
        from shopkart.console import require_key

        key = require_key(KEY_NAMES[self.provider])
        # max_retries=0: WE do the retrying. The SDKs retry twice by default,
        # and three tries inside three tries is nine calls.
        kw: dict[str, Any] = dict(api_key=key, timeout=self.timeout, max_retries=0)
        if http_client is not None:
            kw["http_client"] = http_client
        if self.provider == "anthropic":
            return anthropic.Anthropic(**kw)
        return openai.OpenAI(**kw)

    # ---- public calls ---------------------------------------------------

    def complete(
        self,
        messages: Messages,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        schema: type[BaseModel] | None = None,
        cache_system: bool = False,
    ) -> Result:
        """One call, the whole answer at once. With `schema`, `result.parsed` is a typed object."""
        msgs = _as_messages(messages)
        try:
            result = self._with_retries(lambda: self._complete_once(msgs, system, max_tokens, schema, cache_system))
            if schema is None:
                return result
            # TODO 2: turn the JSON text into a typed object.
            #   - result.parsed = schema.model_validate_json(result.text)
            #   - On ValidationError: if result.stop_reason is "max_tokens" or "refusal",
            #     raise SchemaError straight away (a cut-off answer won't fix itself).
            #   - Otherwise retry ONCE: add the answer as an "assistant" message and a "user"
            #     message with _short_errors(err), then call self._with_retries(...) again.
            #   - Still invalid? raise SchemaError(..., text=...). One retry, then a safe fallback.
            raise NotImplementedError("TODO 2: validate against the schema")
        except LLMError as err:
            if self.fallback is not None and err.retryable:
                log.warning("fallback: %s failed (%s), trying %s %s",
                            self.model, err.kind, self.fallback.provider, self.fallback.model)
                return self.fallback.complete(messages, system=system, max_tokens=max_tokens,
                                              schema=schema, cache_system=cache_system)
            raise

    def stream(
        self,
        messages: Messages,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        schema: type[BaseModel] | None = None,
        cache_system: bool = False,
    ) -> Iterator[str | Result]:
        """Yield text pieces as they arrive, then one final Result.

        Retries happen only before the first piece is shown. An error after that
        raises StreamInterrupted with the partial text: keep what the user saw.
        With `schema`, the JSON is validated once the stream has finished.
        """
        msgs = _as_messages(messages)
        attempt, waited, start = 0, 0.0, time.monotonic()
        while True:
            attempt += 1
            budget.check()
            shown: list[str] = []
            try:
                gen = self._stream_once(msgs, system, max_tokens, schema, cache_system)
                for piece in gen:
                    if isinstance(piece, str):
                        shown.append(piece)
                        yield piece
                    else:
                        piece.attempts = attempt
                        piece.latency_s = time.monotonic() - start
                        self._log(piece)
                        if schema is not None:
                            try:
                                piece.parsed = schema.model_validate_json(piece.text)
                            except ValidationError as err:
                                raise SchemaError(f"streamed answer is not valid {schema.__name__}: {_short_errors(err)}",
                                                  text=piece.text, attempts=attempt) from err
                        yield piece
                return
            except (anthropic.APIError, openai.APIError) as exc:
                v = classify(exc)
                if shown:
                    raise StreamInterrupted(f"stream cut off after {len(''.join(shown))} chars: {v.kind}",
                                            partial_text="".join(shown), kind=v.kind, status=v.status,
                                            request_id=v.request_id, attempts=attempt, retryable=v.retry) from exc
                delay = self._next_delay(v, attempt, waited, start)
                if delay is None:
                    err = _to_error(v, attempt)
                    if self.fallback is not None and v.retry:
                        log.warning("fallback: %s failed (%s), trying %s", self.model, v.kind, self.fallback.model)
                        yield from self.fallback.stream(messages, system=system, max_tokens=max_tokens,
                                                        schema=schema, cache_system=cache_system)
                        return
                    raise err from exc
                waited += delay
                self._sleep(delay)

    # ---- retry loop -----------------------------------------------------

    def _next_delay(self, v: Verdict, attempt: int, waited: float, start: float) -> float | None:
        """How long to wait before the next attempt, or None to stop now."""
        # TODO 5: decide the wait.
        #   - not v.retry -> log.error("stop: ...") and return None
        #   - attempt >= self.max_attempts -> log.error("give up: ...") and return None
        #   - v.retry_after set -> wait that long (the server knows best)
        #   - else exponential backoff with jitter:
        #       min(self.base_delay * 2 ** (attempt - 1), self.max_delay) * random.uniform(0.5, 1.5)
        #   - would we pass self.max_total_s since `start`? give up (return None)
        #   - log.warning("retry %d/%d: %s, waiting %.1fs", ...) and return the delay
        raise NotImplementedError("TODO 5: backoff with jitter")

    def _with_retries(self, call: Callable[[], Result]) -> Result:
        # TODO 6: the retry loop. Until now this makes exactly one attempt.
        #   loop: attempt += 1; budget.check(); try call() and return the result
        #         (set result.attempts and result.latency_s, then self._log(result): the CSV row);
        #   on anthropic.APIError / openai.APIError: v = classify(exc);
        #         delay = self._next_delay(v, attempt, waited, start)
        #         None -> raise _to_error(v, attempt) from exc;  else self._sleep(delay)
        start = time.monotonic()
        budget.check()
        try:
            result = call()
        except (anthropic.APIError, openai.APIError) as exc:
            raise _to_error(classify(exc), 1) from exc
        result.latency_s = time.monotonic() - start
        self._log(result)
        return result

    # ---- one attempt, per provider --------------------------------------

    def _finish(self, text: str, usage: dict[str, int], stop: str, start: float,
                request_id: str | None, ttft: float | None = None) -> Result:
        cost = call_cost_usd(self.model, usage["in"], usage["out"], usage["cache_read"], usage["cache_write"])
        result = Result(
            text=text, parsed=None, input_tokens=usage["in"], output_tokens=usage["out"],
            cost_usd=cost, cost_inr=usd_to_inr(cost), latency_s=time.monotonic() - start,
            model=self.model, provider=self.provider, stop_reason=stop, ttft_s=ttft,
            cache_read_tokens=usage["cache_read"], cache_write_tokens=usage["cache_write"],
            request_id=request_id,
        )
        # Paid for, whatever happens next: record it now (attempts/latency get
        # filled in by the retry loop, which then calls _log).
        budget.record(cost)
        return result

    def _log(self, result: Result) -> None:
        log.info("cost: %s · today $%.6f", result.summary(), budget.spent_today())
        try:
            log_call(result)
        except OSError:
            pass

    def _complete_once(self, msgs, system, max_tokens, schema, cache_system) -> Result:
        start = time.monotonic()
        if self.provider == "anthropic":
            args = self._anthropic_args(msgs, system, max_tokens, schema, cache_system)
            # TODO 1a (Anthropic): resp = self._client.messages.create(**args)
            #   text = the .text of every block in resp.content whose .type is "text", joined
            #   return self._finish(text, _anthropic_usage(resp.usage),
            #                       _anthropic_stop(resp.stop_reason), start, getattr(resp, "_request_id", None))
            raise NotImplementedError("TODO 1a: call Claude")
        args = self._openai_args(msgs, system, max_tokens, schema)
        # TODO 1b (OpenAI): resp = self._client.responses.create(**args)
        #   return self._finish(resp.output_text, _openai_usage(resp.usage), _openai_stop(resp),
        #                       start, getattr(resp, "_request_id", None))
        raise NotImplementedError("TODO 1b: call OpenAI")

    def _stream_once(self, msgs, system, max_tokens, schema, cache_system) -> Iterator[str | Result]:
        start = time.monotonic()
        ttft = None  # time to first token: log it next to the cost
        if self.provider == "anthropic":
            args = self._anthropic_args(msgs, system, max_tokens, schema, cache_system)
            # TODO 3a (Anthropic):
            #   with self._client.messages.stream(**args) as s:
            #       for text in s.text_stream: note ttft on the first piece, then yield text
            #       final = s.get_final_message()     # usage arrives at the END
            #   yield self._finish(<all text of final>, _anthropic_usage(final.usage), ..., ttft)
            raise NotImplementedError("TODO 3a: stream from Claude")
        args = self._openai_args(msgs, system, max_tokens, schema)
        # TODO 3b (OpenAI):
        #   with self._client.responses.stream(**args) as s:
        #       for event in s: if event.type == "response.output_text.delta": yield event.delta
        #       final = s.get_final_response()
        #   yield self._finish(final.output_text, _openai_usage(final.usage), _openai_stop(final), ..., ttft)
        raise NotImplementedError("TODO 3b: stream from OpenAI")

    def _anthropic_args(self, msgs, system, max_tokens, schema, cache_system) -> dict[str, Any]:
        args: dict[str, Any] = dict(
            model=self.model, max_tokens=max_tokens, messages=msgs,
            thinking={"type": "disabled"},  # thinking tokens bill as output; turn on only when needed
        )
        if system:
            if cache_system:  # the stable prefix gets cached; changing content goes last
                args["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            else:
                args["system"] = system
        if schema is not None:
            # The same schema messages.parse() would send. We validate ourselves,
            # so a bad answer still has its usage recorded.
            args["output_config"] = {"format": {"type": "json_schema",
                                                "schema": anthropic.transform_schema(schema)}}
        return args

    def _openai_args(self, msgs, system, max_tokens, schema) -> dict[str, Any]:
        args: dict[str, Any] = dict(
            model=self.model, input=msgs, max_output_tokens=max_tokens,
            reasoning={"effort": "none"},  # reasoning tokens bill as output
        )
        if system:
            args["instructions"] = system
        if schema is not None:
            from openai.lib._parsing._responses import type_to_text_format_param

            # The same strict schema responses.parse() would send.
            args["text"] = {"format": type_to_text_format_param(schema)}
        return args


def _short_errors(err: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'value'}: {e['msg']}" for e in err.errors()[:5])


def _get(obj: Any, name: str, default: Any = 0) -> Any:
    value = getattr(obj, name, default) if obj is not None else default
    return default if value is None else value


def _anthropic_usage(u: Any) -> dict[str, int]:
    return {"in": _get(u, "input_tokens"), "out": _get(u, "output_tokens"),
            "cache_read": _get(u, "cache_read_input_tokens"),
            "cache_write": _get(u, "cache_creation_input_tokens")}


def _openai_usage(u: Any) -> dict[str, int]:
    cached = _get(_get(u, "input_tokens_details", None), "cached_tokens")
    return {"in": _get(u, "input_tokens") - cached, "out": _get(u, "output_tokens"),
            "cache_read": cached, "cache_write": 0}


def _anthropic_stop(reason: str | None) -> str:
    return {"end_turn": "end", "stop_sequence": "end", "max_tokens": "max_tokens",
            "refusal": "refusal"}.get(reason or "", reason or "end")


def _openai_stop(resp: Any) -> str:
    if getattr(resp, "status", None) == "incomplete":
        reason = _get(_get(resp, "incomplete_details", None), "reason", "incomplete")
        return "max_tokens" if reason == "max_output_tokens" else reason
    return "end"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="llm_client.py", description="Ask ShopKart's LLM client one question.")
    parser.add_argument("question")
    parser.add_argument("--stream", action="store_true", help="print the answer as it arrives")
    parser.add_argument("--provider", choices=["anthropic", "openai"], default=None,
                        help="default: $LLM_PROVIDER, else anthropic")
    parser.add_argument("--model", default=None)
    parser.add_argument("--system", default=(
        "You are ShopKart's support assistant. Return window: 14 days (footwear 10 days, "
        "damaged electronics 7 days). Answer in two short sentences."))
    parser.add_argument("--max-tokens", type=int, default=300)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("-v", "--verbose", action="store_true", help="also log the cost line of every call")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s] %(message)s", stream=sys.stderr)
    log.setLevel(logging.INFO if args.verbose else logging.WARNING)  # retries always show; cost lines with -v
    llm = LLM(args.provider, args.model, timeout=args.timeout)
    try:
        if args.stream:
            result = None
            for piece in llm.stream(args.question, system=args.system, max_tokens=args.max_tokens):
                if isinstance(piece, str):
                    print(piece, end="", flush=True)  # flush, or Python prints it in lumps
                else:
                    result = piece
            print()
        else:
            result = llm.complete(args.question, system=args.system, max_tokens=args.max_tokens)
            print(result.text)
    except budget.BudgetExceeded as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except StreamInterrupted as exc:
        print("\n[answer cut off, please try again]", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    except LLMError as exc:
        print(f"Call failed: {exc}", file=sys.stderr)
        return 1
    assert result is not None
    print(f"\n{result.summary()}")
    print(f"Today: ${budget.spent_today():.6f} of ${budget.daily_budget_usd():.2f} daily budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
