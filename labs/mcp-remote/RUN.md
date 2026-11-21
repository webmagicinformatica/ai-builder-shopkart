# Live run: MCP server Part 2, remote with login (2026-11-21)

A real run of `done/` on AWS Lambda in `ap-southeast-2`. Commands are the README's; output exactly as printed (`...` marks lines left out). Your URLs and IDs will differ.

## Checkpoints

```text
$ uv run pytest labs/mcp-remote -q
........                                                                 [100%]
8 passed in 2.61s
```

## Deploy

```text
$ uv run python labs/mcp-remote/done/issue_token.py keygen
private key: .../.shopkart/mcp-issuer.pem (stays here)
public key:  .../.shopkart/mcp-issuer.pub (goes to the server)

$ aws ecr create-repository --repository-name $MCP_REPO --query repository.repositoryUri --output text
045510280991.dkr.ecr.ap-southeast-2.amazonaws.com/shopkart-tickets-mcp
$ docker build ... && docker push $MCP_IMAGE
045510280991.dkr.ecr.ap-southeast-2.amazonaws.com/shopkart-tickets-mcp:0cb0212
$ aws iam create-role --role-name shopkart-mcp-lambda ... --query Role.Arn --output text
arn:aws:iam::045510280991:role/shopkart-mcp-lambda
$ aws lambda create-function --function-name $MCP_FUNCTION ... --query '{name: FunctionName, state: State}'
{
    "name": "shopkart-tickets-mcp",
    "state": "Pending"
}
$ aws lambda create-function-url-config --function-name $MCP_FUNCTION --auth-type NONE --query FunctionUrl --output text
https://zs3nmxdihrtwjibhrngzgm52ty0fuhdu.lambda-url.ap-southeast-2.on.aws/
$ export MCP_URL=...mcp; aws lambda update-function-configuration ... --query LastUpdateStatus --output text
InProgress
```

The image is 242 MB (the MCP SDK, PyJWT with cryptography, uvicorn, boto3).

## No token, and the metadata

```text
$ curl -s -i -X POST $MCP_URL -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | grep -iE "^HTTP|www-authenticate"
HTTP/1.1 401 Unauthorized
x-amzn-Remapped-www-authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="https://zs3nmxdihrtwjibhrngzgm52ty0fuhdu.lambda-url.ap-southeast-2.on.aws/.well-known/oauth-protected-resource/mcp"

$ curl -s $B/.well-known/oauth-protected-resource/mcp
{"resource":"https://zs3nmxdihrtwjibhrngzgm52ty0fuhdu.lambda-url.ap-southeast-2.on.aws/mcp","authorization_servers":["https://auth.shopkart.example"],"scopes_supported":["tickets:read"],"bearer_methods_supported":["header"]}
```

Note the header name: the function URL renamed `WWW-Authenticate`.

## The Inspector, with a read-only token

```text
$ export MCP_TOKEN=$(uv run python labs/mcp-remote/done/issue_token.py token --sub asha@shopkart.in --scope tickets:read --aud $MCP_URL)
$ $I $MCP_URL --transport http --header "Authorization: Bearer $MCP_TOKEN" --method tools/list     (tool names only)
['search_tickets', 'get_ticket', 'add_note', 'set_status']

$ $I $MCP_URL --transport http --header "Authorization: Bearer $MCP_TOKEN" --method tools/call --tool-name get_ticket --tool-arg ticket_id=TCK-20123
{
  "content": [
    {
      "type": "text",
      "text": "{\n  \"ticket_id\": \"TCK-20123\",\n  \"created_at\": \"2026-11-15T20:39+05:30\",\n  \"channel\": \"chat\",\n  \"language\": \"en\",\n  \"customer_id\": \"C1007\",\n  \"order_id\": \"SK48450\",\n  \"message\": \"My Nova 5G phone arrived with a cracked screen. Order SK48450. I want my money back, Rs 18,999.\",\n  \"status\": \"open\",\n  ...

$ $I $MCP_URL --transport http --header "Authorization: Bearer $MCP_TOKEN" --method tools/call --tool-name add_note --tool-arg ticket_id=TCK-20123 --tool-arg text=hi
{"error":{"code":"auth_required","message":"Error POSTing to endpoint: {\"error\": \"insufficient_scope\", \"error_description\": \"Required scope: tickets:write\"}","status":403}}
```

## The Copilot app, over HTTPS with a token

