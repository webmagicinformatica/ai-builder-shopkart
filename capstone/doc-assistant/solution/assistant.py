"""The document assistant: ShopKart's policies, answered with sources, or an honest "I don't know".

    question
      → hybrid search (BM25 + vectors, current documents only)      from the hybrid-search lab
      → rerank the top 20 with a local cross-encoder, keep 5        from the hybrid-search lab
      → score floor: best chunk below 0.01? hand over, no model call
      → LLM, JSON out: answerable, answer, citations                from the RAG lab
      → grounding check: every sentence cited, every number found   from the RAG lab
      → the answer with its sources, or the same polite handover

Almost nothing here is new code. The capstone is about putting the lab pieces
together, choosing the settings with data, and proving it works (evaluate.py).

Run:   uv run python capstone/doc-assistant/solution/assistant.py "How many days do I have to return a product?"
       uv run python capstone/doc-assistant/solution/assistant.py --demo
       uv run python capstone/doc-assistant/solution/assistant.py --search "Do you sell refurbished phones?"   (free)
Add --provider openai to run on OpenAI.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

LABS = Path(__file__).resolve().parents[3] / "labs"
sys.path.insert(0, str(LABS / "rag" / "done"))  # parse, chunk, index, ask
sys.path.insert(0, str(LABS / "rag-hybrid" / "done"))  # hybrid search + rerank

from hybrid import HybridSearch, Reranker  # noqa: E402
from index import REPO, Index  # noqa: E402  (also puts the repo root on sys.path)

import ask  # noqa: E402  (the RAG lab: prompt, JSON answer, grounding check, handover)
from shopkart import budget  # noqa: E402
from shopkart.llm import LLM, LLMError  # noqa: E402
from shopkart.pricing import usd_to_inr  # noqa: E402

K = 5  # chunks the model reads
# Below this best reranker score: hand over without calling the model.
# Chosen on data (evaluate.py prints it): the lowest score of an ANSWERABLE question
# in the 50 is 0.020, and 6 of our 10 unanswerable questions score below 0.01.
MIN_SCORE = 0.01
CACHE_DIR = REPO / ".shopkart" / "cache" / "capstone"

DEMO = [
    "How many days do I have to return a product?",
    "Can I return my Stride RN220 running shoes after a run?",
    "How much does express delivery cost?",
    "Do you sell refurbished phones?",  # not in any policy: no model call
    "I got this as a gift. Can I return it without the buyer's order number?",  # the model says no
]


class DocAssistant:
    """Retrieve, answer, check. Every piece can be swapped for a fake in the tests."""

    def __init__(self, llm: LLM | None = None, index: Index | None = None, reranker: Reranker | None = None,
                 min_score: float = MIN_SCORE, k: int = K, cache_dir: Path | None = CACHE_DIR):
        self.index = index or Index()
        self.search = HybridSearch(self.index, reranker=reranker)
        self._llm = llm
        self.min_score, self.k, self.cache_dir = min_score, k, cache_dir

    @property
    def llm(self) -> LLM:
        if self._llm is None:
            self._llm = LLM()
        return self._llm

    def retrieve(self, question: str) -> list[tuple[dict, float]]:
        """Hybrid search, then the reranker picks the best k. Scores are the reranker's, 0 to 1."""
        return self.search.search(question, "rerank", k=self.k)

    def ask(self, question: str) -> ask.Reply:
        return answer(question, self.retrieve(question), self)


def answer(question: str, hits: list[tuple[dict, float]], bot: DocAssistant) -> ask.Reply:
    """The RAG lab's answer step (prompt, JSON, handover), with our floor and our grounding check."""
    reply = ask.Reply(question, "handover", ask.HANDOVER_TEXT, hits=hits)
    if not hits or hits[0][1] < bot.min_score:
        best = f"{hits[0][1]:.3f}" if hits else "none"
        reply.reason = f"best chunk scores {best}, below the floor of {bot.min_score}: no model call"
        return reply

    result, reply.cached = ask.cached_complete(bot.llm, ask.SYSTEM, ask.build_prompt(question, hits),
                                               cache_dir=bot.cache_dir)
    reply.result = result
    out: ask.Answer = result.parsed  # type: ignore[assignment]
    if not out.answerable or not out.answer.strip():
        reply.reason = "the model says the sources don't cover it (answerable = false)"
        return reply
    problems, cited = check_passages(out.answer, hits, question)
    if problems:
        reply.reason = "check failed: " + "; ".join(problems)
        reply.text = out.answer  # kept for the log, NOT shown to the customer
        return reply
    reply.kind, reply.text, reply.cited = "answer", out.answer, cited
    return reply


