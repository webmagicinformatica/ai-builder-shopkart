"""The agent's three tools. The model sees only TOOLS (names, descriptions, schemas)
and what each tool returns. Everything that matters is decided in code.

    lookup_order(order_id)                          read only, runs automatically
    check_policy(topic)                             read only, runs automatically
    request_refund(order_id, reason, opened, sku)   the one action: code computes the
                                                    amount and decides refund / approval / no

The customer ID comes from the login (Session), never from the model. Another
customer's order gets the same answer as an order that doesn't exist.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import rules
import store
from shopkart import data

TOPICS = {  # topic -> (policy doc, sections)
    "return_window": ("returns-and-refunds", ["2.1", "2.2"]),
    "damaged_items": ("damaged-items", ["2", "4"]),
    "refund_approval": ("refunds", ["1"]),
    "exceptions": ("returns-and-refunds", ["4"]),
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "lookup_order",
        "description": (
            "Look up one order of the signed-in customer by its ID, like SK12345. Returns status, "
            "items (with sku and category), amount paid in rupees, delivery date, days since delivery "
            "and refunds so far. Use it before anything about an order. If the customer gave no "
            "order ID, ask for it. Never guess one."),
        "input_schema": {"type": "object", "properties": {
            "order_id": {"type": "string", "description": "SK followed by 5 digits"}},
            "required": ["order_id"], "additionalProperties": False},
    },
    {
        "name": "check_policy",
        "description": (
            "Read the current ShopKart policy text for one topic, with its source. Use it to explain "
            "a decision to the customer in the policy's own terms. Answer only from what it returns."),
        "input_schema": {"type": "object", "properties": {
            "topic": {"type": "string", "enum": list(TOPICS)}},
            "required": ["topic"], "additionalProperties": False},
    },
    {
        "name": "request_refund",
        "description": (
            "Ask ShopKart's refund system to refund one order (or one item, by sku). You don't choose "
            "the amount: the system works it out from what was paid, and it decides by policy. "
            "It answers with one outcome: 'refund' (started now), 'needs_approval' (a support lead "
            "must approve, you can't promise it) or 'not_eligible' (no refund, with the rule). "
            "Use it once, after lookup_order, when the customer asks for their money back. "
            "Then tell the customer exactly what tell_customer says, in your own warm words."),
        "input_schema": {"type": "object", "properties": {
            "order_id": {"type": "string", "description": "SK followed by 5 digits"},
            "reason": {"type": "string", "enum": rules.REASONS,
                       "description": "damaged = arrived broken; defective = doesn't work; "
                                      "wrong_item; changed_mind = anything else"},
            "opened": {"type": "boolean", "description": "Has the box been opened? true if unsure."},
            "sku": {"type": "string", "description": "Only for one item of a multi-item order"}},
            "required": ["order_id", "reason", "opened"], "additionalProperties": False},
    },
]


class ToolError(Exception):
    """A failure the model should read: what happened, and what to do next."""


@dataclass
class Session:
    """From the login, never from the model."""

    customer_id: str
    conversation: str = field(default_factory=lambda: "conv-" + datetime.now().strftime("%H%M%S%f")[:10])


def actions_off() -> bool:
    """Kill switch: SHOPKART_ACTIONS_OFF=1 and no refund can start or be queued."""
    return os.environ.get("SHOPKART_ACTIONS_OFF", "") not in ("", "0")


def _own_order(session: Session, raw: Any) -> dict:
    oid = data.normalize_order_id(str(raw or ""))
    if oid is None:
        raise ToolError(f"Order IDs look like SK12345. You sent {raw!r}. Ask the customer to check it.")
    order = data.get_order(oid)
    if order is None or order["customer_id"] != session.customer_id:
        raise ToolError(f"No order {oid} on this customer's account. Ask them to check the ID. "
                        "Don't try other IDs.")
    return order


def lookup_order(session: Session, order_id: str) -> dict:
    o = _own_order(session, order_id)
    return {
        "order_id": o["order_id"], "status": o["status"].replace("_", " "),
        "delivered_on": o["delivered_on"], "days_since_delivery": data.days_since_delivery(o),
        "items": [{"sku": i["sku"], "name": i["name"], "category": i["category"], "qty": i["qty"],
                   "price_inr": i["unit_price_inr"], "clearance": i["clearance"]} for i in o["items"]],
        "paid_inr": o["total_inr"], "payment_method": o["payment_method"],
        "refunded_so_far_inr": o["total_inr"] - rules.refundable_left(o, store.issued_on(o["order_id"])),
    }


def check_policy(session: Session, topic: str) -> dict:
    if topic not in TOPICS:
        raise ToolError(f"Unknown topic {topic!r}. Use one of: {', '.join(TOPICS)}.")
    doc_id, numbers = TOPICS[topic]
    doc = data.load_policy(doc_id)
    text = "\n\n".join(f"{s.number} {s.title}\n{s.text}" for s in data.sections(doc) if s.number in numbers)
    return {"source": f"{doc.title} v{doc.meta.get('version', '?')}, section {', '.join(numbers)}",
            "text": text}


TELL = {
    "refund": "Refund of ₹{amount:,} approved by policy ({id}). It reaches the original payment "
              "method in 5 to 7 working days after pickup.",
    "needs_approval": "A refund request for ₹{amount:,} is raised ({id}). A support lead reviews it "
                      "within one working day. Don't say it is approved or done.",
    "not_eligible": "No refund under the policy: {why}. A colleague can review exceptions and will "
                    "reply within one working day.",
}


def request_refund(session: Session, order_id: str, reason: str, opened: bool = True,
                   sku: str | None = None) -> dict:
    if actions_off():
        raise ToolError("Refunds are switched off right now. Don't retry. Tell the customer a "
                        "colleague will pick this up within one working day.")
    order = _own_order(session, order_id)
    oid = order["order_id"]
    if (pending := store.open_request(oid)) is not None:  # asking twice doesn't queue twice
        return {"outcome": "needs_approval", "amount_inr": pending["amount_inr"], "id": pending["id"],
                "tell_customer": TELL["needs_approval"].format(amount=pending["amount_inr"], id=pending["id"])}
    customer = data.get_customer(session.customer_id) or {}
    try:
        d = rules.decide(order, reason, sku=sku, opened=bool(opened), issued_here=store.issued_on(oid),
                         refunds_last_30_days=customer.get("refunds_last_30_days", 0)
                         + store.requests_by(session.customer_id),
                         auto_today_inr=store.auto_today())
    except ValueError as err:
        raise ToolError(f"{err}. Check the inputs and try once more.") from err

    asked = {"order_id": oid, "reason": reason, "opened": opened, "sku": sku}
    base = {"conversation": session.conversation, "customer": session.customer_id, "input": asked,
            "decision": d.outcome, "amount_inr": d.amount_inr, "why": d.why, "policy": d.policy}
    if d.outcome == "not_eligible":
        store.audit("refund_not_eligible", **base)
        return {"outcome": d.outcome, "why": d.why, "policy": d.policy,
                "tell_customer": TELL["not_eligible"].format(why="; ".join(d.why))}

    row = store.add({"order_id": oid, "customer_id": session.customer_id, "conversation": session.conversation,
                     "amount_inr": d.amount_inr, "reason": reason, "why": d.why,
                     "status": "issued" if d.moves_money_now else "pending",
                     "approved_by": "auto" if d.moves_money_now else None})
    store.audit("refund_issued" if d.moves_money_now else "approval_requested", id=row["id"], **base)
    return {"outcome": d.outcome, "amount_inr": d.amount_inr, "id": row["id"], "why_a_person": d.why,
            "tell_customer": TELL[d.outcome].format(amount=d.amount_inr, id=row["id"])}


FUNCTIONS = {"lookup_order": lookup_order, "check_policy": check_policy, "request_refund": request_refund}


def run_tool(session: Session, name: str, args: dict) -> tuple[str, bool]:
    """Run one tool. Returns (result text, is_error). Every call gets a result."""
    if name not in FUNCTIONS:
        return f"No tool called {name!r}. Use one of: {', '.join(FUNCTIONS)}.", True
    try:
        return json.dumps(FUNCTIONS[name](session, **args), ensure_ascii=False), False
    except ToolError as err:
        return str(err), True
    except TypeError as err:
        return f"Bad inputs for {name}: {err}. Check the schema and try again.", True
    except Exception as err:  # noqa: BLE001  an outage or a bug: tell the model, don't crash the chat
        return f"{name} failed inside ShopKart ({type(err).__name__}). Don't retry; hand over.", True
