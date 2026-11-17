"""Part 2: the layers that make a fooled Copilot harmless.

Soft layers lower the odds:  wrap_untrusted (labels around text we didn't write).
Hard layers live in code:    redact, lookup_order, draft_refund, check_output.

No single layer stops prompt injection. Assume the model will be fooled, and
make sure a fooled model can't do much harm.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from shopkart import data

APPROVAL_LIMIT_INR = 5000          # refunds above ₹5,000 need a human: decided here, in code
TRUSTED_DOMAINS = ("shopkart.in",)  # the only links and images a reply may carry
SAFE_REPLY = "Sorry, I can't help with that here. A colleague from ShopKart will follow up with you."


# ---------------------------------------------------------------- 1. redact at the front door


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


PATTERNS: list[tuple[str, re.Pattern]] = [
    # Order matters: the longest numbers first, so a card isn't read as a phone.
    ("CARD", re.compile(r"\b\d(?:[ -]?\d){12,18}\b")),                 # then a Luhn check
    ("AADHAAR", re.compile(r"\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b")),      # 12 digits, never starts 0 or 1
    ("CVV", re.compile(r"(?i)\b(cvv|cvc)\b\s*(?:is|:)?\s*\d{3,4}\b")),
    ("OTP", re.compile(r"(?i)\botp\b\s*(?:is|:)?\s*\d{4,8}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),                     # 5 letters, 4 digits, a letter
    ("PHONE", re.compile(r"(?:\+91[ -]?)?\b[6-9]\d{4}[ -]?\d{5}\b")),   # 10 digits starting 6-9
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("UPI", re.compile(r"\b[\w.-]+@(?:ok\w+|ybl|upi|paytm|ibl|axl)\b", re.I)),
]


def redact(text: str) -> tuple[str, set[str]]:
    """Swap personal data for placeholders like [CARD_1]. Returns (masked text, kinds found).

    Run it first, before anything is logged or sent to the model.
    """
    # TODO 4: Run every pattern in PATTERNS, in order. Replace each match with a numbered
    # placeholder like [CARD_1], [PHONE_2], and add the kind to `found`.
    # For CARD, keep the match unchanged if _luhn_ok() fails (it isn't a card).
    raise NotImplementedError("TODO 4")


# ---------------------------------------------------------------- 2. delimit untrusted text

TAGS = ("customer_message", "tool_result")


def wrap_untrusted(text: str, tag: str) -> str:
    """Put text we didn't write inside labels, after removing any fake labels from it."""
    # TODO 5: Remove any <customer_message> / <tool_result> tags (opening or closing,
    # any case) from the text, then wrap it: f"<{tag}>\n{text}\n</{tag}>".
    raise NotImplementedError("TODO 5")


# ---------------------------------------------------------------- 3. least-privilege tools

ORDER_FIELDS = ("order_id", "status", "placed_on", "promised_by", "delivered_on",
                "total_inr", "payment_method", "tracking_number")


def lookup_order(shop, customer_id: str, order_id: str | None) -> dict:
    """Only the logged-in customer's own orders, and only the fields a reply needs.

    The customer ID comes from the login session, never from the model. Another
    customer's order gets the same answer as an order that doesn't exist.
    No names, no phone numbers, no free-text notes written by someone else.
    """
    # TODO 6: Return {"error": ...} unless the order exists AND belongs to customer_id.
    # Return only ORDER_FIELDS, the items (name, qty, price) and the refunds
    # (amount, status). No names, phones, addresses or notes.
    raise NotImplementedError("TODO 6")


def draft_refund(shop, customer_id: str, order_id: str | None, amount_inr: int | None, reason: str | None) -> dict:
    """Own orders only, never more than was paid, and code decides when a human must approve.

    The model's opinion on approval isn't even asked. An injection can make the model
    ask for a refund. It can't make the approver click.
    """
    # TODO 7: Own orders only. Amount between ₹1 and what's left after earlier refunds.
    # Status: "awaiting_human" if this order's refunds in the session (including
    # this one) go above APPROVAL_LIMIT_INR, else "issued". Record it with
    # shop.add_refund(...) and return order_id, amount_inr and status.
    raise NotImplementedError("TODO 7")


# ---------------------------------------------------------------- 4. check what goes out


def _other_customers(customer_id: str) -> list[str]:
    """Names, phones, emails and order IDs that belong to anyone else."""
    out: list[str] = []
    for c in data.load_customers():
        if c["customer_id"] != customer_id:
            out += [c["name"], c["phone"][-10:], c["email"], *c["order_ids"]]
    return out


def _host_ok(url: str) -> bool:
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in TRUSTED_DOMAINS)


IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)[^)]*\)")
URL = re.compile(r"https?://[^\s)\]>\"']+")


def check_output(reply: str, customer_id: str, canary: str, seen: str = "") -> tuple[str, list[str]]:
    """Check a reply before anyone sees it. Returns (safe reply, problems found).

    `seen` is what the customer typed: an order ID they gave us isn't a leak.
    """
    # TODO 8: 1. Canary in the reply: return SAFE_REPLY. 2. Another customer's data
    # (_other_customers) not typed by the customer (`seen`): return SAFE_REPLY.
    # 3. Remove images (IMAGE) and links (URL) whose host isn't trusted (_host_ok).
    # 4. redact() the reply. Return (reply, problems).
    raise NotImplementedError("TODO 8")
