"""Part 1 checkpoint: classify 20 ShopKart messages with a typed schema, 0 crashes.

Run:  uv run python labs/llm-client/done/triage.py [--provider openai] [--limit 20]
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from llm_client import LLM, LLMError, SchemaError  # also puts the repo root on sys.path
from shopkart import budget

MESSAGES = Path(__file__).resolve().parent.parent / "messages.json"

SYSTEM = (
    "You triage messages sent to ShopKart, an Indian online store. "
    "Read the customer's message and fill in the fields."
)


class Triage(BaseModel):
    """The ShopKart Copilot's triage of one customer message."""

    intent: Literal["where_is_order", "refund", "cancel", "product", "other"]
    order_id: str | None = Field(description="the order number like SK48213, or null if not given")
    urgency: Literal["low", "normal", "high"]
    summary: str = Field(description="one line, always in English")

    # A rule the schema can't hold: our own check, in our own code.
    @field_validator("order_id")
    @classmethod
    def looks_like_an_order(cls, value: str | None) -> str | None:
        if value is not None and not (len(value) == 7 and value.startswith("SK") and value[2:].isdigit()):
            raise ValueError("order_id must look like SK followed by 5 digits")
        return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s] %(message)s")

    llm = LLM(args.provider)
    messages = json.loads(MESSAGES.read_text())[: args.limit]
    ok = needs_review = crashed = 0
    total_cost = 0.0

    print(f"{'#':>2}  {'intent':<15}{'order':<9}{'urgency':<8}summary")
    for i, message in enumerate(messages, 1):
        try:
            result = llm.complete(message, system=SYSTEM, schema=Triage, max_tokens=200)
        except SchemaError:
            needs_review += 1  # one retry already happened: a human looks at it
            print(f"{i:>2}  needs review")
            continue
        except (LLMError, budget.BudgetExceeded) as exc:
            crashed += 1
            print(f"{i:>2}  FAILED: {exc}")
            continue
        t: Triage = result.parsed  # a real Triage object, not a dict
        total_cost += result.cost_usd
        ok += 1
        print(f"{i:>2}  {t.intent:<15}{t.order_id or '-':<9}{t.urgency:<8}{t.summary}")

    print(
        f"\n{ok} classified, {needs_review} need review, {crashed} crashes · "
        f"{llm.model} · ${total_cost:.6f} (₹{total_cost * 88:.4f})"
    )
    return 0 if crashed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
