"""Part 1: one invoice in, validated JSON out.

    document -> page images -> a vision call with a schema -> an Invoice object

Run:
    uv run python labs/invoices/done/extract.py --estimate            # tokens and $ first, no call
    uv run python labs/invoices/done/extract.py inv-01                # one invoice, printed as JSON
    uv run python labs/invoices/done/extract.py inv-01 --provider openai

Results are cached in .shopkart/invoice-cache/ by file hash and model, so a
second run costs nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # the repo root, where shopkart/ lives

import pages  # noqa: E402
from shopkart import budget, data  # noqa: E402
from shopkart.llm import DEFAULT_MODELS, LLM, LLMError, image_block, user_message  # noqa: E402
from shopkart.pricing import cost_usd, usd_to_inr  # noqa: E402

PROMPT_VERSION = "inv-v1"  # stored with every row: which prompt and schema read it
MAX_TOKENS = 1500

# A rough size for what isn't the image: the instructions, the schema, the JSON answer.
TEXT_TOKENS_EST = 2100
OUTPUT_TOKENS_EST = 300


# --------------------------------------------------------------------------
# The schema. Every field allows null: if it can't be read, null, not a guess.
# --------------------------------------------------------------------------


class LineItem(BaseModel):
    description: str | None
    hsn: str | None = Field(description="HSN or SAC code, digits only")
    qty: float | None
    unit_price_inr: float | None = Field(description="the rate per unit, in rupees")
    taxable_value_inr: float | None = Field(description="the line amount before tax")
    gst_rate_pct: float | None = Field(description="the GST rate printed on this line, e.g. 18")


class Invoice(BaseModel):
    supplier_name: str | None
    supplier_gstin: str | None = Field(description="the seller's 15-character GSTIN, null if none is printed")
    buyer_name: str | None
    buyer_gstin: str | None
    # TODO 3: the rest of the invoice. Same names as data/invoices/expected.json,
    # every one nullable (`| None`), with a Field(description=...) where it helps the model:
    #   invoice_number (str), invoice_date (str, "as YYYY-MM-DD"), place_of_supply (str),
    #   line_items (list[LineItem]), taxable_value_inr, cgst_inr, sgst_inr, igst_inr, total_inr (float)
    #   Tip: tell the model a tax line that isn't printed is 0.

    # Normalise in code: rules can only compare clean values.
    @field_validator("supplier_gstin", "buyer_gstin")
    @classmethod
    def clean_gstin(cls, v: str | None) -> str | None:
        v = re.sub(r"[\s-]", "", v or "").upper()
        return v or None

    @field_validator("invoice_date", check_fields=False)
    @classmethod
    def iso_date(cls, v: str | None) -> str | None:
        if not v:
            return None
        if m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", v.strip()):  # DD/MM/YYYY
            v = f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"
        date.fromisoformat(v)  # raises (and so retries once) if it isn't a real date
        return v


SYSTEM = (
    "You read supplier invoices for ShopKart, an Indian online store. "
    "Copy each value exactly as printed on the page: do not correct, round or recompute anything, "
    "even if the numbers look wrong. Amounts are plain numbers in rupees: 2,49,200.00 becomes 249200. "
    "If a field is not printed, or you cannot read it, use null."
)
ASK = "Extract this GST invoice."


# --------------------------------------------------------------------------
# One extraction
# --------------------------------------------------------------------------


@dataclass
class Extraction:
    file: str
    sha256: str
    invoice: Invoice | None
    pages: int
    image_tokens_est: int
    sharpness: float
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    cached: bool = False
    error: str | None = None


def file_hash(path: Path) -> str:
    """A fingerprint of the original bytes: the first idempotency key."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def find(name: str) -> Path:
    """'inv-01' or a full file name, inside data/invoices/."""
    for f in data.invoice_files():
        if f.name == name or f.stem.startswith(name):
            return f
    p = Path(name)
    if p.exists():
        return p
    raise SystemExit(f"No invoice matches {name!r}")


