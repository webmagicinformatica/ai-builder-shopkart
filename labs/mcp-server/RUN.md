# Live run: MCP server lab (Part 1)

Recorded 2026-11-17 in this repo with real keys, on `claude-haiku-5-5`, plus one OpenAI smoke run on `gpt-6-luna`.
Commands as typed and exactly what they printed (stdout and stderr). Model answers will differ on your run. `.shopkart/ticket-state.json` was deleted before the first Copilot run (and before the OpenAI run), so the summary sees the note and status the first run added.

## Tests (no key, no network)

```text
$ uv run pytest labs/mcp-server -q
9 passed in 2.91s

$ LAB=start uv run pytest labs/mcp-server -q        # the start/ copy, before the TODOs
9 failed in 2.98s
```

## The MCP Inspector (CLI mode)

```text
$ npx -y @modelcontextprotocol/inspector@2.15.0 --cli uv run python labs/mcp-server/done/ticket_server.py -- --method tools/list | grep '"name"'
[tickets] starting on stdio: 61 tickets
      "name": "search_tickets",
      "name": "get_ticket",
      "name": "add_note",
      "name": "set_status",

$ npx -y @modelcontextprotocol/inspector@2.15.0 --cli uv run python labs/mcp-server/done/ticket_server.py -- --method tools/call --tool-name get_ticket --tool-arg ticket_id=TCK-20104
[tickets] starting on stdio: 61 tickets
{
  "content": [
    {
      "type": "text",
      "text": "{\n  \"ticket_id\": \"TCK-20104\",\n  \"created_at\": \"2026-11-14T13:56+05:30\",\n  \"channel\": \"chat\",\n  \"language\": \"en\",\n  \"customer_id\": \"C1003\",\n  \"order_id\": \"SK47731\",\n  \"message\": \"I bought running shoes 12 days ago (order SK47731). Can I still return them?\",\n  \"status\": \"open\",\n  \"notes\": [],\n  \"order\": {\n    \"order_id\": \"SK47731\",\n    \"status\": \"delivered\",\n    \"items\": [\n      \"1 x Stride RN210 Running Shoes (₹2,799)\"\n    ],\n    \"total_inr\": 2799,\n    \"payment_method\": \"upi\",\n    \"delivered_on\": \"2026-11-05\"\n  }\n}"
    }
  ],
  "structuredContent": {
    "ticket_id": "TCK-20104",
    "created_at": "2026-11-14T13:56+05:30",
    "channel": "chat",
    "language": "en",
    "customer_id": "C1003",
    "order_id": "SK47731",
    "message": "I bought running shoes 12 days ago (order SK47731). Can I still return them?",
    "status": "open",
    "notes": [],
    "order": {
      "order_id": "SK47731",
      "status": "delivered",
      "items": [
        "1 x Stride RN210 Running Shoes (₹2,799)"
      ],
      "total_inr": 2799,
      "payment_method": "upi",
      "delivered_on": "2026-11-05"
    }
  },
  "isError": false
}

$ npx -y @modelcontextprotocol/inspector@2.15.0 --cli uv run python labs/mcp-server/done/ticket_server.py -- --method tools/call --tool-name get_ticket --tool-arg ticket_id=TCK-99999
[tickets] starting on stdio: 61 tickets
[tickets] Tool 'get_ticket' failed: 'Error executing tool get_ticket: No ticket TCK-99999. Ticket IDs look like TCK-20101; use search_tickets to find one.'
{
  "content": [
    {
      "type": "text",
      "text": "Error executing tool get_ticket: No ticket TCK-99999. Ticket IDs look like TCK-20101; use search_tickets to find one."
    }
  ],
  "isError": true
}
{"error":{"code":"tool_is_error","message":"Tool 'get_ticket' returned isError:true."}}

$ npx -y @modelcontextprotocol/inspector@2.15.0 --cli uv run python labs/mcp-server/done/ticket_server.py -- --method resources/templates/list
[tickets] starting on stdio: 61 tickets
{
  "resourceTemplates": [
    {
      "name": "ticket_resource",
      "uriTemplate": "shopkart://tickets/{ticket_id}",
      "description": "One ShopKart support ticket, with its notes and linked order, as JSON.",
      "mimeType": "application/json"
    }
  ]
}

$ npx -y @modelcontextprotocol/inspector@2.15.0 --cli uv run python labs/mcp-server/done/ticket_server.py -- --method resources/read --uri shopkart://tickets/TCK-20101
[tickets] starting on stdio: 61 tickets
{
  "contents": [
    {
      "uri": "shopkart://tickets/TCK-20101",
      "mimeType": "application/json",
      "text": "{\n  \"ticket_id\": \"TCK-20101\",\n  \"created_at\": \"2026-11-14T09:05+05:30\",\n  \"channel\": \"chat\",\n  \"language\": \"en\",\n  \"customer_id\": \"C1001\",\n  \"order_id\": \"SK48213\",\n  \"message\": \"My order SK48213 arrived with a cracked screen. I want my money back.\",\n  \"status\": \"open\",\n  \"notes\": [],\n  \"order\": {\n    \"order_id\": \"SK48213\",\n    \"status\": \"delivered\",\n    \"items\": [\n      \"1 x Pulse Fit S2 Smartwatch (₹1,299)\"\n    ],\n    \"total_inr\": 1299,\n    \"payment_method\": \"upi\",\n    \"delivered_on\": \"2026-11-13\"\n  }\n}"
    }
  ]
}

$ npx -y @modelcontextprotocol/inspector@2.15.0 --cli uv run python labs/mcp-server/done/ticket_server.py -- --method prompts/get --prompt-name summarise_ticket --prompt-args ticket_id=TCK-20101
[tickets] starting on stdio: 61 tickets
{
  "description": "Summarise one support ticket for a teammate: the problem, what's been done, the next step.",
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "resource",
        "resource": {
          "uri": "shopkart://tickets/TCK-20101",
          "mimeType": "application/json",
          "text": "{\n  \"ticket_id\": \"TCK-20101\",\n  \"created_at\": \"2026-11-14T09:05+05:30\",\n  \"channel\": \"chat\",\n  \"language\": \"en\",\n  \"customer_id\": \"C1001\",\n  \"order_id\": \"SK48213\",\n  \"message\": \"My order SK48213 arrived with a cracked screen. I want my money back.\",\n  \"status\": \"open\",\n  \"notes\": [],\n  \"order\": {\n    \"order_id\": \"SK48213\",\n    \"status\": \"delivered\",\n    \"items\": [\n      \"1 x Pulse Fit S2 Smartwatch (₹1,299)\"\n    ],\n    \"total_inr\": 1299,\n    \"payment_method\": \"upi\",\n    \"delivered_on\": \"2026-11-13\"\n  }\n}"
        }
      }
    },
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Summarise ticket TCK-20101 for a ShopKart support teammate, in English, in at most four short lines: 1) the customer's problem, 2) the order and its state, 3) what has been done so far (notes, status), 4) the next step. Refunds above ₹5,000 need a human. Never repeat card numbers, CVVs, OTPs or ID numbers."
      }
    }
  ]
}

```

