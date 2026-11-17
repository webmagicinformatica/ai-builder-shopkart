"""Part 2: retrieve, then answer with sources, or say "I don't know" and hand over.

    question -> top 5 chunks (current documents only) -> score floor -> LLM (JSON)
             -> check every sentence's citation -> answer, or hand over to a human

Run:   uv run python labs/rag/done/ask.py "How many days do I have to return a product?"
       uv run python labs/rag/done/ask.py --demo                 (five questions, one it must refuse)
       uv run python labs/rag/done/ask.py --demo --provider openai

Answers are cached in .shopkart/cache/, so running the same question again is free.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))

from index import REPO, Index  # noqa: E402  (also puts the repo root on sys.path)
from shopkart import budget  # noqa: E402
from shopkart.llm import LLM, LLMError, Result  # noqa: E402
from shopkart.pricing import usd_to_inr  # noqa: E402

K = 5  # chunks sent to the model
MIN_SCORE = 0.55  # if even the best chunk is below this, don't call the model at all
CACHE_DIR = REPO / ".shopkart" / "cache" / "rag"

HANDOVER_TEXT = ("I couldn't find this in our policies, so I don't want to guess. "
                 "I've passed your question to our support team, and an agent will continue right here, in this chat.")

SYSTEM = """You are ShopKart's support Copilot. ShopKart is an online store in India.
Answer the customer's question using ONLY the sources in the message. Rules:
- End every sentence with the label of the source it came from, exactly as written, e.g. [returns-and-refunds § 2.1].
- Use only facts that are written in the sources. No general knowledge, no guesses.
- If the sources don't answer the question, set answerable to false and leave answer empty.
- At most three short sentences. Write amounts in rupees as ₹."""

DEMO = [
    "How many days do I have to return a product?",
    "What is the delivery charge on a ₹799 order to Kochi?",
    "Can I return headphones I've already opened?",
    "You match lower prices, right?",
    "I got this as a gift. Can I return it without the buyer's order number?",  # must hand over
]


class Answer(BaseModel):
    """What the model must send back: a field our code can read, not just words."""

    answerable: bool = Field(description="true only if the sources answer the question")
    answer: str = Field(description="the answer, every sentence ending with its [doc § section] label; empty if not answerable")
    citations: list[str] = Field(description="the labels you used, like 'returns-and-refunds § 2.1'")


@dataclass
class Reply:
    """What the customer gets, plus everything we need to debug it."""

    question: str
    kind: str  # "answer" or "handover"
    text: str
    reason: str = ""  # why we handed over
    hits: list[tuple[dict, float]] = field(default_factory=list)
    cited: list[str] = field(default_factory=list)  # chunk ids
    result: Result | None = None
    cached: bool = False

    @property
    def cost_usd(self) -> float:
        return 0.0 if self.cached or self.result is None else self.result.cost_usd


def label(chunk: dict) -> str:
    """How a chunk is cited: [doc § section]."""
    return f"{chunk['doc_id']} § {chunk['section']}"


def build_prompt(question: str, hits: list[tuple[dict, float]]) -> str:
    """The sources, clearly labelled, then the question (it goes last)."""
    parts = []
    for chunk, _ in hits:
        date = f", effective {chunk['effective']}" if chunk["effective"] else ""
        parts.append(f"[{label(chunk)}] ({chunk['title']}{date})\n{chunk['text']}")
    return "Sources:\n\n" + "\n\n---\n\n".join(parts) + f"\n\nCustomer question: {question}"


# --------------------------------------------------------------------------
# Checks in code: the prompt sets the rule, our code makes sure it's kept
# --------------------------------------------------------------------------

CITATION = re.compile(r"\[([a-z0-9-]+ § [\w.-]+)\]")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def sentences(text: str) -> list[str]:
    """Split after a citation (or a group of them: "... 7 days. [a § 1] [b § 2]") or a full stop.
    Good enough for short support answers."""
    parts = re.split(r"(?<=\])\s+(?!\[)|(?<=[.!?])\s+(?=[A-Z₹])", text.strip())
    return [p.strip() for p in parts if p.strip() and not CITATION.fullmatch(p.strip())]


def check_answer(text: str, hits: list[tuple[dict, float]], question: str = "") -> tuple[list[str], list[str]]:
    """Return (problems, cited chunk ids).

    1. Every sentence cites a source (a short opener like "No." makes no claim, so it needs none).
    2. Every cited label is one we actually sent.
    3. Every number in a sentence appears in a chunk it cites, or in the question
       (14 days, ₹49, 5 to 7 ...). A cheap grounding check, no extra model call.
    """
    sent = {label(c): c for c, _ in hits}
    problems: list[str] = []
    cited: list[str] = []
    for s in sentences(text):
        labels = CITATION.findall(s)
        if not labels:
            if len(s.split()) <= 3 and not NUMBER.search(s):
                continue  # a short opener like "No." or "Yes, you can." makes no claim of its own
            problems.append(f"no citation: {s[:60]!r}")
            continue
        unknown = [lb for lb in labels if lb not in sent]
        if unknown:
            problems.append(f"cites a source we never sent: {unknown}")
            continue
        cited += [sent[lb]["id"] for lb in labels if sent[lb]["id"] not in cited]
        source_text = " ".join(sent[lb]["text"] for lb in labels).replace(",", "") + " " + question.replace(",", "")
        claim = CITATION.sub("", s)
        for n in NUMBER.findall(claim):
            if n.replace(",", "") not in source_text:
                problems.append(f"number {n} is not in {labels}")
    return problems, cited


# --------------------------------------------------------------------------
# A small disk cache: the same prompt to the same model is never paid twice
# --------------------------------------------------------------------------


def cached_complete(llm: LLM, system: str, prompt: str, schema=Answer,
                    cache_dir: Path | None = CACHE_DIR) -> tuple[Result, bool]:
    key = hashlib.sha256(json.dumps([llm.provider, llm.model, system, prompt]).encode()).hexdigest()[:24]
    path = cache_dir / f"{key}.json" if cache_dir else None
    if path and path.exists():
        data = json.loads(path.read_text())
        result = Result(**{k: v for k, v in data.items() if k != "parsed"}, parsed=None)
        result.parsed = schema.model_validate_json(result.text)
        return result, True
    result = llm.complete(prompt, system=system, schema=schema, max_tokens=400)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in vars(result).items() if k != "parsed"}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return result, False


# --------------------------------------------------------------------------


def retrieve(index: Index, question: str, k: int = K) -> list[tuple[dict, float]]:
    return index.vector_search(question, k=k)  # status = current only, inside the search


def answer_from_hits(question: str, hits: list[tuple[dict, float]], llm: LLM,
                     min_score: float | None = MIN_SCORE, cache_dir: Path | None = CACHE_DIR) -> Reply:
    reply = Reply(question, "handover", HANDOVER_TEXT, hits=hits)
    if not hits or (min_score is not None and hits[0][1] < min_score):
        best = f"{hits[0][1]:.2f}" if hits else "none"
        reply.reason = f"best chunk scores {best}, below {min_score}: no model call"
        return reply

    result, reply.cached = cached_complete(llm, SYSTEM, build_prompt(question, hits), cache_dir=cache_dir)
    reply.result = result
    out: Answer = result.parsed  # type: ignore[assignment]
    if not out.answerable or not out.answer.strip():
        reply.reason = "the model says the sources don't cover it (answerable = false)"
        return reply
    problems, cited = check_answer(out.answer, hits, question)
    if problems:
        reply.reason = "check failed: " + "; ".join(problems)
        reply.text = out.answer  # kept for the log, NOT shown to the customer
        return reply
    reply.kind, reply.text, reply.cited = "answer", out.answer, cited
    return reply


def ask(index: Index, question: str, llm: LLM, k: int = K, **kw) -> Reply:
    return answer_from_hits(question, retrieve(index, question, k), llm, **kw)


def print_reply(reply: Reply, index: Index) -> None:
    print(f"\nQ: {reply.question}")
    print("   retrieved (vector search, current documents only):")
    for chunk, score in reply.hits:
        print(f"     {score:.2f}  {chunk['id']:32} {chunk['section_title'][:40]}")
    if reply.kind == "answer":
        print(f"A: {reply.text}")
        for cid in reply.cited:
            c = index.by_id[cid]
            where = f"{c['source']}" + (f", page {c['page']}" if c["page"] else "")
            print(f"   source: [{label(c)}] {c['heading_path']}  ({where})")
        print("   check: every sentence cited, every number found in its source ✓")
    else:
        print(f"A: {reply.text}")
        print(f"   → handed over to a human. Why: {reply.reason}")
    if reply.result is not None:
        cost = "cached, $0" if reply.cached else f"${reply.result.cost_usd:.6f} (₹{reply.result.cost_inr:.4f})"
        print(f"   {reply.result.model} · {reply.result.input_tokens} in / {reply.result.output_tokens} out · {cost}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ask the Copilot's knowledge base.")
    ap.add_argument("question", nargs="?")
    ap.add_argument("--demo", action="store_true", help="run five demo questions")
    ap.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("-k", type=int, default=K)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--search", action="store_true",
                    help="retrieval only (free, no LLM): top k with the filter, and without it")
    args = ap.parse_args(argv)
    questions = DEMO if args.demo else [args.question] if args.question else None
    if not questions:
        ap.error("give a question, or --demo")

    logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s] %(message)s")
    index = Index()
    if args.search:
        for q in questions:
            print(f"\nQ: {q}")
            for name, statuses in (("current only", ("current",)),
                                   ("no filter", ("current", "archived", "withdrawn"))):
                print(f"   {name}:")
                for chunk, score in index.vector_search(q, k=args.k, statuses=statuses):
                    print(f"     {score:.2f}  {chunk['id']:32} {chunk['status']}")
        return 0
    llm = LLM(args.provider, args.model)
    total = 0.0
    try:
        for q in questions:
            reply = ask(index, q, llm, k=args.k, cache_dir=None if args.no_cache else CACHE_DIR)
            print_reply(reply, index)
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
