"""The mcp-remote lab's checkpoints: the server runs in memory, tokens are signed with a test key.
No AWS, no network, no model.

Against the finished answer:   uv run pytest labs/mcp-remote -q
Against your copy:             LAB=start uv run pytest labs/mcp-remote -q
"""

import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from tests.fakes import FakeServer

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")
URL = "http://testserver/mcp"
ISSUER = "https://auth.shopkart.example"


def load(name: str, folder: Path = FOLDER):
    for shared in ("auth",):
        sys.modules.pop(shared, None)
    spec = importlib.util.spec_from_file_location(f"mcpremote_{folder.name}_{name}", folder / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    issuer = load("issue_token", LAB / "done")
    private, public = issuer.keygen(tmp_path_factory.mktemp("keys"))
    return issuer, private.read_bytes(), public.read_text()


@pytest.fixture
def token(keys):
    issuer, private, _ = keys

    def make(scope="tickets:read", sub="asha@shopkart.in", aud=URL, ttl=600):
        return issuer.issue(private, sub=sub, scope=scope, aud=aud, ttl_s=ttl)

    return make


@pytest.fixture
def server(keys, tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_RESOURCE_URL", URL)
    monkeypatch.setenv("MCP_ISSUER", ISSUER)
    monkeypatch.setenv("MCP_JWT_PUBLIC_KEY", keys[2])
    monkeypatch.setenv("SHOPKART_TICKET_STATE", str(tmp_path / "state.json"))
    monkeypatch.delenv("TICKET_STATE_TABLE", raising=False)
    monkeypatch.setattr("shopkart.budget.LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("DAILY_BUDGET_USD", "1")
    return load("ticket_server")


def served(server):
    """Run the app's start-up, then hand back an ASGI transport to it."""
    inner = server.app.app  # inside StepUpScopes: the SDK's Starlette app

    class Running:
        async def __aenter__(self):
            self.ctx = inner.router.lifespan_context(inner)
            await self.ctx.__aenter__()
            return httpx2.ASGITransport(app=server.app)

        async def __aexit__(self, *exc):
            await self.ctx.__aexit__(*exc)

    return Running()


def mcp_client(transport, tok):
    http = httpx2.AsyncClient(transport=transport, headers={"Authorization": f"Bearer {tok}"})
    return Client(streamable_http_client(URL, http_client=http))


async def raw_post(transport, body: dict, tok: str | None = None, host: str | None = None) -> httpx2.Response:
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    if host:
        headers["Host"] = host
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as c:
        return await c.post("/mcp", json=body, headers=headers)


CALL_ADD_NOTE = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "add_note", "arguments": {"ticket_id": "TCK-20123", "text": "hi"}}}


# ---- TODO 1: check the token (auth.py) ------------------------------------------------


def test_verifier_accepts_only_our_tokens_for_this_server(server, token, keys, tmp_path):
    v = server.verifier
    good = asyncio.run(v.verify_token(token("tickets:read tickets:write")))
    assert good.subject == "asha@shopkart.in" and set(good.scopes) == {"tickets:read", "tickets:write"}
    assert good.resource == URL
    assert asyncio.run(v.verify_token(token(aud="https://orders.shopkart.example/mcp"))) is None  # not for us
    assert asyncio.run(v.verify_token(token(ttl=-10))) is None                                    # expired
    other_key = keys[0].keygen(tmp_path / "someone-else")
    forged = keys[0].issue(other_key[0].read_bytes(), sub="mallory", scope="tickets:write", aud=URL)
    assert asyncio.run(v.verify_token(forged)) is None                                            # not signed by us


def test_no_token_is_401_with_a_pointer_to_the_metadata(server):
    async def go():
        async with served(server) as t:
            r = await raw_post(t, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            async with httpx2.AsyncClient(transport=t, base_url="http://testserver") as c:
                meta = (await c.get("/.well-known/oauth-protected-resource/mcp")).json()
            return r, meta

    r, meta = asyncio.run(go())
    assert r.status_code == 401
    assert "resource_metadata=" in r.headers["www-authenticate"]
    assert meta["resource"] == URL and meta["authorization_servers"] == [ISSUER]
    assert meta["scopes_supported"] == ["tickets:read"]  # only the basic set


# ---- TODO 2: least privilege: a write tool needs tickets:write --------------------------


def test_read_token_reads_but_cannot_write(server, token):
    async def go():
        async with served(server) as t:
            async with mcp_client(t, token("tickets:read")) as c:
                tools = [x.name for x in (await c.list_tools()).tools]
                one = await c.call_tool("get_ticket", {"ticket_id": "TCK-20123"})
            denied = await raw_post(t, CALL_ADD_NOTE, token("tickets:read"))
            return tools, one, denied

    tools, one, denied = asyncio.run(go())
    assert set(tools) == {"search_tickets", "get_ticket", "add_note", "set_status"}
    assert one.structured_content["ticket_id"] == "TCK-20123"
    assert denied.status_code == 403
    www = denied.headers["www-authenticate"]
    assert 'error="insufficient_scope"' in www and "tickets:write" in www


# ---- TODO 3: who wrote it comes from the token ----------------------------------------


def test_write_token_writes_and_the_author_comes_from_the_token(server, token):
    async def go():
        async with served(server) as t:
            async with mcp_client(t, token("tickets:read tickets:write", sub="ravi@shopkart.in")) as c:
                tools = {x.name: x for x in (await c.list_tools()).tools}
                out = await c.call_tool("add_note", {"ticket_id": "TCK-20123", "text": "Escalate: above ₹5,000"})
                await c.call_tool("set_status", {"ticket_id": "TCK-20123", "status": "escalated"})
                return tools, out

    tools, out = asyncio.run(go())
    assert "author" not in tools["add_note"].input_schema["properties"]  # the model can't pick a name
    note = out.structured_content["notes"][-1]
    assert note["author"] == "ravi@shopkart.in"
    state = json.loads(Path(os.environ["SHOPKART_TICKET_STATE"]).read_text())
    assert state["TCK-20123"]["status"] == "escalated"


def test_wrong_host_is_refused(server, token):
    async def go():
        async with served(server) as t:
            return await raw_post(t, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token(), host="evil.example")

    assert asyncio.run(go()).status_code == 421


def test_state_goes_to_the_shared_table_when_set(server, monkeypatch):
    class FakeTable:
        rows: dict = {}

        def scan(self, **kw):
            return {"Items": [{"ticket_id": k, "ticket_state": v} for k, v in self.rows.items()]}

        def put_item(self, Item):
            self.rows[Item["ticket_id"]] = Item["ticket_state"]

    monkeypatch.setattr(server, "TABLE_NAME", "shopkart-ticket-state")
    monkeypatch.setattr(server, "_table", lambda: FakeTable())
    server._save_ticket("TCK-20101", {"status": "resolved"})
    assert server._state() == {"TCK-20101": {"status": "resolved"}}
    assert not Path(os.environ["SHOPKART_TICKET_STATE"]).exists()  # nothing written to local files


# ---- the app: Part 1's Copilot over HTTPS with a token ------------------------------------


def tool_use(name: str, args: dict, tid: str = "tu_1") -> dict:
    return {"id": "msg_t", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": [{"type": "tool_use", "id": tid, "name": name, "input": args}],
            "stop_reason": "tool_use", "stop_sequence": None, "usage": {"input_tokens": 50, "output_tokens": 10}}


def final(text: str) -> dict:
    return {"id": "msg_f", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 60, "output_tokens": 12}}


def test_the_copilot_uses_the_remote_server(server, token, capsys):
    app = load("remote_copilot", LAB / "done")
    fake = FakeServer("anthropic", [tool_use("search_tickets", {"query": "cracked screen"}), final("Two tickets.")])

    async def go():
        async with served(server) as t:
            return await app.ask("Which tickets mention a cracked screen?", llm=fake.llm(),
                                 url=URL, token=token("tickets:read"), transport=t)

    out = asyncio.run(go())
    assert out["tools"] == ["search_tickets"] and out["answer"] == "Two tickets."
    assert "over Streamable HTTP" in capsys.readouterr().out


def test_the_copilot_asks_for_step_up_on_403(server, token):
    app = load("remote_copilot", LAB / "done")
    fake = FakeServer("anthropic", [tool_use("add_note", {"ticket_id": "TCK-20123", "text": "x"})])

    async def go():
        async with served(server) as t:
            try:
                await app.ask("Add a note to TCK-20123", llm=fake.llm(), url=URL,
                              token=token("tickets:read"), transport=t)
            except app.StepUpNeeded as exc:
                return exc

    err = asyncio.run(go())
    assert isinstance(err, app.StepUpNeeded) and "tickets:write" in err.scope
