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
    found: set[str] = set()
    counts: dict[str, int] = {}

    for kind, pattern in PATTERNS:
        def swap(m: re.Match, kind: str = kind) -> str:
            if kind == "CARD" and not _luhn_ok(re.sub(r"\D", "", m.group(0))):
                return m.group(0)  # a long number that isn't a card: leave it
            found.add(kind)
            counts[kind] = counts.get(kind, 0) + 1
            return f"[{kind}_{counts[kind]}]"

        text = pattern.sub(swap, text)
    return text, found


# ---------------------------------------------------------------- 2. delimit untrusted text

TAGS = ("customer_message", "tool_result")


def wrap_untrusted(text: str, tag: str) -> str:
    """Put text we didn't write inside labels, after removing any fake labels from it."""
    for t in TAGS:
        text = re.sub(rf"</?\s*{t}\s*>", "", text, flags=re.I)  # so it can't fake a closing tag
    return f"<{tag}>\n{text}\n</{tag}>"


# ---------------------------------------------------------------- 3. least-privilege tools

ORDER_FIELDS = ("order_id", "status", "placed_on", "promised_by", "delivered_on",
                "total_inr", "payment_method", "tracking_number")


def lookup_order(shop, customer_id: str, order_id: str | None) -> dict:
    """Only the logged-in customer's own orders, and only the fields a reply needs.

    The customer ID comes from the login session, never from the model. Another
    customer's order gets the same answer as an order that doesn't exist.
    No names, no phone numbers, no free-text notes written by someone else.
    """
    order = shop.order(order_id)
    if order is None or order["customer_id"] != customer_id:
        return {"error": "no such order on this customer's account"}
    out = {k: order.get(k) for k in ORDER_FIELDS}
    out["items"] = [{"name": i["name"], "qty": i["qty"], "price_inr": i["unit_price_inr"]} for i in order["items"]]
    out["refunds"] = [{"amount_inr": r["amount_inr"], "status": r["status"]} for r in order.get("refunds", [])]
    out["days_since_delivery"] = data.days_since_delivery(order)
    return out


def draft_refund(shop, customer_id: str, order_id: str | None, amount_inr: int | None, reason: str | None) -> dict:
    """Own orders only, never more than was paid, and code decides when a human must approve.

    The model's opinion on approval isn't even asked. An injection can make the model
    ask for a refund. It can't make the approver click.
    """
    order = shop.order(order_id)
    if order is None or order["customer_id"] != customer_id:
        return {"error": "no such order on this customer's account"}
    amount = int(amount_inr or 0)
    already = shop.refunded_so_far(order["order_id"]) + sum(r["amount_inr"] for r in order.get("refunds", []))
    if amount <= 0 or amount + already > order["total_inr"]:
        return {"error": f"amount must be between ₹1 and ₹{order['total_inr'] - already:,}"}
    # Count every refund on this order, so ₹4,999 three times is still ₹14,997.
    session_total = shop.refunded_so_far(order["order_id"]) + amount
    status = "awaiting_human" if session_total > APPROVAL_LIMIT_INR else "issued"
    shop.add_refund(order["order_id"], amount, reason or "", status)
    return {"order_id": order["order_id"], "amount_inr": amount, "status": status}


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
    problems: list[str] = []
    if canary in reply:
        return SAFE_REPLY, ["canary (system prompt leaked)"]
    flat = re.sub(r"[\s-]", "", reply).lower()
    typed = re.sub(r"[\s-]", "", seen).lower()
    for value in _other_customers(customer_id):
        v = re.sub(r"[\s-]", "", value).lower()
        if v in flat and v not in typed:
            return SAFE_REPLY, ["another customer's data"]

    def strip_image(m: re.Match) -> str:
        if _host_ok(m.group(1)):
            return m.group(0)
        problems.append("untrusted image")
        return ""

    def strip_link(m: re.Match) -> str:
        if _host_ok(m.group(0)):
            return m.group(0)
        problems.append("untrusted link")
        return "[link removed]"

    reply = IMAGE.sub(strip_image, reply)
    reply = URL.sub(strip_link, reply)
    reply, found = redact(reply)
    if found:
        problems.append("personal data in reply")
    return reply, problems
