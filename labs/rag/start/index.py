"""Step 3: embeddings and the index (one SQLite file), plus vector search.

Embeddings run locally with fastembed (ONNX, no torch, no API key, no cost):
BAAI/bge-small-en-v1.5, 384 numbers per chunk, about 70 MB, downloaded once
into .shopkart/models/.

The index is a single SQLite file. Each row is a chunk: its text, its metadata
(doc_id, section, page, status, ...) and its vector as raw bytes. A few hundred
chunks fit in memory, so search is one numpy dot product.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import sys
from pathlib import Path
from typing import Protocol

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))  # so `import shopkart` works from any folder

INDEX_PATH = REPO / ".shopkart" / "rag" / "index.sqlite"
MODELS_DIR = REPO / ".shopkart" / "models"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"

COLUMNS = ["id", "doc_id", "section", "section_title", "heading_path", "text", "source", "page",
           "title", "doc_type", "status", "effective", "hash"]


class Embedder(Protocol):
    name: str

    def passages(self, texts: list[str]) -> np.ndarray: ...
    def query(self, text: str) -> np.ndarray: ...


def quiet_onnx() -> None:
    """fastembed's ONNX runtime and the model download are chatty. Keep the screen clean."""
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    import warnings

    warnings.filterwarnings("ignore", message=".*(unauthenticated requests|progress bars).*")
    try:
        import onnxruntime

        onnxruntime.set_default_logger_severity(3)  # errors only
    except ImportError:
        pass
    import logging

    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)


@contextlib.contextmanager
def native_stderr_silenced():
    """ONNX Runtime prints a harmless hardware warning from C++ on cloud VMs (Codespaces too).
    Python can't filter it, so we point the stderr file descriptor at /dev/null while loading."""
    sys.stderr.flush()
    saved = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(devnull)
        os.close(saved)


class LocalEmbedder:
    """fastembed on the CPU. Vectors come back normalised, so a dot product is the cosine."""

    def __init__(self, model: str = EMBED_MODEL):
        self.name = model
        with native_stderr_silenced():
            quiet_onnx()
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model, cache_dir=str(MODELS_DIR), threads=len(os.sched_getaffinity(0)))

    def passages(self, texts: list[str]) -> np.ndarray:
        return np.array(list(self._model.passage_embed(texts, batch_size=8)), dtype=np.float32)

    def query(self, text: str) -> np.ndarray:
        return np.array(next(iter(self._model.query_embed([text]))), dtype=np.float32)


# --------------------------------------------------------------------------
# The SQLite index
# --------------------------------------------------------------------------


def connect(path: Path = INDEX_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def save_index(chunks: list, embedder: Embedder, path: Path = INDEX_PATH) -> dict:
    """Write every chunk and its vector. Unchanged chunks (same id, same hash) keep their vector.

    Returns counts: {"chunks", "embedded", "reused", "removed"}.
    """
    # TODO 4: Embed the chunks (only those whose (id, hash) isn't already in the old
    # table with the same embed model), then rewrite the chunks table: COLUMNS plus
    # the vector as float32 bytes. Store the model name in meta.
    # Return {"chunks", "embedded", "reused", "removed"}.
    raise NotImplementedError("TODO 4")


class Index:
    """The saved index, loaded into memory: chunk rows plus one matrix of vectors."""

    def __init__(self, path: Path = INDEX_PATH, embedder: Embedder | None = None):
        if not path.exists():
            raise SystemExit(f"No index at {path}. Build it first:  uv run python labs/rag/start/ingest.py")
        self.path = path
        db = connect(path)
        rows = db.execute("SELECT * FROM chunks ORDER BY rowid").fetchall()
        model = db.execute("SELECT value FROM meta WHERE key = 'embed_model'").fetchone()[0]
        db.close()
        self.chunks = [{col: r[col] for col in COLUMNS} for r in rows]
        self.vectors = np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
        self.by_id = {c["id"]: c for c in self.chunks}
        self._embedder = embedder
        self.model = model

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = LocalEmbedder(self.model)  # the SAME model that built the index
        return self._embedder

    def allowed(self, statuses: tuple[str, ...] = ("current",)) -> np.ndarray:
        """The metadata filter, as a mask: which chunks may be searched at all."""
        return np.array([c["status"] in statuses for c in self.chunks])

    def vector_search(self, question: str, k: int = 5,
                      statuses: tuple[str, ...] = ("current",)) -> list[tuple[dict, float]]:
        """Top k chunks by cosine similarity. The filter runs INSIDE the search,
        so archived chunks never take a place in the top k."""
        # TODO 5: Embed the question with self.embedder.query(), score every chunk with
        # self.vectors @ q, set the score of chunks that fail the filter
        # (self.allowed(statuses)) to -inf BEFORE ranking, return the top k as
        # [(chunk, score)].
        raise NotImplementedError("TODO 5")
