"""YOUR COPY: the Copilot's three tools, and the refund rules that live in code.

Part 1: TODO 1 (descriptions), TODO 2 (small results, helpful errors).
Part 2: TODO 7 (refund rules in code), TODO 8 (approve exactly once).

    lookup_order(order_id)                       read only: runs automatically
    check_policy(topic)                          read only: runs automatically
    draft_refund(order_id, amount_inr, reason)   prepares a refund: no money moves

A tool is an interface for a model. The model never sees this code, only each
tool's name, description and input schema (TOOLS, below) and what it returns.
So the descriptions are written for a new teammate who can't ask a question,
and every error says what happened and what to do next.

The limits are here, in code, not in the prompt:
  per action    a refund above ₹5,000 always goes to a person (HUMAN_ABOVE_INR)
  per order     never refund more than was paid, minus what's already refunded
  per day       ₹50,000 of automatic refunds, then everything waits for a person
  per customer  a third refund request in 30 days goes to a person
  kill switch   SHOPKART_ACTIONS_OFF=1 turns off every action tool at once
In this lab, every refund waits for a person (AUTO_REFUND_UP_TO_INR = 0).
Raise it later, a little at a time, when the audit trail shows the agent gets
small refunds right.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # the repo root, for `shopkart`

from shopkart import budget, data  # noqa: E402

HUMAN_ABOVE_INR = 5000          # per action: above this, ALWAYS a person
DAILY_AUTO_LIMIT_INR = 50_000   # per day: automatic refunds across all chats
REFUNDS_IN_30_DAYS_LIMIT = 2    # per customer: the third request goes to a person

# Days to report a problem or return, counted from delivery (policies: returns 2.2, damaged items 2).
RETURN_WINDOW_DAYS = {"electronics": 7, "footwear": 10, "beauty": 7, "grocery": 2,
                      "large_appliances": 2}
DEFAULT_WINDOW_DAYS = 14
NOT_REFUNDABLE = {"gift_card"}


def auto_refund_up_to_inr() -> int:
    """Refunds up to this amount may run without a person. Lab default 0: every refund waits.
    Never above HUMAN_ABOVE_INR, whatever the setting says."""
    return min(int(os.environ.get("SHOPKART_AUTO_REFUND_UP_TO", "0")), HUMAN_ABOVE_INR)


def actions_off() -> bool:
    """The kill switch: the Copilot can still answer, but it can't move money."""
    return os.environ.get("SHOPKART_ACTIONS_OFF", "") not in ("", "0")


# ---------------------------------------------------------------------------
# What the model sees: name, description, input schema
# ---------------------------------------------------------------------------

REASONS = ["damaged", "defective", "wrong_item", "not_delivered", "duplicate_charge", "other"]
TOPICS = {  # topic -> (policy doc_id, section numbers)
    "return_window": ("returns-and-refunds", ["2.1", "2.2"]),
    "damaged_items": ("damaged-items", ["2", "4"]),
    "refund_approval": ("refunds", ["1"]),
    "refund_timelines": ("refunds", ["2"]),
    "footwear": ("footwear", ["1", "3"]),
    "electronics": ("electronics", ["1", "2"]),
    "cancellations": ("cancellations", ["1", "2", "4"]),
    "price_drop": ("refunds", ["4"]),
    "double_charge": ("refunds", ["6"]),
    "handover": ("escalation-and-handover", ["1", "2"]),
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "lookup_order",
        "description": (
            # TODO 1: brief a new teammate who can't ask you a question, in 3-4 sentences:
            # what it does, when to use it (and when not), what it returns, and its limits.
            "Gets order."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "SK followed by 5 digits, e.g. SK48213"},
            },
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_policy",
        "description": (
            # TODO 1: brief a new teammate who can't ask you a question, in 3-4 sentences:
            # what it does, when to use it (and when not), what it returns, and its limits.
            "Gets policy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "enum": list(TOPICS)},
            },
            "required": ["topic"],
            "additionalProperties": False,
        },
    },
    {
        "name": "draft_refund",
        "description": (
            # TODO 1: brief a new teammate who can't ask you a question, in 3-4 sentences:
            # what it does, when to use it (and when not), what it returns, and its limits.
            "Refunds an order."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "SK followed by 5 digits, e.g. SK48213"},
                "amount_inr": {"type": "integer", "description": "Refund amount in whole rupees, e.g. 1299"},
                "reason": {"type": "string", "enum": REASONS},
            },
            "required": ["order_id", "amount_inr", "reason"],
            "additionalProperties": False,
        },
    },
]


