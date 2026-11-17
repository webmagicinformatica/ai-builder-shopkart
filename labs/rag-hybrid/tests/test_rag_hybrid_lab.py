"""The lab's checkpoints. No key, no network, no cost: fake embedder, fake reranker, fake LLM.

Against the finished answer:   uv run pytest labs/rag-hybrid -q
Against your copy:             LAB=start uv run pytest labs/rag-hybrid -q
"""

import hashlib
import importlib
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pytest

from shopkart import budget
from tests.fakes import FakeServer, anthropic_message

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")
RAG_DONE = LAB.parent / "rag" / "done"
LAB_MODULES = ("parse", "chunker", "index", "ingest", "ask", "hybrid", "measure")


def _load_lab():
    for name in LAB_MODULES:  # the RAG lab's tests may have loaded its start/ copy
        sys.modules.pop(name, None)
    sys.path.insert(0, str(RAG_DONE))
    sys.path.insert(0, str(FOLDER))
    try:
        return [importlib.import_module(n) for n in ("hybrid", "measure", "index", "ingest", "ask")]
    finally:
        sys.path.remove(str(FOLDER))
        sys.path.remove(str(RAG_DONE))


hybrid, measure, index, ingest, ask = _load_lab()


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
    """Scores a chunk by how many question words it contains, squashed to 0..1."""

    def scores(self, question, texts):
        words = set(re.findall(r"\w+", question.lower()))
        return [len(words & set(re.findall(r"\w+", t.lower()))) / (len(words) or 1) for t in texts]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")


@pytest.fixture(scope="module")
def search(tmp_path_factory):
    path = tmp_path_factory.mktemp("idx") / "index.sqlite"
    ingest.PARSED_DIR = path.parent / "parsed"
    ingest.build(index_path=path, embedder=FakeEmbedder(), log=lambda *a: None)
    return hybrid.HybridSearch(index.Index(path, embedder=FakeEmbedder()), reranker=FakeReranker())


# ---- 1. keyword search -----------------------------------------------------

def test_keyword_index_has_every_chunk(search):
    n = search.db.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    assert n == len(search.index.chunks)


def test_query_drops_stopwords():
    assert hybrid.fts_query("Can I return my Stride RN220?") == '"return" OR "stride" OR "rn220"'


def test_keyword_search_finds_the_exact_model_number(search):
    hits = search.keyword_search("Can I return my Stride RN220 running shoes?", k=5)
    assert hits[0][0]["doc_id"] == "product-stride-rn220"


def test_keyword_search_filters_inside_the_search(search):
    hits = search.keyword_search("price match lower price", k=50)
    assert hits and all(c["status"] == "current" for c, _ in hits)


# ---- 2. reciprocal rank fusion -----------------------------------------------

def test_rrf_uses_ranks_not_scores():
    a, b, c = {"id": "rn220"}, {"id": "care-guide"}, {"id": "other"}
    keyword = [(a, 12.4)]  # first for keywords
    vector = [(b, 0.81), (c, 0.80), ({"id": "x"}, 0.7), (a, 0.6)]  # fourth for vectors
    fused = dict((ch["id"], s) for ch, s in hybrid.HybridSearch.rrf(vector, keyword))
    assert fused["rn220"] == pytest.approx(1 / 61 + 1 / 64)  # about 0.032
    assert fused["care-guide"] == pytest.approx(1 / 61)  # about 0.016: half as much
    assert list(fused)[0] == "rn220"


# ---- 3. rerank ------------------------------------------------------------------

def test_rerank_reads_many_keeps_few(search):
    q = "How much does express delivery cost?"
    candidates = search.hybrid_search(q, k=20)
    top = search.rerank(q, candidates, k=5)
    assert len(candidates) > 5 and len(top) == 5
    assert [s for _, s in top] == sorted((s for _, s in top), reverse=True)


# ---- 4. measure ---------------------------------------------------------------------

def test_relevance_and_metrics():
    case = {"source_doc": "payments", "section": "3", "also_relevant": ["refunds#7"]}
    assert measure.is_relevant({"doc_id": "payments", "section": "3.1"}, case)  # inside section 3
    assert measure.is_relevant({"doc_id": "refunds", "section": "7"}, case)
    assert not measure.is_relevant({"doc_id": "payments", "section": "4"}, case)
    m = measure.retrieval_metrics([1, 2, None, 6])
    assert (m["hit@1"], m["hit@3"], m["hit@5"]) == (1, 2, 2)
    assert m["mrr"] == pytest.approx((1 + 1 / 2 + 0 + 1 / 6) / 4)


def test_measure_runs_on_the_golden_set(search):
    cases = measure.load_golden()[:5]
    ranks, per_q = measure.run_retrieval(search, cases)
    assert set(hybrid.MODES) <= set(ranks) and all(len(r) == 5 for r in ranks.values())


def test_grade_answers(tmp_path):
    case = {"source_doc": "shipping-and-delivery", "section": "1", "also_relevant": [],
            "expected_answer": "₹49. Kochi is an 'other city', and orders of ₹499 and above pay ₹49 there."}
    good = ask.Reply("q", "answer", "Delivery is ₹49 for ₹499 and above [shipping-and-delivery § 1].",
                     cited=["shipping-and-delivery§1"])
    assert measure.grade(good, case) == {"answered": True, "source": True, "facts": True}
    wrong = ask.Reply("q", "answer", "Delivery is free [shipping-and-delivery § 2].", cited=["shipping-and-delivery§2"])
    assert measure.grade(wrong, case) == {"answered": True, "source": False, "facts": False}


def test_answer_after_rerank_uses_llm_once(search, tmp_path):
    q = "How much does express delivery cost?"
    hits = search.search(q, "rerank", k=5)
    lb = ask.label(hits[0][0])
    body = json.dumps({"answerable": True, "answer": f"Express costs ₹99 extra [{lb}].", "citations": [lb]})
    server = FakeServer("anthropic", [anthropic_message(body)])
    reply = ask.answer_from_hits(q, hits, server.llm(), min_score=measure.RERANK_MIN_SCORE, cache_dir=tmp_path)
    assert server.calls == 1 and reply.result is not None
