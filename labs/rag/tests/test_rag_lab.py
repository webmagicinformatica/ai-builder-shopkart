"""The lab's checkpoints. No key, no network, no cost: a fake embedder and a fake LLM server.

Against the finished answer:   uv run pytest labs/rag -q
Against your copy:             LAB=start uv run pytest labs/rag -q
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
from tests.fakes import FakeServer, anthropic_message, openai_response

LAB = Path(__file__).resolve().parent.parent
REPO = LAB.parents[1]
FOLDER = LAB / os.environ.get("LAB", "done")
LAB_MODULES = ("parse", "chunker", "index", "ingest", "ask", "hybrid", "measure")


def _load_lab():
    for name in LAB_MODULES:  # another lab's copy may be loaded already
        sys.modules.pop(name, None)
    sys.path.insert(0, str(FOLDER))
    try:
        return [importlib.import_module(n) for n in ("parse", "chunker", "index", "ingest", "ask")]
    finally:
        sys.path.remove(str(FOLDER))


parse, chunker, index, ingest, ask = _load_lab()


class FakeEmbedder:
    """Bag of words hashed into 384 numbers: same words, close vectors. Good enough for tests."""

    name = "fake-embedder"

    def __init__(self):
        self.calls = 0

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(384, dtype=np.float32)
        for word in re.findall(r"\w+", text.lower()):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % 384] += 1
        return v / (np.linalg.norm(v) or 1)

    def passages(self, texts):
        self.calls += 1
        return np.array([self._vec(t) for t in texts])

    def query(self, text):
        return self._vec(text)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setattr(ingest, "PARSED_DIR", tmp_path / "parsed")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    path = tmp_path_factory.mktemp("idx") / "index.sqlite"
    ingest.PARSED_DIR = path.parent / "parsed"
    emb = FakeEmbedder()
    chunks, stats = ingest.build(index_path=path, embedder=emb, log=lambda *a: None)
    return path, emb, chunks, stats


# ---- Part 1, step 1: parsing -------------------------------------------

def test_pages_are_routed():
    import pdfplumber

    def routes(name):
        with pdfplumber.open(REPO / "data/policies/pdf" / name) as pdf:
            return [parse.route_page(p) for p in pdf.pages]

    assert routes("warranty-scanned.pdf") == ["scan", "scan"]
    assert routes("returns-and-refunds.pdf")[0] == "two_columns"
    assert routes("shipping-and-delivery.pdf") == ["text", "text"]


def test_table_rows_become_sentences_with_headers():
    rows = [["Order value", "Metro cities", "Other cities"], ["₹499 and above", "Free", "₹49"]]
    assert parse.table_to_sentences(rows) == ["Order value: ₹499 and above; Metro cities: Free; Other cities: ₹49."]


def test_pdf_table_is_kept_and_furniture_removed():
    doc = parse.parse(REPO / "data/policies/pdf/shipping-and-delivery.pdf")
    assert "Order value: ₹499 and above; Metro cities: Free; Other cities: ₹49." in doc.markdown
    assert "## 1. Delivery charges" in doc.markdown
    assert "ShopKart Confidential" not in doc.markdown and "Page 1" not in doc.markdown
    assert "<!-- page 2 -->" in doc.markdown


def test_two_column_pdf_reads_left_then_right():
    md = parse.parse(REPO / "data/policies/pdf/returns-and-refunds.pdf").markdown
    assert md.index("### 2.1 Return window") < md.index("### 2.2 Category return windows") < md.index("### 2.3 Refunds")
    assert "Category: Footwear; Return window: 10 days" in md
    assert "Category: Electronics; Return window: 7 days" in md
    assert "You can return most products within 14 days of delivery." in md  # not mixed with the other column


def test_scanned_pdf_is_flagged_not_silently_empty():
    doc = parse.parse(REPO / "data/policies/pdf/warranty-scanned.pdf")
    assert doc.pages_needing_ocr == [1, 2]


def test_markdown_front_matter():
    doc = parse.parse(REPO / "data/policies/archive/returns-2024.md")
    assert doc.doc_id == "returns-2024" and doc.meta["status"] == "archived"


# ---- Part 1, step 2: chunking ------------------------------------------

def test_chunks_follow_headings_with_path_and_stable_ids():
    doc = parse.parse(REPO / "data/policies/footwear.md")
    chunks = chunker.chunk_document(doc)
    by_id = {c.id: c for c in chunks}
    c = by_id["footwear§1"]
    assert c.section == "1" and c.section_title == "Return window"
    assert c.text.startswith("Footwear Returns and Exchanges Policy > 1. Return window")
    assert "10 days" in c.text
    again = [x.id for x in chunker.chunk_document(parse.parse(REPO / "data/policies/footwear.md"))]
    assert again == [x.id for x in chunks]  # same input, same ids


def test_long_section_is_split_at_paragraphs_never_mid_sentence():
    para = "This sentence is about returns. " * 30  # 150 words
    md = f"# Doc\n\n## 1. Long\n\n{para}\n\n{para}\n\n{para}\n"
    doc = parse.Parsed("long-doc", "x.md", md, {"title": "Doc"})
    chunks = chunker.chunk_document(doc, max_words=350)
    assert [c.id for c in chunks] == ["long-doc§1#1", "long-doc§1#2"]
    assert all(c.text.startswith("Doc > 1. Long") for c in chunks)
    assert all(c.text.rstrip().endswith("returns.") for c in chunks)


# ---- Part 1, steps 3-4: embed and save -----------------------------------

def test_ingest_builds_the_index(built):
    path, _, chunks, stats = built
    ids = {c.id for c in chunks}
    assert stats["chunks"] == len(chunks) > 100
    assert {"returns-and-refunds§2.1", "shipping-and-delivery§1", "warranty§2", "price-match§1"} <= ids
    sources = {c.doc_id: c.source for c in chunks}
    assert sources["shipping-and-delivery"].endswith(".pdf")  # the PDF was parsed and used
    assert sources["warranty"].endswith("warranty.md")  # the scan fell back to the web version
    assert {c.status for c in chunks} == {"current", "archived", "withdrawn"}


def test_reingest_only_embeds_what_changed(built, tmp_path):
    path, _, _, _ = built
    emb = FakeEmbedder()
    _, stats = ingest.build(index_path=path, embedder=emb, log=lambda *a: None)
    assert stats["embedded"] == 0 and stats["reused"] == stats["chunks"] and emb.calls == 0


# ---- Part 2: retrieve ------------------------------------------------------

def test_search_filters_archived_inside_the_search(built):
    path, emb, _, _ = built
    idx = index.Index(path, embedder=emb)
    hits = idx.vector_search("price match lower price claim", k=5)
    assert len(hits) == 5
    assert all(c["status"] == "current" for c, _ in hits)
    every = idx.vector_search("price match lower price claim", k=5, statuses=("current", "archived", "withdrawn"))
    assert any(c["doc_id"] == "price-match" for c, _ in every)


# ---- Part 2: answer with sources, or hand over -----------------------------

def _hits(built, ids=("returns-and-refunds§2.1", "footwear§1", "electronics§1", "refunds§2", "gift-cards§4")):
    """Five chunks as if search had found them, with a good score."""
    path, emb, _, _ = built
    idx = index.Index(path, embedder=emb)
    return idx, [(idx.by_id[i], 0.8) for i in ids]


def test_check_answer_needs_citations_and_real_numbers(built):
    _, hits = _hits(built)
    src = next(c for c, _ in hits if c["id"] == "returns-and-refunds§2.1")
    lb = ask.label(src)
    ok, cited = ask.check_answer(f"You can return most products within 14 days of delivery [{lb}].", hits)
    assert ok == [] and cited == ["returns-and-refunds§2.1"]
    grouped = "Most products 14 days, footwear 10 days. [returns-and-refunds § 2.1] [footwear § 1]"
    assert ask.check_answer(grouped, hits) == ([], ["returns-and-refunds§2.1", "footwear§1"])
    assert ask.check_answer("No. You can return within 14 days [returns-and-refunds § 2.1].", hits)[0] == []
    problems, _ = ask.check_answer("You can return within 14 days.", hits)
    assert "no citation" in problems[0]
    problems, _ = ask.check_answer("You have 30 days [returns-and-refunds § 2.1].", hits)
    assert "30" in problems[0]
    problems, _ = ask.check_answer("We match prices [price-match § 1].", hits)
    assert "never sent" in problems[0]


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_answer_with_sources(built, tmp_path, provider):
    _, hits = _hits(built)
    body = json.dumps({"answerable": True, "citations": ["returns-and-refunds § 2.1"],
                       "answer": "You can return most products within 14 days of delivery [returns-and-refunds § 2.1]."})
    reply_body = anthropic_message(body, 900, 40) if provider == "anthropic" else openai_response(body, 900, 40)
    server = FakeServer(provider, [reply_body])
    q = "How many days do I have to return a product?"
    reply = ask.answer_from_hits(q, hits, server.llm(), cache_dir=tmp_path)
    assert reply.kind == "answer" and reply.cited == ["returns-and-refunds§2.1"]
    assert "[returns-and-refunds § 2.1]" in json.dumps(server.requests[-1], ensure_ascii=False)
    again = ask.answer_from_hits(q, hits, FakeServer(provider, []).llm(), cache_dir=tmp_path)
    assert again.cached and again.kind == "answer" and again.cost_usd == 0  # second time: from the cache


def test_not_covered_means_handover(built, tmp_path):
    _, hits = _hits(built)
    body = json.dumps({"answerable": False, "answer": "", "citations": []})
    reply = ask.answer_from_hits("gift?", hits, FakeServer("anthropic", [anthropic_message(body)]).llm(),
                                 cache_dir=tmp_path)
    assert reply.kind == "handover" and "answerable = false" in reply.reason
    assert reply.text == ask.HANDOVER_TEXT


def test_made_up_number_is_never_shown(built, tmp_path):
    _, hits = _hits(built)
    body = json.dumps({"answerable": True, "citations": ["returns-and-refunds § 2.1"],
                       "answer": "You have 30 days to return anything [returns-and-refunds § 2.1]."})
    reply = ask.answer_from_hits("days?", hits, FakeServer("anthropic", [anthropic_message(body)]).llm(),
                                 cache_dir=tmp_path)
    assert reply.kind == "handover" and "30" in reply.reason


def test_low_score_skips_the_model(built, tmp_path):
    _, hits = _hits(built)
    low = [(c, 0.2) for c, _ in hits]
    server = FakeServer("anthropic", [])
    reply = ask.answer_from_hits("Do you deliver to Antarctica?", low, server.llm(), cache_dir=tmp_path)
    assert reply.kind == "handover" and reply.result is None and server.calls == 0