class ToolError(Exception):
    """A failure the model should read: what happened, and what to do next."""


# ---------------------------------------------------------------------------
# Who is asking, and where drafts, refunds and the audit trail live
# ---------------------------------------------------------------------------


@dataclass
class Session:
    """Comes from the login, never from the model: one clever message can't change it."""

    customer_id: str
    conversation_id: str = field(default_factory=lambda: "conv-" + datetime.now().strftime("%H%M%S"))
    model: str = ""


def store_dir() -> Path:
    return budget.LEDGER_DIR / "agent-tools"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_refunds() -> list[dict]:
    """Drafts and refunds this lab has made (.shopkart/agent-tools/refunds.json, gitignored)."""
    path = store_dir() / "refunds.json"
    return json.loads(path.read_text()) if path.exists() else []


def save_refunds(rows: list[dict]) -> None:
    path = store_dir() / "refunds.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def audit(event: str, session: Session | None, **details: Any) -> dict:
    """One line per action, proposed or taken, in an append-only file. Nobody edits it later."""
    row = {"time": _now(), "event": event}
    if session is not None:
        row |= {"conversation": session.conversation_id, "customer": session.customer_id,
                "model": session.model}
    row |= details
    path = store_dir() / "audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_order_id(raw: Any) -> str:
    oid = data.normalize_order_id(str(raw or ""))
    if oid is None:
        # TODO 2: say what was wrong and what to do next (and whether to retry).
        raise ToolError("invalid order id")
    return oid


def _customer_order(session: Session, raw_id: Any) -> dict:
    oid = _clean_order_id(raw_id)
    order = data.get_order(oid)
    if order is None or order["customer_id"] != session.customer_id:
        # TODO 2: a helpful "not found" (and never reveal that it is someone else's order).
        raise ToolError("not found")
    return order


def window_days(order: dict) -> int:
    return min(RETURN_WINDOW_DAYS.get(i["category"], DEFAULT_WINDOW_DAYS) for i in order["items"])


def refunded_inr(order: dict) -> int:
    """Refunded so far: the order system's refunds plus refunds issued in this lab."""
    done = sum(r["amount_inr"] for r in order["refunds"] if r.get("status") != "failed")
    done += sum(r["amount_inr"] for r in load_refunds()
                if r["order_id"] == order["order_id"] and r["status"] == "issued")
    return done


# ---------------------------------------------------------------------------
# The tools
# ---------------------------------------------------------------------------


def lookup_order(session: Session, order_id: str) -> dict:
    order = _customer_order(session, order_id)
    # TODO 2: the whole row is ~40 fields and stays in the history on every turn.
    # Return only what the model needs: order_id, status, placed_on, delivered_on, items,
    # paid_inr, payment_method, refunded_so_far_inr (refunded_inr), tracking_number,
    # days_since_delivery and the return_window (window_days), in readable words.
    return order


def check_policy(session: Session, topic: str) -> dict:
    if topic not in TOPICS:
        raise ToolError(f"Unknown topic {topic!r}. Use one of: {', '.join(TOPICS)}. "
                        "If none fits, hand the customer to a person.")
    doc_id, numbers = TOPICS[topic]
    doc = data.load_policy(doc_id)
    parts = [f"{s.number} {s.title}\n{s.text}" for s in data.sections(doc) if s.number in numbers]
    return {"source": f"{doc.title} v{doc.meta.get('version', '?')}, section {', '.join(numbers)}",
            "text": "\n\n".join(parts)}


@dataclass
class Assessment:
    """What the code decides about a refund, before anything is saved."""

    order: dict
    amount_inr: int
    needs_human: list[str]  # why a person must approve (empty: may run automatically)


