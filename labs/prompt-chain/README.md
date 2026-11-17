# Lab: turn one fragile mega-prompt into a 3-step chain with versioned prompts

The Copilot's first refund prompt does everything in one call: read the message, find the order, check the policy, work out the dates, decide, reply in the customer's language, stay polite, stay short, and return JSON.
In this lab you run it on 10 real tickets and watch it break, then split it into **Extract → Decide → Write**, with code between the steps and every prompt in its own versioned file.

```text
labs/prompt-chain/
  cases.json            the 10 tickets, with what a support lead would decide
  start/                your copy, with TODO 1–7
  done/                 the finished answer
    prompts/            mega.v1.md, extract.v1.md, decide.v1.md, write.v1.md, write.v2.md, chain.json
    promptfiles.py      load a prompt by name and version, fill its placeholders
    chain.py            Extract -> gate -> Decide -> gate -> Write -> gate
    mega.py             the old one-call prompt
    compare.py          both on the same 10 tickets, in one table
    prompt_diff.py      review a prompt change: the text diff, then the answers that changed
    checks.py           the checks both are scored with
    calls.py, facts.py  cached, cost-logged calls; orders and policies from data/
  tests/                checkpoints with fake models, plus prompt snapshots
```

Runs on Anthropic (`claude-haiku-5-5`) by default. For OpenAI add `--provider openai` (or set `LLM_PROVIDER=openai`).
Every call goes through `shopkart.llm` (budget check first, cost log after), and every answer is cached in `.shopkart/cache/`, so running a command again costs nothing. Add `--fresh` to call the API again.
The whole lab costs about **$0.035** on Anthropic (≈ ₹3).

"Today" is 17 November 2026 for every fixture. The rules come from `data/policies/`: return window 14 days, footwear 10, electronics 7 (damaged or faulty only once opened), and **any refund above ₹5,000 goes to a human**.

## 1. Run the mega-prompt and watch it break

```bash
uv run python labs/prompt-chain/done/mega.py
```

`prompts/mega.v1.md` has fourteen instructions and all 13 policies. On our run: **0 of 10 clean**.

- **Broken format, 10 of 10.** We asked for JSON "with no other text". Every answer came wrapped in a markdown code fence, so `json.loads()` fails.
- **A missed handover.** The ₹9,499 tablet (TCK-20116) got "allowed". Rule 7 was right there in the prompt.
- **A wrong window for footwear.** The clearance shoes delivered 4 days ago (TCK-20138): "it's also past the 10-day footwear return window". Right number, wrong date arithmetic.
- **A wrong decision.** Formal shoes delivered 9 days ago (TCK-20115) were refused, inside the 10-day window.

And when it fails, you can't tell which part went wrong: the reading, the deciding or the writing.

## 2. Prompts as versioned files

One file per prompt and version. The header pins the model and settings to the words; the fixed instructions come first; placeholders and customer text come last, in their own tags, as data.

```text
---
name: extract
version: v1
model_anthropic: claude-haiku-5-5
model_openai: gpt-6-luna
max_tokens: 300
changelog: first version
---
You read one customer message ... (the system prompt)
<!-- user -->
<customer_message>
{{message}}
</customer_message>
```

`prompts/chain.json` says which versions run together: `{"extract": "v1", "decide": "v1", "write": "v1"}`.

- **TODO 1** `load_prompt(name, version)`: read `prompts/<name>.<version>.md`, check the header matches the file name, and list what exists when it doesn't.
- **TODO 2** `Prompt.render(**values)`: fill every `{{placeholder}}`; a missing **or** unused value is an error.

## 3. Extract: a typed step

`extract.v1.md` gets only the message. Its schema, `Extraction`, holds the order id, item category, issue, amount, sentiment and language (Write needs it).

