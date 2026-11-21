"""The Copilot from Part 1, now using the REMOTE ticket server: over HTTPS, with a token.

    export MCP_URL=https://<your function URL>/mcp
    export MCP_TOKEN=$(uv run python labs/mcp-remote/done/issue_token.py token --sub asha@shopkart.in --aud $MCP_URL)
    uv run python labs/mcp-remote/done/remote_copilot.py "Which open tickets mention a cracked screen?"

The agent loop is Part 1's (labs/mcp-server/done/copilot.py): only the connection changes.
Part 1 started the server as a child process (stdio). Here the server is a URL, and every
request carries the token in an Authorization header.

When a tool needs a scope the token doesn't have, the server answers 403 insufficient_scope,
and this app tells you which scope to ask for (step-up). It never tries to get around it.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import re
import sys
from pathlib import Path

import httpx2
from mcp import MCPError
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from shopkart import budget  # noqa: E402
from shopkart.llm import LLM  # noqa: E402
from shopkart.pricing import usd_to_inr  # noqa: E402


def part1_copilot():
    """Part 1's Copilot: the same tool loop, the same three doors."""
    path = ROOT / "labs" / "mcp-server" / "done" / "copilot.py"
    spec = importlib.util.spec_from_file_location("part1_copilot", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StepUpNeeded(Exception):
    def __init__(self, scope: str, www_authenticate: str):
        self.scope = scope
        self.www_authenticate = www_authenticate
        super().__init__(f"the server needs scope {scope}")


def connect(url: str, token: str, seen: dict, transport: httpx2.AsyncBaseTransport | None = None):
    """A Streamable HTTP connection that sends the token, and remembers a 403's WWW-Authenticate."""

    async def remember(response: httpx2.Response) -> None:
        if response.status_code in (401, 403):
            seen["status"] = response.status_code
            # Lambda function URLs rename this header to x-amzn-Remapped-www-authenticate.
            seen["www"] = (response.headers.get("www-authenticate")
                           or response.headers.get("x-amzn-remapped-www-authenticate", ""))

    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30,
                              event_hooks={"response": [remember]}, transport=transport)
    return streamable_http_client(url, http_client=http)


async def ask(question: str, *, llm: LLM, url: str, token: str, attach: str | None = None,
              summarise: str | None = None, transport: httpx2.AsyncBaseTransport | None = None) -> dict:
    copilot = part1_copilot()
    seen: dict = {}

    def show(line: str) -> None:
        print(line.replace("over stdio", f"over Streamable HTTP ({url.split('/')[2]})"))

    try:
        return await copilot.run(question, llm=llm, attach=attach, summarise=summarise,
                                 server=connect(url, token, seen, transport), show=show)
    except (MCPError, BaseExceptionGroup):  # inside the client's task group it arrives as a group
        if seen.get("status") == 403:
            needed = re.search(r'scope="([^"]*)"', seen["www"])
            raise StepUpNeeded(needed.group(1) if needed else "?", seen["www"]) from None
        if seen.get("status") == 401:
            raise PermissionError("401: the token is missing, expired, or made for another server") from None
        raise


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ShopKart Copilot with the REMOTE ticket MCP server")
    p.add_argument("question", nargs="?", default="")
    p.add_argument("--attach", metavar="TICKET_ID")
    p.add_argument("--summarise", metavar="TICKET_ID")
    p.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    args = p.parse_args(argv)
    if not args.question and not args.summarise:
        p.error("give a question, or --summarise TICKET_ID")
    url, token = os.environ.get("MCP_URL"), os.environ.get("MCP_TOKEN")
    if not url or not token:
        p.error("set MCP_URL (ending in /mcp) and MCP_TOKEN first")

    llm = LLM(args.provider)
    try:
        out = asyncio.run(ask(args.question, llm=llm, url=url, token=token,
                              attach=args.attach, summarise=args.summarise))
    except StepUpNeeded as exc:
        print(f"\n403 insufficient_scope. The server says this needs: {exc.scope}")
        print("Ask a team lead to approve write access, then get a new token with that scope.")
        return 3
    except PermissionError as exc:
        print(f"\n{exc}")
        return 4
    except budget.BudgetExceeded as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"\nCopilot: {out['answer']}\n")
    print(f"{llm.model} · {len(out['tools'])} tool calls · ${out['cost_usd']:.6f} "
          f"(₹{usd_to_inr(out['cost_usd']):.4f}) · today ${budget.spent_today():.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