def assess_refund(session: Session, order_id: str, amount_inr: int, reason: str) -> Assessment:
    """Check every rule. Raises ToolError for a refund that must not happen at all."""
    if actions_off():
        raise ToolError("Refunds are switched off right now (kill switch). Don't retry. "
                        "Tell the customer a colleague will pick this up within one working day.")
    order = _customer_order(session, order_id)
    if reason not in REASONS:
        raise ToolError(f"reason must be one of {', '.join(REASONS)}. You sent {reason!r}.")
    if not isinstance(amount_inr, int) or isinstance(amount_inr, bool) or amount_inr <= 0:
        raise ToolError(f"amount_inr must be a whole number of rupees above 0, like 1299. You sent {amount_inr!r}.")
    # TODO 7 (per order): never refund more than was paid minus what's already refunded
    # (refunded_inr). Nothing left? Block it: "already refunded in full ... hand over".
    # Too much? Say the maximum refundable, so the model can correct itself.
    categories = {i["category"] for i in order["items"]}
    if categories & NOT_REFUNDABLE:
        raise ToolError("Gift cards can't be refunded (Gift Card Policy). Hand the customer to a person.")
    if reason in ("damaged", "defective", "wrong_item", "other") and not order["delivered_on"]:
        raise ToolError(f"Order {order['order_id']} hasn't been delivered yet (status: {order['status']}), "
                        f"so a '{reason}' refund doesn't apply. Use check_policy('cancellations') instead.")

    why: list[str] = []
    # TODO 7 (per action and policy): above HUMAN_ABOVE_INR always needs a person, and so does
    # a refund outside the return window (window_days, data.days_since_delivery) or a clearance item.
    customer = data.get_customer(session.customer_id) or {}
    recent = customer.get("refunds_last_30_days", 0) + sum(
        1 for r in load_refunds() if r["customer_id"] == session.customer_id and r["status"] != "rejected")
    if recent >= REFUNDS_IN_30_DAYS_LIMIT:
        why.append(f"refund request number {recent + 1} in 30 days")
    auto_limit = auto_refund_up_to_inr()
    if amount_inr > auto_limit and not why:
        why.append("every refund is reviewed by a person in this shop" if auto_limit == 0
                   else f"above the automatic limit of ₹{auto_limit:,}")
    today_auto = sum(r["amount_inr"] for r in load_refunds()
                     if r["approved_by"] == "auto" and r["created"][:10] == date.today().isoformat())
    if not why and today_auto + amount_inr > DAILY_AUTO_LIMIT_INR:
        why.append(f"today's automatic refunds would pass ₹{DAILY_AUTO_LIMIT_INR:,}")
    return Assessment(order, amount_inr, why)


def draft_refund(session: Session, order_id: str, amount_inr: int, reason: str,
                 approved_by: str | None = None) -> dict:
    """Save the exact action. Small, inside-policy refunds may run at once; the rest wait.

    `approved_by` is only for agent SDKs that pause the run for approval before
    the tool runs (the agent-sdk lab): the person has already said yes.
    """
    try:
        a = assess_refund(session, order_id, amount_inr, reason)
    except ToolError as err:
        audit("refund_blocked", session, tool="draft_refund",
              input={"order_id": order_id, "amount_inr": amount_inr, "reason": reason}, why=str(err))
        raise
    oid = a.order["order_id"]
    rows = load_refunds()
    # Safe to call twice: an open draft for this order is returned, not doubled.
    for r in rows:
        if r["order_id"] == oid and r["status"] == "pending":
            return {"draft_id": r["draft_id"], "status": "pending approval (already drafted)",
                    "amount_inr": r["amount_inr"],
                    "tell_customer": "A refund request is already waiting for a support lead. "
                                     "They will reply within one working day. Don't promise the refund."}
    draft = {
        "draft_id": f"RD-{oid[2:]}-{sum(r['order_id'] == oid for r in rows) + 1}",
        "order_id": oid, "customer_id": session.customer_id, "conversation": session.conversation_id,
        "amount_inr": a.amount_inr, "reason": reason, "payment_method": a.order["payment_method"],
        "needs_human": a.needs_human, "status": "pending", "created": _now(),
        "approved_by": None, "refund_id": None,
    }
    rows.append(draft)
    save_refunds(rows)
    audit("refund_drafted", session, tool="draft_refund",
          input={"order_id": oid, "amount_inr": a.amount_inr, "reason": reason},
          decision="needs approval" if a.needs_human else "automatic", why=a.needs_human)
    if not a.needs_human:
        refund = approve(draft["draft_id"], "auto")
        return {"draft_id": draft["draft_id"], "status": "refund started (automatic, inside policy)",
                "refund_id": refund["refund_id"], "amount_inr": a.amount_inr,
                "tell_customer": "The refund has been started. It reaches the original payment method "
                                 "in 5 to 7 working days."}
    if approved_by:
        refund = approve(draft["draft_id"], approved_by)
        return {"draft_id": draft["draft_id"], "status": f"refund started (approved by {approved_by})",
                "refund_id": refund["refund_id"], "amount_inr": a.amount_inr,
                "tell_customer": "The refund was approved and started. It reaches the original "
                                 "payment method in 5 to 7 working days."}
    return {"draft_id": draft["draft_id"], "status": "waiting for approval", "amount_inr": a.amount_inr,
            "why_a_person": a.needs_human,
            "tell_customer": "A support lead will review this refund request within one working day. "
                             "Don't promise the refund or the amount."}


