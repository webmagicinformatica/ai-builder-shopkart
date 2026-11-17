"""Step 7: review a prompt change like code. The text diff, then what changed in the answers.

Run:  uv run python labs/prompt-chain/done/prompt_diff.py write v1 v2 [--provider openai]
The old version's answers come from the cache; only the new version costs anything.
"""

from __future__ import annotations

import argparse
import difflib
import os
import textwrap

import facts
from calls import Caller
from chain import run_chain
from promptfiles import PROMPTS, chain_versions, load_prompt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("step", choices=["extract", "decide", "write"])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--provider", default=None, choices=["anthropic", "openai"])
    args = ap.parse_args(argv)
    provider = args.provider or os.environ.get("LLM_PROVIDER", "anthropic")

    old, new = load_prompt(args.step, args.old), load_prompt(args.step, args.new)
    print(f"=== prompt diff: {old.id} -> {new.id} ===")
    for line in difflib.unified_diff((PROMPTS / f"{old.id}.md").read_text().splitlines(),
                                     (PROMPTS / f"{new.id}.md").read_text().splitlines(),
                                     f"prompts/{old.id}.md", f"prompts/{new.id}.md", lineterm="", n=1):
        print(line)

    base = chain_versions()
    callers = {v: Caller(provider=provider) for v in (args.old, args.new)}
    runs = {v: [run_chain(callers[v], c, {**base, args.step: v}) for c in facts.cases()] for v in callers}

    print(f"\n=== answers: {old.id} -> {new.id} (other steps: "
          + ", ".join(f"{s}.{v}" for s, v in base.items() if s != args.step) + ") ===")
    changed = 0
    for a, b in zip(runs[args.old], runs[args.new]):
        if (a["decision"], a["reply"]) == (b["decision"], b["reply"]):
            continue
        changed += 1
        print(f"\n{a['ticket_id']}  {a['decision']} -> {b['decision']}  "
              f"problems: {', '.join(a['problems']) or 'none'} -> {', '.join(b['problems']) or 'none'}")
        print(textwrap.indent(textwrap.fill(a["reply"], 94), f"  {args.old}  "))
        print(textwrap.indent(textwrap.fill(b["reply"], 94), f"  {args.new}  "))

    def clean(v: str) -> int:
        return sum(not r["problems"] for r in runs[v])

    gate = {"extract": "gate:order", "decide": "gate:citation", "write": "gate:reply"}[args.step]

    def retries(v: str) -> int:  # how often this step's gate had to send it back
        return sum(s["step"] == gate and str(s.get("result", "")).startswith("retry")
                   for r in runs[v] for s in r["steps"])

    def words(v: str) -> float:
        return sum(len(r["reply"].split()) for r in runs[v]) / len(runs[v])

    print(f"\n{changed} of {len(runs[args.new])} answers changed · clean {clean(args.old)}/10 -> {clean(args.new)}/10 · "
          f"{gate} retries {retries(args.old)} -> {retries(args.new)} · "
          f"words per reply {words(args.old):.0f} -> {words(args.new):.0f}")
    print(f"{args.old}: {callers[args.old].summary()}\n{args.new}: {callers[args.new].summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
