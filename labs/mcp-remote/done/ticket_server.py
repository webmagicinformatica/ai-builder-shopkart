"""ShopKart's ticket MCP server, REMOTE: Streamable HTTP at /mcp, with a login and least privilege.

The same tools, resource and prompt as Part 1 (labs/mcp-server). What changed (look for "REMOTE"):
  1. Streamable HTTP instead of stdio: one endpoint, every message a POST, no sessions,
     so any copy behind a load balancer (or any Lambda environment) can answer any request.
  2. A resource server: every request needs a token made for THIS server (auth.py).
     401 without one, with a header that points to our protected resource metadata.
  3. Two scopes: tickets:read for reading, tickets:write for add_note and set_status (403 otherwise).
  4. Who wrote a note comes from the token, never from the model.
  5. Host and Origin checks, so a web page can't trick a browser into calling us.
  6. Notes and statuses live in a shared table (DynamoDB), not in one copy's files: the next
     request may land on a different copy. The server reaches it with its OWN narrow AWS role.

Who decides when each one is used?
  tools     the MODEL   search_tickets, get_ticket, add_note, set_status
  resource  the APP     shopkart://tickets/{ticket_id}
  prompt    the USER    summarise_ticket (a slash command in Claude Code)

The tickets come from data/tickets.json (read only). Notes and status changes are
kept in .shopkart/ticket-state.json (gitignored), so you can reset them by deleting it.

Run it locally (settings in the README):
    uv run python labs/mcp-remote/done/ticket_server.py      # http://localhost:8000/mcp
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
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.routes import build_resource_metadata_url
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.prompts.base import UserMessage
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import INVALID_PARAMS, EmbeddedResource, TextResourceContents, ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth import READ, WRITE, JWTVerifier, StepUpScopes  # noqa: E402  (REMOTE)

HERE = Path(__file__).resolve().parent
ROOT = next((p for p in (HERE, *HERE.parents) if (p / "data" / "tickets.json").exists()), HERE)
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


# REMOTE: with TICKET_STATE_TABLE set, state lives in DynamoDB, shared by every copy of the server.
# Without it (your laptop, the tests), in a local file as in Part 1.
TABLE_NAME = os.environ.get("TICKET_STATE_TABLE")
_table_cache: list = []


def _table():
    if not _table_cache:
        import boto3  # only needed when the table is used

        _table_cache.append(boto3.resource("dynamodb").Table(TABLE_NAME))
    return _table_cache[0]


def _state() -> dict:
    if TABLE_NAME:
        items = _table().scan(ProjectionExpression="ticket_id, ticket_state")["Items"]  # small: one row per changed ticket
        return {i["ticket_id"]: json.loads(i["ticket_state"]) for i in items}
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def _save_ticket(ticket_id: str, entry: dict) -> None:
    """Save ONE ticket's notes and status."""
    if TABLE_NAME:
        _table().put_item(Item={"ticket_id": ticket_id, "ticket_state": json.dumps(entry, ensure_ascii=False)})
        return
    state = _state()
    state[ticket_id] = entry
    _save_state(state)


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

# REMOTE: where we live, and who issues our tokens. The URL is also the token's audience.
RESOURCE_URL = os.environ.get("MCP_RESOURCE_URL", "http://localhost:8000/mcp")
verifier = JWTVerifier.from_env()

mcp = MCPServer(
    "shopkart-tickets",
    instructions="ShopKart's support ticket system. Search and read tickets, add internal notes, change status.",
    token_verifier=verifier,
    auth=AuthSettings(
        issuer_url=verifier.issuer,          # the authorization server that runs the login
        resource_server_url=RESOURCE_URL,    # us: tokens must be made for this URL
        validate_token_resource=True,        # refuse tokens made for anyone else
        required_scopes=[READ],              # the basic scope, for every request
    ),
)


def require_write() -> str:
    """REMOTE: check again inside the tool (the HTTP layer already did). Returns who is calling."""
    token = get_access_token()
    if token is None or WRITE not in token.scopes:
        raise ToolError(f"insufficient_scope: this tool needs {WRITE}")
    return token.subject or token.client_id


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
def add_note(ticket_id: str, text: str) -> Ticket:
    """Add an internal note to a ticket. Notes are for the support team, never shown to the customer."""
    author = require_write()  # REMOTE: the author comes from the token, not from the model
    ticket = _find(ticket_id)
    text = text.strip()
    if not text:
        raise ToolError("A note needs some text.")
    entry = _state().get(ticket.ticket_id, {})
    note = Note(at=datetime.now().isoformat(timespec="seconds"), author=author, text=text[:2000])
    entry.setdefault("notes", []).append(note.model_dump())
    _save_ticket(ticket.ticket_id, entry)
    log.info("note added to %s by %s", ticket.ticket_id, author)
    return _find(ticket.ticket_id)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True))
def set_status(ticket_id: str, status: Status) -> Ticket:
    """Change a ticket's status: open, waiting_on_customer, escalated (handed to a person) or resolved."""
    who = require_write()
    ticket = _find(ticket_id)
    entry = _state().get(ticket.ticket_id, {})
    entry["status"] = status
    _save_ticket(ticket.ticket_id, entry)
    log.info("%s: %s -> %s by %s", ticket.ticket_id, ticket.status, status, who)
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


# ---- REMOTE: the web app ----------------------------------------------------------------


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """For the load balancer or Lambda's readiness check. No token needed, no data in it."""
    return JSONResponse({"status": "ok"})


def build_app():
    host = RESOURCE_URL.split("/")[2]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[host, "localhost:*", "127.0.0.1:*"],
        allowed_origins=[o for o in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if o],
    )
    inner = mcp.streamable_http_app(stateless_http=True, json_response=True, transport_security=security)
    return StepUpScopes(inner, verifier, str(build_resource_metadata_url(RESOURCE_URL)))


app = build_app()

if __name__ == "__main__":
    import uvicorn

    log.info("starting on http://0.0.0.0:8000/mcp: %d tickets, resource %s", len(_load("tickets.json")), RESOURCE_URL)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
