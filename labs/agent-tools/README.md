# Lab: give the Copilot tools, with approval before acting

The ShopKart Copilot becomes an agent. It gets three tools, a loop you write by hand, limits it can't argue with, and a person who approves every refund.

```text
labs/agent-tools/
  start/tools.py    your copy of the tools and the refund rules (TODO 1, 2, 7, 8)
  start/agent.py    your copy of the loop and the approval desk (TODO 3–6, 8)
  done/             the finished answer
  scenarios.json    4 customer messages: cracked watch, damaged tablet, already refunded, late shoes
  tests/            the checkpoints, with fake servers
```

Runs on Anthropic by default. For OpenAI add `--provider openai` (or set `LLM_PROVIDER=openai`).

| Tool | What it does | Runs |
| --- | --- | --- |
| `lookup_order(order_id)` | One order of the signed-in customer, from `data/orders.json`: 10 small fields | automatically (read only) |
| `check_policy(topic)` | The current policy sections for one topic, with source and version | automatically (read only) |
| `draft_refund(order_id, amount_inr, reason)` | Prepares a refund. No money moves | a person approves it |

## Part 1: tools and the loop

1. **TODO 1, descriptions.** The first drafts say "Gets order." Brief a new teammate who can't ask a question: what the tool does, when to use it (and when not), what it returns, its limits. Three or four sentences each. The names are verb + object, `amount_inr` says its unit, and `reason` is an enum.
2. **TODO 2, small results and helpful errors.** `lookup_order` returns the whole order row; cut it down to what the model needs (status, items, ₹ paid, delivery date, days since delivery, return window, refunds so far, tracking). Errors say what happened and what to do next: `Order ID must look like SK48213 (SK and 5 digits). You sent '48213'. Ask the customer to confirm the order ID, then try again.` Someone else's order gets the same answer as a missing one. The customer ID comes from the login (`Session`), never from the model.
3. **TODO 3, Claude's turn.** `messages.create` with `tools` (schema in `input_schema`). Append the reply exactly as it came, collect the `tool_use` blocks, read `stop_reason`. Send every result back in ONE user message of `tool_result` blocks with the matching `tool_use_id`, and `is_error` for failures.
4. **TODO 4, OpenAI's turn.** `responses.create` with `tools` (schema in `parameters`). Add `resp.output` to the input, parse each `function_call`'s `arguments` (a JSON string), and send back `function_call_output` items with the same `call_id`. No error flag: the error goes in the output text.
5. **TODO 5, the loop.** Call the model, run the tools it asks for, send the results back, until it stops asking. Every call goes through `paid_turn()`: the budget check first, then the cost recorded and logged to `.shopkart/calls.csv`.
   ```bash
   uv run python labs/agent-tools/start/agent.py --scenario cracked-watch --no-desk --fresh
   ```
6. **Checkpoint:** three model calls, several tools in one turn, one answer, and a draft waiting for a person.

## Part 2: approvals, stopping conditions and a trace

7. **TODO 6, the exits.** The model decides when the work is done; your code decides when the loop must stop. Before every call: 10 turns, $0.10 per conversation, 60 seconds, and the daily budget. After it: a cut-off reply (`max_tokens`) is not done, and the same tool with the same inputs a third time is a loop. Every exit hands the customer to a person and writes to the audit trail.
   ```bash
   uv run python labs/agent-tools/start/agent.py --scenario cracked-watch --fresh --max-steps 1
   ```
8. **TODO 7, the limits live in code.** In `assess_refund`: never more than was paid minus what's already refunded (the Friday test: ₹18,999 already refunded), above ₹5,000 always a person, outside the return window a person. Also there already: a third refund in 30 days, ₹50,000 a day of automatic refunds, and a kill switch, `SHOPKART_ACTIONS_OFF=1`. In this lab every refund waits for a person (`SHOPKART_AUTO_REFUND_UP_TO=0`). Even if someone sets it to 20000, ₹5,000 stays the ceiling.
9. **TODO 8, the approval desk.** The run ends with "sent for approval"; nobody waits in the chat. The desk shows the exact action, the evidence from our own order system and why it needs a person, then approve, edit or reject. Approving runs exactly the saved action, once, without asking the model again. A second click pays nothing.
   ```bash
   uv run python labs/agent-tools/start/agent.py --scenario damaged-tablet
   ```
10. **The trace and the audit trail.** Every step prints its tokens and cost, every tool call and its result. Every proposal, block, approval and hand-over is one line in `.shopkart/agent-tools/audit.jsonl`, append only.
    ```bash
    tail -n 4 .shopkart/agent-tools/audit.jsonl
    ```
11. **Checkpoint:**
    ```bash
    LAB=start uv run pytest labs/agent-tools -q
    ```

The real output of a live run is in [RUN.md](RUN.md).

## Options

```text
agent.py [message] [--customer C1001] [--scenario NAME] [--provider openai] [--model ...]
         [--max-steps 10] [--max-usd 0.10] [--no-desk] [--fresh]
```

`--fresh` clears this lab's drafts and refunds (`.shopkart/agent-tools/refunds.json`), so a scenario can be run again from the start. The audit trail is never cleared.
