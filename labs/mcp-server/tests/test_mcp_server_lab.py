"""The lab's checkpoints: no key, no network, no cost.

Against the finished answer:   uv run pytest labs/mcp-server -q
Against your copy:             LAB=start uv run pytest labs/mcp-server -q
"""

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from tests.fakes import FakeServer, anthropic_message, openai_response

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"mcp_lab_{FOLDER.name}_{name}", FOLDER / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    """Fake keys and a throwaway spend ledger: nothing real is touched."""
    monkeypatch.setattr("shopkart.budget.LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setenv("DAILY_BUDGET_USD", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")


@pytest.fixture
def server(tmp_path, monkeypatch):
    mod = _load("ticket_server")
    monkeypatch.setattr(mod, "STATE_FILE", tmp_path / "ticket-state.json")
    return mod


def run(coro):
    return asyncio.run(coro)


# ---- the server: three doors -------------------------------------------------


def test_four_tools_with_schemas_and_hints(server):
    async def go():
        async with Client(server.mcp) as c:
            return {t.name: t for t in (await c.list_tools()).tools}

    tools = run(go())
    assert set(tools) == {"search_tickets", "get_ticket", "add_note", "set_status"}
    assert tools["get_ticket"].input_schema["required"] == ["ticket_id"]
    assert tools["get_ticket"].output_schema is not None  # structured JSON back
    assert tools["search_tickets"].annotations.read_only_hint is True
    assert tools["set_status"].annotations.read_only_hint is False
    assert set(tools["set_status"].input_schema["properties"]["status"]["enum"]) == {
        "open", "waiting_on_customer", "escalated", "resolved"}


def test_search_and_get(server):
    async def go():
        async with Client(server.mcp) as c:
            found = await c.call_tool("search_tickets", {"query": "cracked screen"})
            one = await c.call_tool("get_ticket", {"ticket_id": "tck-20123"})
            missing = await c.call_tool("get_ticket", {"ticket_id": "TCK-99999"})
            return found, one, missing

    found, one, missing = run(go())
    assert [t["ticket_id"] for t in found.structured_content["tickets"]] == ["TCK-20101", "TCK-20123"]
    t = one.structured_content
    assert t["order"]["total_inr"] > 5000 and t["status"] == "open"
    assert "labels" not in t  # eval labels never reach the model
    assert missing.is_error and "TCK-20101" in missing.content[0].text  # a message the model can act on


def test_note_and_status_are_saved(server):
    async def go():
        async with Client(server.mcp) as c:
            await c.call_tool("add_note", {"ticket_id": "TCK-20123", "text": "Above ₹5,000: needs a human."})
            await c.call_tool("set_status", {"ticket_id": "TCK-20123", "status": "escalated"})
            bad = await c.call_tool("set_status", {"ticket_id": "TCK-20123", "status": "deleted"})
            escalated = await c.call_tool("search_tickets", {"status": "escalated"})
            return bad, escalated

    bad, escalated = run(go())
    assert bad.is_error  # not one of the four statuses: the schema refuses it
    assert [t["ticket_id"] for t in escalated.structured_content["tickets"]] == ["TCK-20123"]
    saved = json.loads(server.STATE_FILE.read_text())
    assert saved["TCK-20123"]["status"] == "escalated"
    assert saved["TCK-20123"]["notes"][0]["text"] == "Above ₹5,000: needs a human."


def test_ticket_resource_template(server):
    async def go():
        async with Client(server.mcp) as c:
            templates = await c.list_resource_templates()
            read = await c.read_resource("shopkart://tickets/TCK-20104")
            return templates, read

    templates, read = run(go())
    assert [t.uri_template for t in templates.resource_templates] == ["shopkart://tickets/{ticket_id}"]
    assert json.loads(read.contents[0].text)["order_id"] == "SK47731"


def test_summarise_prompt_embeds_the_ticket(server):
    async def go():
        async with Client(server.mcp) as c:
            listed = await c.list_prompts()
            got = await c.get_prompt("summarise_ticket", {"ticket_id": "TCK-20101"})
            return listed, got

    listed, got = run(go())
    assert [p.name for p in listed.prompts] == ["summarise_ticket"]
    kinds = [m.content.type for m in got.messages]
    assert "resource" in kinds and "text" in kinds
    embedded = next(m.content.resource for m in got.messages if m.content.type == "resource")
    assert embedded.uri == "shopkart://tickets/TCK-20101"


def test_stdio_server_starts_and_keeps_stdout_clean(tmp_path):
    """Over real stdio: a print() to stdout would corrupt the stream."""
    params = StdioServerParameters(command=sys.executable, args=[str(FOLDER / "ticket_server.py")],
                                   env={"SHOPKART_TICKET_STATE": str(tmp_path / "s.json")})

    async def go():
        async with Client(params) as c:
            return await c.call_tool("get_ticket", {"ticket_id": "TCK-20101"})

    assert run(go()).structured_content["order_id"] == "SK48213"


# ---- the app: an MCP client + tool calling, with fake LLM servers ------------


def _tool_use(name: str, args: dict) -> dict:
    msg = anthropic_message("", stop_reason="tool_use")
    msg["content"] = [{"type": "tool_use", "id": "toolu_1", "name": name, "input": args}]
    return msg


def _function_call(name: str, args: dict) -> dict:
    resp = openai_response("")
    resp["output"] = [{"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": name,
                       "arguments": json.dumps(args), "status": "completed"}]
    return resp


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_copilot_runs_the_tools_the_model_asks_for(server, provider):
    copilot = _load("copilot")
    if provider == "anthropic":
        fake = FakeServer("anthropic", [_tool_use("get_ticket", {"ticket_id": "TCK-20123"}),
                                        anthropic_message("Escalate it: ₹18,999 is above ₹5,000.")])
    else:
        fake = FakeServer("openai", [_function_call("get_ticket", {"ticket_id": "TCK-20123"}),
                                     openai_response("Escalate it: ₹18,999 is above ₹5,000.")])

    out = run(copilot.run("What about the Nova phone?", llm=fake.llm(), server=server.mcp, show=lambda *_: None))

    assert out["tools"] == ["get_ticket"]
    assert out["answer"].startswith("Escalate it")
    assert fake.calls == 2 and out["cost_usd"] > 0
    first, second = fake.requests
    names = [t["name"] for t in first["tools"]]
    assert set(names) == {"search_tickets", "get_ticket", "add_note", "set_status"}
    # The tool's result went back to the model in the second request.
    assert "SK48450" in json.dumps(second)


def test_attach_reads_the_resource_into_the_context(server):
    copilot = _load("copilot")
    fake = FakeServer("anthropic", [anthropic_message("Outside the 10-day footwear window.")])
    run(copilot.run("Can they return it?", llm=fake.llm(), attach="TCK-20104", server=server.mcp,
                    show=lambda *_: None))
    sent = fake.requests[0]["messages"][0]["content"]
    assert "<ticket>" in sent and "SK47731" in sent