def estimate(path: Path, model: str) -> tuple[int, float]:
    """(input tokens, $) for one invoice, before any call."""
    tokens = sum(pages.image_tokens(img) for img in pages.prepare(path)) + TEXT_TOKENS_EST
    return tokens, cost_usd(model, tokens, OUTPUT_TOKENS_EST)


def extract(llm: LLM, path: Path, use_cache: bool = True) -> Extraction:
    """Read one invoice with a vision call. Never raises for a bad read: `error` says what went wrong."""
    path = Path(path)
    sha = file_hash(path)
    images = pages.prepare(path)
    ex = Extraction(file=path.name, sha256=sha, invoice=None, pages=len(images),
                    image_tokens_est=sum(pages.image_tokens(i) for i in images),
                    sharpness=round(min(pages.sharpness(p) for p in pages.load_pages(path)), 1),
                    provider=llm.provider, model=llm.model)

    cache = budget.LEDGER_DIR / "invoice-cache" / f"{sha[:16]}-{llm.model}-{PROMPT_VERSION}.json"
    if use_cache and cache.exists():
        saved = json.loads(cache.read_text())
        ex.invoice = Invoice.model_validate(saved["invoice"])
        ex.input_tokens, ex.output_tokens = saved["input_tokens"], saved["output_tokens"]
        ex.cached = True
        return ex

    # TODO 4: the vision call.
    #   - each page -> image_block(pages.to_png(img), "image/png")
    #   - one user_message(ASK, blocks), sent with llm.complete(..., system=SYSTEM,
    #     schema=Invoice, max_tokens=MAX_TOKENS)
    #   - an LLMError (SchemaError included: one retry already happened) is not a crash:
    #     set ex.error = f"{err.kind}: {err}" and return ex, so a person types it in.
    raise NotImplementedError("TODO 4: read the invoice with a vision call")
    result: Any = None
    ex.invoice = result.parsed  # type: ignore[assignment]
    ex.input_tokens, ex.output_tokens = result.input_tokens, result.output_tokens
    ex.cost_usd, ex.latency_s = result.cost_usd, result.latency_s

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"invoice": ex.invoice.model_dump(), "input_tokens": ex.input_tokens,
                                 "output_tokens": ex.output_tokens}, indent=2))
    return ex


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def print_estimate(files: list[Path], model: str) -> float:
    total = 0.0
    print(f"{'file':<34}{'pages':>6}{'~in tokens':>12}{'~$':>11}")
    for f in files:
        tokens, usd = estimate(f, model)
        total += usd
        print(f"{f.name:<34}{len(pages.prepare(f)):>6}{tokens:>12}{usd:>11.6f}")
    print(f"\n{len(files)} invoice{'s' * (len(files) != 1)} on {model}: about ${total:.4f} (₹{usd_to_inr(total):.2f}), "
          f"assuming ~{OUTPUT_TOKENS_EST} output tokens each")
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read one GST invoice into validated JSON.")
    parser.add_argument("names", nargs="*", help="e.g. inv-01 (default: all, with --estimate)")
    parser.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--estimate", action="store_true", help="print tokens and cost, make no call")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s] %(message)s")

    files = [find(n) for n in args.names] or data.invoice_files()
    if args.estimate:
        provider = args.provider or os.environ.get("LLM_PROVIDER", "anthropic")
        print_estimate(files, args.model or DEFAULT_MODELS[provider])
        return 0

    llm = LLM(args.provider, args.model)
    for f in files:
        ex = extract(llm, f, use_cache=not args.no_cache)
        if ex.error:
            print(f"{f.name}: could not read it ({ex.error})")
            continue
        print(json.dumps(ex.invoice.model_dump(), indent=2, ensure_ascii=False))
        how = "cached, $0" if ex.cached else f"${ex.cost_usd:.6f} (₹{usd_to_inr(ex.cost_usd):.4f}) · {ex.latency_s:.1f}s"
        print(f"\n{f.name} · {ex.pages} page · ~{ex.image_tokens_est} image tokens · "
              f"{ex.input_tokens} in / {ex.output_tokens} out · {how}")
    print(f"Today: ${budget.spent_today():.6f} of ${budget.daily_budget_usd():.2f} daily budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())

