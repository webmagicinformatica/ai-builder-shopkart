"""The model solution's tests. No key, no network, no cost: fake embedder, fake reranker, fake LLM.

    uv run pytest capstone/doc-assistant -q
"""

import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest

from shopkart import budget
from tests.fakes import FakeServer, anthropic_message

PROJECT = Path(__file__).resolve().parents[1]
SOLUTION = PROJECT / "solution"
LABS = PROJECT.parents[1] / "labs"
SHARED = ("parse", "chunker", "index", "ingest", "ask", "hybrid", "measure", "assistant", "judge", "evaluate")


def _load():
    for name in SHARED:  # the labs' own tests may have loaded their start/ copies
        sys.modules.pop(name, None)
    paths = [str(SOLUTION), str(LABS / "rag-hybrid" / "done"), str(LABS / "rag" / "done")]
    for p in paths:
        sys.path.insert(0, p)
    try:
        return [importlib.import_module(n) for n in ("assistant", "evaluate", "judge", "ingest", "index", "ask")]
    finally:
        for p in paths:
            sys.path.remove(p)


assistant, evaluate, judge, ingest, index, ask = _load()


class FakeEmbedder:
    name = "fake-embedder"

    def _vec(self, text):
        v = np.zeros(384, dtype=np.float32)
        for word in re.findall(r"\w+", text.lower()):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % 384] += 1
        return v / (np.linalg.norm(v) or 1)

    def passages(self, texts):
        return np.array([self._vec(t) for t in texts])

    def query(self, text):
        return self._vec(text)


class FakeReranker:
    """Share of the question's longer words found in the chunk: 0 when nothing matches."""

    def scores(self, question, texts):
        words = {w for w in re.findall(r"\w+", question.lower()) if len(w) > 3}
        return [len(words & set(re.findall(r"\w+", t.lower()))) / (len(words) or 1) for t in texts]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")


@pytest.fixture(scope="module")
def idx(tmp_path_factory):
    path = tmp_path_factory.mktemp("idx") / "index.sqlite"
    ingest.PARSED_DIR = path.parent / "parsed"
    ingest.build(index_path=path, embedder=FakeEmbedder(), log=lambda *a: None)
    return index.Index(path, embedder=FakeEmbedder())


def bot(idx, server=None, tmp_path=None):
    return assistant.DocAssistant(server.llm() if server else None, index=idx, reranker=FakeReranker(),
                                  cache_dir=tmp_path)


def answer_json(answer, labels, answerable=True):
    return anthropic_message(json.dumps({"answerable": answerable, "answer": answer, "citations": labels}))


def judge_json(*supported):
    claims = [{"claim": f"claim {i}", "supported": s} for i, s in enumerate(supported)]
    return anthropic_message(json.dumps({"claims": claims}))


# ---- the assistant -------------------------------------------------------------

def test_retrieves_current_documents_only(idx):
    hits = bot(idx).retrieve("You match lower prices, right?")
    assert len(hits) == 5 and all(c["status"] == "current" for c, _ in hits)


def test_score_floor_hands_over_without_a_call(idx, tmp_path):
    server = FakeServer("anthropic", [])
    reply = bot(idx, server, tmp_path).ask("Zxqv blorptastic wibbles?")
    assert reply.kind == "handover" and reply.result is None and server.calls == 0
    assert reply.text == ask.HANDOVER_TEXT


def test_answer_with_a_checked_citation(idx, tmp_path):
    b = bot(idx, None, tmp_path)
    q = "How many days do I have to return a product?"
    lb = ask.label(idx.by_id["returns-and-refunds§2.1"])
    assert lb in [ask.label(c) for c, _ in b.retrieve(q)]
    server = FakeServer("anthropic", [answer_json(f"You have 14 days from delivery [{lb}].", [lb])])
    b._llm = server.llm()
    reply = b.ask(q)
    assert reply.kind == "answer" and reply.cited == ["returns-and-refunds§2.1"]


def test_a_number_not_in_the_source_is_never_shown(idx, tmp_path):
    b = bot(idx, None, tmp_path)
    q = "How many days do I have to return a product?"
    lb = ask.label(idx.by_id["returns-and-refunds§2.1"])
    b._llm = FakeServer("anthropic", [answer_json(f"You have 30 days [{lb}].", [lb])]).llm()
    reply = b.ask(q)
    assert reply.kind == "handover" and "30" in reply.reason


def test_answerable_false_is_a_handover(idx, tmp_path):
    b = bot(idx, None, tmp_path)
    b._llm = FakeServer("anthropic", [answer_json("", [], answerable=False)]).llm()
    reply = b.ask("I got this as a gift. Can I return it without the buyer's order number?")
    assert reply.kind == "handover" and "answerable = false" in reply.reason


