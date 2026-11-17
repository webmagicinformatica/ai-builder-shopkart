"""The ShopKart Copilot as an agent: a hand-written loop with native tool calling.

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
    resp = client.messages.create(model=model, max_tokens=max_tokens, system=SYSTEM,
                                  tools=CLAUDE_TOOLS, messages=history,
                                  thinking={"type": "disabled"})
    history.append({"role": "assistant", "content": resp.content})  # the request, exactly as it came
    calls = [(b.id, b.name, b.input) for b in resp.content if b.type == "tool_use"]
    text = "".join(b.text for b in resp.content if b.type == "text")
    stop = {"tool_use": "tool_use", "max_tokens": "max_tokens"}.get(resp.stop_reason, "end")
    return Turn(calls, text, stop, resp.usage.input_tokens, resp.usage.output_tokens)


def claude_results(history: list, results: list[tuple[str, str, bool]]) -> None:
    # All results in ONE user message, each with the tool_use id it answers.
    history.append({"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": call_id, "content": text, "is_error": is_error}
        for call_id, text, is_error in results]})


def openai_turn(client: Any, model: str, history: list, max_tokens: int) -> Turn:
    resp = client.responses.create(model=model, instructions=SYSTEM, input=history,
                                   tools=OPENAI_TOOLS, max_output_tokens=max_tokens,
                                   reasoning={"effort": "none"})
    history += resp.output  # the function_call items, exactly as they came
    # The arguments arrive as a JSON string: parse them yourself.
    calls = [(i.call_id, i.name, json.loads(i.arguments)) for i in resp.output if i.type == "function_call"]
    if resp.status == "incomplete":
        stop = "max_tokens"
    else:
        stop = "tool_use" if calls else "end"  # no stop reason for tools: look for function calls
    return Turn(calls, resp.output_text, stop, resp.usage.input_tokens, resp.usage.output_tokens)


def openai_results(history: list, results: list[tuple[str, str, bool]]) -> None:
    # No error flag on OpenAI: the error goes in the output text.
    history += [{"type": "function_call_output", "call_id": call_id,
                 "output": f"ERROR: {text}" if is_error else text}
                for call_id, text, is_error in results]


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
        # Our exits, checked before every call. The model can't argue with these.
        if run.steps >= limits.max_steps:
            return stop("max_steps", f"{run.steps} model calls, limit {limits.max_steps}")
        if run.cost_usd >= limits.max_usd:
            return stop("spend_cap", f"${run.cost_usd:.6f} spent, cap ${limits.max_usd}")
        if time.monotonic() - start > limits.max_seconds:
            return stop("time_limit", f"over {limits.max_seconds:.0f}s")
        try:
            turn, cost = paid_turn(provider, client, model, history, limits.max_tokens)
        except budget.BudgetExceeded as exc:
            return stop("daily_budget", str(exc))
        run.steps += 1
        run.cost_usd += cost
        run.input_tokens += turn.input_tokens
        run.output_tokens += turn.output_tokens
        trace(f"step {run.steps}  {model} · {turn.input_tokens:,} in / {turn.output_tokens:,} out · ${cost:.6f}")

        # The model's own exit.
        if turn.stop == "max_tokens":
            return stop("cut_off", "the reply was cut off; a half-written tool call is never run")
        if turn.stop == "end":
            run.answer, run.stop = turn.text, "end"
            return run

        # The model asked for tools: our code runs them, and every call gets a result.
        results = []
        for call_id, name, args in turn.calls:
            trace(f"  → {name} {json.dumps(args, ensure_ascii=False)}")
            key = name + json.dumps(args, sort_keys=True)
            seen[key] += 1
            if seen[key] >= limits.max_repeats:
                return stop("repeat", f"{name} with the same inputs {seen[key]} times")
            text, is_error = tools.run_tool(session, name, args)
            run.tool_calls.append(name)
            if name == "draft_refund" and not is_error:
                run.drafts.append(json.loads(text)["draft_id"])
            trace(f"    {'✗ error' if is_error else '←'} {_short(text)}")
            results.append((call_id, text, is_error))
        add_results(history, results)


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
        order = tools.data.get_order(d["order_id"])
        show("")
        for line in tools.approval_screen(order, d["amount_inr"], d["reason"], d["needs_human"]):
            show(line)
        try:
            choice = ask("  [a]pprove  [e]dit amount  [r]eject > ").strip().lower()[:1]
        except EOFError:  # nobody at the desk: the draft stays in the queue
            show("\n  Left in the queue for later.")
            break
        try:
            if choice == "a":
                row = tools.approve(draft_id, approver)
            elif choice == "e":
                amount = int(ask("  New amount in rupees > ").strip().replace(",", ""))
                row = tools.approve(draft_id, approver, amount_inr=amount)
            else:
                row = tools.reject(draft_id, approver, ask("  Reason > ").strip() or "rejected")
        except tools.ToolError as err:
            show(f"  Not issued: {err}")
            continue
        if row["status"] == "issued":
            show(f"  Issued {row['refund_id']}: ₹{row['amount_inr']:,} by {approver}. "
                 "The customer gets an SMS with the reference.")
        else:
            show(f"  Rejected by {approver}: {str(row.get('rejected_because')).rstrip('.')}. A colleague tells the customer.")
        decided.append(row)
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
