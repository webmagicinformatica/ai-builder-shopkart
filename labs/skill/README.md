# Lab: a skill for the Copilot's reply style and policies

Package ShopKart's reply know-how as an agent skill: a folder with `SKILL.md`, reference files and a script.
Then watch it load only when a task needs it: in Claude Code, in your own app, and on the Claude API. Last, compare replies with and without it on 5 tickets.

```text
labs/skill/
  start/skills/shopkart-replies/   your skill, with TODO 1–4
  start/skill_loader.py            progressive disclosure in your own app, TODO 5–6
  start/compare.py                 with vs without the skill, on 5 tickets
  start/api_skill.py               the same skill on the Claude API
  done/                            the finished answer
  tests/                           the checkpoints (no key, no network)
```

## 1. The skill folder

```text
shopkart-replies/
  SKILL.md                  header (name, description) + the steps
  references/policies.md    return windows, refunds, handover rules (given)
  references/tone.md        do, don't, good and bad example replies
  references/templates.md   one reply template per common case
  scripts/return_window.py  counts the days, so the model doesn't (given)
```

It follows the open Agent Skills format (agentskills.io). The header needs `name` (lowercase and hyphens, the same as the folder, at most 64 characters) and `description` (at most 1024 characters). `license` and `metadata` are optional.

1. **TODO 1, the description.** It's the only line the agent sees up front, so say **what** the skill does and **when** to use it. "Helps with replies" never says when.
2. **TODO 2, the steps.** Brief it like a new colleague: read the message, decide whether to answer or hand over, check the facts (run the script for a return window), write, then check before sending. The rules: four sentences at most, the customer's language, never promise a refund before it's approved, and refunds above ₹5,000 go to a person.
3. **TODO 3 and 4, `tone.md` and `templates.md`.**

Validate it, and read every file before you install it anywhere. A skill runs with your agent's access.

```bash
uvx --from skills-ref agentskills validate labs/skill/start/skills/shopkart-replies
```

## 2. In Claude Code

In Claude Code, a project skill is a folder in `.claude/skills/`, so it reaches your team through git.

```bash
mkdir -p .claude/skills && cp -r labs/skill/start/skills/shopkart-replies .claude/skills/
claude
> Draft a reply to this customer: "I bought running shoes 12 days ago (order SK47731, delivered 5 Nov). Can I still return them?"
> /shopkart-replies TCK-20137
```

Claude loads the skill when the request matches its description, and you'll see it read `SKILL.md`, open `references/policies.md` and run the script. `/shopkart-replies` runs it directly.
Is the ticket server from the MCP lab still added? Then ask *"Draft a reply to ticket TCK-20104"*. MCP gets the ticket, and the skill says how to answer it.

## 3. In your own app: progressive disclosure by hand

`skill_loader.py` does what Claude Code does, with plain tool calling, so it works on Claude and on OpenAI:

- **Level 1:** `catalog()` puts only each skill's name and description in the system prompt (**TODO 5**).
- **Level 2:** the model calls `load_skill`, and gets the body of `SKILL.md` (**TODO 6**).
- **Level 3:** `read_skill_file` opens a reference file, and `run_skill_script` runs the script and returns its output, not its code.

```bash
uv run python labs/skill/start/compare.py                    # 5 tickets, with and without
uv run python labs/skill/start/compare.py --provider openai --tickets TCK-20137
```

Each ticket prints both replies, what loaded, and five simple checks (sentence count, short, language, no promised refund, handover when needed). Results are cached in `.shopkart/cache/`, so a re-run is free; `--fresh` calls the model again.
The skill costs more tokens per reply: the model reads it, then writes. Weigh that against the replies it fixes, and against a four-page system prompt sent with every message.

## 4. On the Claude API

Upload the skill once, then attach it to a request together with the code execution tool. The skill runs in that tool's sandbox, which has no internet. A skill in the Claude apps or in Claude Code isn't on the API until you upload it there too.

```bash
uv run python labs/skill/start/api_skill.py --upload      # prints skill_..., saved in .shopkart/
uv run python labs/skill/start/api_skill.py TCK-20104      # shows each sandbox step, then the reply
uv run python labs/skill/start/api_skill.py --delete
```

In code: `client.skills.create(files=[...])`, then `messages.create(..., container={"skills": [{"type": "custom", "skill_id": ..., "version": "latest"}]}, tools=[{"type": "code_execution_20250825", "name": "code_execution"}])`.
Code execution time is billed separately from tokens (each organisation gets 1,550 free hours a month).

## 5. Checkpoint

```bash
LAB=start uv run pytest labs/skill -q      # your copy
uv run pytest labs/skill -q                # the answer
```

- [ ] `agentskills validate` says the skill is valid
- [ ] With the skill, all 5 replies pass the checks, and you can see which levels loaded
- [ ] Without it, the replies are longer, and at least one gets a fact wrong
- [ ] The API run shows the sandbox reading `SKILL.md` and running the script

The real output of a live run is in [RUN.md](RUN.md).
