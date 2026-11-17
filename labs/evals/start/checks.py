"""Code checks: cheap, fast, and the same result every time.

Each check returns a Check: passed is True, False, or None when the check
doesn't apply to this case (a question with no return window has nothing to
check for "14 days").

  days       the answer names the return window the case expects: 14, 10 or 7 days
  handover   handed over exactly when the case says it must
  must_not   none of the case's forbidden phrases ("30 days", "refund is approved")
  amounts    every ₹ amount in the answer exists in the policies, the order or the question
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

WINDOW_DAYS = {14: "14|fourteen", 10: "10|ten", 7: "7|seven"}


@dataclass
class Check:
    name: str
    passed: bool | None  # None: not applicable
    note: str = ""


# ---- 1. the return window ------------------------------------------------

def required_days(case: dict[str, Any]) -> set[int]:
    """Which windows the expected notes name: '14 days', 'within 10 days', '7 days for electronics'."""
    found = set()
    for phrase in case.get("expected", []):
        for m in re.finditer(r"\b(14|10|7) days\b", phrase):
            found.add(int(m.group(1)))
    return found


def mentions_days(text: str, n: int) -> bool:
    """'10 days', '10-day', 'ten days', '10 din' (Hinglish), but not '7 working days'."""
    return re.search(rf"\b(?:{WINDOW_DAYS[n]})[\s-]*(?:days?|din)\b", text, re.IGNORECASE) is not None


def check_days(case: dict[str, Any], reply: str) -> Check:
    # TODO 2: the return window.
    #   - required_days(case) gives the windows the case expects, e.g. {10}
    #   - none: Check("days", None), the check doesn't apply
    #   - any window the reply doesn't mention (mentions_days): Check("days", False, "doesn't mention 10 days")
    #   - otherwise Check("days", True, "10 days")
    raise NotImplementedError("TODO 2: check_days")


# ---- 2. handover ---------------------------------------------------------

def check_handover(case: dict[str, Any], handover: bool) -> Check:
    # TODO 3: handover flagged exactly when it should be.
    #   - case["must_handover"] says what should happen; `handover` is what the Copilot did
    #   - both ways are failures, with different notes:
    #     "should hand over, but answered" (the dangerous one) / "handed over, but should answer"
    raise NotImplementedError("TODO 3: check_handover")


# ---- 3. forbidden phrases ------------------------------------------------

def check_must_not(case: dict[str, Any], reply: str) -> Check:
    """A forbidden phrase must not appear. A one-word phrase ('yes', 'no') only
    counts at the start of the reply, where it is the answer."""
    phrases = case.get("must_not", [])
    if not phrases:
        return Check("must_not", None)
    low = reply.lower().replace("’", "'")
    hits = []
    for p in dict.fromkeys(phrases):  # the golden set repeats some phrases
        p_low = p.lower()
        if " " not in p_low.strip():
            if re.match(rf"\W*{re.escape(p_low)}\b", low):
                hits.append(p)
        elif re.search(rf"(?<!\w){re.escape(p_low)}(?!\w)", low):
            hits.append(p)
    if hits:
        return Check("must_not", False, "says " + ", ".join(f'"{h}"' for h in hits))
    return Check("must_not", True)


# ---- 4. no made-up amounts -----------------------------------------------

AMOUNT = re.compile(r"(?:₹|\brs\.?|\binr)\s*(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s*(?:rupees|/-)",
                    re.IGNORECASE)


def amounts_in(text: str) -> set[int]:
    """Every rupee amount in a text, as whole rupees: '₹5,000' -> 5000."""
    found = set()
    for m in AMOUNT.finditer(text):
        raw = (m.group(1) or m.group(2)).replace(",", "")
        found.add(round(float(raw)))
    return found


def all_numbers(text: str) -> set[int]:
    """Any number at all: the order record stores prices as plain numbers (unit_price_inr: 1299)."""
    return {round(float(n.replace(",", ""))) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)
            if n.replace(",", "").replace(".", "").isdigit()}


def allowed_amounts(policies: str, question: str, order: dict[str, Any] | None) -> set[int]:
    """The amounts an answer may use: ₹ amounts in the policies, any number in the order or question."""
    return amounts_in(policies) | all_numbers(question) | all_numbers(json.dumps(order) if order else "")


def check_amounts(reply: str, allowed: set[int]) -> Check:
    # TODO 4: no made-up amounts.
    #   - amounts_in(reply) finds every ₹ amount in the answer
    #   - none: the check doesn't apply
    #   - any amount not in `allowed`: fail, and name it ("not in policy or order: ₹1,500")
    raise NotImplementedError("TODO 4: check_amounts")


# ---- all of them ---------------------------------------------------------

def run_checks(case: dict[str, Any], reply: str, handover: bool, policies: str,
               order: dict[str, Any] | None = None) -> list[Check]:
    allowed = allowed_amounts(policies, case["question"], order)
    return [
        check_days(case, reply),
        check_handover(case, handover),
        check_must_not(case, reply),
        check_amounts(reply, allowed),
    ]


def code_pass(checks: list[Check | dict[str, Any]]) -> bool:
    """A case passes the code checks when no applicable check failed."""
    return all((c.passed if isinstance(c, Check) else c["passed"]) is not False for c in checks)


def as_dicts(checks: list[Check]) -> list[dict[str, Any]]:
    return [asdict(c) for c in checks]
