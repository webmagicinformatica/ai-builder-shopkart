"""The regression gate a pull request must pass: run the eval slice, block if it got worse.

Two rules, decided before the run:
  1. Hard rule: every must-hand-over case hands over. One miss blocks the change.
  2. The pass rate (code checks + judge) must be at least --threshold.

It writes a markdown summary to $GITHUB_STEP_SUMMARY when GitHub Actions sets it,
and exits 1 to block, 0 to pass. With no API key it skips cleanly (exit 0), so
forks and copies of the repo without the secret stay green.

    uv run python labs/evals-ci/done/ci_gate.py                  # 10 cases, threshold 0.7, judge on
    uv run python labs/evals-ci/done/ci_gate.py --no-judge       # code checks only (cheaper)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
CI_LAB = HERE.parents[1]
EVALS = CI_LAB.parent / "evals" / "done"  # the eval suite from the previous lab
sys.path.insert(0, str(EVALS))

from cases import CATEGORIES, load_cases  # noqa: E402  (also puts the repo root on sys.path)
from shopkart import budget  # noqa: E402
from shopkart.llm import KEY_NAMES, LLM  # noqa: E402

from cache import CachedLLM  # noqa: E402
from judge import judge_rows  # noqa: E402
from report import passed  # noqa: E402
from run_evals import run  # noqa: E402

SLICE = CI_LAB / "ci-10.json"
OUT = CI_LAB / "out"


def slice_ids(path: Path = SLICE) -> list[str]:
    return json.loads(path.read_text(encoding="utf-8"))["ids"]


def decide(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    """The gate's verdict, from result rows (judged or not)."""
    n = len(rows)
    errors = [r for r in rows if r.get("error")]
    if errors:  # the calls failed (network, outage, spend limit): not a verdict on the change
        return {"cases": n, "passed": 0, "rate": 0.0, "threshold": threshold, "blocked": True, "error": True,
                "reasons": [f"{len(errors)} of {n} calls failed, so nothing was measured: {errors[0]['error']}"]}
    ok = sum(passed(r) for r in rows)
    rate = ok / n if n else 0.0
    missed = [r["id"] for r in rows if r["category"] == "must_handover" and r.get("handover") is not True]
    reasons = []
    if missed:
        reasons.append(f"hard rule: must-hand-over case(s) answered instead: {', '.join(missed)}")
    if rate < threshold:
        reasons.append(f"pass rate {rate:.0%} is below the {threshold:.0%} threshold")
    return {"cases": n, "passed": ok, "rate": rate, "threshold": threshold,
            "blocked": bool(reasons), "error": False, "reasons": reasons}


def summary_markdown(rows: list[dict[str, Any]], d: dict[str, Any], model: str, spent: float) -> str:
    if d.get("error"):
        return f"## Evals: ERROR\n\n- {d['reasons'][0]}\n\nThe change was not tested. Re-run the job once the API is reachable.\n"
    head = "## Evals: BLOCKED" if d["blocked"] else "## Evals: passed"
    lines = [head, "",
             f"**{d['passed']}/{d['cases']} cases pass ({d['rate']:.0%})**, threshold {d['threshold']:.0%} · "
             f"{model} · new spend ${spent:.4f}"]
    if d["reasons"]:
        lines += [""] + [f"- {r}" for r in d["reasons"]]
    lines += ["", "| Category | Cases | Pass |", "| --- | ---: | ---: |"]
    for cat in CATEGORIES:
        sub = [r for r in rows if r["category"] == cat]
        if sub:
            lines.append(f"| {cat} | {len(sub)} | {sum(passed(r) for r in sub)} |")
    fails = [r for r in rows if not passed(r)]
    if fails:
        lines += ["", "### Failing cases", ""]
        for r in fails:
            why = [f"{c['name']}: {c['note']}" for c in r.get("checks", []) if c["passed"] is False]
            if r.get("judge") and r["judge"].get("verdict") == "fail":
                why.append(f"judge: {r['judge']['reason']}")
            if r.get("error"):
                why.append(f"error: {r['error']}")
            lines.append(f"- **{r['id']}** ({r['category']}) {r['question']}<br>{'<br>'.join(why)}")
    return "\n".join(lines) + "\n"


def write_summary(text: str) -> None:
    """Append to the job summary page in GitHub Actions; print it everywhere."""
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the eval slice and block a change that made things worse.")
    p.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    p.add_argument("--threshold", type=float, default=0.7, help="minimum pass rate, 0 to 1 (default 0.7)")
    p.add_argument("--no-judge", action="store_true", help="code checks only")
    p.add_argument("--slice", type=Path, default=SLICE)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s] %(message)s", stream=sys.stderr)

    provider = args.provider or os.environ.get("LLM_PROVIDER", "anthropic")
    key = KEY_NAMES[provider]
    if not os.environ.get(key, "").strip():
        write_summary(f"## Evals: skipped\n\nNo `{key}` secret in this run, so no model was called. "
                      "Add it under Settings → Secrets and variables → Actions to run the evals.\n")
        return 0

    cases = load_cases(ids=slice_ids(args.slice))
    llm = CachedLLM(LLM(provider))
    print(f"eval slice: {len(cases)} cases · {llm.provider} {llm.model}\n")
    try:
        rows = run(llm, cases, OUT / "results.jsonl")
        if not args.no_judge and not any(r.get("error") for r in rows):
            print()
            rows = judge_rows(llm, rows)
    except budget.BudgetExceeded as exc:
        write_summary(f"## Evals: BLOCKED\n\n{exc}\n")
        return 1
    spent = sum(r.get("cost_usd") or 0 for r in rows) + sum(
        (r.get("judge") or {}).get("cost_usd") or 0 for r in rows)
    d = decide(rows, args.threshold)
    print()
    write_summary(summary_markdown(rows, d, f"{llm.provider} {llm.model}", spent))
    print(f"{llm.misses} new calls, {llm.hits} from cache")
    return 1 if d["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
