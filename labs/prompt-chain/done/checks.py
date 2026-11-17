"""Checks we run on every answer, from the mega-prompt and from the chain alike.

Each check returns a short label for the table: "missed handover",
"wrong window 14d", "broken format", "promised refund", "reply not in hinglish", "too long".
"""

from __future__ import annotations

import re

import facts

WINDOW_CLAIMS = [
    re.compile(r"(\d+)[- ]days?\s+(?:return\s+|exchange\s+)?window", re.I),
    re.compile(r"within\s+(\d+)\s+days", re.I),
    re.compile(r"(\d+)\s+days?\s+(?:of|from|after)\s+delivery", re.I),
    re.compile(r"(\d+)\s+din\s+(?:ke andar|tak|mein)", re.I),
]

CLOSED = re.compile(
    r"\b(?:past|outside|after|beyond)\b[^.]{0,40}\bwindow\b|\bwindow\b[^.]{0,30}\b(?:closed|has passed|is over|ended)\b",
    re.I,
)

PROMISES = re.compile(
    r"\b(?:I've|I have|we've|we have)\s+(?:processed|approved|issued|refunded)\b"
    r"|\b(?:has|have) been (?:processed|approved|issued|refunded)\b"
    r"|\brefund is (?:processed|approved|confirmed)\b"
    r"|\b(?:approve|process|refund)\s+(?:ho gaya|ho gayi|kar diya|kar di)\b",   # Hinglish
    re.I,
)


HINGLISH = {"hai", "hain", "aap", "aapka", "aapki", "aapke", "main", "mein", "ke", "ki", "ka", "ko", "nahi",
            "sakta", "sakti", "kar", "karti", "karta", "liye", "abhi", "kya", "hoon", "yeh", "se", "par"}


def language_ok(language: str, reply: str) -> bool:
    """A Hindi or Hinglish message needs a Hindi or Hinglish reply (a rough check, by common words)."""
    if language not in ("hi", "hinglish"):
        return True
    if any("\u0900" <= ch <= "\u097f" for ch in reply):  # Devanagari
        return True
    words = re.findall(r"[a-z]+", reply.lower())
    return sum(w in HINGLISH for w in words) >= 4


def windows_claimed(reply: str) -> set[int]:
    """Every 'N days' return window the reply states."""
    return {int(n) for pattern in WINDOW_CLAIMS for n in pattern.findall(reply)}


def days_since_delivery(case: dict) -> int | None:
    order = facts.orders().get(facts.tickets()[case["ticket_id"]]["order_id"] or "")
    return facts.order_facts(order)["days_since_delivery"] if order else None


def problems(case: dict, decision: str | None, reply: str, *, format_ok: bool = True,
             max_words: int = 120) -> list[str]:
    found = []
    if not format_ok:
        found.append("broken format")
    if case["expected"] == "handover" and decision != "handover":
        found.append("missed handover")
    elif decision != case["expected"]:
        found.append(f"wrong decision ({decision or '?'})")
    wrong = sorted(n for n in windows_claimed(reply) if n != case["window_days"])
    if wrong:
        found.append(f"wrong window {', '.join(f'{n}d' for n in wrong)} (is {case['window_days']}d)")
    days = days_since_delivery(case)
    if days is not None and days <= case["window_days"] and CLOSED.search(reply):
        found.append(f"says window closed (day {days} of {case['window_days']})")
    if PROMISES.search(reply):
        found.append("promised refund")
    language = facts.tickets()[case["ticket_id"]]["language"]
    if reply and not language_ok(language, reply):
        found.append(f"reply not in {language}")
    if len(reply.split()) > max_words:
        found.append(f"too long ({len(reply.split())} words)")
    return found
