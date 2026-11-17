"""Measure it: does hybrid search + reranking actually find the right section more often?

Step 1, retrieval (free, no LLM): all 50 questions of the RAG golden set, four searches.
    hit@k   in how many questions the right section is in the top k
    MRR     mean reciprocal rank: 1 for first place, 1/2 for second, 1/3 ... 0 if missing
    found   is it anywhere in the list at all (top 50; for rerank, the 20 it reads)?
            Finding it is the search's job; the order inside the top 5 is the reranker's job.

Step 2, answers (paid, cached): 10 questions, answered twice with the Part 2 Copilot,
before (vector top 5) and after (hybrid + rerank top 5).

Run:  uv run python labs/rag-hybrid/start/measure.py                 (retrieval only, free)
      uv run python labs/rag-hybrid/start/measure.py --answers 10    (+ answers before/after)
      uv run python labs/rag-hybrid/start/measure.py --answers 10 --provider openai
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hybrid import CANDIDATES, MODES, HybridSearch  # noqa: E402  (also puts labs/rag/done on sys.path)
from index import REPO, Index  # noqa: E402

GOLDEN = REPO / "data" / "golden" / "rag-50.jsonl"
# Below this best reranker score, hand over without calling the model. Tuned on the 50
# questions (see print_floor): 0.5 would have handed over answerable questions.
RERANK_MIN_SCORE = 0.01


def load_golden(path: Path = GOLDEN) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def is_relevant(chunk: dict, case: dict) -> bool:
    """The chunk is the expected section (or inside it: 3.1 is part of 3), or an also-relevant one."""
    targets = [(case["source_doc"], str(case["section"]))]
    targets += [tuple(a.split("#", 1)) for a in case.get("also_relevant", [])]
    return any(chunk["doc_id"] == doc and (chunk["section"] == sec or chunk["section"].startswith(sec + "."))
               for doc, sec in targets)


def first_rank(hits, case: dict) -> int | None:
    """1-based rank of the first relevant chunk, or None if it isn't in the list."""
    # TODO 4a: The 1-based rank of the first chunk where is_relevant(chunk, case), or None.
    raise NotImplementedError("TODO 4a")


def retrieval_metrics(ranks: list[int | None]) -> dict:
    # TODO 4b: hit@1, hit@3, hit@5 (counts), mrr (mean of 1/rank, 0 if missing),
    # found (in the list at all: rank not None) and n.
    raise NotImplementedError("TODO 4b")


def run_retrieval(search: HybridSearch, cases: list[dict]) -> tuple[dict, dict]:
    """ranks[mode][case id] and seconds per question for every mode.
    ranks["best_score"][case id] is the reranker's top score (for the I-don't-know floor)."""
    ranks: dict[str, dict] = {m: {} for m in (*MODES, "best_score")}
    seconds = {m: 0.0 for m in MODES}
    for case in cases:
        q = case["question"]
        for mode in MODES:
            t0 = time.monotonic()
            hits = search.search(q, mode, k=CANDIDATES)  # the full ranked list, to see where it lands
            seconds[mode] += time.monotonic() - t0
            ranks[mode][case["id"]] = first_rank(hits, case)
            if mode == "rerank":
                ranks["best_score"][case["id"]] = hits[0][1] if hits else 0.0
    return ranks, {m: s / len(cases) for m, s in seconds.items()}


def print_retrieval(ranks: dict, per_question_s: dict) -> None:
    labels = {"vector": "vector only", "keyword": "keyword only (BM25)",
              "hybrid": "hybrid (RRF)", "rerank": "hybrid + rerank"}
    print(f"\n{'search':22} {'hit@1':>6} {'hit@3':>6} {'hit@5':>6} {'MRR':>6} {'found':>7} {'ms/q':>6}")
    for mode in MODES:
        m = retrieval_metrics(list(ranks[mode].values()))
        print(f"{labels[mode]:22} {m['hit@1']:>3}/{m['n']} {m['hit@3']:>3}/{m['n']} {m['hit@5']:>3}/{m['n']} "
              f"{m['mrr']:>6.3f} {m['found']:>4}/{m['n']} {per_question_s[mode] * 1000:>6.0f}")


def print_floor(ranks: dict) -> None:
    """Every one of the 50 questions IS answerable. So where would a score floor wrongly hand over?"""
    best = sorted(ranks["best_score"].values())
    print(f"\nReranker best score on the 50 answerable questions: lowest {best[0]:.3f}, "
          f"median {best[len(best) // 2]:.3f}")
    for floor in (0.5, 0.1, RERANK_MIN_SCORE):
        n = sum(1 for b in best if b < floor)
        print(f"  floor {floor:<4} would hand over {n} of them without calling the model")