`npx` also printed an `EBADENGINE` warning here (Node 22.23.3, the Inspector asks for 22.23.4+). It's left out above.

## From your app (Anthropic, main video)

```text
$ uv run python labs/mcp-server/done/copilot.py "Find the ticket about the cracked Nova 5G phone. Add a short note for the team, and escalate it if the refund is above ₹5,000."
[tickets] starting on stdio: 61 tickets
[tickets] note added to TCK-20123 by copilot
[tickets] TCK-20123: open -> escalated
Connected to shopkart-tickets over stdio: 4 tools (search_tickets, get_ticket, add_note, set_status)
  -> search_tickets({"query": "cracked Nova 5G", "limit": 10})  ok
  -> get_ticket({"ticket_id": "TCK-20123"})  ok
  -> add_note({"ticket_id": "TCK-20123", "text": "Customer reports Nova 5G (order SK48450) arrived with a cracked screen and requests a refund of ₹18,999. Order status is returned. Refund exceeds ₹5,000, so escalated to a human agent for approval. No refund promised to the customer."})  ok
  -> set_status({"ticket_id": "TCK-20123", "status": "escalated"})  ok

Copilot: I'll start by searching for the ticket.

The refund is ₹18,999, which is above ₹5,000, so it needs escalation. I'll add the note and escalate.

Found ticket TCK-20123 (order SK48450, cracked Nova 5G, refund requested ₹18,999).

- **Note added:** the refund request, the order's returned status, and that no refund was promised.
- **Escalated:** the refund is above ₹5,000, so it's now with a human agent.

claude-haiku-5-5 · 4 tool calls · $0.000982 (₹0.0864) · today $0.026122

$ uv run python labs/mcp-server/done/copilot.py --summarise TCK-20123
[tickets] starting on stdio: 61 tickets
Connected to shopkart-tickets over stdio: 4 tools (search_tickets, get_ticket, add_note, set_status)
Prompt summarise_ticket(TCK-20123): 2 messages, one embeds the ticket resource

Copilot: 1) Customer says their Nova 5G arrived with a cracked screen and wants a ₹18,999 refund.
2) Order SK48450 (1 x Nova 5G, ₹18,999, card payment, delivered 4 Nov 2026); order status is "returned".
3) Copilot note added: refund exceeds ₹5,000, escalated to a human; no refund promised. Ticket status is escalated.
4) Next step: a human agent needs to review the cracked-screen claim and approve or decline the ₹18,999 refund.

claude-haiku-5-5 · 0 tool calls · $0.000261 (₹0.0230) · today $0.026384

$ uv run python labs/mcp-server/done/copilot.py "Can this customer still return them? Draft a reply." --attach TCK-20104
[tickets] starting on stdio: 61 tickets
Connected to shopkart-tickets over stdio: 4 tools (search_tickets, get_ticket, add_note, set_status)
Attached resource shopkart://tickets/TCK-20104

Copilot: I need the return window policy, which isn't in the tools I have. Based on the ticket data: the order was delivered on 2026-11-05, and today is 2026-11-17, so it has been 12 days since delivery.

I can't confirm eligibility from the information available. ShopKart's return window policy isn't accessible to me, so I'd check it before replying.

**Draft reply to the customer:**

> Hi, thanks for reaching out about order SK47731 (Stride RN210 Running Shoes). Your order was delivered on 5 November 2026. Let me check our return policy for this item and confirm whether a return is still possible. I'll get back to you shortly with the details and next steps.

**Facts for you:**
- Delivered: 5 Nov 2026 (12 days ago)
- Amount: ₹2,799, so a refund would be under the ₹5,000 escalation threshold
- Payment: UPI

If you tell me the return window (e.g. 7, 10, or 30 days), I can confirm eligibility and add an internal note to the ticket.

claude-haiku-5-5 · 0 tool calls · $0.000320 (₹0.0282) · today $0.023486
```