```text
$ uv run python labs/mcp-remote/done/remote_copilot.py "Which open tickets mention a cracked screen? One line each."
Connected to shopkart-tickets over Streamable HTTP (zs3nmxdihrtwjibhrngzgm52ty0fuhdu.lambda-url.ap-southeast-2.on.aws): 4 tools (search_tickets, get_ticket, add_note, set_status)
  -> search_tickets({"query": "cracked screen", "status": "open", "limit": 50})  ok

Copilot: - TCK-20101 (order SK48213): arrived with a cracked screen, customer wants a refund.
- TCK-20123 (order SK48450): Nova 5G phone arrived with a cracked screen, customer wants a refund.

claude-haiku-5-5 · 1 tool calls · $0.000352 (₹0.0309) · today $0.000352

$ uv run python labs/mcp-remote/done/remote_copilot.py "Find the ticket about the cracked Nova 5G phone. Add a short note for the team, and escalate it if the refund is above ₹5,000."
Connected to shopkart-tickets over Streamable HTTP (zs3nmxdihrtwjibhrngzgm52ty0fuhdu.lambda-url.ap-southeast-2.on.aws): 4 tools (search_tickets, get_ticket, add_note, set_status)
  -> search_tickets({"query": "cracked Nova 5G", "limit": 10})  ok
  -> get_ticket({"ticket_id": "TCK-20123"})  ok

403 insufficient_scope. The server says this needs: tickets:read tickets:write
Ask a team lead to approve write access, then get a new token with that scope.
```

Step-up: a new token with the one extra scope.

```text
$ export MCP_TOKEN=$(uv run python labs/mcp-remote/done/issue_token.py token --sub asha@shopkart.in --scope "tickets:read tickets:write" --aud $MCP_URL)
$ uv run python labs/mcp-remote/done/remote_copilot.py "Find the ticket about the cracked Nova 5G phone. Add a short note for the team, and escalate it if the refund is above ₹5,000."
Connected to shopkart-tickets over Streamable HTTP (zs3nmxdihrtwjibhrngzgm52ty0fuhdu.lambda-url.ap-southeast-2.on.aws): 4 tools (search_tickets, get_ticket, add_note, set_status)
  -> search_tickets({"query": "cracked Nova 5G", "limit": 10})  ok
  -> get_ticket({"ticket_id": "TCK-20123"})  ok
  -> add_note({"ticket_id": "TCK-20123", "text": "Customer reports Nova 5G (order SK48450) arrived with a cracked screen and requests a refund of ₹18,999. Order status is already \"returned\". Refund exceeds ₹5,000, so escalated for human approval."})  ok
  -> set_status({"ticket_id": "TCK-20123", "status": "escalated"})  ok

Copilot: I'll start by searching for the ticket.

Found one match. Let me get the full ticket to check the refund amount.

The refund is ₹18,999, which is above ₹5,000, so it needs escalation. I'll add the note and escalate.

Ticket TCK-20123 (order SK48450) is now escalated.

- **Issue:** Nova 5G arrived with a cracked screen; customer wants a refund of ₹18,999.
- **Note added:** Summarises the request and notes that the refund exceeds ₹5,000, so it needs human approval.
- **Status:** Changed from open to escalated.

No refund was promised.

claude-haiku-5-5 · 4 tool calls · $0.000994 (₹0.0875) · today $0.003780
```

Read back by a teammate with a read-only token (another request, possibly another Lambda copy):

```text
$ export MCP_TOKEN=$(uv run python labs/mcp-remote/done/issue_token.py token --sub ravi@shopkart.in --scope tickets:read --aud $MCP_URL)
$ $I $MCP_URL ... --method tools/call --tool-name get_ticket --tool-arg ticket_id=TCK-20123     (status and notes only)
status: escalated
note by asha@shopkart.in · Customer reports Nova 5G (order SK48450) arrived with a cracked screen and requests a refu
```

**What went wrong first:** before the shared table, notes lived in each Lambda copy's `/tmp`. The same read-back then printed `status: open` and `notes: []`: the write had landed on one copy and the read on another. That's why `TICKET_STATE_TABLE` exists.

A token made for another server:

```text
$ MCP_TOKEN=$(... token --sub asha@shopkart.in --scope tickets:read --aud https://orders.shopkart.example/mcp) uv run python labs/mcp-remote/done/remote_copilot.py "Which tickets are open?"

401: the token is missing, expired, or made for another server
```

## OpenAI

```text
$ uv run python labs/mcp-remote/done/remote_copilot.py "Which open tickets mention a cracked screen? One line each." --provider openai
Connected to shopkart-tickets over Streamable HTTP (zs3nmxdihrtwjibhrngzgm52ty0fuhdu.lambda-url.ap-southeast-2.on.aws): 4 tools (search_tickets, get_ticket, add_note, set_status)
  -> search_tickets({"query": "cracked screen", "status": "open", "limit": 10})  ok

Copilot: TCK-20101 — Order SK48213: arrived with a cracked screen; customer wants a refund.
TCK-20123 — Order SK48450: Nova 5G arrived with a cracked screen; customer wants a refund.

gpt-6-luna · 1 tool calls · $0.000143 (₹0.0126) · today $0.002786
```

## Tear down

`bash labs/deploy/teardown.sh all` (full output in the deploy lab's RUN.md) deleted the function, its URL and log group, both ECR repositories, the table and the roles, and ended with every line `none`.

## Spend

- Anthropic (`claude-haiku-5-5`): **$0.0036** for the five Copilot runs (including the two cut short by the 403 and the `/tmp` read-back problem). OpenAI (`gpt-6-luna`): **$0.00014**.
- AWS: Lambda, DynamoDB on demand and ECR storage for under an hour: a fraction of a cent.