def print_changes(ranks: dict, cases: list[dict]) -> None:
    """The questions where the rank moved between vector only and hybrid + rerank."""
    show = lambda r: "-" if r is None else str(r)  # noqa: E731
    moved = [c for c in cases if ranks["vector"][c["id"]] != ranks["rerank"][c["id"]]]
    print(f"\nRank of the right section, where it changed ({len(moved)} of {len(cases)}):")
    print(f"  {'id':7} {'vector':>6} {'keyword':>7} {'hybrid':>6} {'rerank':>6}  question")
    for c in moved:
        r = [show(ranks[m][c["id"]]) for m in MODES]
        print(f"  {c['id']:7} {r[0]:>6} {r[1]:>7} {r[2]:>6} {r[3]:>6}  {c['question'][:60]}")


# --------------------------------------------------------------------------
# Step 2: answers, before and after
# --------------------------------------------------------------------------


def numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*", text)}


def grade(reply, case: dict) -> dict:
    """Cheap, no extra model call: answered? right section cited? the expected numbers present?"""
    answered = reply.kind == "answer"
    right_source = answered and any(is_relevant({"doc_id": cid.split("§")[0],
                                                 "section": cid.split("§")[1].split("#")[0]}, case)
                                    for cid in reply.cited)
    want = numbers(case["expected_answer"])
    facts = answered and want <= numbers(reply.text) if want else answered
    return {"answered": answered, "source": right_source, "facts": bool(facts)}


def _why(reply) -> str:
    if reply.result is None:
        return "no call"
    return "check failed" if reply.reason.startswith("check") else "not answerable"


def run_answers(search: HybridSearch, cases: list[dict], ranks: dict, n: int, llm) -> None:
    from ask import MIN_SCORE, answer_from_hits

    # Spend the LLM money where retrieval differs: the questions vector search ranks worst.
    order = sorted(cases, key=lambda c: (-(ranks["vector"][c["id"]] or 99), c["id"]))
    picked = sorted(order[:n], key=lambda c: c["id"])
    print(f"\nAnswers on {len(picked)} questions (the ones vector search ranks worst), {llm.model}:")
    print(f"  {'id':7} {'before: vector top 5':28} {'after: hybrid + rerank top 5':28}")
    totals = {"before": {"answered": 0, "source": 0, "facts": 0}, "after": {"answered": 0, "source": 0, "facts": 0}}
    spent, calls, cached = 0.0, 0, 0
    for case in picked:
        q = case["question"]
        row = []
        for side, mode, floor in (("before", "vector", MIN_SCORE), ("after", "rerank", RERANK_MIN_SCORE)):
            hits = search.search(q, mode, k=5)
            reply = answer_from_hits(q, hits, llm, min_score=floor)
            g = grade(reply, case)
            for key in g:
                totals[side][key] += g[key]
            spent += reply.cost_usd
            calls += reply.result is not None and not reply.cached
            cached += reply.cached
            mark = lambda ok: "✓" if ok else "✗"  # noqa: E731
            cell = (f"answered {mark(g['answered'])} source {mark(g['source'])} facts {mark(g['facts'])}"
                    if g["answered"] else f"handed over ({_why(reply)})")
            row.append(cell)
        print(f"  {case['id']:7} {row[0]:28} {row[1]:28}")
    n_ = len(picked)
    print(f"\n{'':22} {'answered':>9} {'right source':>13} {'facts right':>12}")
    for side, name in (("before", "before (vector)"), ("after", "after (hybrid+rerank)")):
        t = totals[side]
        print(f"{name:22} {t['answered']:>6}/{n_} {t['source']:>10}/{n_} {t['facts']:>9}/{n_}")
    print(f"\nLLM: {calls} paid calls, {cached} from cache · ${spent:.6f} this run")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Measure retrieval (free) and, optionally, answers (paid).")
    ap.add_argument("--answers", type=int, default=0, metavar="N", help="also answer N questions before/after")
    ap.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s] %(message)s")

    cases = load_golden()
    search = HybridSearch(Index())
    search.search("warm up", "rerank")  # load both local models before timing anything
    print(f"Retrieval on {len(cases)} questions (no LLM, $0). Right section = source_doc + section in rag-50.jsonl")
    ranks, per_q = run_retrieval(search, cases)
    print_retrieval(ranks, per_q)
    print_floor(ranks)
    print_changes(ranks, cases)

    if args.answers:
        from shopkart.llm import LLM

        run_answers(search, cases, ranks, args.answers, LLM(args.provider))
    return 0


if __name__ == "__main__":
    sys.exit(main())
