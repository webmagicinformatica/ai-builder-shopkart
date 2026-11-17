"""The same Copilot, built with the OpenAI Agents SDK.

    uv sync --group agents
    uv run python labs/agent-sdk/done/openai_sdk_agent.py --scenario cracked-watch

Same tools, same descriptions, same rules in code (labs/agent-tools/done/tools.py).
What changes: Runner.run() runs the loop, and @function_tool turns plain
functions into tool definitions. Where our rules plug in:

    max_turns                    the turn limit (the SDK's default is 10)
    needs_approval               the run pauses before a refund; a person decides
    failure_error_function       OUR error wording (the default hides the error)
    RunHooks                     the trace, the repeat check and the spend cap
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Callable, Literal

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "agent-tools" / "done"))  # the hand-built lab: tools.py, agent.py

import agent as hand_built  # noqa: E402  (SYSTEM, HANDOVER, Limits, Run: the same agent)
import tools  # noqa: E402
from agents import (  # noqa: E402
    Agent, MaxTurnsExceeded, ModelSettings, RunContextWrapper, RunHooks, Runner, function_tool,
)
from openai.types.shared import Reasoning  # noqa: E402

from shopkart import budget  # noqa: E402
from shopkart.llm import call_cost_usd  # noqa: E402

DESCRIPTION = {t["name"]: t["description"] for t in tools.TOOLS}
Ctx = RunContextWrapper[tools.Session]


class StopRun(Exception):
    """One of OUR limits hit: hand over."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def tool_error(ctx: Ctx, error: Exception) -> str:
    # The SDK's default says only "An error occurred while running the tool. Please try again."
    # Our errors say what happened and what to do next, so pass them through.
    return f"ERROR: {error}"


@function_tool(description_override=DESCRIPTION["lookup_order"], failure_error_function=tool_error)
def lookup_order(ctx: Ctx, order_id: str) -> str:
    """Args:
        order_id: SK followed by 5 digits, e.g. SK48213
    """
    return json.dumps(tools.lookup_order(ctx.context, order_id), ensure_ascii=False)


@function_tool(description_override=DESCRIPTION["check_policy"], failure_error_function=tool_error)
def check_policy(ctx: Ctx, topic: Literal[tuple(tools.TOPICS)]) -> str:  # type: ignore[valid-type]
    return json.dumps(tools.check_policy(ctx.context, topic), ensure_ascii=False)


async def needs_a_person(ctx: Ctx, args: dict[str, Any], call_id: str) -> bool:
    """Pause the run for approval only when the refund is valid AND our rules want a person."""
    try:
        return bool(tools.assess_refund(ctx.context, args["order_id"], args["amount_inr"], args["reason"]).needs_human)
    except (tools.ToolError, KeyError):
        return False  # let the tool run and return its own error


@function_tool(description_override=DESCRIPTION["draft_refund"], failure_error_function=tool_error,
               needs_approval=needs_a_person)
def draft_refund(ctx: Ctx, order_id: str, amount_inr: int,
                 reason: Literal[tuple(tools.REASONS)]) -> str:  # type: ignore[valid-type]
    """Args:
        order_id: SK followed by 5 digits, e.g. SK48213
        amount_inr: Refund amount in whole rupees, e.g. 1299
    """
    approver = getattr(ctx.context, "approved", {}).get((order_id, amount_inr))
    return json.dumps(tools.draft_refund(ctx.context, order_id, amount_inr, reason, approved_by=approver),
                      ensure_ascii=False)


class Guard(RunHooks[tools.Session]):
    """Our trace, repeat check and spend cap, around every model call and tool call."""

    def __init__(self, model: str, limits: hand_built.Limits, run: hand_built.Run, trace: Callable[[str], None]):
        self.model, self.limits, self.run, self.trace = model, limits, run, trace
        self.seen: dict[str, int] = {}

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        budget.check()
        if self.run.cost_usd >= self.limits.max_usd:
            raise StopRun("spend_cap")

    async def on_llm_end(self, context, agent, response) -> None:
        u = response.usage
        cost = call_cost_usd(self.model, u.input_tokens, u.output_tokens)
        budget.record(cost)
        self.run.steps += 1
        self.run.cost_usd += cost
        self.run.input_tokens += u.input_tokens
        self.run.output_tokens += u.output_tokens
        self.trace(f"step {self.run.steps}  {self.model} · {u.input_tokens:,} in / {u.output_tokens:,} out · ${cost:.6f}")

    async def on_tool_start(self, context, agent, tool) -> None:
        args = getattr(context, "tool_arguments", None) or "{}"
        self.trace(f"  → {tool.name} {args}")
        key = tool.name + json.dumps(json.loads(args), sort_keys=True)
        self.seen[key] = self.seen.get(key, 0) + 1
        if self.seen[key] >= self.limits.max_repeats:
            raise StopRun("repeat")
        self.run.tool_calls.append(tool.name)

    async def on_tool_end(self, context, agent, tool, result) -> None:
        self.trace(f"    ← {hand_built._short(str(result))}")


