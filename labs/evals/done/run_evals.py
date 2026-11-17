"""Part 1: run the Copilot on the eval set, score it with code checks, write results.jsonl.

    uv run python labs/evals/done/run_evals.py --estimate      # what a run would cost, no calls
    uv run python labs/evals/done/run_evals.py --limit 5       # a quick slice
    uv run python labs/evals/done/run_evals.py                 # all 50 (cached answers are free)
    uv run python labs/evals/done/run_evals.py --provider openai --limit 3
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from cases import CATEGORIES, LAB, load_cases  # also puts the repo root on sys.path
from shopkart import budget  # noqa: E402
from shopkart.llm import LLM, LLMError  # noqa: E402
from shopkart.pricing import (  # noqa: E402
    CACHE_READ_FACTOR, CACHE_WRITE_FACTOR, DEFAULT_CACHE_READ_FACTOR, PRICES_PER_MILLION_USD)

import copilot  # noqa: E402
from cache import CachedLLM  # noqa: E402
from checks import as_dicts, code_pass, run_checks  # noqa: E402
from judge import judge_system, judge_user_estimate  # noqa: E402

OUT = LAB / "out"
MARK = {True: "ok", False: "FAIL", None: "-"}


def default_out(provider: str) -> Path:
    return OUT / "results.jsonl" if provider == "anthropic" else OUT / provider / "results.jsonl"


def evaluate(llm: Any, case: dict[str, Any]) -> dict[str, Any]:
    """One case: ask the Copilot, run the code checks, return the result row."""
    row: dict[str, Any] = {
        "id": case["id"], "category": case["category"], "language": case.get("language", "en"),
        "question": case["question"], "order_id": case.get("order_id"),
        "provider": llm.provider, "model": llm.model, "prompt_version": copilot.PROMPT_VERSION,
    }
    try:
        reply, result = copilot.answer(llm, case)
    except LLMError as err:  # SchemaError included: record it, keep going
        row.update(reply=None, handover=None, error=str(err), checks=[], code_pass=False,
                   cost_usd=0.0, cached=False)
        return row
    order = copilot.orders().get(case.get("order_id") or "")
    checks = run_checks(case, reply.reply, reply.handover, copilot.policies(), order)
    row.update(
        reply=reply.reply, handover=reply.handover, error=None,
        checks=as_dicts(checks), code_pass=code_pass(checks),
        cost_usd=result.cost_usd, cached=getattr(result, "cached", False),
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        cache_read_tokens=result.cache_read_tokens, cache_write_tokens=result.cache_write_tokens,
    )
    return row


def run(llm: Any, cases: list[dict[str, Any]], out: Path, echo=print) -> list[dict[str, Any]]:
    rows = []
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for case in cases:
            row = evaluate(llm, case)
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            marks = " ".join(f"{c['name']}:{MARK[c['passed']]}" for c in row["checks"]) or f"ERROR {row['error']}"
            src = "cache" if row["cached"] else f"${row['cost_usd']:.5f}"
            echo(f"{row['id']}  {row['category']:<13} {'PASS' if row['code_pass'] else 'FAIL'}  {marks}  ({src})")
    return rows


def summary(rows: list[dict[str, Any]]) -> str:
    lines = ["", f"{'category':<14} {'cases':>5} {'code pass':>10}"]
    for cat in CATEGORIES:
        sub = [r for r in rows if r["category"] == cat]
        if sub:
            ok = sum(r["code_pass"] for r in sub)
            lines.append(f"{cat:<14} {len(sub):>5} {ok:>4} ({ok / len(sub):.0%})")
    ok = sum(r["code_pass"] for r in rows)
    lines.append(f"{'all':<14} {len(rows):>5} {ok:>4} ({ok / len(rows):.0%})")
    fails = Counter(c["name"] for r in rows for c in r["checks"] if c["passed"] is False)
    if fails:
        lines.append("failed checks: " + ", ".join(f"{k} {v}" for k, v in fails.most_common()))
    return "\n".join(lines)


# ---- estimate before you spend --------------------------------------------

def tokens(text: str) -> int:
    """A rough count. Plain English is about 4 characters per token; our policies,
    full of tables, ₹ signs and markdown, measured 2.8 (51,000 characters = 18,161 tokens)."""
    return int(len(text) / 2.8) + 1


def estimate(model: str, cases: list[dict[str, Any]], n_judge: int, cached_ids: set[str] = frozenset(),
             reply_tokens: int = 150, judge_tokens: int = 150) -> dict[str, float]:
    """Dollars for a run: the Copilot on the uncached cases, then the judge on n_judge.

    The system prompt (instructions + policies) is cached: one write (1.25x on
    Claude), then each call reads it at the model's cache-read price (0.1x for
    the small models, see shopkart/pricing.py). Worst case (no cache hit) is shown too.
    """
    price_in, price_out = PRICES_PER_MILLION_USD[model]
    read = CACHE_READ_FACTOR.get(model, DEFAULT_CACHE_READ_FACTOR)
    todo = [c for c in cases if c["id"] not in cached_ids]

    def part(system: str, users: list[str], out_tokens: int) -> tuple[float, float]:
        if not users:
            return 0.0, 0.0
        s, u = tokens(system), sum(tokens(x) for x in users)
        cached = s * CACHE_WRITE_FACTOR + s * read * (len(users) - 1)
        cost = ((cached + u) * price_in + len(users) * out_tokens * price_out) / 1e6
        worst = ((s * len(users) + u) * price_in + len(users) * out_tokens * price_out) / 1e6
        return cost, worst

    a, a_worst = part(copilot.system_prompt(), [copilot.user_message(c) for c in todo], reply_tokens)
    j, j_worst = part(judge_system(), [judge_user_estimate(c) for c in cases[:n_judge]], judge_tokens)
    return {"copilot": a, "judge": j, "total": a + j, "worst": a_worst + j_worst,
            "copilot_calls": len(todo), "judge_calls": min(n_judge, len(cases))}


def cached_case_ids(llm: CachedLLM, cases: list[dict[str, Any]]) -> set[str]:
    return {c["id"] for c in cases
            if (llm.dir / f"{llm.key(copilot.user_message(c), copilot.system_prompt(), 400, copilot.Reply)}.json").exists()}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the ShopKart Copilot eval set (code checks).")
    p.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--limit", type=int, default=None, help="only the first N cases")
    p.add_argument("--ids", default=None, help="comma-separated case IDs, e.g. g-001,g-126")
    p.add_argument("--out", type=Path, default=None, help="default: labs/evals/out/results.jsonl")
    p.add_argument("--estimate", action="store_true", help="print the cost of a run (plus the judge) and stop")
    p.add_argument("--judge-cases", type=int, default=50, help="for --estimate: how many cases the judge grades")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s] %(message)s", stream=sys.stderr)

    cases = load_cases(limit=args.limit, ids=args.ids.split(",") if args.ids else None)
    llm = CachedLLM(LLM(args.provider, args.model))

    if args.estimate:
        cached = cached_case_ids(llm, cases)
        e = estimate(llm.model, cases, args.judge_cases, cached)
        print(f"{len(cases)} cases on {llm.model}, {len(cached)} already cached")
        print(f"  Copilot: {e['copilot_calls']:>3} calls  ~${e['copilot']:.4f}  (policies cached after the first call)")
        print(f"  Judge:   {e['judge_calls']:>3} calls  ~${e['judge']:.4f}")
        print(f"  Total:            ~${e['total']:.4f}   (no prompt caching at all: ~${e['worst']:.4f})")
        return 0

    out = args.out or default_out(llm.provider)
    print(f"{len(cases)} cases · {llm.provider} {llm.model} · prompt {copilot.PROMPT_VERSION}\n")
    try:
        rows = run(llm, cases, out)
    except budget.BudgetExceeded as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(summary(rows))
    spent = sum(r["cost_usd"] for r in rows)
    print(f"\nwrote {out.relative_to(LAB.parents[1]) if out.is_relative_to(LAB.parents[1]) else out}")
    print(f"this run: ${spent:.6f} · {llm.misses} new calls, {llm.hits} from cache · "
          f"today ${budget.spent_today():.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