# --------------------------------------------------------------------------
# The grounding check, per passage
#
# What broke: in the first full eval run, 10 of 50 answerable questions were handed
# over, 9 of them correct answers. The model often cites once, after two sentences:
#   "Wait 30 minutes. If it is still pending ... [payments § 2]."
# The lab's check wants a citation on EVERY sentence, so it rejected them.
# The fix: an uncited sentence belongs to the next citation, as one passage, and every
# number in the whole passage must still be in the cited source. A sentence with no
# citation after it still fails. Nothing unchecked reaches the customer.
# --------------------------------------------------------------------------


def passages(text: str) -> list[str]:
    """Group sentences up to and including the next one that cites a source."""
    out, run = [], []
    for s in ask.sentences(text):
        run.append(s)
        if ask.CITATION.search(s):
            out.append(" ".join(run))
            run = []
    if run:
        out.append(" ".join(run))  # trailing sentences with no citation: the check below fails them
    return out


def check_passages(text: str, hits: list[tuple[dict, float]], question: str = "") -> tuple[list[str], list[str]]:
    """Return (problems, cited chunk ids). The lab's three rules, per passage instead of per sentence."""
    sent = {ask.label(c): c for c, _ in hits}
    problems: list[str] = []
    cited: list[str] = []
    for p in passages(text):
        labels = ask.CITATION.findall(p)
        if not labels:
            if len(p.split()) <= 3 and not ask.NUMBER.search(p):
                continue  # a short opener like "No." makes no claim of its own
            problems.append(f"no citation: {p[:60]!r}")
            continue
        unknown = [lb for lb in labels if lb not in sent]
        if unknown:
            problems.append(f"cites a source we never sent: {unknown}")
            continue
        cited += [sent[lb]["id"] for lb in labels if sent[lb]["id"] not in cited]
        source = " ".join(sent[lb]["text"] for lb in labels).replace(",", "") + " " + question.replace(",", "")
        for n in ask.NUMBER.findall(ask.CITATION.sub("", p)):
            if n.replace(",", "") not in source:
                problems.append(f"number {n} is not in {labels}")
    return problems, cited


def print_reply(reply: ask.Reply, index: Index) -> None:
    print(f"\nQ: {reply.question}")
    print("   retrieved (hybrid + rerank, current documents only):")
    for chunk, score in reply.hits:
        print(f"     {score:.3f}  {chunk['id']:32} {chunk['section_title'][:40]}")
    print(f"A: {reply.text}")
    if reply.kind == "answer":
        for cid in reply.cited:
            c = index.by_id[cid]
            where = c["source"] + (f", page {c['page']}" if c["page"] else "")
            print(f"   source: [{ask.label(c)}] {c['heading_path']}  ({where})")
        print("   check: every sentence cited, every number found in its source ✓")
    else:
        print(f"   → handed over to a human. Why: {reply.reason}")
    if reply.result is not None:
        cost = "cached, $0" if reply.cached else f"${reply.result.cost_usd:.6f}"
        print(f"   {reply.result.model} · {reply.result.input_tokens} in / {reply.result.output_tokens} out · {cost}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ask ShopKart's document assistant.")
    ap.add_argument("question", nargs="?")
    ap.add_argument("--demo", action="store_true", help="five questions: three answers, two honest handovers")
    ap.add_argument("--search", action="store_true", help="retrieval only, free: the top 5 and their scores")
    ap.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args(argv)
    questions = DEMO if args.demo else [args.question] if args.question else None
    if not questions:
        ap.error("give a question, or --demo")
    logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s] %(message)s")

    llm = None if args.search else LLM(args.provider, args.model)
    bot = DocAssistant(llm, cache_dir=None if args.no_cache else CACHE_DIR)
    if args.search:
        for q in questions:
            print(f"\nQ: {q}")
            for chunk, score in bot.retrieve(q):
                print(f"   {score:.3f}  {chunk['id']:34} {chunk['section_title'][:40]}")
            best = bot.retrieve(q)[0][1]
            print(f"   best {best:.3f} → " + ("model is called" if best >= bot.min_score
                                             else f"below {bot.min_score}: hand over, no model call"))
        return 0

    total = 0.0
    try:
        for q in questions:
            reply = bot.ask(q)
            print_reply(reply, bot.index)
            total += reply.cost_usd
    except budget.BudgetExceeded as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except LLMError as exc:
        print(f"Call failed: {exc}", file=sys.stderr)
        return 1
    print(f"\nThis run: ${total:.6f} (₹{usd_to_inr(total):.4f}) · today ${budget.spent_today():.6f} "
          f"of ${budget.daily_budget_usd():.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
