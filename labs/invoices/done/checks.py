"""Part 2, step 1: the model reads, your code checks.

A schema only checks the shape. These rules check whether the invoice makes
sense. Every rule that fails returns an Issue with a code and a reason a
person can act on. No issues: the invoice can go straight through.

    required fields      supplier GSTIN, invoice number, date, totals, lines
    GSTIN                format (state code + PAN + ...) and the check character
    line items           qty x rate = amount, and the lines add up to the subtotal
    GST                  tax = each line x its rate; CGST+SGST in-state, IGST across states
    total                subtotal + tax = total, give or take one rupee
    billed to us         the buyer GSTIN is ShopKart's own
    scan quality         a blurred photo goes to a person, however good the JSON looks
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from extract import Invoice

TOLERANCE_INR = 1.0                    # rounding: one rupee either way
SHOPKART_GSTIN = "27AAKCS4821M1ZW"     # ShopKart Retail Pvt Ltd, Maharashtra
BLUR_LIMIT = 100                       # see pages.sharpness()

GSTIN_RE = re.compile(r"^(\d{2})([A-Z]{5}\d{4}[A-Z])([1-9A-Z])Z([0-9A-Z])$")
CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
REQUIRED = ["supplier_name", "supplier_gstin", "invoice_number", "invoice_date",
            "taxable_value_inr", "total_inr"]


@dataclass(frozen=True)
class Issue:
    code: str      # e.g. total_mismatch: stable, so you can count and test them
    field: str     # which field a reviewer should look at
    message: str   # the reason, in words

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


# --------------------------------------------------------------------------
# GSTIN: 2-digit state code, the 10-character PAN, entity number, Z, check character
# --------------------------------------------------------------------------


def gstin_check_char(first14: str) -> str:
    """The 15th character, computed from the first 14 (a mod-36 checksum).

    Each character becomes its index in 0-9A-Z. Every second one is doubled.
    Each product is split into (product // 36) + (product % 36) and summed.
    The check character is the one at (36 - sum % 36) % 36.
    """
    total = 0
    for i, ch in enumerate(first14):
        product = CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return CHARS[(36 - total % 36) % 36]


def gstin_problem(gstin: str) -> str | None:
    """None if the GSTIN is valid, else what is wrong with it."""
    m = GSTIN_RE.match(gstin)
    if not m:
        return "not in GSTIN format (2 digits, PAN, entity, Z, check)"
    if not 1 <= int(m.group(1)) <= 38:
        return f"state code {m.group(1)} does not exist"
    expected = gstin_check_char(gstin[:14])
    if gstin[14] != expected:
        return f"check character is {gstin[14]}, should be {expected}: a digit was probably misread"
    return None


def state_code(place_of_supply: str | None) -> str | None:
    """'Maharashtra (27)' -> '27'."""
    m = re.search(r"\b(\d{2})\b", place_of_supply or "")
    return m.group(1) if m else None


def _off(a: float, b: float) -> bool:
    return abs(a - b) > TOLERANCE_INR


def inr(x: float) -> str:
    """Rupees the Indian way: 283604 -> ₹2,83,604.00 (lakhs and crores)."""
    whole, paise = f"{abs(x):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    while head:
        head, tail = head[:-2], f"{head[-2:]},{tail}"
    return f"{'-' if x < 0 else ''}₹{tail}.{paise}"


# --------------------------------------------------------------------------
# All the rules
# --------------------------------------------------------------------------


def validate(inv: Invoice, sharpness: float | None = None) -> list[Issue]:
    issues: list[Issue] = []

    # 1. Required fields: null means "couldn't read it", and that needs a person.
    for name in REQUIRED:
        if getattr(inv, name) in (None, ""):
            issues.append(Issue(f"missing_{name}", name, f"no {name.replace('_', ' ')} on the invoice"))
    if not inv.line_items:
        issues.append(Issue("missing_line_items", "line_items", "no line items found"))

    # 2. GSTIN format and check character.
    for name in ("supplier_gstin", "buyer_gstin"):
        value = getattr(inv, name)
        if value and (problem := gstin_problem(value)):
            issues.append(Issue(f"bad_{name}", name, f"{value}: {problem}"))
    if inv.buyer_gstin and inv.buyer_gstin != SHOPKART_GSTIN and not gstin_problem(inv.buyer_gstin):
        issues.append(Issue("not_billed_to_shopkart", "buyer_gstin",
                            f"billed to {inv.buyer_gstin}, not ShopKart's {SHOPKART_GSTIN}"))

    # 3. Each line: qty x rate = amount.
    for n, line in enumerate(inv.line_items, 1):
        if None not in (line.qty, line.unit_price_inr, line.taxable_value_inr):
            if _off(line.qty * line.unit_price_inr, line.taxable_value_inr):
                issues.append(Issue("line_mismatch", f"line_items[{n}]",
                                    f"line {n}: {line.qty:g} x {inr(line.unit_price_inr)} is not "
                                    f"{inr(line.taxable_value_inr)}"))

    # 4. The lines add up to the subtotal.
    amounts = [line.taxable_value_inr for line in inv.line_items]
    if inv.line_items and None not in amounts and inv.taxable_value_inr is not None:
        if _off(sum(amounts), inv.taxable_value_inr):
            issues.append(Issue("subtotal_mismatch", "taxable_value_inr",
                                f"lines add up to {inr(sum(amounts))}, subtotal says {inr(inv.taxable_value_inr)}"))

    # 5. GST maths: each line's amount x its own rate, against the tax charged.
    tax = (inv.cgst_inr or 0) + (inv.sgst_inr or 0) + (inv.igst_inr or 0)
    rated = [(line.taxable_value_inr, line.gst_rate_pct) for line in inv.line_items]
    if inv.line_items and all(a is not None and r is not None for a, r in rated):
        expected_tax = sum(a * r / 100 for a, r in rated)
        if _off(expected_tax, tax):
            issues.append(Issue("tax_mismatch", "igst_inr" if inv.igst_inr else "cgst_inr",
                                f"tax charged is {inr(tax)}, but the line rates give {inr(expected_tax)}"))

    # 6. Which tax: same state, CGST + SGST in equal halves; different states, IGST.
    seller = inv.supplier_gstin[:2] if inv.supplier_gstin and not gstin_problem(inv.supplier_gstin) else None
    supply = state_code(inv.place_of_supply) or (inv.buyer_gstin or "")[:2] or None
    if seller and supply and tax > 0:
        cgst, sgst, igst = inv.cgst_inr or 0, inv.sgst_inr or 0, inv.igst_inr or 0
        if seller == supply and (igst > 0 or _off(cgst, sgst)):
            issues.append(Issue("wrong_tax_type", "igst_inr",
                                f"seller and place of supply are both state {seller}: expected CGST + SGST, equal halves"))
        if seller != supply and (cgst > 0 or sgst > 0):
            issues.append(Issue("wrong_tax_type", "cgst_inr",
                                f"state {seller} to state {supply} is inter-state: expected IGST, not CGST + SGST"))

    # 7. Subtotal + tax = total.
    if inv.taxable_value_inr is not None and inv.total_inr is not None:
        if _off(inv.taxable_value_inr + tax, inv.total_inr):
            issues.append(Issue("total_mismatch", "total_inr",
                                f"{inr(inv.taxable_value_inr)} + tax {inr(tax)} = "
                                f"{inr(inv.taxable_value_inr + tax)}, but the total says {inr(inv.total_inr)}"))

    # 8. A check on the image itself, not on the model's answer.
    if sharpness is not None and sharpness < BLUR_LIMIT:
        issues.append(Issue("low_quality_scan", "file",
                            f"blurred or tilted photo (sharpness {sharpness:.0f}, limit {BLUR_LIMIT}): "
                            "check every number against the page"))
    return issues


if __name__ == "__main__":
    # Try the GSTIN check by hand:  uv run python labs/invoices/done/checks.py 33AAQFS5532D1Z8
    # By default: a real one, a 6 misread as a 5, and an S misread as a 5.
    import sys

    for value in sys.argv[1:] or ["29AAECN6604H1ZD", "29AAECN5604H1ZD", "33AAQF55532D1Z8"]:
        print(f"{value:<17} {gstin_problem(value.upper()) or 'valid'}")
