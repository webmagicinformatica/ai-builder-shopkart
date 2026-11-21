# Lab: an MCP server for ShopKart's ticket system (Part 2, deploy remotely with login)

Part 1 (`labs/mcp-server`) ran the ticket server on your machine, over stdio. Now it goes online: **Streamable HTTP** on one HTTPS endpoint, on **AWS Lambda**, as an **OAuth resource server** that checks a token on every request, with **two small scopes** instead of one admin key. Then your Copilot app connects to it with a token, and gets a **403 insufficient_scope** when it tries to write with a read-only token.

```text
labs/mcp-remote/
  start/auth.py            the token check and the per-tool scope check: TODO 1–2
  start/ticket_server.py   Part 1's server, made remote (look for "REMOTE"): TODO 3
  start/issue_token.py     a stand-in authorization server: signs tokens (given)
  start/remote_copilot.py  Part 1's Copilot, connected over HTTPS with a token (given)
  start/Dockerfile         the server's image (given)
  done/                    the finished answer
  iam/                     the server's own AWS permission: one table, three actions
  tests/                   the checkpoints (the server in memory, test keys: no AWS, no model)
```

| Scope | Allows |
| --- | --- |
| `tickets:read` | `search_tickets`, `get_ticket`, the ticket resource, the `summarise_ticket` prompt |
| `tickets:write` | `add_note`, `set_status` (they change things) |

**Who issues the tokens?** In production, your company's identity provider (Cognito, Entra ID, Okta, Keycloak...) is the authorization server: it shows the login page, runs PKCE and issues tokens. Here `issue_token.py` plays that role, signing short-lived JWTs with a private key that never leaves your Codespace. The MCP server only gets the **public** key: it can check tokens, never make them.

## 1. The resource server (`start/auth.py`, `start/ticket_server.py`)

- **TODO 1, check every token.** `jwt.decode()` with our public key, `RS256` only, our issuer, and **audience = this server's URL**, requiring `exp`, `sub`, `aud` and `iss`. A token made for another server is refused: no token passthrough. The MCP SDK calls this on every request and answers **401** without a valid token, with a `WWW-Authenticate` header that points to the **protected resource metadata** (`/.well-known/oauth-protected-resource/mcp`). The metadata lists only the basic scope.
- **TODO 2, least privilege.** A write tool needs `tickets:write`. Without it: **403** `insufficient_scope`, naming the scope. The client asks the user to approve it and gets a new token: step-up.
- **TODO 3, identity from the token.** Part 1's `add_note` let the model pass an `author`. Now the author is the token's `sub`. The model never decides who someone is.

Also new in `ticket_server.py`: `stateless_http=True` and JSON responses (no sessions: any copy can answer any request), Host and Origin checks, `/health`, and the state of notes and statuses in a **shared table** (`TICKET_STATE_TABLE`) when it's set. On your laptop it stays a local file.

```bash
LAB=start uv run pytest labs/mcp-remote -q
```

## 2. Run it locally

```bash
uv run python labs/mcp-remote/start/issue_token.py keygen
export MCP_RESOURCE_URL=http://localhost:8000/mcp MCP_ISSUER=https://auth.shopkart.example
export MCP_JWT_PUBLIC_KEY="$(cat .shopkart/mcp-issuer.pub)"
uv run python labs/mcp-remote/start/ticket_server.py &
curl -i -X POST localhost:8000/mcp -H 'Content-Type: application/json' -d '{}'     # 401, and where to log in
curl -s localhost:8000/.well-known/oauth-protected-resource/mcp
```

## 3. Deploy it on Lambda

The same pattern as the Copilot in the deploy lab, Part 2: one image, a function URL, a role. This server needs no LLM key at all.

```bash
source labs/deploy/aws-vars.sh
export MCP_REPO=shopkart-tickets-mcp MCP_FUNCTION=shopkart-tickets-mcp
export MCP_IMAGE=$REGISTRY/$MCP_REPO:$TAG
aws ecr create-repository --repository-name $MCP_REPO --query repository.repositoryUri --output text
aws ecr get-login-password | docker login --username AWS --password-stdin $REGISTRY
docker build --platform linux/amd64 --provenance=false -f labs/mcp-remote/start/Dockerfile -t $MCP_IMAGE . && docker push $MCP_IMAGE
```

**The server's own permissions.** It writes notes to one DynamoDB table, and its role can do exactly three things to that one table, plus write its logs. Nothing else in the account.

```bash
aws dynamodb create-table --table-name shopkart-ticket-state \
  --attribute-definitions AttributeName=ticket_id,AttributeType=S --key-schema AttributeName=ticket_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST --query TableDescription.TableStatus --output text
aws iam create-role --role-name shopkart-mcp-lambda --assume-role-policy-document file://labs/deploy/iam/lambda-trust.json --query Role.Arn --output text
aws iam attach-role-policy --role-name shopkart-mcp-lambda --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam put-role-policy --role-name shopkart-mcp-lambda --policy-name ticket-state-table \
  --policy-document "$(sed "s/ACCOUNT/$ACCOUNT/" labs/mcp-remote/iam/ticket-state-table.json)"
```

The function, then its URL. The server must know its own URL (it's the tokens' audience), so it gets a placeholder first:

