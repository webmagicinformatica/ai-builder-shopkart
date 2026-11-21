"""The eval report: does the document assistant actually work? Measured, not eyeballed.

Two test sets:
  data/golden/rag-50.jsonl   the 50 policy questions of the golden set. All answerable, each
                             labelled with the section the answer lives in.
  solution/idk-10.jsonl      10 questions our documents do NOT cover. The right reply is "I don't know".

Three layers of numbers, cheapest first:
  1. retrieval (free)    hit@1, hit@5, MRR: is the right section in the top 5 the model reads?
  2. answers (paid)      answered, right source cited, expected numbers present, handed over and why
  3. faithfulness (paid) a small judge splits each answer into claims and checks each one
                         against the chunks it cites
Plus the "I don't know" score on the 10, and the acceptance criteria from the brief.

Run:  uv run python capstone/doc-assistant/solution/evaluate.py --estimate     (free: what it would cost)
      uv run python capstone/doc-assistant/solution/evaluate.py --limit 5      (a small paid slice first)
      uv run python capstone/doc-assistant/solution/evaluate.py                (all 60, cached: re-runs are free)
      uv run python capstone/doc-assistant/solution/evaluate.py --retrieval-only
Writes capstone/doc-assistant/out/report.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import assistant  # noqa: E402  (puts the labs and the repo root on sys.path)
import ask  # noqa: E402
import judge as judge_mod  # noqa: E402
import measure  # noqa: E402  (the hybrid lab: is_relevant, grade)
from shopkart import budget  # noqa: E402
from shopkart.llm import LLM  # noqa: E402
from shopkart.pricing import PRICES_PER_MILLION_USD, cost_usd  # noqa: E402

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
RAG_50 = assistant.REPO / "data" / "golden" / "rag-50.jsonl"
IDK_10 = HERE / "idk-10.jsonl"
OUT = PROJECT / "out"
JUDGE_CACHE = assistant.REPO / ".shopkart" / "cache" / "capstone-judge"
RERANK_READS = 20  # the reranker reads 20, the model gets the top 5

# The acceptance criteria from the brief (README.md). The report marks each one.
TARGETS = {
    "hit@5": 45,             # of 50: the right section is in the top 5
    "answered_right": 40,    # of 50: answered, with the right source, and the expected numbers
    "faithful_claims": 0.90,  # share of claims the judge finds supported
    "idk": 9,                # of 10: honest "I don't know"
    "cost_usd": 0.05,        # one full run, from an empty cache
}


def load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


@dataclass
class Row:
    case: dict
    kind: str  # "answerable" or "idk"
    rank: int | None = None  # rank of the right section in the reranked 20 (answerable only)
    best: float = 0.0  # best reranker score
    reply: ask.Reply | None = None
    grade: dict = field(default_factory=dict)
    claims: list[dict] | None = None
    cost: float = 0.0
    calls: int = 0
    cached: int = 0

    @property
    def id(self) -> str:
        return self.case["id"]

    @property
    def handover_why(self) -> str:
        r = self.reply
        if r is None or r.kind == "answer":
            return ""
        if r.result is None:
            return "score floor (no model call)"
        return "check failed" if r.reason.startswith("check") else "model: answerable = false"

    @property
    def faithful(self) -> bool | None:
        if self.claims is None:
            return None
        return all(c["supported"] for c in self.claims)

    @property
    def passed(self) -> bool:
        if self.kind == "idk":
            return self.reply is not None and self.reply.kind == "handover"
        g = self.grade
        return bool(g.get("answered") and g.get("source") and g.get("facts") and self.faithful is not False)


# --------------------------------------------------------------------------
# Running the cases
# --------------------------------------------------------------------------


def run_case(bot: assistant.DocAssistant, case: dict, kind: str, judge_llm: LLM | None,
             judge_cache: Path | None = JUDGE_CACHE) -> Row:
    row = Row(case, kind)
    q = case["question"]
    hits20 = bot.search.search(q, "rerank", k=RERANK_READS)
    row.best = hits20[0][1] if hits20 else 0.0
    if kind == "answerable":
        row.rank = measure.first_rank(hits20, case)
    reply = assistant.answer(q, hits20[: bot.k], bot)
    row.reply = reply
    row.cost += reply.cost_usd
    if reply.result is not None:
        row.calls += not reply.cached
        row.cached += reply.cached
    if kind == "answerable":
        row.grade = measure.grade(reply, case)
    if reply.kind == "answer" and judge_llm is not None:
        verdict, result, cached = judge_mod.judge(judge_llm, reply, bot.index.by_id, judge_cache)
        row.claims = [c.model_dump() for c in verdict.claims]
        row.cost += 0.0 if cached else result.cost_usd
        row.calls += not cached
        row.cached += cached
    return row


def estimate(bot: assistant.DocAssistant, cases: list[tuple[dict, str]]) -> None:
    """What a full run would cost, before spending anything: retrieval is free, so we build the
    real prompts and count about 4 characters per token."""
    model = bot.llm.model
    price_in, price_out = PRICES_PER_MILLION_USD[model]
    calls, tok_in, skipped = 0, 0, 0
    for case, _ in cases:
        hits = bot.retrieve(case["question"])
        if not hits or hits[0][1] < bot.min_score:
            skipped += 1
            continue
        calls += 1
        tok_in += (len(ask.SYSTEM) + len(ask.build_prompt(case["question"], hits))) // 4 + 300  # + schema
    answer_out, judge_in, judge_out = 120 * calls, 700 * calls, 180 * calls  # typical sizes from a small run
    usd = cost_usd(model, tok_in + judge_in, answer_out + judge_out)
    print(f"Estimate on {model} (${price_in}/${price_out} per million tokens):")
    print(f"  {len(cases)} questions: {calls} answer calls + up to {calls} judge calls, "
          f"{skipped} skipped by the score floor (no call)")
    print(f"  about {tok_in + judge_in:,} input and {answer_out + judge_out:,} output tokens → about ${usd:.4f}")
    print("  Re-runs read the disk cache: $0.")


# --------------------------------------------------------------------------
# The numbers and the report
# --------------------------------------------------------------------------


def summarise(rows: list[Row]) -> dict:
    ans = [r for r in rows if r.kind == "answerable"]
    idk = [r for r in rows if r.kind == "idk"]
    ranks = [r.rank for r in ans]
    m = measure.retrieval_metrics(ranks) if ans else {}
    answered = [r for r in ans if r.reply and r.reply.kind == "answer"]
    judged = [r for r in answered if r.claims is not None]
    n_claims = sum(len(r.claims) for r in judged)
    n_supported = sum(sum(c["supported"] for c in r.claims) for r in judged)
    floor_skips = [r for r in rows if r.reply and r.reply.result is None]
    return {
        "n": len(ans), "n_idk": len(idk),
        "hit@1": m.get("hit@1", 0), "hit@5": m.get("hit@5", 0), "mrr": m.get("mrr", 0.0),
        "answered": len(answered),
        "right_source": sum(bool(r.grade.get("source")) for r in ans),
        "facts": sum(bool(r.grade.get("facts")) for r in ans),
        "answered_right": sum(bool(r.grade.get("answered") and r.grade.get("source") and r.grade.get("facts"))
                              for r in ans),
        "judged": len(judged), "claims": n_claims, "supported": n_supported,
        "faithful_answers": sum(bool(r.faithful) for r in judged),
        "faithful_claims": n_supported / n_claims if n_claims else 0.0,
        "false_handover": [r for r in ans if r.reply and r.reply.kind == "handover"],
        "idk": sum(r.passed for r in idk),
        "idk_floor": sum(1 for r in idk if r.handover_why.startswith("score")),
        "idk_model": sum(1 for r in idk if r.handover_why.startswith("model")),
        "idk_check": sum(1 for r in idk if r.handover_why.startswith("check")),
        "idk_answered": [r for r in idk if r.reply and r.reply.kind == "answer"],
        "passed": sum(r.passed for r in ans), "floor_skips": len(floor_skips),
        "cost": sum(r.cost for r in rows), "calls": sum(r.calls for r in rows),
        "cached": sum(r.cached for r in rows),
        "worst_answerable_score": min((r.best for r in ans), default=0.0),
    }


def need(target: int, of: int, n: int) -> int:
    """A target like 45/50, scaled to a smaller slice (--limit): 45/50 of 5 questions is 5."""
    return math.ceil(target * n / of)


def criteria(s: dict, full_cost: float | None) -> list[tuple[str, str, bool]]:
    out = []
    n, ni = s["n"], s["n_idk"]
    if n:
        hit, right = need(TARGETS["hit@5"], 50, n), need(TARGETS["answered_right"], 50, n)
        out += [
            (f"Right section in the top 5 ≥ {hit}/{n}", f"{s['hit@5']}/{n}", s["hit@5"] >= hit),
            (f"Answered with the right source and facts ≥ {right}/{n}", f"{s['answered_right']}/{n}",
             s["answered_right"] >= right),
        ]
        if s["claims"]:
            out.append((f"Claims supported by their source ≥ {TARGETS['faithful_claims']:.0%}",
                        f"{s['faithful_claims']:.1%}", s["faithful_claims"] >= TARGETS["faithful_claims"]))
    if ni:
        idk = need(TARGETS["idk"], 10, ni)
        out.append((f"Honest \"I don't know\" ≥ {idk}/{ni}", f"{s['idk']}/{ni}", s["idk"] >= idk))
    if full_cost is not None:
        out.append((f"One full run ≤ ${TARGETS['cost_usd']:.2f}", f"${full_cost:.4f}", full_cost <= TARGETS["cost_usd"]))
    return out


def print_summary(s: dict, rows: list[Row], model: str, crit: list) -> None:
    n, ni = s["n"], s["n_idk"]
    if n:
        print(f"\nRetrieval (hybrid + rerank, free) on {n} answerable questions")
        print(f"  right section first {s['hit@1']}/{n} · in the top 5 {s['hit@5']}/{n} · MRR {s['mrr']:.3f}")
        print(f"  lowest best-chunk score of an answerable question: {s['worst_answerable_score']:.3f} "
              f"(score floor {assistant.MIN_SCORE})")
        print(f"\nAnswers ({model})")
        print(f"  answered {s['answered']}/{n} · right source cited {s['right_source']}/{n} · "
              f"expected numbers present {s['facts']}/{n}")
        if s["judged"]:
            print(f"  faithfulness (judge): {s['supported']}/{s['claims']} claims supported "
                  f"({s['faithful_claims']:.1%}) · {s['faithful_answers']}/{s['judged']} answers fully supported")
        print(f"  handed over although answerable: {len(s['false_handover'])}")
    if ni:
        print(f"\n\"I don't know\" on {ni} questions the documents don't cover")
        print(f"  handed over {s['idk']}/{ni}: {s['idk_floor']} by the score floor (no call), "
              f"{s['idk_model']} by the model (answerable = false), {s['idk_check']} by the grounding check")
    fails = [r for r in rows if not r.passed]
    print(f"\nFailures ({len(fails)}):")
    for r in fails:
        print(f"  {r.id:7} {failure_note(r)}")
    print("\nAcceptance criteria")
    for name, value, ok in crit:
        print(f"  {'✓' if ok else '✗'} {name:52} {value}")


def failure_note(r: Row) -> str:
    q = r.case["question"][:52]
    if r.kind == "idk":
        return f"answered a question the documents don't cover · {q}"
    if r.reply.kind == "handover":
        return f"handed over ({r.handover_why}) · rank {r.rank or '-'} · {q}"
    bits = []
    if not r.grade.get("source"):
        bits.append(f"cited {', '.join(r.reply.cited)}, expected {r.case['source_doc']}§{r.case['section']}")
    if not r.grade.get("facts"):
        bits.append(f"missing numbers from: {r.case['expected_answer'][:50]!r}")
    if r.faithful is False:
        bad = [c["claim"] for c in r.claims if not c["supported"]]
        bits.append(f"unsupported: {'; '.join(bad)[:70]}")
    return " · ".join(bits) + f" · {q}"


def write_report(path: Path, s: dict, rows: list[Row], model: str, crit: list, seconds: float) -> None:
    n, ni = s["n"], s["n_idk"]
    L = [f"# Eval report: ShopKart document assistant",
         "",
         f"Model `{model}` · retrieval hybrid (BM25 + vectors) + local reranker, top 5 · score floor {assistant.MIN_SCORE} · "
         f"judge rubric {judge_mod.JUDGE_VERSION} · {seconds:.0f} s · this run ${s['cost']:.4f} "
         f"({s['calls']} paid calls, {s['cached']} from cache)",
         "",
         "## Acceptance criteria", "", "| Criterion | Result | |", "|---|---|---|"]
    L += [f"| {name} | {value} | {'pass' if ok else 'FAIL'} |" for name, value, ok in crit]
    if n:
        L += ["", f"## Answerable questions ({n}, data/golden/rag-50.jsonl)", "",
              "| Metric | Value |", "|---|---|",
              f"| Right section ranked first (hit@1) | {s['hit@1']}/{n} |",
              f"| Right section in the top 5 (hit@5) | {s['hit@5']}/{n} |",
              f"| Mean reciprocal rank | {s['mrr']:.3f} |",
              f"| Answered | {s['answered']}/{n} |",
              f"| Right source cited | {s['right_source']}/{n} |",
              f"| Expected numbers present | {s['facts']}/{n} |",
              f"| Claims supported (judge) | {s['supported']}/{s['claims']} ({s['faithful_claims']:.1%}) |",
              f"| Answers fully supported (judge) | {s['faithful_answers']}/{s['judged']} |",
              f"| Handed over although answerable | {len(s['false_handover'])} |",
              f"| **Passed every check** | **{s['passed']}/{n}** |"]
    if ni:
        L += ["", f"## Questions the documents don't cover ({ni}, solution/idk-10.jsonl)", "",
              f"Handed over {s['idk']}/{ni}: {s['idk_floor']} by the score floor (no model call), "
              f"{s['idk_model']} by the model (answerable = false), {s['idk_check']} by the grounding check."]
    fails = [r for r in rows if not r.passed]
    L += ["", f"## Every failure ({len(fails)})", ""]
    L += [f"- `{r.id}` {failure_note(r)}" for r in fails] or ["None."]
    L += ["", "## Every question", "", "| id | rank | best score | result | why / sources |", "|---|---|---|---|---|"]
    for r in rows:
        res = "pass" if r.passed else "FAIL"
        what = ", ".join(r.reply.cited) if r.reply.kind == "answer" else f"handover: {r.handover_why}"
        L.append(f"| {r.id} | {r.rank or '-'} | {r.best:.3f} | {res} | {what} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate the document assistant and write the report.")
    ap.add_argument("--estimate", action="store_true", help="print what a full run would cost, spend nothing")
    ap.add_argument("--limit", type=int, default=None, help="only the first N of each set")
    ap.add_argument("--retrieval-only", action="store_true", help="free: retrieval numbers only")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", type=Path, default=OUT / "report.md")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s] %(message)s")

    answerable = load(RAG_50)[: args.limit] if args.limit else load(RAG_50)
    idk = load(IDK_10)[: args.limit] if args.limit else load(IDK_10)
    cases = [(c, "answerable") for c in answerable] + [(c, "idk") for c in idk]
    llm = LLM(args.provider, args.model)
    bot = assistant.DocAssistant(llm)
    bot.retrieve("warm up")  # load the embedder and the reranker before timing

    if args.estimate:
        estimate(bot, cases)
        return 0
    if args.retrieval_only:
        rows = []
        for c in answerable:
            hits = bot.search.search(c["question"], "rerank", k=RERANK_READS)
            rows.append(measure.first_rank(hits, c))
        m = measure.retrieval_metrics(rows)
        print(f"Retrieval on {m['n']}: hit@1 {m['hit@1']} · hit@5 {m['hit@5']} · MRR {m['mrr']:.3f} · "
              f"found in the 20 the reranker reads {sum(r is not None for r in rows)}/{m['n']}")
        return 0

    t0 = time.monotonic()
    judge_llm = None if args.no_judge else llm
    rows: list[Row] = []
    print(f"Evaluating {len(answerable)} answerable + {len(idk)} \"I don't know\" questions on {llm.model}")
    try:
        for case, kind in cases:
            row = run_case(bot, case, kind, judge_llm)
            rows.append(row)
            src = "cache" if row.cached and not row.calls else (f"${row.cost:.5f}" if row.calls else "no call")
            print(f"  {row.id:7} {'pass' if row.passed else 'FAIL'}  "
                  f"{'answered' if row.reply.kind == 'answer' else 'handover':8} ({src})")
    except budget.BudgetExceeded as exc:
        print(str(exc), file=sys.stderr)
        return 2

    s = summarise(rows)
    # What one full run costs from an empty cache: every cached answer and verdict remembers its cost.
    full = sum(r.reply.result.cost_usd for r in rows if r.reply and r.reply.result is not None)
    full += judge_costs(rows, bot)
    crit = criteria(s, full if not args.limit else None)
    print_summary(s, rows, llm.model, crit)
    write_report(args.out, s, rows, llm.model, crit, time.monotonic() - t0)
    print(f"\nWrote {args.out.relative_to(assistant.REPO)} · this run ${s['cost']:.6f} "
          f"({s['calls']} paid calls, {s['cached']} from cache) · a full run from empty: ${full:.4f}")
    return 0


def judge_costs(rows: list[Row], bot: assistant.DocAssistant) -> float:
    """The judge's cost per answer, read back from its cache (cached calls cost $0 now, not then)."""
    total = 0.0
    for r in rows:
        if r.claims is None:
            continue
        verdict, result, _ = judge_mod.judge(bot.llm, r.reply, bot.index.by_id, JUDGE_CACHE)
        total += result.cost_usd
    return total


if __name__ == "__main__":
    sys.exit(main())