async def run_openai_sdk(message: str, session: tools.Session, *, model: str = "gpt-6-luna",
                         limits: hand_built.Limits | None = None, ask: Callable[[str], str] = input,
                         trace: Callable[[str], None] = print, approver: str = "support.lead",
                         model_provider: Any = None) -> hand_built.Run:
    limits = limits or hand_built.Limits()
    session.model = model
    session.approved = {}
    run = hand_built.Run(answer="", stop="")
    copilot = Agent[tools.Session](
        name="ShopKart Copilot",
        instructions=hand_built.SYSTEM,
        model=model,
        tools=[lookup_order, check_policy, draft_refund],
        model_settings=ModelSettings(max_tokens=limits.max_tokens, reasoning=Reasoning(effort="none")),
    )
    hooks = Guard(model, limits, run, trace)
    run_config = {"model_provider": model_provider} if model_provider else None
    turn_input: Any = message
    try:
        async with asyncio.timeout(limits.max_seconds):
            while True:
                result = await Runner.run(copilot, turn_input, context=session, max_turns=limits.max_steps,
                                          hooks=hooks, run_config=run_config)
                if not result.interruptions:
                    break
                # The run paused before draft_refund. A person decides; then we resume it.
                state = result.to_state()
                for item in result.interruptions:
                    args = json.loads(item.arguments or "{}")
                    a = tools.assess_refund(session, args["order_id"], args["amount_inr"], args["reason"])
                    for line in tools.approval_screen(a.order, a.amount_inr, args["reason"], a.needs_human):
                        trace(line)
                    if ask("  [a]pprove  [r]eject > ").strip().lower().startswith("a"):
                        session.approved[(args["order_id"], args["amount_inr"])] = approver
                        state.approve(item)
                    else:
                        why = ask("  Reason > ").strip() or "rejected"
                        tools.audit("refund_rejected", session, input=args, by=approver, why=why)
                        state.reject(item, rejection_message=f"A support lead rejected this refund: {why}. "
                                     "Don't draft it again. Tell the customer a colleague will contact them.")
                turn_input = state
        run.answer, run.stop = str(result.final_output), "end"
    except MaxTurnsExceeded:
        run.stop = "max_steps"
    except StopRun as stop:
        run.stop = stop.reason
    except budget.BudgetExceeded:
        run.stop = "daily_budget"
    except TimeoutError:
        run.stop = "time_limit"
    if run.stop != "end":
        run.answer = hand_built.HANDOVER
        trace(f"  stop    {run.stop} → hand over to a person")
        tools.audit("handover", session, why=run.stop)
    run.drafts = [r["draft_id"] for r in tools.load_refunds() if r["conversation"] == session.conversation_id]
    return run


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="The Copilot on the OpenAI Agents SDK.")
    p.add_argument("message", nargs="?")
    p.add_argument("--customer", default="C1001")
    p.add_argument("--scenario")
    p.add_argument("--model", default="gpt-6-luna")
    p.add_argument("--fresh", action="store_true", help="clear the lab's drafts and refunds first")
    args = p.parse_args(argv)
    message, customer = args.message, args.customer
    if args.scenario:
        sc = {s["name"]: s for s in json.loads(hand_built.SCENARIOS.read_text())}[args.scenario]
        message, customer = sc["message"], sc["customer"]
    if args.fresh:
        tools.save_refunds([])
    from shopkart.console import require_key
    require_key("OPENAI_API_KEY")

    print(f"Customer {customer}: {message}\n")
    run = asyncio.run(run_openai_sdk(message, tools.Session(customer), model=args.model, ask=hand_built._ask))
    print(f"\nCopilot: {run.answer}\n")
    print(f"Run: {run.steps} model calls · {len(run.tool_calls)} tool calls · stop: {run.stop} · "
          f"{run.input_tokens:,} in / {run.output_tokens:,} out · ${run.cost_usd:.6f}")
    print(f"Today: ${budget.spent_today():.6f} of ${budget.daily_budget_usd():.2f} daily budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