```bash
aws lambda create-function --function-name $MCP_FUNCTION \
  --package-type Image --code ImageUri=$MCP_IMAGE \
  --role arn:aws:iam::$ACCOUNT:role/shopkart-mcp-lambda --memory-size 512 --timeout 30 \
  --environment "Variables={MCP_RESOURCE_URL=https://pending/mcp,MCP_ISSUER=https://auth.shopkart.example}" \
  --query '{name: FunctionName, state: State}'
aws lambda wait function-active-v2 --function-name $MCP_FUNCTION
aws lambda create-function-url-config --function-name $MCP_FUNCTION --auth-type NONE --query FunctionUrl --output text
aws lambda add-permission --function-name $MCP_FUNCTION --statement-id public-url \
  --action lambda:InvokeFunctionUrl --principal '*' --function-url-auth-type NONE
aws lambda add-permission --function-name $MCP_FUNCTION --statement-id public-invoke \
  --action lambda:InvokeFunction --principal '*' --invoked-via-function-url

export MCP_URL=$(aws lambda get-function-url-config --function-name $MCP_FUNCTION --query FunctionUrl --output text)mcp
aws lambda wait function-updated-v2 --function-name $MCP_FUNCTION
aws lambda update-function-configuration --function-name $MCP_FUNCTION \
  --environment "Variables={MCP_RESOURCE_URL=$MCP_URL,MCP_ISSUER=https://auth.shopkart.example,TICKET_STATE_TABLE=shopkart-ticket-state,MCP_JWT_PUBLIC_KEY=\"$(cat .shopkart/mcp-issuer.pub)\"}" \
  --query LastUpdateStatus --output text
```

`--auth-type NONE` means the URL is public, and the **server** checks every token itself. That's the point of this lab.

**Why a table?** Lambda runs many copies of the server, each with its own `/tmp`. In our first try, notes lived in `/tmp`: the Copilot added a note, and the next request, on another copy, didn't see it. Any copy can answer any request only if the state lives outside all of them.

## 4. Use it

```bash
B=${MCP_URL%/mcp}
curl -s -i -X POST $MCP_URL -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | grep -iE "^HTTP|www-authenticate"
curl -s $B/.well-known/oauth-protected-resource/mcp
```

Lambda function URLs rename the `WWW-Authenticate` header to `x-amzn-Remapped-www-authenticate`. MCP clients then fall back to the well-known metadata address, and our app reads either header. If a client you use insists on the original header, run the server behind a load balancer instead (ECS Express Mode, as in the deploy lab).

With a **read-only** token, from the MCP Inspector:

```bash
export MCP_TOKEN=$(uv run python labs/mcp-remote/start/issue_token.py token --sub asha@shopkart.in --scope tickets:read --aud $MCP_URL)
I="npx -y @modelcontextprotocol/inspector@2.15.0 --cli"
$I $MCP_URL --transport http --header "Authorization: Bearer $MCP_TOKEN" --method tools/list
$I $MCP_URL --transport http --header "Authorization: Bearer $MCP_TOKEN" --method tools/call --tool-name get_ticket --tool-arg ticket_id=TCK-20123
$I $MCP_URL --transport http --header "Authorization: Bearer $MCP_TOKEN" --method tools/call --tool-name add_note --tool-arg ticket_id=TCK-20123 --tool-arg text=hi   # 403
```

And from **your app**: Part 1's Copilot, with the same agent loop. Only the connection changed.

```bash
C="uv run python labs/mcp-remote/start/remote_copilot.py"
$C "Which open tickets mention a cracked screen? One line each."
$C "Find the ticket about the cracked Nova 5G phone. Add a short note for the team, and escalate it if the refund is above ₹5,000."
```

The second one reads fine, then stops at `add_note`: **403 insufficient_scope**. A team lead approves write access, so you get a new token with that one extra scope, and run it again:

```bash
export MCP_TOKEN=$(uv run python labs/mcp-remote/start/issue_token.py token --sub asha@shopkart.in --scope "tickets:read tickets:write" --aud $MCP_URL)
$C "Find the ticket about the cracked Nova 5G phone. Add a short note for the team, and escalate it if the refund is above ₹5,000."
```

Read it back as a teammate with a read-only token: the note's author is `asha@shopkart.in`, from her token. And a token made for another server gets 401:

```bash
export MCP_TOKEN=$(uv run python labs/mcp-remote/start/issue_token.py token --sub ravi@shopkart.in --scope tickets:read --aud $MCP_URL)
$I $MCP_URL --transport http --header "Authorization: Bearer $MCP_TOKEN" --method tools/call --tool-name get_ticket --tool-arg ticket_id=TCK-20123
MCP_TOKEN=$(uv run python labs/mcp-remote/start/issue_token.py token --sub asha@shopkart.in --aud https://orders.shopkart.example/mcp) $C "Which tickets are open?"
```

On OpenAI, add `--provider openai` to the Copilot. The server doesn't change at all.

Claude's MCP connector and OpenAI's remote MCP tool can also call this server: their cloud calls your public URL, and your app passes the token in. On camera we connect from our own app and the Inspector instead.

## 5. Tear down

```bash
bash labs/deploy/teardown.sh all        # the function, its URL and logs, the image, the table, the roles
rm .shopkart/mcp-issuer.pem             # the signing key: tokens it made can't be checked anywhere now anyway
```

## Checkpoint

```bash
LAB=start uv run pytest labs/mcp-remote -q      # your copy
uv run pytest labs/mcp-remote -q                # the answer
```

- [ ] No token: 401, and the metadata names the authorization server and only `tickets:read`
- [ ] A read token lists and reads; `add_note` gets 403 `insufficient_scope`
- [ ] With `tickets:write`, the Copilot notes and escalates the ₹18,999 Nova 5G ticket, and the note's author comes from the token
- [ ] A token for another server gets 401
- [ ] `leftovers.sh` says `none` everywhere

The real output of a live run is in [RUN.md](RUN.md).
