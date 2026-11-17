"""ShopKart's ticket system as an MCP server: tools, a resource and a prompt, in one server.

Who decides when each one is used?
  tools     the MODEL   search_tickets, get_ticket, add_note, set_status
  resource  the APP     shopkart://tickets/{ticket_id}
  prompt    the USER    summarise_ticket (a slash command in Claude Code)

The tickets come from data/tickets.json (read only). Notes and status changes are
kept in .shopkart/ticket-state.json (gitignored), so you can reset them by deleting it.

Run it (stdio, the transport for a local server):
    uv run python labs/mcp-server/done/ticket_server.py

Never print() in a stdio server: standard output IS the wire. Logs go to stderr.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

from mcp import MCPError  # noqa: F401  (the imports below are for your TODOs)
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
from mcp.server.mcpserver.prompts.base import UserMessage
from mcp.types import INVALID_PARAMS, EmbeddedResource, TextResourceContents, ToolAnnotations
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("SHOPKART_DATA_DIR", ROOT / "data"))
STATE_FILE = Path(os.environ.get("SHOPKART_TICKET_STATE", ROOT / ".shopkart" / "ticket-state.json"))

# Logs go to stderr. One print() to stdout and the client sees a line that isn't JSON.
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[tickets] %(message)s")
log = logging.getLogger("tickets")

Status = Literal["open", "waiting_on_customer", "escalated", "resolved"]


# --------------------------------------------------------------------------
# The "ticket system": JSON fixtures plus a small state file
# --------------------------------------------------------------------------


def _load(name: str) -> list[dict]:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(STATE_FILE)


class Note(BaseModel):
    at: str
    author: str
    text: str


class OrderSummary(BaseModel):
    order_id: str
    status: str
    items: list[str]
    total_inr: int
    payment_method: str
    delivered_on: str | None


class Ticket(BaseModel):
    ticket_id: str
    created_at: str
    channel: str
    language: str
    customer_id: str | None
    order_id: str | None
    message: str
    status: Status = "open"
    notes: list[Note] = Field(default_factory=list)
    order: OrderSummary | None = None


class TicketHit(BaseModel):
    """One line in a search result: enough to pick the right ticket."""

    ticket_id: str
    status: Status
    order_id: str | None
    preview: str


class SearchResult(BaseModel):
    count: int
    tickets: list[TicketHit]


def _order_summary(order_id: str | None) -> OrderSummary | None:
    for o in _load("orders.json"):
        if o["order_id"] == order_id:
            return OrderSummary(
                order_id=o["order_id"], status=o["status"],
                items=[f'{i["qty"]} x {i["name"]} (₹{i["unit_price_inr"]:,})' for i in o["items"]],
                total_inr=o["total_inr"], payment_method=o["payment_method"],
                delivered_on=o.get("delivered_on"),
            )
    return None


def _tickets() -> list[Ticket]:
    state = _state()
    out = []
    for raw in _load("tickets.json"):
        extra = state.get(raw["ticket_id"], {})
        # The fixtures carry eval labels (expected answers). The model must never see them.
        fields = {k: v for k, v in raw.items() if k != "labels"}
        out.append(Ticket(**fields, status=extra.get("status", "open"), notes=extra.get("notes", [])))
    return out


def _find(ticket_id: str) -> Ticket:
    ticket_id = ticket_id.strip().upper()
    for t in _tickets():
        if t.ticket_id == ticket_id:
            t.order = _order_summary(t.order_id)
            return t
    # A ToolError becomes an error result (isError: true) with this message, so the model
    # can read it and try again. Any other exception shows only "Error executing tool".
    raise ToolError(f"No ticket {ticket_id}. Ticket IDs look like TCK-20101; use search_tickets to find one.")


# --------------------------------------------------------------------------
# The server
# --------------------------------------------------------------------------

mcp = MCPServer(
    "shopkart-tickets",
    instructions="ShopKart's support ticket system. Search and read tickets, add internal notes, change status.",
)


# ---- Tools: the MODEL decides when to call them ---------------------------
# Type hints become the input schema, the docstring becomes the description,
# and the Pydantic return type becomes the output schema (structured JSON).


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
def search_tickets(query: str = "", status: Status | None = None, order_id: str | None = None,
                   limit: int = 10) -> SearchResult:
    """Search ShopKart support tickets by words in the message, by status or by order ID. Returns IDs and short previews; call get_ticket for the full ticket."""
    words = query.lower().split()
    hits = [
        t for t in _tickets()
        if all(w in t.message.lower() for w in words)
        and (status is None or t.status == status)
        and (order_id is None or (t.order_id or "").upper() == order_id.strip().upper())
    ]
    limit = max(1, min(limit, 25))
    return SearchResult(count=len(hits), tickets=[
        TicketHit(ticket_id=t.ticket_id, status=t.status, order_id=t.order_id, preview=t.message[:80])
        for t in hits[:limit]
    ])


# TODO 1: get_ticket(ticket_id) -> Ticket
#   A read-only tool, like search_tickets above. The docstring is the description the model reads:
#   say what it returns, and what a ticket ID looks like (TCK-20101). _find() does the lookup and
#   raises ToolError, so a wrong ID comes back as an error message the model can act on.


# TODO 2: add_note(ticket_id, text, author="copilot") -> Ticket   and   set_status(ticket_id, status: Status) -> Ticket
#   Both change something, so: ToolAnnotations(read_only_hint=False, destructive_hint=False, ...).
#   set_status is idempotent (same call twice = same result); add_note is not.
#   Save changes with _state() / _save_state(), log to stderr with log.info(), return _find(...) again.


# ---- Resource: the APP decides when to read it -----------------------------

# TODO 3: a resource TEMPLATE at "shopkart://tickets/{ticket_id}" (mime_type="application/json")
#   that returns the ticket as JSON: _find(ticket_id).model_dump_json(indent=2).
#   Turn a ToolError into ResourceNotFoundError, so the client gets a clean "not found".


# ---- Prompt: the USER picks it (a slash command) ---------------------------

# TODO 4: a prompt summarise_ticket(ticket_id) -> list[UserMessage], title "Summarise a ticket".
#   Message 1 embeds the ticket as a resource:
#     UserMessage(EmbeddedResource(type="resource", resource=TextResourceContents(uri=..., mime_type=..., text=...)))
#   Message 2 is the instruction: four short lines (problem, order, what's been done, next step),
#   refunds above ₹5,000 need a human, never repeat card numbers or OTPs.


if __name__ == "__main__":
    log.info("starting on stdio: %d tickets", len(_load("tickets.json")))
    mcp.run()  # stdio by default. Never print() here: stdout is the wire.
