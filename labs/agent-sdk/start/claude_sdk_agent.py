"""YOUR COPY: the same Copilot, built with the Claude Agent SDK.

TODO 1 (tools), TODO 2 (options), TODO 3 (approval), TODO 4 (repeat check).

    uv sync --group agents          # once: installs the SDK (it bundles the Claude Code CLI)
    uv run python labs/agent-sdk/done/claude_sdk_agent.py --scenario cracked-watch

Same tools, same descriptions, same rules in code (labs/agent-tools/done/tools.py).
What changes: the SDK runs the loop. It starts the Claude Code CLI as a
subprocess, our tools run in-process as an SDK MCP server, and we plug our
rules into the places the SDK gives us:

    max_turns, max_budget_usd    the SDK's own limits (we set them, not its defaults)
    can_use_tool                 a person approves a refund before the tool runs
    PreToolUse hook              our repeat check, and the trace
"""

from __future__ import annotations

import asyncio
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "agent-tools" / "done"))  # the hand-built lab: tools.py, agent.py

import agent as hand_built  # noqa: E402  (SYSTEM, HANDOVER, Limits, Run: the same agent)
import tools  # noqa: E402
from claude_agent_sdk import (  # noqa: E402
    ClaudeAgentOptions, HookMatcher, PermissionResultAllow, PermissionResultDeny, ResultMessage,
    create_sdk_mcp_server, query, tool,
)

from shopkart import budget  # noqa: E402
from shopkart.llm import call_cost_usd  # noqa: E402

# allowed_tools auto-approves the read tools, so can_use_tool never sees them: that's what we want.
warnings.filterwarnings("ignore", message="can_use_tool will not be invoked")

PREFIX = "mcp__shopkart__"  # SDK MCP tools are named mcp__<server>__<tool>


def build_tools(session: tools.Session, approved: dict) -> list:
    """Our three tools, with the SAME descriptions and schemas as the hand-built agent."""
    spec = {t["name"]: t for t in tools.TOOLS}

    def wrap(name: str, fn: Callable) -> Any:
        @tool(name, spec[name]["description"], spec[name]["input_schema"])
        async def handler(args: dict) -> dict:
            # TODO 1: run fn(args) and return {"content": [{"type": "text", "text": <JSON of the result>}]}.
            # On tools.ToolError return the same, with str(err) as the text and "is_error": True,
            # so the model reads OUR wording.
            raise NotImplementedError("TODO 1")
        return handler

    return [
        wrap("lookup_order", lambda a: tools.lookup_order(session, a["order_id"])),
        wrap("check_policy", lambda a: tools.check_policy(session, a["topic"])),
        wrap("draft_refund", lambda a: tools.draft_refund(
            session, a["order_id"], a["amount_inr"], a["reason"],
            approved_by=approved.get((a["order_id"], a["amount_inr"])))),
    ]


def make_options(session: tools.Session, run: hand_built.Run, limits: hand_built.Limits, model: str,
                 ask: Callable[[str], str], trace: Callable[[str], None], approver: str) -> ClaudeAgentOptions:
    """Everything the SDK needs: our tools, our limits, and our checks."""
    approved: dict = {}
    seen: dict[str, int] = {}

    async def approve_refunds(name: str, args: dict, context: Any):
        """Runs before any tool that isn't in allowed_tools: here, only draft_refund."""
        # TODO 3: a = tools.assess_refund(session, args["order_id"], args["amount_inr"], args["reason"]).
        # ToolError, or no a.needs_human? -> PermissionResultAllow() (the tool returns its own error).
        # Otherwise trace each line of tools.approval_screen(...), then ask "[a]pprove  [r]eject > ".
        # Approve: approved[(order_id, amount_inr)] = approver; return PermissionResultAllow().
        # Reject: ask for a reason, tools.audit("refund_rejected", ...), and return
        # PermissionResultDeny(message=...) telling the model what to say to the customer.
        raise NotImplementedError("TODO 3")

    async def check_each_call(data: dict, tool_use_id: str | None, context: Any) -> dict:
        """PreToolUse hook: our trace and our repeat check, before every tool call."""
        name = data["tool_name"].removeprefix(PREFIX)
        trace(f"  → {name} {json.dumps(data['tool_input'], ensure_ascii=False)}")
        # TODO 4: count name + inputs in `seen`. At limits.max_repeats, set run.stop = "repeat" and return
        # {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
        #                         "permissionDecisionReason": "..."}}
        run.tool_calls.append(name)
        return {}

    async def show_result(data: dict, tool_use_id: str | None, context: Any) -> dict:
        """PostToolUse hook: the trace line for what the tool sent back."""
        out = data.get("tool_response")
        if isinstance(out, list):  # MCP content blocks
            out = " ".join(b.get("text", "") for b in out if isinstance(b, dict))
        trace(f"    ← {hand_built._short(str(out))}")
        return {}

    return ClaudeAgentOptions(
        model=model,
        mcp_servers={"shopkart": create_sdk_mcp_server("shopkart", tools=build_tools(session, approved))},
        # TODO 2: our system prompt (hand_built.SYSTEM), no built-in tools (tools=[]), the two read tools
        # in allowed_tools (PREFIX + name), can_use_tool=approve_refunds, the PreToolUse and PostToolUse
        # hooks (HookMatcher), max_turns and max_budget_usd from `limits`, and setting_sources=[].
        env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
        stderr=lambda line: None if "claude.ai connectors" in line else print(line, file=sys.stderr),
    )

