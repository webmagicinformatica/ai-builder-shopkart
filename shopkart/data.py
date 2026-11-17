"""Loaders for the shared ShopKart fixtures in `data/`.

Every lab reads data through these functions, so file layouts can change in one place.
Only the standard library is used.

    from shopkart import data
    data.get_order("SK48213")
    data.load_policies()                 # current policies only
    data.load_golden(category="hard")

"Today" for all fixtures is fixed at 2026-11-17 (override with SHOPKART_TODAY=YYYY-MM-DD),
so return windows give the same answers whenever the labs are run.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(os.environ.get("SHOPKART_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
POLICY_DIR = DATA_DIR / "policies"
POLICY_PDF_DIR = POLICY_DIR / "pdf"
ARCHIVE_DIR = POLICY_DIR / "archive"
PRODUCT_DIR = DATA_DIR / "products"
INVOICE_DIR = DATA_DIR / "invoices"
GOLDEN_DIR = DATA_DIR / "golden"

DEFAULT_TODAY = date(2026, 11, 17)
ORDER_ID_RE = re.compile(r"^SK\d{5}$")


def today() -> date:
    """The fixtures' 'today' (2026-11-17 unless SHOPKART_TODAY is set)."""
    v = os.environ.get("SHOPKART_TODAY")
    return date.fromisoformat(v) if v else DEFAULT_TODAY


# ---------------------------------------------------------------- documents

@dataclass(frozen=True)
class Doc:
    """A markdown policy, product page or guide, with its front matter."""
    doc_id: str
    title: str
    status: str            # current | archived | withdrawn
    path: Path
    text: str              # markdown body, front matter removed
    meta: dict = field(default_factory=dict)

    @property
    def effective(self) -> date | None:
        v = self.meta.get("effective")
        return date.fromisoformat(v) if v else None

    @property
    def is_current(self) -> bool:
        return self.status == "current"


@dataclass(frozen=True)
class Section:
    doc_id: str
    number: str            # "2.1", or "" for the intro before the first numbered heading
    title: str
    heading_path: tuple[str, ...]   # e.g. ("Returns and Refunds Policy", "2. Returns", "2.1 Return window")
    text: str


def _parse_front_matter(raw: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
    if not m:
        return {}, raw
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, raw[m.end():]


def load_doc(path: str | Path) -> Doc:
    path = Path(path)
    meta, body = _parse_front_matter(path.read_text(encoding="utf-8"))
    return Doc(doc_id=meta.get("doc_id", path.stem), title=meta.get("title", path.stem),
               status=meta.get("status", "current"), path=path, text=body.strip() + "\n", meta=meta)


def load_policies(include_archived: bool = False) -> list[Doc]:
    """Current policies; with include_archived=True also the old/withdrawn ones in policies/archive/."""
    docs = [load_doc(p) for p in sorted(POLICY_DIR.glob("*.md"))]
    if include_archived:
        docs += [load_doc(p) for p in sorted(ARCHIVE_DIR.glob("*.md"))]
    return docs


def load_policy(doc_id: str) -> Doc:
    for d in load_policies(include_archived=True):
        if d.doc_id == doc_id:
            return d
    raise KeyError(f"No policy with doc_id {doc_id!r}")


def load_products() -> list[Doc]:
    """Product pages and guides (Stride RN220, SonicBuds X2, shoe care, ...)."""
    return [load_doc(p) for p in sorted(PRODUCT_DIR.glob("*.md"))]


def policy_pdfs() -> list[Path]:
    """shipping-and-delivery.pdf (tables), returns-and-refunds.pdf (two columns), warranty-scanned.pdf (image only)."""
    return sorted(POLICY_PDF_DIR.glob("*.pdf"))


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.*)$")


def sections(doc: Doc) -> list[Section]:
    """Split a document by its headings. Each section keeps its heading path."""
    out: list[Section] = []
    path: list[tuple[int, str]] = []
    number, title, buf = "", doc.title, []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            out.append(Section(doc.doc_id, number, title, tuple(h for _, h in path) or (doc.title,), body))

    for line in doc.text.splitlines():
        m = _HEADING.match(line)
        if not m:
            buf.append(line)
            continue
        flush()
        buf = []
        level, heading = len(m.group(1)), m.group(2).strip()
        path = [(lvl, h) for lvl, h in path if lvl < level] + [(level, heading)]
        n = _NUMBERED.match(heading)
        number, title = (n.group(1), n.group(2)) if n else ("", heading)
    flush()
    return out


# ---------------------------------------------------------------- JSON fixtures

def _read_json(name: str):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


@lru_cache(maxsize=1)
def _orders() -> tuple[dict, ...]:
    return tuple(_read_json("orders.json"))


def load_orders() -> list[dict]:
    return [dict(o) for o in _orders()]


def normalize_order_id(raw: str | None) -> str | None:
    """'sk-48213', ' SK 48213 ' -> 'SK48213'. Returns None if it doesn't look like SK + 5 digits."""
    if not raw:
        return None
    v = re.sub(r"[\s\-]", "", str(raw)).upper()
    return v if ORDER_ID_RE.match(v) else None


def get_order(order_id: str) -> dict | None:
    """One order by ID (exact SK + 5 digits after normalising), or None if not found."""
    oid = normalize_order_id(order_id)
    for o in _orders():
        if o["order_id"] == oid:
            return dict(o)
    return None


def orders_for_customer(customer_id: str) -> list[dict]:
    return [dict(o) for o in _orders() if o["customer_id"] == customer_id]


def days_since_delivery(order: dict, on: date | None = None) -> int | None:
    """Whole days from delivery to `on` (default: fixtures' today). None if not delivered."""
    if not order.get("delivered_on"):
        return None
    return ((on or today()) - date.fromisoformat(order["delivered_on"])).days


def load_customers() -> list[dict]:
    return _read_json("customers.json")


def get_customer(customer_id: str) -> dict | None:
    return next((c for c in load_customers() if c["customer_id"] == customer_id), None)


def load_tickets(tag: str | None = None) -> list[dict]:
    """Support tickets; filter by a label tag such as 'injection', 'pii', 'hinglish', 'angry'."""
    t = _read_json("tickets.json")
    return [x for x in t if tag in x["labels"]["tags"]] if tag else t


def load_golden(category: str | None = None) -> list[dict]:
    """The 150-case golden set. category: 'everyday' | 'hard' | 'must_handover'."""
    rows = _read_jsonl(GOLDEN_DIR / "golden-150.jsonl")
    return [r for r in rows if r["category"] == category] if category else rows


def load_rag50() -> list[dict]:
    """The 50 policy questions, each with expected answer, source_doc and section."""
    return _read_jsonl(GOLDEN_DIR / "rag-50.jsonl")


def invoice_files() -> list[Path]:
    return sorted(p for p in INVOICE_DIR.iterdir() if p.suffix in (".pdf", ".png"))


def load_invoice_expected() -> list[dict]:
    """Ground truth for each invoice file, including expected_validation_errors."""
    return json.loads((INVOICE_DIR / "expected.json").read_text(encoding="utf-8"))


def load_workload() -> list[dict]:
    """200 customer questions for the cost lab, with cluster and easy/hard labels."""
    return _read_jsonl(DATA_DIR / "workload.jsonl")
