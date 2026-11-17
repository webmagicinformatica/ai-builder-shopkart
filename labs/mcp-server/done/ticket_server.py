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

from mcp import MCPError
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


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
def get_ticket(ticket_id: str) -> Ticket:
    """Get one ShopKart ticket by ID (like TCK-20101): the customer's message, status, internal notes and the linked order."""
    return _find(ticket_id)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False))
def add_note(ticket_id: str, text: str, author: str = "copilot") -> Ticket:
    """Add an internal note to a ticket. Notes are for the support team, never shown to the customer."""
    ticket = _find(ticket_id)
    text = text.strip()
    if not text:
        raise ToolError("A note needs some text.")
    state = _state()
    entry = state.setdefault(ticket.ticket_id, {})
    note = Note(at=datetime.now().isoformat(timespec="seconds"), author=author, text=text[:2000])
    entry.setdefault("notes", []).append(note.model_dump())
    _save_state(state)
    log.info("note added to %s by %s", ticket.ticket_id, author)
    return _find(ticket.ticket_id)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True))
def set_status(ticket_id: str, status: Status) -> Ticket:
    """Change a ticket's status: open, waiting_on_customer, escalated (handed to a person) or resolved."""
    ticket = _find(ticket_id)
    state = _state()
    state.setdefault(ticket.ticket_id, {})["status"] = status
    _save_state(state)
    log.info("%s: %s -> %s", ticket.ticket_id, ticket.status, status)
    return _find(ticket.ticket_id)


# ---- Resource: the APP decides when to read it -----------------------------
# A template: one address with a blank in it covers every ticket.


@mcp.resource("shopkart://tickets/{ticket_id}", mime_type="application/json")
def ticket_resource(ticket_id: str) -> str:
    """One ShopKart support ticket, with its notes and linked order, as JSON."""
    try:
        return _find(ticket_id).model_dump_json(indent=2)
    except ToolError as exc:
        raise ResourceNotFoundError(str(exc)) from exc


# ---- Prompt: the USER picks it (a slash command) ---------------------------


@mcp.prompt(title="Summarise a ticket")
def summarise_ticket(ticket_id: str) -> list[UserMessage]:
    """Summarise one support ticket for a teammate: the problem, what's been done, the next step."""
    try:
        ticket = _find(ticket_id)
    except ToolError as exc:
        raise MCPError(INVALID_PARAMS, str(exc)) from exc
    uri = f"shopkart://tickets/{ticket.ticket_id}"
    return [
        UserMessage(EmbeddedResource(type="resource", resource=TextResourceContents(
            uri=uri, mime_type="application/json", text=ticket.model_dump_json(indent=2)))),
        UserMessage(
            f"Summarise ticket {ticket.ticket_id} for a ShopKart support teammate, in English, in at most "
            "four short lines: 1) the customer's problem, 2) the order and its state, 3) what has been done "
            "so far (notes, status), 4) the next step. Refunds above ₹5,000 need a human. "
            "Never repeat card numbers, CVVs, OTPs or ID numbers."
        ),
    ]


if __name__ == "__main__":
    log.info("starting on stdio: %d tickets", len(_load("tickets.json")))
    mcp.run()  # stdio by default