# ---- the eval --------------------------------------------------------------------

def test_the_test_sets():
    rag = evaluate.load(evaluate.RAG_50)
    idk = evaluate.load(evaluate.IDK_10)
    assert len(rag) == 50 and len(idk) == 10
    assert len({c["id"] for c in idk}) == 10 and all(c["question"].strip() for c in idk)


def test_run_case_grades_and_judges(idx, tmp_path):
    case = next(c for c in evaluate.load(evaluate.RAG_50) if c["id"] == "rag-01")
    lb = ask.label(idx.by_id["returns-and-refunds§2.1"])
    server = FakeServer("anthropic", [answer_json(f"You have 14 days from delivery [{lb}].", [lb]),
                                      judge_json(True, True)])
    b = bot(idx, server, tmp_path)
    row = evaluate.run_case(b, case, "answerable", b.llm, judge_cache=tmp_path / "j")
    assert row.rank is not None and row.grade == {"answered": True, "source": True, "facts": True}
    assert row.faithful is True and row.passed and row.calls == 2
    again = evaluate.run_case(b, case, "answerable", b.llm, judge_cache=tmp_path / "j")
    assert again.calls == 0 and again.cached == 2 and again.cost == 0  # all from the disk cache
    assert server.calls == 2


def test_an_unsupported_claim_fails_the_case(idx, tmp_path):
    case = next(c for c in evaluate.load(evaluate.RAG_50) if c["id"] == "rag-01")
    lb = ask.label(idx.by_id["returns-and-refunds§2.1"])
    server = FakeServer("anthropic", [answer_json(f"You have 14 days from delivery, in your wallet [{lb}].", [lb]),
                                      judge_json(True, False)])
    b = bot(idx, server, tmp_path)
    row = evaluate.run_case(b, case, "answerable", b.llm, judge_cache=tmp_path / "j")
    assert row.faithful is False and not row.passed


def test_summary_criteria_and_report(idx, tmp_path):
    case = next(c for c in evaluate.load(evaluate.RAG_50) if c["id"] == "rag-01")
    lb = ask.label(idx.by_id["returns-and-refunds§2.1"])
    server = FakeServer("anthropic", [answer_json(f"You have 14 days from delivery [{lb}].", [lb]),
                                      judge_json(True, True, False)])
    b = bot(idx, server, tmp_path)
    rows = [evaluate.run_case(b, case, "answerable", b.llm, judge_cache=tmp_path / "j"),
            evaluate.run_case(b, {"id": "idk-x", "question": "Zxqv blorptastic wibbles?"}, "idk", b.llm,
                              judge_cache=tmp_path / "j")]
    s = evaluate.summarise(rows)
    assert (s["answered"], s["claims"], s["supported"], s["idk"], s["idk_floor"]) == (1, 3, 2, 1, 1)
    crit = evaluate.criteria(s, 0.01)
    assert [ok for *_, ok in crit] == [True, True, False, True, True]  # 2 of 3 claims is below 90%
    assert evaluate.need(45, 50, 50) == 45 and evaluate.need(45, 50, 5) == 5 and evaluate.need(9, 10, 5) == 5
    out = tmp_path / "report.md"
    evaluate.write_report(out, s, rows, "claude-haiku-5-5", crit, 1.0)
    text = out.read_text()
    assert "## Acceptance criteria" in text and "idk-x" in text and "rag-01" in text


# ---- the fix after the first eval run: citations per passage ---------------------

def test_one_citation_can_cover_the_sentences_before_it(idx):
    hits = [(idx.by_id["payments§2"], 0.9)]
    lb = ask.label(idx.by_id["payments§2"])
    text = f"No, do not pay again. Wait 30 minutes, the order is confirmed or the money reversed [{lb}]."
    assert ask.check_answer(text, hits)[0]  # the lab's per-sentence check rejects it
    problems, cited = assistant.check_passages(text, hits)
    assert problems == [] and cited == ["payments§2"]


def test_a_passage_still_needs_its_numbers_and_a_citation(idx):
    hits = [(idx.by_id["payments§2"], 0.9)]
    lb = ask.label(idx.by_id["payments§2"])
    made_up = f"Wait 45 minutes. Then check again [{lb}]."
    assert any("45" in p for p in assistant.check_passages(made_up, hits)[0])
    trailing = f"Wait 30 minutes [{lb}]. Refunds take 3 days."
    assert any("no citation" in p for p in assistant.check_passages(trailing, hits)[0])
