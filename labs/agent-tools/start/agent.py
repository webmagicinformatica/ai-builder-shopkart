"""YOUR COPY: the ShopKart Copilot as an agent, a hand-written loop with native tool calling.

Part 1: TODO 3 (Claude turn), TODO 4 (OpenAI turn), TODO 5 (the loop).
Part 2: TODO 6 (the exits), TODO 8 (the approval desk).

    uv run python labs/agent-tools/done/agent.py --scenario cracked-watch
    uv run python labs/agent-tools/done/agent.py "Where is SK48213?" --customer C1001
    uv run python labs/agent-tools/done/agent.py --scenario cracked-watch --provider openai

An agent is a loop: call the model, run the tools it asks for, send the results
back, and repeat until it answers. The model decides. Your code acts. And your
code decides when the loop must stop:

    the model's own stop    end_turn (Claude) / no function calls (OpenAI)
    a cut-off reply         max_tokens / incomplete: not done, never run it
    a turn limit            10 model calls
    a repeat check          the same tool with the same inputs, 3 times
    a time limit            60 seconds for the whole run
    a spend cap             $0.10 per conversation, plus the daily budget

When a limit hits, the customer gets a hand-over, not a crash. Refunds the
tools drafted then go to a person, at the approval desk in this terminal.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import anthropic
import openai

import tools  # this folder's tools.py (it also puts the repo root on sys.path)
from shopkart import budget
from shopkart.console import require_key
from shopkart.llm import DEFAULT_MODELS, KEY_NAMES, Result, call_cost_usd, log_call
from shopkart.pricing import usd_to_inr

SCENARIOS = Path(__file__).resolve().parent.parent / "scenarios.json"

SYSTEM = """You are the ShopKart Support Copilot. ShopKart is an Indian online store.
Today is Tuesday 17 November 2026. Prices are in rupees (₹).
Use your tools: look up the order, check the policy, then act. Never guess an order ID or a policy.
You can't approve or promise refunds: draft_refund only prepares one for review.
If a tool says to hand over, or the policy says a person must decide, tell the customer
a colleague will take over and when they'll hear back.
Reply to the customer in 2 to 4 short, warm sentences."""

HANDOVER = ("I'm handing this to a colleague so it's done right. "
            "You'll hear from us within one working day.")


@dataclass
class Limits:
    max_steps: int = 10        # model calls per run
    max_usd: float = 0.10      # spend per conversation
    max_seconds: float = 60.0  # time for the whole run
    max_repeats: int = 3       # same tool + same inputs
    max_tokens: int = 800      # per reply


@dataclass
class Turn:
    """One model call, the same shape for both providers."""

    calls: list[tuple[str, str, dict]]  # (call id, tool name, inputs)
    text: str
    stop: str                           # "tool_use", "end" or "max_tokens"
    input_tokens: int
    output_tokens: int


@dataclass
class Run:
    answer: str
    stop: str                           # end, max_steps, spend_cap, repeat, time_limit, cut_off, daily_budget
    steps: int = 0
    tool_calls: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    drafts: list[str] = field(default_factory=list)

    @property
    def handed_over(self) -> bool:
        return self.stop != "end"


# ---------------------------------------------------------------------------
# One model call, per provider. Same tools, different labels.
# ---------------------------------------------------------------------------

# Claude: the schema goes in "input_schema". OpenAI: in "parameters".
CLAUDE_TOOLS = [{**t, "strict": True} for t in tools.TOOLS]
OPENAI_TOOLS = [{"type": "function", "name": t["name"], "description": t["description"],
                 "parameters": t["input_schema"], "strict": True} for t in tools.TOOLS]


def claude_turn(client: Any, model: str, history: list, max_tokens: int) -> Turn:
    # TODO 3: call client.messages.create with model, max_tokens, system=SYSTEM, tools=CLAUDE_TOOLS,
    # messages=history and thinking={"type": "disabled"}. Append the reply to history EXACTLY as it
    # came (role "assistant", content=resp.content). Collect the tool_use blocks as (id, name, input).
    # stop: "tool_use" / "max_tokens" / "end", from resp.stop_reason. Tokens from resp.usage.
    raise NotImplementedError("TODO 3")


def claude_results(history: list, results: list[tuple[str, str, bool]]) -> None:
    # TODO 3: ONE user message with a tool_result block per call:
    # {"type": "tool_result", "tool_use_id": ..., "content": text, "is_error": is_error}
    raise NotImplementedError("TODO 3")


def openai_turn(client: Any, model: str, history: list, max_tokens: int) -> Turn:
    # TODO 4: client.responses.create with model, instructions=SYSTEM, input=history, tools=OPENAI_TOOLS,
    # max_output_tokens and reasoning={"effort": "none"}. Add resp.output to history. The function_call
    # items have call_id, name and arguments (a JSON STRING: parse it). No stop reason for tools:
    # calls -> "tool_use", resp.status == "incomplete" -> "max_tokens", else "end".
    raise NotImplementedError("TODO 4")


def openai_results(history: list, results: list[tuple[str, str, bool]]) -> None:
    # TODO 4: one {"type": "function_call_output", "call_id": ..., "output": ...} per call.
    # No error flag on OpenAI: start the output with "ERROR: " when is_error.
    raise NotImplementedError("TODO 4")


PROVIDERS = {"anthropic": (claude_turn, claude_results), "openai": (openai_turn, openai_results)}


def make_client(provider: str) -> Any:
    key = require_key(KEY_NAMES[provider])
    return anthropic.Anthropic(api_key=key, timeout=30) if provider == "anthropic" \
        else openai.OpenAI(api_key=key, timeout=30)


def paid_turn(provider: str, client: Any, model: str, history: list, max_tokens: int) -> tuple[Turn, float]:
    """Every call: the budget check first, then cost recorded and logged."""
    budget.check()
    start = time.monotonic()
    turn = PROVIDERS[provider][0](client, model, history, max_tokens)
    cost = call_cost_usd(model, turn.input_tokens, turn.output_tokens)
    budget.record(cost)
    log_call(Result(text=turn.text, parsed=None, input_tokens=turn.input_tokens,
                    output_tokens=turn.output_tokens, cost_usd=cost, cost_inr=usd_to_inr(cost),
                    latency_s=time.monotonic() - start, model=model, provider=provider))
    return turn, cost


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def run_agent(message: str, session: tools.Session, *, provider: str = "anthropic",
              client: Any = None, model: str | None = None, limits: Limits | None = None,
              trace: Callable[[str], None] = print) -> Run:
    model = model or DEFAULT_MODELS[provider]
    client = client or make_client(provider)
    limits = limits or Limits()
    session.model = model
    add_results = PROVIDERS[provider][1]
    history: list = [{"role": "user", "content": message}]
    run = Run(answer="", stop="")
    seen: Counter[str] = Counter()
    start = time.monotonic()

    def stop(reason: str, why: str) -> Run:
        run.answer, run.stop = HANDOVER, reason
        trace(f"  stop    {reason}: {why} → hand over to a person")
        tools.audit("handover", session, why=f"{reason}: {why}", steps=run.steps)
        return run

    while True:
        # TODO 6 (Part 2): our exits, checked before every call. Use stop(reason, why) for:
        #   run.steps >= limits.max_steps            -> "max_steps"
        #   run.cost_usd >= limits.max_usd           -> "spend_cap"
        #   time.monotonic() - start > max_seconds   -> "time_limit"
        #   budget.BudgetExceeded from paid_turn     -> "daily_budget"
        #   turn.stop == "max_tokens"                -> "cut_off" (never run a half-written tool call)
        #   the same name + inputs max_repeats times -> "repeat" (count them in `seen`)

        # TODO 5 (Part 1): the loop.
        #   turn, cost = paid_turn(provider, client, model, history, limits.max_tokens)
        #   add the cost and tokens to `run`, run.steps += 1, and trace one line per step
        #   turn.stop == "end"?  run.answer, run.stop = turn.text, "end"; return run
        #   else for each (call_id, name, args) in turn.calls:
        #       text, is_error = tools.run_tool(session, name, args); keep run.tool_calls and run.drafts
        #   add_results(history, results) and go round again
        raise NotImplementedError("TODO 5")


def _short(text: str, width: int = 150) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


# ---------------------------------------------------------------------------
# The approval desk: a person decides, our code runs exactly that, once
# ---------------------------------------------------------------------------


def approval_desk(draft_ids: list[str], approver: str = "support.lead",
                  ask: Callable[[str], str] = input, show: Callable[[str], None] = print) -> list[dict]:
    """Show each waiting draft with the evidence from OUR systems, then approve, edit or reject."""
    decided = []
    for draft_id in draft_ids:
        d = tools.find_draft(draft_id)
        if d["status"] != "pending":
            continue
        # TODO 8: show tools.approval_screen(order, amount, reason, why) for this draft (evidence from
        # OUR order system, via tools.data.get_order), then ask "[a]pprove  [e]dit amount  [r]eject > ".
        # a -> tools.approve(draft_id, approver); e -> ask for the amount, approve with amount_inr=...;
        # r -> tools.reject(draft_id, approver, reason). Show what happened, append the row to `decided`.
        raise NotImplementedError("TODO 8")
    return decided


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _ask(prompt: str) -> str:
    answer = input(prompt)
    if not sys.stdin.isatty():
        print(answer)  # piped answers (e.g. printf 'a\n' | ...) still show in the output
    return answer


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the ShopKart Copilot agent on one customer message.")
    p.add_argument("message", nargs="?")
    p.add_argument("--customer", default="C1001", help="the signed-in customer (from the login, not the model)")
    p.add_argument("--scenario", help="a scenario from scenarios.json, e.g. cracked-watch")
    p.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--max-steps", type=int, default=Limits.max_steps)
    p.add_argument("--max-usd", type=float, default=Limits.max_usd)
    p.add_argument("--no-desk", action="store_true", help="leave drafts in the queue for later")
    p.add_argument("--fresh", action="store_true", help="clear this lab's drafts and refunds first")
    args = p.parse_args(argv)

    import os
    provider = args.provider or os.environ.get("LLM_PROVIDER", "anthropic")
    message, customer = args.message, args.customer
    if args.scenario:
        sc = {s["name"]: s for s in json.loads(SCENARIOS.read_text())}[args.scenario]
        message, customer = sc["message"], sc["customer"]
    if not message:
        p.error("give a message or --scenario")
    if args.fresh:
        tools.save_refunds([])

    session = tools.Session(customer)
    print(f"Customer {customer}: {message}\n")
    run = run_agent(message, session, provider=provider, model=args.model,
                    limits=Limits(max_steps=args.max_steps, max_usd=args.max_usd))
    print(f"\nCopilot: {run.answer}\n")
    print(f"Run: {run.steps} model calls · {len(run.tool_calls)} tool calls · stop: {run.stop} · "
          f"{run.input_tokens:,} in / {run.output_tokens:,} out · "
          f"${run.cost_usd:.6f} (₹{usd_to_inr(run.cost_usd):.4f})")
    if run.drafts and not args.no_desk:
        approval_desk(run.drafts, ask=_ask)
    print(f"\nToday: ${budget.spent_today():.6f} of ${budget.daily_budget_usd():.2f} daily budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