async def run_claude_sdk(message: str, session: tools.Session, *, model: str = "claude-haiku-5-5",
                         limits: hand_built.Limits | None = None, ask: Callable[[str], str] = input,
                         trace: Callable[[str], None] = print, approver: str = "support.lead") -> hand_built.Run:
    limits = limits or hand_built.Limits()
    session.model = model
    run = hand_built.Run(answer="", stop="")
    options = make_options(session, run, limits, model, ask, trace, approver)
    budget.check()  # the daily budget, before we start
    result: ResultMessage | None = None
    try:
        async with asyncio.timeout(limits.max_seconds):
            async for msg in query(prompt=message, options=options):  # the SDK runs the loop
                if isinstance(msg, ResultMessage):  # the last message: answer, turns, usage and cost
                    result = msg
    except TimeoutError:
        run.stop = "time_limit"

    if result is not None:
        run.steps = result.num_turns
        usage = result.usage or {}
        run.input_tokens = (usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                            + usage.get("cache_creation_input_tokens", 0))
        run.output_tokens = usage.get("output_tokens", 0)
        run.cost_usd = result.total_cost_usd or 0.0   # the SDK's own estimate
        run.sdk_cost_usd = run.cost_usd
        ours = call_cost_usd(model, usage.get("input_tokens", 0), run.output_tokens,
                             usage.get("cache_read_input_tokens", 0), usage.get("cache_creation_input_tokens", 0))
        run.our_cost_usd = ours
        budget.record(max(ours, run.cost_usd))
        if result.subtype == "success" and run.stop != "repeat":
            run.answer, run.stop = result.result or "", "end"
        elif run.stop != "repeat":
            run.stop = {"error_max_turns": "max_steps", "error_max_budget_usd": "spend_cap"}.get(
                result.subtype, result.subtype)
    if run.stop != "end":
        run.answer = hand_built.HANDOVER
        tools.audit("handover", session, why=run.stop)
    run.drafts = [r["draft_id"] for r in tools.load_refunds() if r["conversation"] == session.conversation_id]
    return run


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="The Copilot on the Claude Agent SDK.")
    p.add_argument("message", nargs="?")
    p.add_argument("--customer", default="C1001")
    p.add_argument("--scenario")
    p.add_argument("--model", default="claude-haiku-5-5")
    p.add_argument("--fresh", action="store_true", help="clear the lab's drafts and refunds first")
    args = p.parse_args(argv)
    message, customer = args.message, args.customer
    if args.scenario:
        sc = {s["name"]: s for s in json.loads(hand_built.SCENARIOS.read_text())}[args.scenario]
        message, customer = sc["message"], sc["customer"]
    if args.fresh:
        tools.save_refunds([])
    from shopkart.console import require_key
    require_key("ANTHROPIC_API_KEY")

    print(f"Customer {customer}: {message}\n")
    run = asyncio.run(run_claude_sdk(message, tools.Session(customer), model=args.model, ask=hand_built._ask))
    print(f"\nCopilot: {run.answer}\n")
    print(f"Run: {run.steps} turns · {len(run.tool_calls)} tool calls · stop: {run.stop} · "
          f"{run.input_tokens:,} in / {run.output_tokens:,} out · "
          f"SDK says ${getattr(run, 'sdk_cost_usd', 0):.6f}, our prices ${getattr(run, 'our_cost_usd', 0):.6f}")
    print(f"Today: ${budget.spent_today():.6f} of ${budget.daily_budget_usd():.2f} daily budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
