"""Step 1: turn every document into clean Markdown, with its metadata.

Markdown pages already have structure: we read the front matter (doc_id,
version, effective date, status) and keep the body as it is.

PDFs don't: a PDF only holds drawing instructions. So each page is routed:
  - almost no characters    -> a scan: it needs OCR, so we flag it loudly
  - a gap down the middle   -> two columns: read the left column, then the right
  - tables                  -> one sentence per row, with the headers repeated
  - big or bold lines       -> headings (#, ##, ###), so chunking can use them
  - the same line on every page (header, footer, page numbers) -> removed
Each page starts with a `<!-- page N -->` marker, so chunks know their page.

Try it:  uv run python labs/rag/start/parse.py data/policies/pdf/shipping-and-delivery.pdf
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

MIN_CHARS = 50  # fewer characters than this on a page: it's a picture of a page, not text


@dataclass
class Parsed:
    """One document as clean Markdown, plus what we know about it."""

    doc_id: str
    source: str  # the file it came from
    markdown: str
    meta: dict = field(default_factory=dict)  # title, version, effective, status, type, ...
    pages_needing_ocr: list[int] = field(default_factory=list)


# --------------------------------------------------------------------------
# Markdown: front matter + body
# --------------------------------------------------------------------------


def parse_front_matter(text: str) -> tuple[dict, str]:
    """Split '---\\nkey: value\\n---\\nbody' into ({key: value}, body)."""
    if not text.startswith("---\n"):
        return {}, text
    head, _, body = text[4:].partition("\n---\n")
    meta = {}
    for line in head.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip().strip('"')
    return meta, body.lstrip("\n")


def parse_markdown(path: Path) -> Parsed:
    meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
    doc_id = meta.get("doc_id", path.stem)
    meta.setdefault("type", "policy")
    meta.setdefault("status", "current")
    meta.setdefault("title", _first_heading(body) or doc_id)
    return Parsed(doc_id, _rel(path), body.strip() + "\n", meta)


# --------------------------------------------------------------------------
# PDF: route each page, keep headings and tables
# --------------------------------------------------------------------------


def table_to_sentences(rows: list[list[str | None]]) -> list[str]:
    """One sentence per row, headers repeated: every row still makes sense on its own.

    [["Order value", "Metro cities", "Other cities"], ["Below ₹499", "₹49", "₹79"]]
      -> ["Order value: Below ₹499; Metro cities: ₹49; Other cities: ₹79."]
    """
    # TODO 2: Turn a table (a list of rows, the first one is the header) into one
    # sentence per row, headers repeated: "Order value: Below ₹499; Metro cities: ₹49."
    # Join cells' line breaks with spaces, skip empty cells and repeated header rows.
    raise NotImplementedError("TODO 2")


def _heading_level(size: float, body_size: float) -> int | None:
    """Bigger than the body text means a heading. The biggest is the title."""
    if size >= body_size + 5:
        return 1
    if size >= body_size + 2:
        return 2
    if size >= body_size + 0.8:
        return 3
    return None


def route_page(page) -> str:
    """Which path does this page take? "scan", "two_columns" or "text".

    A scan has (almost) no characters: it's a picture of a page, and a basic
    extractor returns an empty string without any error. A two-column page has a
    gutter: no character crosses a strip down the middle of the page.
    """
    # TODO 1: Route the page: return "scan" if it has fewer than MIN_CHARS characters,
    # "two_columns" if no character crosses a strip down the middle (a gutter),
    # otherwise "text". Tip: page.chars is a list of dicts with x0, x1, top.
    raise NotImplementedError("TODO 1")


def _region_items(region, body_size: float) -> list[tuple[float, float, str]]:
    """(top, bottom, markdown line) for one column: headings, text lines, table sentences."""
    tables = region.find_tables()
    boxes = [t.bbox for t in tables]
    items: list[tuple[float, float, str]] = []
    for t in tables:
        for sentence in table_to_sentences(t.extract()):
            items.append((t.bbox[1], t.bbox[3], f"- {sentence}"))

    def outside_tables(obj) -> bool:
        x, y = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
        return not any(x0 <= x <= x1 and top <= y <= bottom for x0, top, x1, bottom in boxes)

    for line in region.filter(outside_tables).extract_text_lines():
        size = max(c["size"] for c in line["chars"])
        level = _heading_level(size, body_size)
        text = line["text"].strip()
        items.append((line["top"], line["bottom"], "#" * level + " " + text if level else text))
    items.sort(key=lambda item: item[0])  # a stable sort keeps table rows in order
    return items


def _join_lines(items: list[tuple[float, float, str]]) -> list[str]:
    """Glue wrapped lines back into paragraphs.

    A line continues the block above it unless it's a heading, a bullet, a table
    row, or there's a blank gap between them (a new paragraph).
    """
    out: list[str] = []
    prev_bottom = None
    for top, bottom, line in items:
        if line.startswith("•"):
            line = "- " + line.lstrip("• ").strip()
        prev = out[-1] if out else ""
        gap = prev_bottom is None or top - prev_bottom > 4 or top < prev_bottom - 20  # new column/page
        new_block = (gap or line.startswith(("#", "- ", "<!--")) or prev.startswith(("#", "<!--"))
                     or _is_table_row(prev)
                or (prev.startswith("- ") and prev.endswith(".") and line[:1].isupper()))  # text after a list
        if prev.startswith("# ") and line.startswith("# "):
            out[-1] = prev + " " + line[2:]  # a title that wraps onto two lines
        elif new_block:
            out.append(line)
        elif prev.endswith("-") and not prev.endswith(" -"):
            out[-1] = prev[:-1] + line  # a word broken by a hyphen at the line end
        else:
            out[-1] = prev + " " + line
        prev_bottom = bottom
    return out


def _is_table_row(line: str) -> bool:
    return line.startswith("- ") and ": " in line and "; " in line


def parse_pdf(path: Path) -> Parsed:
    pages_needing_ocr: list[int] = []
    page_items: list[list[tuple[float, float, str]]] = []
    with pdfplumber.open(path) as pdf:
        sizes = Counter(round(c["size"], 1) for p in pdf.pages for c in p.chars)
        body_size = sizes.most_common(1)[0][0] if sizes else 10.0
        for page in pdf.pages:
            route = route_page(page)
            if route == "scan":
                pages_needing_ocr.append(page.page_number)  # flag it: the gap would be silent
                page_items.append([])
                continue
            if route == "two_columns":
                mid = page.width / 2
                regions = [page.crop((0, 0, mid, page.height)), page.crop((mid, 0, page.width, page.height))]
            else:
                regions = [page]
            items = []
            for region in regions:  # left column first, then the right one
                items += _region_items(region, body_size)
            page_items.append(items)

    # Page furniture: a line that shows up on most pages ("ShopKart Confidential"),
    # or a page number. Remove it everywhere.
    seen = Counter(text for items in page_items for text in {t for _, _, t in items})
    text_pages = sum(1 for items in page_items if items)
    furniture = {text for text, n in seen.items() if text_pages > 1 and n >= text_pages}

    kept: list[tuple[float, float, str]] = []
    for number, items in enumerate(page_items, start=1):
        kept.append((-1, -1, f"<!-- page {number} -->"))
        kept += [it for it in items if it[2] not in furniture and not re.fullmatch(r"Page \d+( of \d+)?", it[2])]
    blocks = _join_lines(kept)
    markdown = "\n\n".join(blocks).strip() + "\n"

    doc_id = path.stem.removesuffix("-scanned")
    title = _first_heading(markdown) or doc_id
    meta = {"title": title, "type": "policy", "status": "current", "format": "pdf"}
    return Parsed(doc_id, _rel(path), markdown, meta, pages_needing_ocr)


# --------------------------------------------------------------------------


def parse(path: Path) -> Parsed:
    """Route by file type."""
    if path.suffix.lower() == ".pdf":
        return parse_pdf(path)
    return parse_markdown(path)


def _first_heading(markdown: str) -> str | None:
    m = re.search(r"^# (.+)$", markdown, flags=re.M)
    return m.group(1).strip() if m else None


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path(__file__).resolve().parents[3]))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    for arg in sys.argv[1:] or ["data/policies/pdf/shipping-and-delivery.pdf"]:
        doc = parse(Path(arg))
        print(f"# --- {doc.source} → doc_id {doc.doc_id} · {doc.meta}")
        if doc.pages_needing_ocr:
            print(f"# !!! pages with no text layer (scans, need OCR): {doc.pages_needing_ocr}")
        print(doc.markdown)
