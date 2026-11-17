"""Hand-built loop vs agent SDK, side by side: lines of code, behaviour and cost.

    uv run python labs/agent-sdk/done/compare.py --loc                      # lines of code only, no calls
    uv run python labs/agent-sdk/done/compare.py                            # Anthropic: hand-built vs Claude Agent SDK
    uv run python labs/agent-sdk/done/compare.py --provider openai --scenario cracked-watch

Every scenario runs once per implementation, from the same clean refund
store, with the same tools and the same approver decision (--decision).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
import tokenize
from pathlib import Path

HERE = Path(__file__).resolve().parent
HAND_BUILT_DIR = HERE.parents[1] / "agent-tools" / "done"
sys.path.insert(0, str(HAND_BUILT_DIR))

import agent as hand_built  # noqa: E402
import tools  # noqa: E402

from shopkart import budget  # noqa: E402
from shopkart.pricing import usd_to_inr  # noqa: E402


def code_lines(path: Path) -> int:
    """Lines with code on them: no blank lines, comments or docstrings."""
    lines: set[int] = set()
    prev = tokenize.NEWLINE
    for tok in tokenize.generate_tokens(io.StringIO(path.read_text()).readline):
        if tok.type == tokenize.STRING and prev in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            pass  # a docstring
        elif tok.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                              tokenize.DEDENT, tokenize.ENDMARKER):
            lines.update(range(tok.start[0], tok.end[0] + 1))
        if tok.type not in (tokenize.COMMENT, tokenize.NL):
            prev = tok.type
    return len(lines)


def print_loc() -> None:
    rows = [("shared tools + rules (tools.py)", HAND_BUILT_DIR / "tools.py"),
            ("hand-built loop, both providers (agent.py)", HAND_BUILT_DIR / "agent.py"),
            ("Claude Agent SDK (claude_sdk_agent.py)", HERE / "claude_sdk_agent.py"),
            ("OpenAI Agents SDK (openai_sdk_agent.py)", HERE / "openai_sdk_agent.py")]
    print("Lines of code (no blanks, comments or docstrings)")
    for label, path in rows:
        print(f"  {label:<46}{code_lines(path):>5}")
    print()


async def run_one(impl: str, scenario: dict, decision: str, provider: str):
    tools.save_refunds([])  # the same clean start for every implementation
    session = tools.Session(scenario["customer"])
    answers = iter([decision, "Need a photo of the damage first"] * 3)
    ask = lambda prompt: next(answers)  # noqa: E731
    quiet = lambda line: None  # noqa: E731
    if impl == "hand-built":
        run = hand_built.run_agent(scenario["message"], session, provider=provider, trace=quiet)
        hand_built.approval_desk(run.drafts, ask=ask, show=quiet)
    elif provider == "anthropic":
        from claude_sdk_agent import run_claude_sdk
        run = await run_claude_sdk(scenario["message"], session, ask=ask, trace=quiet)
    else:
        from openai_sdk_agent import run_openai_sdk
        run = await run_openai_sdk(scenario["message"], session, ask=ask, trace=quiet)
    rows = [r for r in tools.load_refunds() if r["conversation"] == session.conversation_id]
    outcome = ", ".join(f"{r['status']} ₹{r['amount_inr']:,}" for r in rows) or "no refund"
    return run, outcome


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--provider", choices=["anthropic", "openai"], default=os.environ.get("LLM_PROVIDER", "anthropic"))
    p.add_argument("--scenario", action="append", help="repeat to pick several (default: all)")
    p.add_argument("--decision", choices=["a", "r"], default="a", help="the approver approves (a) or rejects (r)")
    p.add_argument("--loc", action="store_true", help="only count lines of code")
    args = p.parse_args(argv)

    print_loc()
    if args.loc:
        return 0
    scenarios = json.loads(hand_built.SCENARIOS.read_text())
    if args.scenario:
        scenarios = [s for s in scenarios if s["name"] in args.scenario]
    sdk = "Claude Agent SDK" if args.provider == "anthropic" else "OpenAI Agents SDK"
    total = {"hand-built": 0.0, sdk: 0.0}

    print(f"{'scenario':<18}{'built with':<19}{'calls':>5}{'tools':>6}  {'stop':<10}{'refund':<22}{'tokens in/out':>15}{'cost $':>11}")
    for sc in scenarios:
        for impl in ("hand-built", sdk):
            run, outcome = asyncio.run(run_one(impl, sc, args.decision, args.provider))
            total[impl] += run.cost_usd
            print(f"{sc['name']:<18}{impl:<19}{run.steps:>5}{len(run.tool_calls):>6}  {run.stop:<10}{outcome:<22}"
                  f"{run.input_tokens:>8,}/{run.output_tokens:<6,}{run.cost_usd:>11.6f}")
            print(f"{'':<18}  → {hand_built._short(run.answer, 110)}")
    print()
    for impl, usd in total.items():
        print(f"Total {impl:<18} ${usd:.6f} (₹{usd_to_inr(usd):.4f})")
    print(f"Today: ${budget.spent_today():.6f} of ${budget.daily_budget_usd():.2f} daily budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
