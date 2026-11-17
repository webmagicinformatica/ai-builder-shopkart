"""The Copilot uses the ticket MCP server from YOUR app: an MCP client over stdio + tool calling.

    uv run python labs/mcp-server/done/copilot.py "Find the ticket about the cracked Nova 5G phone. Add a note and set the right status."
    uv run python labs/mcp-server/done/copilot.py "What should we reply?" --attach TCK-20104
    uv run python labs/mcp-server/done/copilot.py --summarise TCK-20123
    ... add --provider openai to run the same thing on OpenAI.

All three doors of the server, from your own code:
  tools     the model picks them: we list them, hand them to the LLM, and run the calls it asks for
  resource  the app decides: --attach reads shopkart://tickets/<id> and puts it in the context
  prompt    the user picks it: --summarise gets the server's summarise_ticket prompt and sends it

Every LLM call goes through shopkart.llm: budget check first, retries, cost log.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from shopkart import budget  # noqa: E402
from shopkart.pricing import usd_to_inr  # noqa: E402
from shopkart.llm import LLM, Result, _anthropic_stop, _anthropic_usage, _openai_stop, _openai_usage  # noqa: E402

SERVER = Path(__file__).resolve().parent / "ticket_server.py"
MAX_TURNS = 8

SYSTEM = (
    "You are ShopKart's support Copilot. You help a ShopKart support agent (staff, not a customer) "
    "work the ticket queue, using the ticket tools. Today is 2026-11-17. Look things up before you answer. "
    "Add notes or change a status only when the agent asks you to. "
    "Refunds above ₹5,000 need a human: escalate them, never promise them. "
    "Never repeat card numbers, CVVs, OTPs or ID numbers. Keep your answer short."
)


def server_params() -> StdioServerParameters:
    """How to start the server: the same Python, as a child process that talks over stdin/stdout."""
    env = {k: os.environ[k] for k in ("SHOPKART_TICKET_STATE", "SHOPKART_DATA_DIR") if k in os.environ}
    return StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env or None)


# --------------------------------------------------------------------------
# MCP tools -> the provider's tool format
# --------------------------------------------------------------------------


def to_anthropic_tools(tools: list[Any]) -> list[dict]:
    # TODO 5: one dict per MCP tool, in Claude's format: name, description, input_schema.
    #   An MCP tool already has all three (t.name, t.description, t.input_schema).
    #   Compare with to_openai_tools below: same data, different key names.
    raise NotImplementedError("TODO 5")


def to_openai_tools(tools: list[Any]) -> list[dict]:
    return [{"type": "function", "name": t.name, "description": t.description or "",
             "parameters": t.input_schema, "strict": False} for t in tools]


def tool_result_text(result: Any) -> str:
    """What the model gets back: the structured JSON if there is any, else the text blocks."""
    if result.structured_content is not None and not result.is_error:
        return json.dumps(result.structured_content, ensure_ascii=False)
    text = "\n".join(getattr(b, "text", "") for b in result.content)
    return f"ERROR: {text}" if result.is_error else text


def resource_text(read_result: Any) -> str:
    return "\n".join(getattr(c, "text", "") for c in read_result.contents)


# --------------------------------------------------------------------------
# One LLM turn with tools, through shopkart.llm
# --------------------------------------------------------------------------
# shopkart.llm has no tool calling of its own, so we reuse its pieces: the same
# provider settings, the budget check and retries (_with_retries), and the cost
# record (_finish). The raw response comes back too, so we can read the tool calls.


def llm_turn(llm: LLM, messages: list, tools: list[dict], max_tokens: int = 800) -> tuple[Result, Any]:
    raw: dict[str, Any] = {}

    def once() -> Result:
        start = time.monotonic()
        if llm.provider == "anthropic":
            args = llm._anthropic_args(messages, SYSTEM, max_tokens, None, False)
            args["tools"] = tools
            resp = llm._client.messages.create(**args)
            text = "".join(b.text for b in resp.content if b.type == "text")
            raw["resp"] = resp
            return llm._finish(text, _anthropic_usage(resp.usage), _anthropic_stop(resp.stop_reason),
                               start, getattr(resp, "_request_id", None))
        args = llm._openai_args(messages, SYSTEM, max_tokens, None)
        args["tools"] = tools
        resp = llm._client.responses.create(**args)
        raw["resp"] = resp
        return llm._finish(resp.output_text, _openai_usage(resp.usage), _openai_stop(resp),
                           start, getattr(resp, "_request_id", None))

    result = llm._with_retries(once)
    return result, raw["resp"]


def tool_calls(llm: LLM, resp: Any) -> list[tuple[str, str, dict]]:
    """(call id, tool name, arguments) for every tool the model asked for."""
    if llm.provider == "anthropic":
        return [(b.id, b.name, b.input) for b in resp.content if b.type == "tool_use"]
    return [(i.call_id, i.name, json.loads(i.arguments or "{}")) for i in resp.output if i.type == "function_call"]


def add_turn(llm: LLM, messages: list, resp: Any, results: list[tuple[str, str]]) -> None:
    """Append the model's turn and our tool results, in each provider's shape."""
    if llm.provider == "anthropic":
        messages.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": cid, "content": out} for cid, out in results]})
    else:
        messages.extend(i.model_dump(exclude_none=True) for i in resp.output)
        messages.extend({"type": "function_call_output", "call_id": cid, "output": out} for cid, out in results)


# --------------------------------------------------------------------------
# The agent loop: the model asks, the MCP client runs, the result goes back
# --------------------------------------------------------------------------


async def run(question: str, *, llm: LLM, attach: str | None = None, summarise: str | None = None,
              server: Any = None, show=print) -> dict:
    """`server`: how to reach the MCP server. Default: start ticket_server.py over stdio."""
    spent = 0.0
    calls_made: list[str] = []
    async with Client(server or server_params()) as mcp:
        listed = await mcp.list_tools()
        show(f"Connected to shopkart-tickets over stdio: {len(listed.tools)} tools "
             f"({', '.join(t.name for t in listed.tools)})")
        tools = to_anthropic_tools(listed.tools) if llm.provider == "anthropic" else to_openai_tools(listed.tools)

        if summarise:  # the USER's door: a prompt from the server, sent as it is
            prompt = await mcp.get_prompt("summarise_ticket", {"ticket_id": summarise})
            show(f"Prompt summarise_ticket({summarise}): {len(prompt.messages)} messages, one embeds the ticket resource")
            parts = []
            for m in prompt.messages:
                c = m.content
                parts.append(c.resource.text if c.type == "resource" else getattr(c, "text", ""))
            messages: list = [{"role": "user", "content": "\n\n".join(parts)}]
        else:
            content = question
            if attach:  # the APP's door: read the resource and put it in the context
                # TODO 6: read shopkart://tickets/<attach> with mcp.read_resource(...), and put its text
                #   (resource_text(...)) before the question, inside <ticket>...</ticket> tags.
                raise NotImplementedError("TODO 6")
            messages = [{"role": "user", "content": content}]

        texts: list[str] = []
        for _ in range(MAX_TURNS):
            result, resp = llm_turn(llm, messages, tools)
            spent += result.cost_usd
            if result.text.strip():
                texts.append(result.text.strip())  # text can come before a tool call too
            calls = tool_calls(llm, resp)
            if not calls:
                break
            outputs = []
            for cid, name, args in calls:  # the MODEL's door: run each tool it asked for
                # TODO 7: run the tool on the MCP server (await mcp.call_tool(name, args)),
                #   turn the result into text for the model (tool_result_text), then
                #   calls_made.append(name), show(...) one line, and outputs.append((cid, text)).
                raise NotImplementedError("TODO 7")
            add_turn(llm, messages, resp, outputs)
        else:
            texts.append("[stopped: too many tool calls]")
    return {"answer": "\n\n".join(texts), "tools": calls_made, "cost_usd": spent}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ShopKart Copilot with the ticket MCP server")
    p.add_argument("question", nargs="?", default="")
    p.add_argument("--attach", metavar="TICKET_ID", help="read this ticket resource into the context")
    p.add_argument("--summarise", metavar="TICKET_ID", help="run the server's summarise_ticket prompt")
    p.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    p.add_argument("--model", default=None)
    args = p.parse_args(argv)
    if not args.question and not args.summarise:
        p.error("give a question, or --summarise TICKET_ID")

    llm = LLM(args.provider, args.model)
    try:
        out = asyncio.run(run(args.question, llm=llm, attach=args.attach, summarise=args.summarise))
    except budget.BudgetExceeded as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"\nCopilot: {out['answer']}\n")
    print(f"{llm.model} · {len(out['tools'])} tool calls · ${out['cost_usd']:.6f} "
          f"(₹{usd_to_inr(out['cost_usd']):.4f}) · today ${budget.spent_today():.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
