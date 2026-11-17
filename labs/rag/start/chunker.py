"""Step 2: cut clean Markdown into chunks, by structure.

A chunk should be the smallest piece of text that still makes sense on its own.
So we cut at the headings the document already has (one chunk per section),
put the heading path on top of every chunk, and only split a section that is
too long, at paragraph breaks, never mid-sentence. A table stays whole.

Every chunk gets a stable id, built from where it lives, not from a counter:
    returns-and-refunds§2.1        (one chunk for the section)
    warranty§2#2                   (part 2 of a long section)
Re-run the ingest and the ids stay the same, so citations and logs keep working.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass

from parse import Parsed

MAX_WORDS = 350  # a section longer than this is split at paragraph breaks

HEADING = re.compile(r"^(#{1,3}) (.+)$")
NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$")  # "2.1 Return window" or "3. Quality check"
PAGE = re.compile(r"^<!-- page (\d+) -->$")


@dataclass
class Chunk:
    id: str  # stable: doc_id§section, plus #part for long sections
    doc_id: str
    section: str  # "2.1", or "intro" for the text under the title
    section_title: str
    heading_path: str  # "Returns and Refunds Policy > 2. Returns > 2.1 Return window"
    text: str  # heading path + section text: what gets embedded and sent to the model
    source: str
    page: int | None
    title: str
    doc_type: str
    status: str  # current, archived, withdrawn
    effective: str
    hash: str  # a fingerprint of the text, to spot changes on the next ingest

    def as_row(self) -> dict:
        return asdict(self)


def split_sections(markdown: str) -> list[dict]:
    """[{level, heading, path, lines, page}] in order, one per heading (plus the intro)."""
    sections: list[dict] = []
    path: list[str] = []
    page: int | None = None
    current = {"level": 1, "heading": "", "path": [], "lines": [], "page": None}
    for line in markdown.splitlines():
        if m := PAGE.match(line.strip()):
            page = int(m.group(1))
            if not current["lines"]:
                current["page"] = page
            continue
        if m := HEADING.match(line):
            sections.append(current)
            level, heading = len(m.group(1)), m.group(2).strip()
            path = path[: level - 1] + [heading]
            current = {"level": level, "heading": heading, "path": list(path), "lines": [], "page": page}
            continue
        current["lines"].append(line)
    sections.append(current)
    return sections


def _section_id(heading: str, level: int) -> tuple[str, str]:
    """('2.1', 'Return window') from '2.1 Return window'. The title heading is the intro."""
    if level == 1 or not heading:
        return "intro", heading
    if m := NUMBERED.match(heading):
        return m.group(1), m.group(2)
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-"), heading


def _paragraphs(lines: list[str]) -> list[str]:
    """Blank-line separated blocks. A table (lines starting with |) stays one block."""
    text = "\n".join(lines).strip()
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _pack(paragraphs: list[str], max_words: int) -> list[str]:
    """Greedy: add whole paragraphs to a part until the next one would pass max_words."""
    parts: list[list[str]] = [[]]
    words = 0
    for p in paragraphs:
        n = len(p.split())
        if parts[-1] and words + n > max_words:
            parts.append([])
            words = 0
        parts[-1].append(p)
        words += n
    return ["\n\n".join(part) for part in parts if part]


def chunk_document(doc: Parsed, max_words: int = MAX_WORDS) -> list[Chunk]:
    # TODO 3: One chunk per section from split_sections(doc.markdown). Skip sections
    # with no text. section, section_title = _section_id(...). Text = heading path,
    # a blank line, then the body. Long sections: _pack() into parts, ids get #1, #2.
    # Stable id: f"{doc.doc_id}§{section}". Fill every Chunk field, hash included.
    raise NotImplementedError("TODO 3")
