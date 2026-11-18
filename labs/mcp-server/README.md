# Lab: an MCP server for ShopKart's ticket system (Part 1, build)

Build one MCP server with all three doors, test it with the MCP Inspector, then use it from your own app and from Claude Code.
Part 2 (later) puts the same server online with a login.

| Door | Who decides | In this server |
| --- | --- | --- |
| Tools | the model | `search_tickets`, `get_ticket`, `add_note`, `set_status` |
| Resource | the app | `shopkart://tickets/{ticket_id}` (a template) |
| Prompt | the user | `summarise_ticket` (a slash command in Claude Code) |

```text
labs/mcp-server/
  start/ticket_server.py   your server, with TODO 1–4
  start/copilot.py         your app's MCP client, with TODO 5–7
  done/                    the finished answer
  tests/                   the checkpoints (no key, no network)
```

The tickets come from `data/tickets.json` (read only). Notes and status changes go to `.shopkart/ticket-state.json` (gitignored). Delete it to start fresh.
SDK: the official MCP Python SDK, `mcp` 2.3.0 (`from mcp.server import MCPServer`), which speaks the 2026-07-28 spec: no handshake or session, so the same server can later run behind a load balancer.

## 1. Build the server (`start/ticket_server.py`)

`search_tickets` is done as the example: a function with `@mcp.tool()`. The type hints become the input schema, the docstring becomes the description, and the Pydantic return type becomes the output schema.

1. **TODO 1, `get_ticket`.** A read-only tool (`ToolAnnotations(read_only_hint=True)`). A wrong ID raises `ToolError`, so the model reads a useful message instead of "Error executing tool".
2. **TODO 2, `add_note` and `set_status`.** They change things, so `read_only_hint=False`. `set_status` is idempotent; `add_note` is not. Hints are only hints: a host should not trust them from a server it doesn't trust.
3. **TODO 3, the resource template** `shopkart://tickets/{ticket_id}`. One address with a blank covers all 61 tickets.
4. **TODO 4, the prompt** `summarise_ticket`. It returns messages, and the first one embeds the ticket as a resource.

Logs go to **stderr**. On stdio, stdout is the wire: one `print("server started")` and the client gets a line that isn't JSON.

## 2. Test it with the MCP Inspector

The Codespace has Node, so `npx` works. CLI mode needs no browser:

```bash
I="npx -y @modelcontextprotocol/inspector@2.15.0 --cli"
S="uv run python labs/mcp-server/start/ticket_server.py"      # done/ for the answer
$I $S -- --method tools/list
$I $S -- --method tools/call --tool-name get_ticket --tool-arg ticket_id=TCK-20104
$I $S -- --method resources/templates/list
$I $S -- --method resources/read --uri shopkart://tickets/TCK-20101
$I $S -- --method prompts/get --prompt-name summarise_ticket --prompt-args ticket_id=TCK-20101
```

Everything before `--` is the server command. Everything after it goes to the Inspector.
Inspector 2.x asks for Node 22.23.4+, 24.22.1+ or 26.12.1+. On an older Node, npm prints an `EBADENGINE` warning, and the CLI still worked in our test.
There's also a terminal UI (`npx @modelcontextprotocol/inspector --tui ...`) and the web UI (no flag). In the browser version of Codespaces, the web UI also needs `ALLOWED_ORIGINS` set to the forwarded address. The CLI avoids that.

## 3. Use it from your app (`start/copilot.py`)

Your app starts the server as a child process and talks to it over stdio (`mcp.Client(StdioServerParameters(...))`). Then:

5. **TODO 5:** turn the MCP tool list into Claude's tool format (OpenAI's is already there).
6. **TODO 6, the app's door:** `--attach TCK-…` reads the ticket resource and puts it in the context.
7. **TODO 7, the model's door:** run each tool call the model asks for with `mcp.call_tool`, and send the result back.

`--summarise TCK-…` is the user's door: it gets the server's prompt and sends it as it is.
Every LLM call still goes through `shopkart.llm`: the budget check, retries and the cost log.

```bash
uv run python labs/mcp-server/start/copilot.py "Find the ticket about the cracked Nova 5G phone. Add a short note for the team, and escalate it if the refund is above ₹5,000."
uv run python labs/mcp-server/start/copilot.py "Can this customer still return them? Draft a reply." --attach TCK-20104
uv run python labs/mcp-server/start/copilot.py --summarise TCK-20123
# add --provider openai for the same run on gpt-6-luna
```

Notice the second run. The Copilot can read the ticket, but it doesn't know the return window. MCP gives access. Know-how is the next lab, the skill.

## 4. Use it from Claude Code

Claude Code is the host here, so it starts the server itself. In the Codespace terminal:

```bash
curl -fsSL https://claude.ai/install.sh | bash      # once; then run `claude` and log in
claude mcp add --transport stdio --scope project shopkart-tickets -- uv run python labs/mcp-server/start/ticket_server.py
claude mcp list
```

`--scope project` writes `.mcp.json` at the repo root, so your team gets the same server through git. Claude Code asks you to approve it the first time it starts. Inside `claude`:

- `/mcp` shows the server, its 4 tools and its prompt.
- Ask: *"Which open tickets mention a cracked screen? Escalate the one above ₹5,000."* Claude asks before it runs `add_note` or `set_status`.
- The prompt is a slash command: `/mcp__shopkart-tickets__summarise_ticket TCK-20123` (also `/mcp__shopkart-tickets__summarise_ticket`).
- A resource is an @-mention: `@shopkart-tickets:shopkart://tickets/TCK-20101`.

## 5. Checkpoint

```bash
LAB=start uv run pytest labs/mcp-server -q      # your copy
uv run pytest labs/mcp-server -q                # the answer
```

- [ ] The Inspector lists 4 tools, 1 resource template and 1 prompt
- [ ] A wrong ticket ID comes back as a readable error (`isError: true`), not a crash
- [ ] Your app's Copilot finds, notes and escalates the ₹18,999 Nova 5G ticket
- [ ] Claude Code shows the server in `/mcp` and runs the prompt as a slash command

The real output of a live run is in [RUN.md](RUN.md).
