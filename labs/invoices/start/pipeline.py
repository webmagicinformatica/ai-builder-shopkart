"""Part 2: the whole pipeline over a folder of invoices.

    intake (hash) -> extract (vision + schema) -> validate (rules) -> approve, or queue for a person

Run:
    uv run python labs/invoices/done/pipeline.py                    # all 8, Anthropic
    uv run python labs/invoices/done/pipeline.py inv-01 --provider openai
    uv run python labs/invoices/done/review.py list                 # then work the queue
    uv run python labs/invoices/done/score.py                       # field accuracy

The estimate runs first: if it's over --max-usd, nothing is sent.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks import validate  # noqa: E402
from extract import PROMPT_VERSION, estimate, extract, find  # noqa: E402
from review import ReviewQueue  # noqa: E402
from shopkart import budget, data  # noqa: E402
from shopkart.llm import DEFAULT_MODELS, LLM  # noqa: E402
from shopkart.pricing import usd_to_inr  # noqa: E402


def run(llm: LLM, files: list[Path], queue: ReviewQueue, use_cache: bool = True) -> dict[str, int]:
    counts = {"approved": 0, "review": 0, "duplicate": 0, "rejected": 0}
    spent = 0.0
    for f in files:
        ex = extract(llm, f, use_cache=use_cache)
        if ex.invoice is None:  # unreadable, or still invalid after one retry: a person types it in
            reasons = [f"extraction_failed: {ex.error}"]
            payload = None
        else:
            reasons = [str(issue) for issue in validate(ex.invoice, ex.sharpness)]
            payload = ex.invoice.model_dump()
        row_id, status, new = queue.store(file=f.name, sha256=ex.sha256, data=payload, reasons=reasons,
                                          model=ex.model, prompt_version=PROMPT_VERSION, cost_usd=ex.cost_usd)
        counts[status] += 1
        spent += ex.cost_usd
        cost = "cached" if ex.cached else f"${ex.cost_usd:.6f}"
        print(f"#{row_id:<3}{f.name:<34}{ex.input_tokens:>6} in{ex.output_tokens:>5} out {cost:>10}  "
              f"{'-> ' + status if new else '(already stored: ' + status + ')'}")
        if new and status != "approved":
            for reason in reasons:
                print(f"       {reason}")
    total = len(files)
    print(f"\n{total} invoice{'s' * (total != 1)}: {counts['approved']} straight through, "
          f"{counts['review']} to review, {counts['duplicate']} held as duplicates")
    print(f"This run: ${spent:.6f} (₹{usd_to_inr(spent):.4f}) on {llm.model} · "
          f"today ${budget.spent_today():.6f} of ${budget.daily_budget_usd():.2f}")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract, validate and route ShopKart's supplier invoices.")
    parser.add_argument("names", nargs="*", help="e.g. inv-01 inv-04 (default: all in data/invoices)")
    parser.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-usd", type=float, default=0.05, help="refuse to start above this estimate")
    parser.add_argument("--db", default=None)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s] %(message)s")

    files = [find(n) for n in args.names] or data.invoice_files()
    provider = args.provider or os.environ.get("LLM_PROVIDER", "anthropic")
    model = args.model or DEFAULT_MODELS[provider]
    est = sum(estimate(f, model)[1] for f in files)
    print(f"Estimate: {len(files)} invoice{'s' * (len(files) != 1)} on {model}, about ${est:.4f} (limit ${args.max_usd:.2f})\n")
    if est > args.max_usd:
        print("Over the limit: nothing sent. Fewer files, a smaller model, or raise --max-usd.")
        return 2

    run(LLM(provider, model), files, ReviewQueue(args.db), use_cache=not args.no_cache)
    return 0


if __name__ == "__main__":
    sys.exit(main())
