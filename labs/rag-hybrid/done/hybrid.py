"""Hybrid search and reranking, on top of the index from the RAG lab.

    keyword search (BM25)  ┐
                           ├─ reciprocal rank fusion → top 20 → cross-encoder reranker → top 5
    vector search          ┘
    (both filtered to current documents, inside the search)

Keyword search is SQLite's own full-text index, FTS5, whose ranking function is
BM25. Same file as the vectors, so there's nothing new to run.
The reranker is a small cross-encoder (ms-marco-MiniLM-L-6-v2, about 80 MB)
that runs locally with fastembed, like the embeddings.

Try it:  uv run python labs/rag-hybrid/done/hybrid.py "Can I return my Stride RN220 running shoes?"
"""

from __future__ import annotations

import argparse
import math
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Protocol

RAG_DONE = Path(__file__).resolve().parents[2] / "rag" / "done"
sys.path.insert(0, str(RAG_DONE))  # the finished RAG lab: index, ask

from index import INDEX_PATH, MODELS_DIR, Index, native_stderr_silenced, quiet_onnx  # noqa: E402

CANDIDATES = 50  # how many each search returns
RERANK_CANDIDATES = 20  # how many the reranker reads. On a 2-core Codespace, 50 took 3x as long, for the same hit@5
RRF_K = 60  # the standard constant in reciprocal rank fusion
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
MODES = ("vector", "keyword", "hybrid", "rerank")

Hits = list[tuple[dict, float]]


class Reranker(Protocol):
    def scores(self, question: str, texts: list[str]) -> list[float]: ...


class LocalReranker:
    """A cross-encoder: reads the question and one chunk TOGETHER, returns one relevance score."""

    def __init__(self, model: str = RERANK_MODEL):
        import os

        self.name = model
        with native_stderr_silenced():
            quiet_onnx()
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._model = TextCrossEncoder(model, cache_dir=str(MODELS_DIR), threads=len(os.sched_getaffinity(0)))

    def scores(self, question: str, texts: list[str]) -> list[float]:
        """0 to 1: the model's raw score through a sigmoid. Higher means "answers it better"."""
        return [1 / (1 + math.exp(-s)) for s in self._model.rerank(question, texts, batch_size=16)]


# --------------------------------------------------------------------------
# 1. Keyword search: BM25 with SQLite FTS5
# --------------------------------------------------------------------------


def build_keyword_index(path: Path = INDEX_PATH) -> int:
    """A full-text index next to the vectors, built from the same chunks table."""
    db = sqlite3.connect(path)
    db.execute("DROP TABLE IF EXISTS chunks_fts")
    # porter: "returns" and "returned" both match "return". unicode61: ₹ and Hindi letters are fine.
    db.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(id UNINDEXED, text, tokenize='porter unicode61')")
    db.execute("INSERT INTO chunks_fts (id, text) SELECT id, text FROM chunks")
    db.commit()
    n = db.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    db.close()
    return n


# Words that say nothing about the topic. BM25 already weighs them down, but in a
# small index they still add noise, so we drop them from the query.
STOPWORDS = set("""a an and are as at be but by can could do does for from had has have how i if in is it
its me my of on or our should so that the their them then there these they this to was we were what when where
which who why will with would you your s t m ve ll d""".split())


def fts_query(question: str) -> str:
    """The question's words, minus stopwords, OR-ed: '"return" OR "stride" OR "rn220" OR "shoes"'.
    BM25 does the weighting: a rare word (rn220) counts far more than a common one (shoes)."""
    words = [w for w in re.findall(r"\w+", question.lower()) if w not in STOPWORDS]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words))


