"""ShopKart's return and refund rules, as plain code. No model in here.

The model reads the customer and fills in a request. This module decides.
Same order, same request, same answer, every time, and it's tested without a key.

    decide(order, reason, ...) -> Decision
        "refund"          inside policy and ₹5,000 or less: may run automatically
        "needs_approval"  inside policy but a person must say yes (above ₹5,000, ...)
        "not_eligible"    outside policy: no refund, a person reviews exceptions

Sources (data/policies): Returns and Refunds 2.1, 2.2, 2.4, 4 · Damaged Items 2, 4 ·
Refund Processing 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from shopkart import data

HUMAN_ABOVE_INR = 5000          # Refund Processing 1: above ₹5,000 always a person
DAILY_AUTO_LIMIT_INR = 50_000   # Refund Processing 1: automatic refunds per day, all customers
THIRD_REQUEST_IN_30_DAYS = 2    # Refund Processing 1: the third request goes to a person

DEFAULT_WINDOW_DAYS = 14        # Returns 2.1
WINDOW_DAYS = {                 # Returns 2.2 and Damaged Items 2, from the delivery date
    "footwear": 10,
    "electronics": 7,
    "beauty": 7,
    "grocery": 2,               # damaged on arrival only, 48 hours
    "large_appliances": 2,      # 48 hours, at installation
}
NOT_RETURNABLE = {"gift_card"}
FAULT_REASONS = {"damaged", "defective", "wrong_item"}
REASONS = sorted(FAULT_REASONS | {"changed_mind"})


@dataclass
class Decision:
    outcome: str                        # refund | needs_approval | not_eligible
    amount_inr: int = 0                 # what would be refunded (0 when not eligible)
    why: list[str] = field(default_factory=list)
    policy: list[str] = field(default_factory=list)

    @property
    def moves_money_now(self) -> bool:
        return self.outcome == "refund"


def window_days(category: str) -> int:
    return WINDOW_DAYS.get(category, DEFAULT_WINDOW_DAYS)


def refundable_left(order: dict, issued_here: int = 0) -> int:
    """Paid, minus every refund already made (the order system's and ours)."""
    done = sum(r["amount_inr"] for r in order.get("refunds", []) if r.get("status") != "failed")
    return order["total_inr"] - done - issued_here


def decide(order: dict, reason: str, *, sku: str | None = None, opened: bool = True,
           issued_here: int = 0, refunds_last_30_days: int = 0, auto_today_inr: int = 0,
           on: date | None = None) -> Decision:
    """Every rule, in order. The amount is computed here, never taken from the model."""
    no = lambda why, *refs: Decision("not_eligible", 0, [why], list(refs))  # noqa: E731

    if reason not in REASONS:
        raise ValueError(f"reason must be one of {', '.join(REASONS)}")
    if not order.get("delivered_on"):
        return no(f"not delivered yet (status: {order['status']}), so this is a cancellation, not a return",
                  "Cancellations 1")
    items = [i for i in order["items"] if sku in (None, i["sku"])]
    if not items:
        raise ValueError(f"no item {sku} in {order['order_id']}")

    left = refundable_left(order, issued_here)
    if left <= 0:
        return no(f"already refunded in full (₹{order['total_inr']:,} paid, nothing left)",
                  "Refund Processing 1")

    days = data.days_since_delivery(order, on)
    for item in items:
        cat = item["category"]
        if cat in NOT_RETURNABLE:
            return no(f"{item['name']}: gift cards can't be returned", "Returns 2.2")
        if cat == "grocery" and reason not in FAULT_REASONS:
            return no(f"{item['name']}: grocery is returnable only if damaged on arrival", "Returns 2.2")
        limit = window_days(cat)
        if days > limit:
            return no(f"{item['name']}: delivered {days} days ago, the {cat.replace('_', ' ')} "
                      f"window is {limit} days", "Returns 2.2", "Damaged Items 2", "Returns 4")
        if cat == "electronics" and reason == "changed_mind" and opened:
            return no(f"{item['name']}: opened electronics can be returned only if faulty or damaged",
                      "Returns 2.2", "Damaged Items 2")
        if item["clearance"]:
            return no(f"{item['name']}: clearance item, final sale"
                      + (": an exchange comes first" if reason in FAULT_REASONS else ""),
                      "Returns 2.4", "Damaged Items 4")

    amount = sum(i["unit_price_inr"] * i["qty"] for i in items)
    if reason in FAULT_REASONS and len(items) == len(order["items"]):
        amount += order.get("delivery_fee_inr", 0) + order.get("cod_fee_inr", 0)  # Damaged Items 4
    amount = min(amount, left)  # Refund Processing 1: never more than was paid

    why: list[str] = []
    if amount > HUMAN_ABOVE_INR:
        why.append(f"₹{amount:,} is above the ₹{HUMAN_ABOVE_INR:,} limit for automatic refunds")
    if refunds_last_30_days >= THIRD_REQUEST_IN_30_DAYS:
        why.append(f"refund request number {refunds_last_30_days + 1} in 30 days")
    if not why and auto_today_inr + amount > DAILY_AUTO_LIMIT_INR:
        why.append(f"today's automatic refunds would pass ₹{DAILY_AUTO_LIMIT_INR:,}")
    refs = ["Refund Processing 1", "Damaged Items 2" if reason in FAULT_REASONS else "Returns 2.1"]
    return Decision("needs_approval" if why else "refund", amount, why, refs)
