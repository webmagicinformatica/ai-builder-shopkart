"""Part 1: ingest and index ShopKart's knowledge base.

    parse (PDF + Markdown) -> chunk by heading -> embed locally -> save to SQLite

Run:   uv run python labs/rag/start/ingest.py
Then:  uv run python labs/rag/start/ingest.py --show returns-and-refunds§2.2   (read one chunk)
       uv run python labs/rag/start/ingest.py --sample 5                      (read random chunks)

Sources:
  data/policies/*.md          the help-centre pages (current)
  data/policies/archive/*.md  old and withdrawn policies: indexed WITH status, filtered out at search
  data/products/*.md          product pages
  data/policies/pdf/*.pdf     PDFs of three policies. A PDF that parses cleanly replaces its
                              Markdown twin, so you see real parsing. A scan (no text layer)
                              would need OCR; we fall back to the web version instead.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chunker import Chunk, chunk_document  # noqa: E402
from index import INDEX_PATH, REPO, Embedder, Index, LocalEmbedder, save_index  # noqa: E402
from parse import Parsed, parse  # noqa: E402

DATA = REPO / "data"
PARSED_DIR = REPO / ".shopkart" / "rag" / "parsed"  # what the parser produced: read it!


def numbers_in(text: str) -> set[str]:
    """Every amount, number and day count in a text: ₹2,999 / 14 / 5–7 ..."""
    return set(re.findall(r"₹?\d[\d,]*(?:\.\d+)?", text))


def collect(data: Path = DATA, log=print) -> list[Parsed]:
    """Parse every source, routing PDFs, and return one Parsed per doc_id."""
    web = {}
    for path in sorted([*data.glob("policies/*.md"), *data.glob("policies/archive/*.md"), *data.glob("products/*.md")]):
        doc = parse(path)
        web[doc.doc_id] = doc

    docs = dict(web)
    for path in sorted(data.glob("policies/pdf/*.pdf")):
        pdf = parse(path)
        twin = web.get(pdf.doc_id)
        if pdf.pages_needing_ocr:
            fallback = f"using the web version {twin.source}" if twin else "SKIPPED (no OCR in this lab)"
            log(f"  {path.name:28} pages {pdf.pages_needing_ocr} have no text: a scan, needs OCR → {fallback}")
            continue
        if twin:
            # Check the numbers that matter: is every amount in the web page also in the parsed PDF?
            want, got = numbers_in(twin.markdown), numbers_in(pdf.markdown)
            missing = sorted(want - got)
            log(f"  {path.name:28} parsed: {len(pdf.markdown.split())} words, "
                f"numbers check {len(want) - len(missing)}/{len(want)}"
                + (f", missing {missing[:6]}" if missing else ""))
            pdf.meta = {**twin.meta, "format": "pdf"}  # version, effective date, status from the CMS
        docs[pdf.doc_id] = pdf
    return list(docs.values())


def build(data: Path = DATA, index_path: Path = INDEX_PATH, embedder: Embedder | None = None,
          log=print) -> tuple[list[Chunk], dict]:
    t0 = time.monotonic()
    log("Parsing")
    docs = collect(data, log)
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        (PARSED_DIR / f"{doc.doc_id}.md").write_text(doc.markdown, encoding="utf-8")

    chunks = [c for doc in docs for c in chunk_document(doc)]
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids)), "chunk ids must be unique"
    by_status: dict[str, int] = {}
    for c in chunks:
        by_status[c.status] = by_status.get(c.status, 0) + 1
    words = [len(c.text.split()) for c in chunks]
    log(f"Chunking: {len(docs)} documents → {len(chunks)} chunks "
        f"({', '.join(f'{n} {s}' for s, n in sorted(by_status.items()))}), "
        f"{min(words)}–{max(words)} words, median {sorted(words)[len(words) // 2]}")

    embedder = embedder or LocalEmbedder()
    log(f"Embedding with {embedder.name} (local, free)")
    stats = save_index(chunks, embedder, index_path)
    log(f"Saved {stats['chunks']} chunks to {index_path.relative_to(REPO) if index_path.is_relative_to(REPO) else index_path}: "
        f"{stats['embedded']} embedded, {stats['reused']} unchanged, {stats['removed']} removed "
        f"· {time.monotonic() - t0:.1f}s")
    return chunks, stats


def show(chunk: dict) -> None:
    print(f"── {chunk['id']}   ({chunk['source']}"
          + (f", page {chunk['page']}" if chunk["page"] else "") + f", {chunk['status']})")
    print(chunk["text"])
    print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the Copilot's knowledge base.")
    ap.add_argument("--show", metavar="CHUNK_ID", help="print one chunk from the saved index")
    ap.add_argument("--sample", type=int, metavar="N", help="print N random chunks from the saved index")
    ap.add_argument("--list", action="store_true", help="list every chunk id")
    args = ap.parse_args(argv)

    if args.show or args.sample or args.list:
        idx = Index()
        if args.list:
            for c in idx.chunks:
                print(f"{c['id']:42} {c['status']:9} {len(c['text'].split()):4} words  {c['source']}")
        if args.show:
            if args.show not in idx.by_id:
                print(f"No chunk {args.show!r}. Try --list.")
                return 1
            show(idx.by_id[args.show])
        if args.sample:
            for c in random.Random(7).sample(idx.chunks, args.sample):
                show(c)
        return 0

    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