The server's log lines (`[tickets] ...`) are its stderr. They show first because the Copilot's stdout was piped while recording; in a terminal they interleave.
The `--attach` run was recorded a few minutes earlier, on a fresh state file, so its "today" total is lower.

## OpenAI smoke run

```text
$ uv run python labs/mcp-server/done/copilot.py "Find the ticket about the cracked Nova 5G phone. Add a short note for the team, and escalate it if the refund is above ₹5,000." --provider openai
[tickets] starting on stdio: 61 tickets
[tickets] note added to TCK-20123 by copilot
[tickets] TCK-20123: open -> escalated
Connected to shopkart-tickets over stdio: 4 tools (search_tickets, get_ticket, add_note, set_status)
  -> search_tickets({"query": "cracked Nova 5G phone", "limit": 10})  ok
  -> get_ticket({"ticket_id": "TCK-20123"})  ok
  -> add_note({"ticket_id": "TCK-20123", "text": "Customer reports Nova 5G arrived with cracked screen and requests ₹18,999 refund. Order is marked returned; refund exceeds ₹5,000 and requires human review.", "author": "copilot"})  ok
  -> set_status({"ticket_id": "TCK-20123", "status": "escalated"})  ok

Copilot: Ticket TCK-20123 has a team note and is escalated for human review. The requested refund is ₹18,999, above the ₹5,000 threshold.

gpt-6-luna · 4 tool calls · $0.000419 (₹0.0369) · today $0.025140
```

What differs: the same MCP tools are sent as Responses API `function` tools, and results go back as `function_call_output` items instead of `tool_result` blocks.

## From Claude Code

Claude Code needs the owner's login, so the video records this step separately. The commands:

```bash
curl -fsSL https://claude.ai/install.sh | bash
claude                                   # log in once (press c to copy the URL if no browser opens), then /exit
claude mcp add --transport stdio --scope project shopkart-tickets -- uv run python labs/mcp-server/done/ticket_server.py
claude mcp list                          # shopkart-tickets ... ⏸ Pending approval, until the first `claude` start
claude
> /mcp
> Which open tickets mention a cracked screen? Escalate the one above ₹5,000.
> /mcp__shopkart-tickets__summarise_ticket TCK-20123
> Summarise @shopkart-tickets:shopkart://tickets/TCK-20101 in one line.
```

Checked here (Claude Code 2.1.302): `claude mcp add --scope project` wrote this `.mcp.json`, and `claude mcp list` showed it as pending approval. Added with the default local scope instead, `claude mcp list` connected to it straight away (`✔ Connected`).

```json
{
  "mcpServers": {
    "shopkart-tickets": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run",
        "python",
        "labs/mcp-server/done/ticket_server.py"
      ],
      "env": {}
    }
  }
}
```

## Cost

| Provider | Live runs (including practice runs while building) | Spend |
| --- | --- | --- |
| Anthropic `claude-haiku-5-5` | 11 Copilot runs | $0.0079 |
| OpenAI `gpt-6-luna` | 2 Copilot runs (the smoke run above, and one practice run) | $0.0008 |

The Inspector runs and the tests cost nothing: no model is called.

**Total spend for this lab: $0.0079 on Anthropic, $0.0008 on OpenAI.**
