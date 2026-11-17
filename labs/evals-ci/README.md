# Lab: run evals automatically in GitHub Actions on every change

A regression test re-runs your saved cases on every change, and blocks the change if something that used to work now fails. Here it runs on every pull request: 10 cases from the eval suite, the code checks and the judge, a pass-rate threshold and one hard rule, and a summary on the run's page.

```text
.github/workflows/evals.yml   the live workflow (same as done/evals.yml)
labs/evals-ci/
  ci-10.json          the pull-request slice: 10 of the 50 (5 everyday, 3 hard, 2 must-hand-over)
  start/              evals.yml with TODO A–D, ci_gate.py with TODO 1–3
  done/               the finished answer
  tests/              the checkpoints, with fake servers
```

It uses the eval suite from the previous lab (`labs/evals/done/`). The real output of a live run is in [RUN.md](RUN.md).

## The gate (`ci_gate.py`)

Decide the rules before the run, not after you see the numbers:

1. **Hard rule:** every must-hand-over case hands over. One miss blocks the change, whatever the pass rate.
2. **Pass rate** (code checks and judge) of at least `--threshold`, 70% by default.

With 10 cases, one failure moves the score by 10 points, so this fast set only catches big drops. The full 50 (`labs/evals/done/run_evals.py`) is the one to run every night and before a release.

- **TODO 1, skip cleanly without the key.** No `ANTHROPIC_API_KEY`: write a "skipped" note and exit 0. Pull requests from forks never get secrets, and a fresh copy of the repo has none yet. Neither should turn the check red.
- **TODO 2, decide.** Count the passes, apply both rules, and give one plain-English reason per broken rule. If the API calls themselves failed, the gate says ERROR, not BLOCKED: nothing was measured.
- **TODO 3, the job summary.** GitHub sets `GITHUB_STEP_SUMMARY` to a file path. Markdown appended to it shows on the run's summary page: pass rate, threshold, a table by category, and the failing cases with reasons.

```bash
uv run python labs/evals-ci/start/ci_gate.py                  # locally, with your Codespaces key
uv run python labs/evals-ci/start/ci_gate.py --threshold 0.9  # see it block
LAB=start uv run pytest labs/evals-ci -q
```

## The workflow (`evals.yml`)

To build it yourself, copy `start/evals.yml` over `.github/workflows/evals.yml` and fill in:

- **TODO A, when to run:** on pull requests that touch anything the answers depend on: the client and model names (`shopkart/**`), the prompt, checks and eval set (`labs/evals/**`), the policies and golden set (`data/**`), the dependencies. Plus `workflow_dispatch`, a "Run workflow" button.
- **TODO B, the secret and a spend cap:** `ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}` and `DAILY_BUDGET_USD: "0.05"`, so one job can never spend more than 5 cents.
- **TODO C, skip without the key:** a first step that writes `ok=true|false` to `$GITHUB_OUTPUT`; every later step has `if: steps.key.outputs.ok == 'true'`.
- **TODO D, cache the answers:** `actions/cache` on `.shopkart/eval-cache`. Cases whose prompt, model and policies didn't change come from the cache and cost $0.

## Add the API key as an Actions secret

**Actions secrets are separate from Codespaces secrets.** The key you added for Codespaces is not visible to GitHub Actions; add it again here.

1. Open your copy of the repository on github.com, then **Settings → Secrets and variables → Actions**.
2. **New repository secret.** Name: `ANTHROPIC_API_KEY`. Value: your key. **Add secret.**
3. Open a pull request that changes, say, a line of the Copilot's prompt in `labs/evals/done/copilot.py`. The **evals** check runs; click **Details**, then **Summary**.

Or from your own terminal: `gh secret set ANTHROPIC_API_KEY --app actions --repo <you>/<repo>`.

Use a key with a low spend limit on the provider's side too. A cold run of the slice costs about $0.01 (10 answers plus 10 judge calls), a cached run $0.

## Try it locally with act

[`act`](https://github.com/nektos/act) runs the workflow in Docker on your machine:

```bash
act workflow_dispatch -W .github/workflows/evals.yml                         # no secret: skips
act workflow_dispatch -W .github/workflows/evals.yml -s ANTHROPIC_API_KEY    # reads the key from your environment
```

The image act uses must have CA certificates. A bare `node:*-slim` image doesn't, and every API call then fails with "Connection error" (the gate reports ERROR). act's default medium image, or GitHub's own `ubuntu-latest`, is fine.

## On OpenAI

Set `LLM_PROVIDER: openai` in the workflow's `env`, pass `OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}` instead of the Anthropic key, check `$OPENAI_API_KEY` in the first step, and add that Actions secret. `ci_gate.py` already checks for the key of whichever provider is selected.