def approval_screen(order: dict, amount_inr: int, reason: str, why: list[str]) -> list[str]:
    """What the approver sees: the exact action, evidence from OUR systems, and why it's here."""
    days = data.days_since_delivery(order)
    return [
        "── Approval needed " + "─" * 52,
        f"  Action    Refund ₹{amount_inr:,} to the original {order['payment_method'].upper()} payment, "
        f"order {order['order_id']} (reason: {reason})",
        f"  Evidence  placed {order['placed_on']}, delivered {order['delivered_on'] or '-'}"
        + (f" ({days} days ago)" if days is not None else "")
        + f", paid ₹{order['total_inr']:,}, refunded so far ₹{refunded_inr(order):,}",
        f"            {'; '.join(str(i['qty']) + ' x ' + i['name'] for i in order['items'])}",
        f"  Why       {'; '.join(why)}",
    ]


# ---------------------------------------------------------------------------
# After the person decides: run exactly the saved action, exactly once
# ---------------------------------------------------------------------------


def find_draft(draft_id: str) -> dict:
    for r in load_refunds():
        if r["draft_id"] == draft_id:
            return r
    raise KeyError(f"No draft {draft_id}")


def approve(draft_id: str, approver: str, amount_inr: int | None = None) -> dict:
    """Issue the saved refund. Never asks the model again. A second click does nothing."""
    rows = load_refunds()
    row = next(r for r in rows if r["draft_id"] == draft_id)
    # TODO 8: approving twice must not pay twice. If the row isn't "pending" any more, return it as it is.
    session = Session(row["customer_id"], row["conversation"])
    if amount_inr is not None and amount_inr != row["amount_inr"]:
        # An edited amount is a new action: check it again, and log who changed it.
        assess_refund(session, row["order_id"], amount_inr, row["reason"])
        audit("refund_edited", session, draft_id=draft_id, by=approver,
              old_amount_inr=row["amount_inr"], new_amount_inr=amount_inr)
        row["amount_inr"] = amount_inr
    else:
        order = data.get_order(row["order_id"])
        left = order["total_inr"] - refunded_inr(order)  # approvals expire if the order changed
        if row["amount_inr"] > left:
            raise ToolError(f"Order {row['order_id']} changed since the draft: only ₹{left:,} is left to refund.")
    row["status"], row["approved_by"] = "issued", approver
    row["refund_id"] = f"RF-{row['order_id'][2:]}-{datetime.now().strftime('%H%M%S')}"
    save_refunds(rows)
    audit("refund_issued", session, draft_id=draft_id, refund_id=row["refund_id"],
          amount_inr=row["amount_inr"], decision="automatic" if approver == "auto" else "approved",
          by=approver)
    return row


def reject(draft_id: str, approver: str, why: str) -> dict:
    rows = load_refunds()
    row = next(r for r in rows if r["draft_id"] == draft_id)
    if row["status"] == "pending":
        row["status"], row["approved_by"], row["rejected_because"] = "rejected", approver, why
        save_refunds(rows)
        audit("refund_rejected", Session(row["customer_id"], row["conversation"]),
              draft_id=draft_id, by=approver, why=why)
    return row


# ---------------------------------------------------------------------------
# One entry point for the loop: run a tool by name
# ---------------------------------------------------------------------------

FUNCTIONS = {"lookup_order": lookup_order, "check_policy": check_policy, "draft_refund": draft_refund}


def run_tool(session: Session, name: str, args: dict) -> tuple[str, bool]:
    """Run one tool. Returns (result text, is_error). Every call gets a result, even a failed one."""
    if name not in FUNCTIONS:
        return f"There is no tool called {name!r}. Use one of: {', '.join(FUNCTIONS)}.", True
    try:
        result = FUNCTIONS[name](session, **args)
        return json.dumps(result, ensure_ascii=False), False
    except ToolError as err:
        return str(err), True
    except TypeError as err:  # wrong or missing inputs
        return f"Bad inputs for {name}: {err}. Check the tool's input schema and try again.", True
    except Exception as err:  # noqa: BLE001 — a bug or an outage: tell the model, don't crash the chat
        return (f"{name} failed inside ShopKart ({type(err).__name__}). Don't retry. "
                "Tell the customer a colleague will follow up within one working day."), True
