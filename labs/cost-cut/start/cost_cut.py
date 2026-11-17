"""Lab (your copy, with TODO 1-4): cut a workload's cost in half with caching and a smaller model.

Run the steps in order. Each one saves what it measured, and `table` compares them.

  uv run python labs/cost-cut/start/cost_cut.py baseline   # 1. large model, long policy prompt
  uv run python labs/cost-cut/start/cost_cut.py cache      # 2. + prompt caching of the policy prompt
  uv run python labs/cost-cut/start/cost_cut.py route      # 3. + easy questions go to the small model
  uv run python labs/cost-cut/start/cost_cut.py final      # 4. + a local cache for exact repeats
  uv run python labs/cost-cut/start/cost_cut.py table      # 5. before/after table and quality check
  uv run python labs/cost-cut/start/cost_cut.py spot       #    answers side by side, for your own eyes

Options: --provider openai, --limit N (default 20 questions), --fresh (call the API
again instead of replaying the saved run, which costs nothing).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # the repo root, where shopkart/ lives

from shopkart import budget, data  # noqa: E402
from shopkart.llm import LLM, LLMError, Result, SchemaError  # noqa: E402
from shopkart.pricing import USD_TO_INR  # noqa: E402

LAB = Path(__file__).resolve().parents[1]
SYSTEM = (LAB / "policies.md").read_text(encoding="utf-8")  # the long, stable prefix
ANSWER_KEY = json.loads((LAB / "answer_key.json").read_text(encoding="utf-8"))
RUNS = budget.LEDGER_DIR / "cost-cut"  # saved runs (gitignored)

MODELS = {
    "anthropic": {"small": "claude-haiku-5-5", "large": "claude-sonnet-5-5"},
    "openai": {"small": "gpt-6-luna", "large": "gpt-6.2-sol"},
}
SHORT = {"claude-haiku-5-5": "haiku", "claude-sonnet-5-5": "sonnet", "gpt-6-luna": "luna", "gpt-6.2-sol": "sol"}
MAX_TOKENS = 250  # a safety net: the prompt asks for one to three sentences
STEPS = ["baseline", "cache", "route", "final"]
TITLES = {"baseline": "1. baseline (large model)", "cache": "2. + prompt caching",
          "route": "3. + routing easy -> small", "final": "4. + local response cache"}


# --------------------------------------------------------------------------
# Answering: one call, the policy sheet as the system prompt
# --------------------------------------------------------------------------


def answer(llm: LLM, question: str, cache: bool) -> Result:
    """Answer one question from the policy sheet. Stable content first (the
    system prompt), changing content last (the question)."""
    # TODO 1 (step 2): when `cache` is True, ask for the system prompt to be cached.
    #   llm.complete() has a `cache_system` flag: on Claude it adds cache_control to
    #   the system prompt. OpenAI caches long prompts on its own, so it ignores it.
    return llm.complete(question, system=SYSTEM, max_tokens=MAX_TOKENS)


# --------------------------------------------------------------------------
# Routing: a cheap step decides how hard the question is
# --------------------------------------------------------------------------

ROUTER_SYSTEM = (
    "You label questions sent to ShopKart's support chat by how hard they are to answer.\n"
    "easy: one fact from one policy, such as a return window, delivery time or charge, how to "
    "track, cancel or change an address, how long a refund takes, payment limits, support hours.\n"
    "hard: needs several rules together, or is about money that went wrong (a refund that has "
    "not arrived, a double charge, a price drop, EMI), damage, defects, opened items, warranty, "
    "or an exception.\n"
    "If you are not sure, answer unsure."
)


class Route(BaseModel):
    level: Literal["easy", "hard", "unsure"]


def route(small: LLM, question: str) -> tuple[str, Result | None]:
    """'easy' or 'hard', and the classifier call (for its cost). When unsure, go big."""
    # TODO 2 (step 3): ask the SMALL model to classify the question.
    #   - small.complete(question, system=ROUTER_SYSTEM, schema=Route, max_tokens=20)
    #   - result.parsed.level is "easy", "hard" or "unsure"
    #   - only "easy" goes to the small model; "unsure" counts as "hard"
    #   - if the answer still isn't valid JSON (SchemaError), go big too: return "hard", None
    raise NotImplementedError("TODO 2: route()")


# --------------------------------------------------------------------------
# A local response cache: exact repeats skip the model completely
# --------------------------------------------------------------------------

ORDER_ID = re.compile(r"\bSK\d{5}\b", re.IGNORECASE)


class ResponseCache:
    """Answers we already gave, keyed by the cleaned-up question.

    In production this is Redis or similar. Only general answers go in: a
    question with an order number is personal and always goes to the model.
    Clear it whenever the policy changes, or customers get yesterday's rules.
    """

    def __init__(self, path: Path | None = None):
        self.path = path
        self.answers: dict[str, str] = {}

    @staticmethod
    def key(question: str) -> str:
        """Lower case, no punctuation, single spaces: "How do I cancel?" == "how do i cancel"."""
        # TODO 3a (step 4): lower case, punctuation replaced by spaces, single spaces.
        return question

    def cacheable(self, question: str) -> bool:
        # TODO 3b (step 4): a question with an order number (ORDER_ID) is personal: never cache it.
        return True

    def get(self, question: str) -> str | None:
        return self.answers.get(self.key(question)) if self.cacheable(question) else None

    def put(self, question: str, text: str) -> None:
        if self.cacheable(question):
            self.answers[self.key(question)] = text

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.answers, indent=2, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# Running one step over the slice
# --------------------------------------------------------------------------


def load_slice(limit: int) -> list[dict]:
    return data.load_workload()[:limit]


def _row(q: dict, result: Result | None, path: str, router: Result | None = None) -> dict:
    """What one question cost: the answer call plus the router call, if any."""
    calls = [r for r in (result, router) if r is not None]
    return {
        "id": q["id"], "question": q["question"], "cluster": q["cluster"], "label": q["difficulty"],
        "path": path, "model": result.model if result else "-",
        "calls": len(calls),
        "input": sum(r.input_tokens for r in calls),
        "cache_write": sum(r.cache_write_tokens for r in calls),
        "cache_read": sum(r.cache_read_tokens for r in calls),
        "output": sum(r.output_tokens for r in calls),
        "cost": sum(r.cost_usd for r in calls),
        "router_cost": router.cost_usd if router else 0.0,
        "answer": result.text.strip() if result else "",
        "stop": result.stop_reason if result else "",
    }


def run_step(step: str, provider: str, questions: list[dict], *, clients: dict[str, LLM] | None = None,
             cache_path: Path | None = None, out=print) -> dict:
    """Run one step of the lab over the questions and return its record."""
    clients = clients or {size: LLM(provider, model) for size, model in MODELS[provider].items()}
    large, small = clients["large"], clients["small"]
    use_prompt_cache = step != "baseline"
    responses = ResponseCache(cache_path) if step == "final" else None

    out(f"{TITLES[step]} · {provider} · {len(questions)} questions")
    out(f"{'#':>3} {'q':<4} {'path':<7} {'in':>6} {'write':>6} {'read':>6} {'out':>4}  {'cost $':>9}  question")
    rows: list[dict] = []
    failed = 0
    start = time.monotonic()
    for i, q in enumerate(questions, 1):
        text = q["question"]
        try:
            if responses is not None and (cached := responses.get(text)) is not None:
                row = _row(q, None, "cache")
                row["answer"] = cached
            elif step in ("route", "final"):
                level, router = route(small, text)
                llm = small if level == "easy" else large
                result = answer(llm, text, cache=True)
                row = _row(q, result, SHORT[llm.model], router)
                if responses is not None:
                    responses.put(text, row["answer"])
            else:
                result = answer(large, text, cache=use_prompt_cache)
                row = _row(q, result, SHORT[large.model])
        except budget.BudgetExceeded as exc:
            out(f"\n{exc}")
            break
        except LLMError as exc:
            out(f"{i:>3} FAILED: {exc}")
            failed += 1
            continue
        rows.append(row)
        out(f"{i:>3} {row['label']:<4} {row['path']:<7} {row['input']:>6} {row['cache_write']:>6} "
            f"{row['cache_read']:>6} {row['output']:>4}  {row['cost']:>9.6f}  {text[:44]}")
    seconds = time.monotonic() - start
    if responses is not None:
        responses.save()

    record = {"step": step, "provider": provider, "limit": len(questions), "rows": rows,
              "failed": failed, "seconds": round(seconds, 2), **totals(rows)}
    out(summary_line(record))
    return record


def totals(rows: list[dict]) -> dict:
    keys = ("calls", "input", "cache_write", "cache_read", "output", "cost")
    return {k: sum(r[k] for r in rows) for k in keys}


def summary_line(rec: dict) -> str:
    paths: dict[str, int] = {}
    for r in rec["rows"]:
        paths[r["path"]] = paths.get(r["path"], 0) + 1
    split = ", ".join(f"{n} {p}" for p, n in paths.items())
    return (f"\n{rec['step']}: {len(rec['rows'])} answered ({split}) · {rec['calls']} API calls · "
            f"${rec['cost']:.6f} (₹{rec['cost'] * USD_TO_INR:.4f}) · {rec['seconds']:.1f}s\n"
            f"tokens: {rec['input']} input, {rec['cache_write']} cache write, "
            f"{rec['cache_read']} cache read, {rec['output']} output")


# --------------------------------------------------------------------------
# Comparing: before/after table, quality, and what batch would cost
# --------------------------------------------------------------------------


def saving(baseline_cost: float, cost: float) -> float:
    """How much cheaper than the baseline, as a fraction (0.5 = half the cost)."""
    # TODO 4 (step 5): 1 - cost / baseline_cost (and 0.0 if the baseline cost nothing).
    raise NotImplementedError("TODO 4: saving()")


def _norm(text: str) -> str:
    text = text.lower().replace("–", "-").replace("—", "-").replace(" ", " ").replace(" ", " ")
    text = re.sub(r"(\d)\s*(?:to|-)\s*(\d)", r"\1-\2", text)  # "5 to 7", "5 – 7" -> "5-7"
    return text


def key_facts_ok(cluster: str, answer_text: str) -> bool:
    """A quick automatic check: does the answer state the key facts for its question type?"""
    key = ANSWER_KEY.get(cluster)
    if key is None:
        return True
    text = _norm(answer_text)
    return (all(re.search(p, text) for p in key["must"])
            and not any(re.search(p, text) for p in key.get("must_not", [])))


def quality(rec: dict) -> tuple[int, int]:
    rows = rec["rows"]
    return sum(key_facts_ok(r["cluster"], r["answer"]) for r in rows), len(rows)


def table(records: dict[str, dict], out=print) -> None:
    base = records.get("baseline")
    if base is None:
        out("Run the baseline first.")
        return
    provider = base["provider"]
    out(f"Before/after · {provider} · {base['limit']} questions "
        f"(large {MODELS[provider]['large']}, small {MODELS[provider]['small']})\n")
    out(f"{'step':<27}{'calls':>6}{'input':>8}{'c.write':>8}{'c.read':>8}{'output':>7}"
        f"{'cost $':>10}{'cost ₹':>8}{'time':>7}{'cheaper':>9}{'facts ok':>10}")
    for step in STEPS:
        rec = records.get(step)
        if rec is None:
            out(f"{TITLES[step]:<27}{'(not run)':>14}")
            continue
        ok, n = quality(rec)
        out(f"{TITLES[step]:<27}{rec['calls']:>6}{rec['input']:>8}{rec['cache_write']:>8}{rec['cache_read']:>8}"
            f"{rec['output']:>7}{rec['cost']:>10.5f}{rec['cost'] * USD_TO_INR:>8.3f}{rec['seconds']:>6.1f}s"
            f"{saving(base['cost'], rec['cost']):>9.0%}{f'{ok}/{n}':>10}")

    last = next((records[s] for s in reversed(STEPS) if s in records), base)
    cut = saving(base["cost"], last["cost"])
    out(f"\nTarget: at least 50% cheaper. Result: {cut:.0%} cheaper -> "
        f"{'target met' if cut >= 0.5 else 'not yet'}.")
    if provider == "openai" and base["cache_read"]:
        out(f"OpenAI cached {base['cache_read']} tokens in the baseline already: "
            "it caches long prompts (1,024+ tokens) on its own.")

    # Quality: which answers lost a key fact compared with the baseline?
    base_ok = {r["id"]: key_facts_ok(r["cluster"], r["answer"]) for r in base["rows"]}
    worse = [r for r in last["rows"] if base_ok.get(r["id"]) and not key_facts_ok(r["cluster"], r["answer"])]
    out(f"Quality: {len(worse)} answer(s) lost a key fact compared with the baseline.")
    for r in worse:
        out(f"  {r['id']} ({r['path']}): {r['question']}\n      -> {r['answer'][:160]}")

    # Batch: mention only, no live run.
    paid = sum(r["cost"] for r in last["rows"])
    out(f"\nBatch API (not run here): the same calls at half price, about ${paid / 2:.5f}, "
        "with results within 24 hours.\nGood for nightly jobs nobody waits for; never for a customer in the chat.")


def spot(records: dict[str, dict], out=print) -> None:
    base, last = records.get("baseline"), records.get("final") or records.get("route")
    if not base or not last:
        out("Run baseline and final first.")
        return
    by_id = {r["id"]: r for r in last["rows"]}
    for b in base["rows"]:
        f = by_id.get(b["id"])
        if f is None:
            continue
        mark = lambda r: "ok " if key_facts_ok(r["cluster"], r["answer"]) else "MISS"  # noqa: E731
        out(f"{b['id']} [{b['label']}] {b['question']}")
        out(f"   {mark(b)} {b['path']:<7} {b['answer'][:150]}")
        out(f"   {mark(f)} {f['path']:<7} {f['answer'][:150]}\n")


# --------------------------------------------------------------------------
# Saved runs: replay costs nothing
# --------------------------------------------------------------------------


def run_path(provider: str, step: str) -> Path:
    return RUNS / provider / f"{step}.json"


def load_records(provider: str) -> dict[str, dict]:
    recs = {}
    for step in STEPS:
        p = run_path(provider, step)
        if p.exists():
            recs[step] = json.loads(p.read_text())
    return recs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=STEPS + ["table", "spot"])
    parser.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    parser.add_argument("--limit", type=int, default=20, help="how many workload questions (default 20)")
    parser.add_argument("--fresh", action="store_true", help="call the API again instead of replaying")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s] %(message)s")
    provider = args.provider or __import__("os").environ.get("LLM_PROVIDER", "anthropic")

    if args.step == "table":
        table(load_records(provider))
        return 0
    if args.step == "spot":
        spot(load_records(provider))
        return 0

    path = run_path(provider, args.step)
    if path.exists() and not args.fresh:
        rec = json.loads(path.read_text())
        if rec["limit"] == args.limit:
            print("\n".join(rec["lines"]))
            print(f"(replayed from {path.relative_to(budget.LEDGER_DIR.parent)}: no API calls, $0. "
                  "Add --fresh to run it again.)")
            return 0

    lines: list[str] = []

    def out(line: str = "") -> None:
        print(line, flush=True)
        lines.append(line)

    rec = run_step(args.step, provider, load_slice(args.limit), out=out,
                   cache_path=RUNS / provider / "response-cache.json")
    if rec["failed"]:
        print(f"{rec['failed']} question(s) failed: not saved, so the table won't use this run.")
        return 1
    rec["lines"] = lines
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n")
    print(f"Today: ${budget.spent_today():.6f} of ${budget.daily_budget_usd():.2f} daily budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
