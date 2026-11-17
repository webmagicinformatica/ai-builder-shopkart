"""Step 6: the mega-prompt and the chain, on the same 10 tickets, in one table.

Run:  uv run python labs/prompt-chain/done/compare.py [--use write=v2] [--provider openai]
Answers come from the cache when mega.py and chain.py already ran, so this is free.
"""

from __future__ import annotations

import argparse
import os

import facts
from calls import Caller
from chain import run_chain
from mega import run_mega
from promptfiles import chain_versions
from shopkart.pricing import usd_to_inr


SHORT = {"broken format": "format", "says window closed": "wrong window", "wrong window": "wrong window",
         "wrong decision": "wrong decision", "too long": "too long", "reply not in": "language"}


def short(problem: str) -> str:
    return next((v for k, v in SHORT.items() if problem.startswith(k)), problem)


def cell(row: dict) -> str:
    if not row["problems"]:
        return f"{row['decision']:<9}✓"
    return f"{row['decision'] or '?':<9}✗ " + ", ".join(dict.fromkeys(short(p) for p in row["problems"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provider", default=None, choices=["anthropic", "openai"])
    ap.add_argument("--use", action="append", default=[], metavar="STEP=VERSION")
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args(argv)
    provider = args.provider or os.environ.get("LLM_PROVIDER", "anthropic")

    mega_caller = Caller(provider=provider, fresh=args.fresh)
    chain_caller = Caller(provider=provider, fresh=args.fresh)
    versions = chain_versions(args.use)
    rows = [(c, run_mega(mega_caller, c), run_chain(chain_caller, c, versions)) for c in facts.cases()]

    W = 42
    print(f"{'ticket':<10} {'expected':<9} {'mega.v1':<{W}} chain: {' → '.join(f'{s}.{v}' for s, v in versions.items())}")
    print("-" * 100)
    for case, m, ch in rows:
        print(f"{case['ticket_id']:<10} {case['expected']:<9} {cell(m):<{W}} {cell(ch)}")
    print("-" * 100)

    def score(i: int) -> str:
        return f"{sum(not r[i]['problems'] for r in rows)}/{len(rows)}"

    def right(i: int) -> str:
        return f"{sum(r[i]['decision'] == r[0]['expected'] for r in rows)}/{len(rows)}"

    def fmt(i: int) -> str:
        return f"{sum(r[i]['format_ok'] for r in rows)}/{len(rows)}"

    def tokens(caller: Caller) -> str:
        return f"{sum(a.input_tokens for a in caller.answers):,} in / {sum(a.output_tokens for a in caller.answers):,} out"

    def cost(caller: Caller) -> str:  # what these calls cost when they were made, cached or not
        usd = sum(a.list_cost_usd for a in caller.answers)
        return f"${usd:.4f} (₹{usd_to_inr(usd):.2f})"

    def latency(caller: Caller) -> str:
        return f"{sum(a.latency_s for a in caller.answers) / len(rows):.1f}s per ticket"

    for label, a, b in [("right decision", right(1), right(2)), ("valid format", fmt(1), fmt(2)),
                        ("no problems", score(1), score(2)),
                        ("calls", len(mega_caller.answers), len(chain_caller.answers)),
                        ("tokens", tokens(mega_caller), tokens(chain_caller)),
                        ("cost, 10 tickets", cost(mega_caller), cost(chain_caller)),
                        ("latency", latency(mega_caller), latency(chain_caller))]:
        print(f"{label:<20} {a!s:<{W}} {b}")
    print(f"\nmega: {mega_caller.summary()}\nchain: {chain_caller.summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
