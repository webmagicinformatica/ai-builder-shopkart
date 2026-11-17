# Lab: the same agent with an agent SDK

Rebuild the Copilot from the agent-tools lab with an agent SDK, then put the two side by side: lines of code, behaviour and cost.
The tools, their descriptions and the refund rules stay exactly the same (`labs/agent-tools/done/tools.py`). Only the loop changes hands.

| Video | SDK | File |
| --- | --- | --- |
| Anthropic | Claude Agent SDK (`claude-agent-sdk` 0.2.183) | `claude_sdk_agent.py` |
| OpenAI | OpenAI Agents SDK (`openai-agents` 0.24.0) | `openai_sdk_agent.py` |

```text
labs/agent-sdk/
  start/claude_sdk_agent.py   your copy (TODO 1–4)
  start/openai_sdk_agent.py   your copy (TODO 5–7)
  start/compare.py            the side-by-side runner (ready to use)
  done/                       the finished answer
  tests/                      offline checkpoints
```

## Install the SDKs (once)

They're an optional group, so the Codespace stays light for every other lab:

```bash
uv sync --group agents
```

- **Claude Agent SDK** runs the Claude Code CLI as a subprocess, and the wheel **bundles that CLI** as a native Linux binary (Claude Code 2.1.326). No Node.js and no separate `npm install`. It's big: about 165 MB to download and 355 MB on disk. Checked in this repo's devcontainer image (`mcr.microsoft.com/devcontainers/python:3.12-bookworm`, x86-64): `uv sync --group agents` took 48 s, `claude --version` ran, and all tests passed.
- **OpenAI Agents SDK** is plain Python (about 1 MB). It sends traces of every run to your OpenAI dashboard by default; turn that off with `OPENAI_AGENTS_DISABLE_TRACING=1`.
- The Claude Agent SDK uses your `ANTHROPIC_API_KEY` from the Codespaces secret, like everything else.

## Anthropic video: the Claude Agent SDK

1. **TODO 1, the tools.** Wrap our three functions with `@tool(name, description, input_schema)`, using the same descriptions and schemas as `tools.TOOLS`. Return `{"content": [...]}`, and add `"is_error": True` on a `ToolError`, so the model reads our wording. `create_sdk_mcp_server()` runs them in-process; the model sees them as `mcp__shopkart__lookup_order` and so on.
2. **TODO 2, the options.** Our system prompt (it replaces Claude Code's), `tools=[]` (no Bash, no file edits), the two read tools in `allowed_tools` (they run without asking), `max_turns=10`, `max_budget_usd=0.10`, and `setting_sources=[]` so no CLAUDE.md on the machine leaks in.
3. **TODO 3, approval.** `draft_refund` isn't in `allowed_tools`, so the SDK asks `can_use_tool` first. Run `assess_refund`: a refund the code blocks needs no person (the tool returns the error), a valid one shows the approval screen and waits. `PermissionResultAllow()` or `PermissionResultDeny(message=...)`.
4. **TODO 4, a `PreToolUse` hook.** Print the trace and do the repeat check: the third identical call gets `permissionDecision: "deny"`.
   ```bash
   uv run python labs/agent-sdk/start/claude_sdk_agent.py --scenario cracked-watch --fresh
   ```
5. **Compare.**
   ```bash
   uv run python labs/agent-sdk/done/compare.py
   ```

## OpenAI video: the OpenAI Agents SDK

5. **TODO 5, error wording.** `@function_tool` builds the schema from the type hints. Its default error text is "An error occurred while running the tool. Please try again." That hides our message and says to retry. Pass `failure_error_function` that returns our error.
6. **TODO 6, approval.** `needs_approval=needs_a_person` on `draft_refund`. When it's true, `Runner.run()` stops with `result.interruptions`. Show the approval screen, `state.approve(item)` or `state.reject(item, rejection_message=...)`, and run the `RunState` again.
7. **TODO 7, the spend cap.** The SDK has a turn limit (`max_turns`, default 10) but no money limit. A `RunHooks.on_llm_end` adds up each call's cost, and `on_llm_start` stops the run at $0.10.
   ```bash
   uv run python labs/agent-sdk/start/openai_sdk_agent.py --scenario cracked-watch --fresh
   uv run python labs/agent-sdk/done/compare.py --provider openai --scenario cracked-watch
   ```

## Side by side (from the live run in [RUN.md](RUN.md))

| | Hand-built loop | Claude Agent SDK | OpenAI Agents SDK |
| --- | --- | --- | --- |
| Lines of code (no blanks, comments, docstrings) | 228 (both providers, approval desk, CLI) | 154 | 150 |
| Who runs the loop | our `while True` | the Claude Code CLI, as a subprocess | `Runner.run()`, in-process |
| Turn limit | ours, 10 | `max_turns` (we set 10) | `max_turns` (default 10) |
| Money limit | ours, $0.10 per conversation | `max_budget_usd` (an estimate) | none: we add it with `RunHooks` |
| Approval | after the run, at the desk (a queue) | `can_use_tool`, during the run | `needs_approval`, the run pauses and resumes |
| Tool errors the model reads | ours | ours (`is_error`) | "Please try again", until we set `failure_error_function` |
| 4 scenarios on Haiku (Anthropic) | 10 calls, $0.0029 | 18 turns, $0.0025 | (OpenAI smoke run: 3 calls, $0.0005) |

What the run showed:

- **Same outcome.** Both builds approved the ₹1,299 and ₹9,499 refunds and refused the already-refunded phone and the late shoes, because the rules live in our code, not in the loop.
- **More turns, more tokens, less money.** The SDK build took 3–5 turns where the hand-built loop took 2–3, and sent more tokens. It still cost a little less, because the Claude Code CLI uses prompt caching automatically. Our hand-built loop doesn't (yet). Its own cost estimate matched our prices exactly.
- **What the customer hears changes.** The hand-built run ends before anyone approves, so the customer hears "a support lead will review it". The SDK runs wait for the person, so the customer hears "approved and started". A waiting run is fine in a terminal. In a real chat, nobody waits for a manager: save the run (OpenAI's `RunState` serializes to JSON) or use a queue like the desk.
- **What the SDK hides.** Its defaults, the error wording (OpenAI's default hides our message), and the cost of every turn. So we set the limits ourselves, add the budget check, and read the traces.

## Checkpoint

```bash
LAB=start uv run pytest labs/agent-sdk -q
```

The OpenAI SDK test runs the whole loop against a fake server. The Claude Agent SDK needs its CLI and the real API to run the loop, so its tests check our parts: the tools, the approval callback and the hook.