class HybridSearch:
    def __init__(self, index: Index, reranker: Reranker | None = None):
        self.index = index
        self._reranker = reranker
        self.db = sqlite3.connect(index.path)
        has_fts = self.db.execute("SELECT 1 FROM sqlite_master WHERE name = 'chunks_fts'").fetchone()
        if not has_fts or self._fts_stale():
            build_keyword_index(index.path)

    def _fts_stale(self) -> bool:
        return self.db.execute("SELECT count(*) FROM chunks_fts").fetchone()[0] != len(self.index.chunks)

    @property
    def reranker(self) -> Reranker:
        if self._reranker is None:
            self._reranker = LocalReranker()
        return self._reranker

    def keyword_search(self, question: str, k: int = CANDIDATES, statuses: tuple[str, ...] = ("current",)) -> Hits:
        """BM25 over the chunks, filter inside the search (the JOIN on status)."""
        query = fts_query(question)
        if not query:
            return []
        marks = ", ".join("?" * len(statuses))
        rows = self.db.execute(
            f"""SELECT f.id, -bm25(chunks_fts) AS score
                FROM chunks_fts f JOIN chunks c ON c.id = f.id
                WHERE chunks_fts MATCH ? AND c.status IN ({marks})
                ORDER BY bm25(chunks_fts) LIMIT ?""",  # bm25() is lower-is-better, so we flip the sign
            (query, *statuses, k),
        ).fetchall()
        return [(self.index.by_id[cid], float(score)) for cid, score in rows]

    # ----------------------------------------------------------------------
    # 2. Reciprocal rank fusion: ranks, not scores
    # ----------------------------------------------------------------------

    @staticmethod
    def rrf(*ranked_lists: Hits, k: int = RRF_K) -> Hits:
        """Each list gives a chunk 1 / (60 + rank). Add them up. Chunks both lists agree on win."""
        points: dict[str, float] = {}
        chunks: dict[str, dict] = {}
        for hits in ranked_lists:
            for rank, (chunk, _) in enumerate(hits, start=1):
                points[chunk["id"]] = points.get(chunk["id"], 0.0) + 1.0 / (k + rank)
                chunks[chunk["id"]] = chunk
        order = sorted(points, key=lambda cid: -points[cid])
        return [(chunks[cid], points[cid]) for cid in order]

    def hybrid_search(self, question: str, k: int = CANDIDATES) -> Hits:
        vec = self.index.vector_search(question, k=CANDIDATES)
        kw = self.keyword_search(question, k=CANDIDATES)
        return self.rrf(vec, kw)[:k]

    # ----------------------------------------------------------------------
    # 3. Rerank: retrieve many, let the cross-encoder pick the best 5
    # ----------------------------------------------------------------------

    def rerank(self, question: str, hits: Hits, k: int = 5) -> Hits:
        scores = self.reranker.scores(question, [c["text"] for c, _ in hits])
        order = sorted(range(len(hits)), key=lambda i: -scores[i])
        return [(hits[i][0], scores[i]) for i in order[:k]]

    def search(self, question: str, mode: str = "rerank", k: int = 5) -> Hits:
        if mode == "vector":
            return self.index.vector_search(question, k=k)
        if mode == "keyword":
            return self.keyword_search(question, k=k)
        if mode == "hybrid":
            return self.hybrid_search(question, k=k)
        if mode == "rerank":
            return self.rerank(question, self.hybrid_search(question, k=RERANK_CANDIDATES), k=k)
        raise ValueError(f"mode must be one of {MODES}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare the four searches on one question (free: no LLM).")
    ap.add_argument("question")
    ap.add_argument("-k", type=int, default=5)
    args = ap.parse_args(argv)
    search = HybridSearch(Index())
    search.search("warm up", "rerank")  # load both models first, so the timings are fair
    for mode in MODES:
        t0 = time.monotonic()
        hits = search.search(args.question, mode, k=args.k)
        ms = (time.monotonic() - t0) * 1000
        print(f"\n{mode}  ({ms:.0f} ms)")
        for rank, (chunk, score) in enumerate(hits, start=1):
            print(f"  {rank}. {score:7.3f}  {chunk['id']:34} {chunk['section_title'][:38]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