- **TODO 3** finish `Extraction` in `chain.py`.
- **TODO 5** the first gate, in plain code: a valid order id (`SK` + 5 digits), looked up in `data/orders.json`. No id in the message? Use the order the chat was opened from; still none, **stop and ask**. Dates, prices and category come from the database, never from the model. The gate works out "delivered 12 days ago", so no model has to.

## 4. Decide: a typed step

`decide.v1.md` gets the order facts and **only the policies it needs** (returns, refunds, handover, plus damaged-items, footwear or electronics when they apply). It returns `allowed`, `denied` or `handover`, the rule, and the policy section it used.

- **TODO 4** the `Decision` schema.
- The citation gate (done for you) checks that the section really exists in a document we sent. If it doesn't, the step is sent back once with the error; then it hands over.
- **TODO 6** a business rule, in code: "allowed" above ₹5,000 becomes "handover". On our run the model said "allowed" for both the ₹9,499 tablet and the ₹5,499 camera, and the gate caught both.

## 5. Write: the customer's reply

`write.v1.md` gets the decision, the customer's name and language, and nothing else. It can't change the decision.

- **TODO 7** the last gate: no "processed" or "approved" (in English or Hinglish), under 80 words, a handover must name the team, no markdown, and the customer's language. On our run it caught "Aapka request approve ho gaya hai", and the retry fixed it.

Run one ticket to see every step, then all ten:

```bash
uv run python labs/prompt-chain/done/chain.py --ticket TCK-20141
uv run python labs/prompt-chain/done/chain.py
```

Every step's input, output and prompt version goes to `.shopkart/prompt-chain/trace.jsonl`.

## 6. Compare, on the same 10 tickets

```bash
uv run python labs/prompt-chain/done/compare.py
```

| | mega.v1 | chain (v1) |
| --- | --- | --- |
| right decision | 8/10 | 10/10 |
| valid format | 0/10 | 10/10 |
| no problems | 0/10 | 10/10 |
| calls | 10 | 33 |
| cost, 10 tickets | $0.0200 | $0.0127 |
| latency | 2.0 s per ticket | 5.4 s per ticket |

Three times the calls, and still cheaper, because each step sends only what its job needs. The price is latency: three round trips instead of one.

## 7. Bump one prompt to v2, and review it like code

The v1 replies passed the checks, but the trace shows what we'd fix: a gate retry for "approve ho gaya", a customer told about the internal ₹5,000 rule, "Warm regards, ShopKart Support" sign-offs. So: copy `write.v1.md` to `write.v2.md`, change the version, write why in `changelog`, and fix it there.

```bash
uv run python labs/prompt-chain/done/prompt_diff.py write v1 v2
```

You get the text diff, then every answer that changed, side by side. Our run: 10 of 10 replies changed, still 10/10 clean, gate retries 1 → 0, words per reply 71 → 54. Only the Write step was called again: Extract and Decide came from the cache.

Happy with it? Point `prompts/chain.json` at `"write": "v2"`. That one line is the release, and rolling back is the same line.

**What we saw on the way:** our first draft of v2 had English examples only, and both Hinglish customers got English replies. The language check caught it before anyone else saw it. The fix was one Hinglish example and one sentence ("whatever language the examples use").

## Checkpoint

```bash
uv run pytest labs/prompt-chain -q                 # the finished answer
LAB=start uv run pytest labs/prompt-chain -q       # your copy
```

The tests use fake models: no key, no network, no cost. One of them fills every prompt with sample values and compares it with a saved snapshot, so any change to what the model actually reads shows up as a diff. Changed a prompt on purpose? `UPDATE_SNAPSHOTS=1 uv run pytest labs/prompt-chain -q`, then review the snapshot diff in your pull request.

- [ ] The mega-prompt's failures, on screen
- [ ] Extract, Decide and Write, each with its own prompt file and version
- [ ] Gates in code: order lookup, ₹5,000 handover, reply check
- [ ] The comparison table
- [ ] `write.v2.md`, with its diff reviewed

The real output of a live run is in [RUN.md](RUN.md).
