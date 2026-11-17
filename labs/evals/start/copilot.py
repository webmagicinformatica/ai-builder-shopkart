"""The system under test: a simple ShopKart Copilot with the policies in its prompt.

No retrieval: all 13 current policies go into the system prompt (about 13,000
tokens), cached, so after the first call each answer pays about a tenth for them.
It answers with a typed Reply, so the handover decision is a field we can check.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field

from cases import load_orders, load_policies

PROMPT_VERSION = "v1"
TODAY = "Tuesday 17 November 2026"

INSTRUCTIONS = f"""You are the ShopKart Support Copilot. ShopKart is an Indian online store.
Today is {TODAY}.

Rules:
- Answer only from the policies below and the order data you are given. Never invent a rule, an amount, a date or a timeline.
- Hand over to a human (handover = true) whenever the escalation policy says so: refunds above ₹5,000, exceptions outside policy, questions the policies don't cover, legal threats, safety, privacy, account takeover, a customer who asks for a person, and the other triggers listed there. When you hand over, say so and say why, and promise nothing.
- Reply in the customer's language (English, Hindi or Hinglish), in at most four short sentences.

The policies:
"""


class Reply(BaseModel):
    """The Copilot's answer to one customer message."""

    reply: str = Field(description="what the customer reads")
    handover: bool = Field(description="true if a human agent must take over this conversation")


@lru_cache(maxsize=1)
def policies() -> str:
    return load_policies()


@lru_cache(maxsize=1)
def system_prompt() -> str:
    return INSTRUCTIONS + "\n" + policies()


@lru_cache(maxsize=1)
def orders() -> dict[str, dict[str, Any]]:
    return load_orders()


def user_message(case: dict[str, Any]) -> str:
    """The customer's question, with the order record when the case is about one."""
    order_id = case.get("order_id")
    if order_id and order_id in orders():
        order = json.dumps(orders()[order_id], ensure_ascii=False)
        return f"<order>\n{order}\n</order>\n\nCustomer: {case['question']}"
    return f"Customer: {case['question']}"


def answer(llm: Any, case: dict[str, Any]) -> tuple[Reply, Any]:
    """Ask the Copilot one case. Returns (the typed Reply, the call's Result)."""
    result = llm.complete(user_message(case), system=system_prompt(), schema=Reply,
                          max_tokens=400, cache_system=True)
    return result.parsed, result
