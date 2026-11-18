# ShopKart Support Copilot

**AI Builder · dabeer.ai**

Starter project for the AI Builder course's first hands-on lab: set up the project and make a cost-tracked API call.
ShopKart is a (fictional) Indian online store. Over the course you'll build its support assistant.

Each lab video follows one provider. Use the file for yours:

| Provider | Script | Codespaces secret | Model |
| --- | --- | --- | --- |
| Anthropic (Claude) | `hello_anthropic.py` | `ANTHROPIC_API_KEY` | `claude-haiku-5-5` |
| OpenAI | `hello_openai.py` | `OPENAI_API_KEY` | `gpt-6-luna` |

## 1. Get your own copy

1. Click **Use this template** → **Create a new repository**. Name it (e.g. `shopkart`), keep it **Private**, create it.
2. In your new repo: **Code** → **Codespaces** → **Create codespace on main**. Setup runs `uv sync` for you.

New to Codespaces? Watch the "Set up GitHub Codespaces" lab first.

## 2. Add your API key as a Codespaces secret

[github.com/settings/codespaces](https://github.com/settings/codespaces) → **Secrets** → **New secret**:

- Name: `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`)
- Value: your key
- Repository access: your new repo

Then reload the codespace when VS Code offers it. The key never goes in your code or in Git.
(Not using Codespaces? Copy `.env.example` to `.env` and fill it in. `.env` is gitignored.)

## 3. Make a cost-tracked call

```bash
uv run hello_anthropic.py      # or: uv run hello_openai.py
```

```text
Model:   claude-haiku-5-5
Reply:   Namaste, and welcome to ShopKart! How can I help you today?
Tokens:  22 in, 17 out
Cost:    $0.000011  (₹0.0009)

Today:   $0.000011 of $0.50 daily budget
```

Your reply and token counts will differ. Costs use the course's example prices in `shopkart/pricing.py`; check the current pricing page for real ones.

## 4. Watch the budget block a call

Every call checks today's spend first (`shopkart/budget.py`, default $0.50 a day, set with `DAILY_BUDGET_USD`).
After one call, set a tiny budget and try again:

```bash
DAILY_BUDGET_USD=0.000001 uv run hello_anthropic.py
```

```text
Budget reached: spent $0.000011 of $0.000001 today. Call blocked.
```

No call is made, and the script exits with an error. Today's spend is kept in `.shopkart/` (gitignored), and it resets every day.

## 5. Run the tests

```bash
uv run pytest
```

They use fake numbers: no key, no network, no cost.

## Checkpoint

- [ ] A call that prints its tokens and its cost in $ and ₹
- [ ] A budget that blocks a call
- [ ] `git status` shows no `.env` and no `.shopkart/`
- [ ] Your work committed and pushed: `git add -A && git commit -m "First cost-tracked call" && git push`

## Get new labs

New labs are added to this course repo over time (`labs/<lab>/`, plus shared data in `data/`).
Your copy doesn't update by itself. Link it to the course repo once, then pull.

**One time only** (in your codespace terminal):

```bash
git remote add upstream https://github.com/webmagicinformatica/ai-builder-shopkart.git
git config pull.rebase false
git pull upstream main --allow-unrelated-histories -X theirs --no-edit
uv sync
git push
```

Why the extra flags? "Use this template" gives your repo a fresh history, so Git sees the course repo as unrelated and refuses to merge without `--allow-unrelated-histories`. On this first pull, `-X theirs` takes the course's version of any file both sides have changed (for example `README.md`); files you created yourself are kept.

**Every time after that:**

```bash
git pull upstream main --no-edit
uv sync
```

Commit your own work first (`git add -A && git commit -m "..."`). Work inside `labs/<lab>/start/` and you won't get conflicts. Each lab's `done/` folder has the finished version if you get stuck.

---

MIT licensed · [dabeer.ai on YouTube](https://www.youtube.com/@dabeer.ai)
