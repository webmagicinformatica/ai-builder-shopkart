"""Facts the chain looks up in code: tickets, orders, policies, and "today".

The model never decides a fact it can read from the database. Dates,
prices and categories come from data/orders.json; the policy text comes from
data/policies/*.md (current documents only, never the archive).
"""

from __future__ import annotations

import json
import re
import sys
from functools import cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))  # so `import shopkart` works from any folder

from shopkart import data  # noqa: E402  (the shared loaders for data/)

LAB = Path(__file__).resolve().parents[1]
ORDER_ID = data.ORDER_ID_RE
today = data.today  # Tuesday 17 November 2026 for every fixture (SHOPKART_TODAY overrides)


@cache
def tickets() -> dict[str, dict]:
    return {t["ticket_id"]: t for t in data.load_tickets()}


@cache
def orders() -> dict[str, dict]:
    return {o["order_id"]: o for o in data.load_orders()}


def cases() -> list[dict]:
    """The lab's 10 tickets, with the answer a support lead would give."""
    return json.loads((LAB / "cases.json").read_text())["cases"]


def order_facts(order: dict, category_hint: str | None = None) -> dict:
    """The facts the Decide step needs, worked out in code (not by the model)."""
    items = order["items"]
    item = next((i for i in items if i["category"] == category_hint), items[0])
    delivered = order.get("delivered_on")
    return {
        "order_id": order["order_id"],
        "status": order["status"],
        "item": item["name"],
        "category": item["category"],
        "item_price_inr": item["unit_price_inr"] * item["qty"],
        "order_total_inr": order["total_inr"],
        "sale_item": item.get("sale", False),
        "clearance_item": item.get("clearance", False),
        "delivered_on": delivered,
        "days_since_delivery": data.days_since_delivery(order),
        "refunds_already": [f"₹{r['amount_inr']:,} {r['status']} on {r['date']}" for r in order.get("refunds", [])],
        "payment_method": order["payment_method"],
    }


# ---- policies -------------------------------------------------------------

@cache
def policies() -> dict[str, dict]:
    """Current policies only (never the archive): {doc_id: {"version", "effective", "body", "sections"}}."""
    return {
        d.doc_id: {"version": d.meta["version"], "effective": d.meta["effective"], "body": d.text.strip(),
                   "sections": set(re.findall(r"^#{2,3} (\d+(?:\.\d+)?)\.? ", d.text, flags=re.M))}
        for d in data.load_policies() if d.is_current
    }


def policy_block(doc_ids: list[str]) -> str:
    """Policies wrapped in tags with their id, version and date (context engineering)."""
    docs = policies()
    return "\n\n".join(
        f'<policy doc_id="{d}" version="{docs[d]["version"]}" effective="{docs[d]["effective"]}">\n'
        f'{docs[d]["body"]}\n</policy>'
        for d in doc_ids
    )


CITATION = re.compile(r"^\s*([a-z-]+)\s*§\s*(\d+(?:\.\d+)?)\s*$")


def citation_error(citation: str, allowed_docs: list[str]) -> str | None:
    """None if `citation` (like "footwear §1") names a real section of a document we sent."""
    m = CITATION.match(citation or "")
    if not m:
        return f'policy_section must look like "footwear §1", got {citation!r}'
    doc, section = m.groups()
    if doc not in allowed_docs:
        return f"policy_section cites {doc!r}, which was not one of the policies given: {', '.join(allowed_docs)}"
    if section not in policies()[doc]["sections"]:
        return f"{doc} has no section {section}"
    return None
