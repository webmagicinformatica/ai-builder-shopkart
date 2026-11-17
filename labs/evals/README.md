# Lab: a 50-question eval suite with a score report

Turn "looks fine" into a number the whole team can trust. You run the ShopKart Copilot on 50 cases from the golden test set, score every answer with code checks and an LLM judge, check the judge against your own labels, and write a report with the pass rate by category and every failure listed.

```text
labs/evals/
  eval-50.json        the test set: 50 golden-set IDs, frozen (30 everyday, 12 hard, 8 must-hand-over)
  hand_labels.jsonl   10 answers labelled pass/fail by a person (ours; you label your own)
  start/              your copy, with TODO 1–8
  done/               the finished answer
    cases.py            load the cases, orders and policies
    copilot.py          the system under test: policies in the prompt, a typed Reply
    checks.py           code checks: days, handover, must_not, amounts
    cache.py            a disk cache, so re-runs are free
    run_evals.py        Part 1 runner -> out/results.jsonl  (--estimate first)
    judge.py            Part 2 judge -> out/judged.jsonl
    calibrate.py        judge vs hand labels
    report.py           -> out/report.md and out/report.html
  tests/              the checkpoints, with fake servers
```

Runs on Anthropic by default (`claude-haiku-5-5`). For OpenAI add `--provider openai` (`gpt-6-luna`).
The real output of a live run is in [RUN.md](RUN.md).

**The system under test** is deliberately simple: all 13 current policies go into the system prompt (about 18,000 tokens), and the Copilot answers with `{"reply": ..., "handover": true/false}`. No RAG, so the eval measures the prompt and the model. The policies are sent with prompt caching, so after the first call each answer pays about a tenth for them.

## Part 1: the test set and the runner

1. **TODO 1, load the cases** (`cases.py`). The golden set has 150 cases: 90 everyday, 35 hard, 25 must-hand-over. `eval-50.json` freezes 50 of them in the same mix: every third case of each category. Each case has the question, what a good answer must say (`expected`), what it must never say (`must_not`), and the expected action (answer or hand over). Fail loudly on an unknown ID: a typo must never shrink the set.
2. **TODO 2, the return window** (`checks.py`). When a case expects 14, 10 or 7 days, the answer must say it: "10 days", "ten-day" and the Hinglish "10 din" all count, "7 working days" doesn't.
3. **TODO 3, handover flagged when it should be.** Both directions fail, with different notes. "Should hand over, but answered" is the dangerous one: the gift-return customer who gets a made-up policy.
4. **TODO 4, no made-up amounts.** Every ₹ amount in the answer must exist in the policies, the order record or the question.
   (`must_not`, the forbidden phrases, is already written. A one-word phrase like "yes" only counts at the start of the reply.)
5. **TODO 5, the cache** (`cache.py`). The key is a hash of provider, model, system prompt, messages and schema. Same key: read the answer from disk, cost $0. Change the prompt or the model and the key changes, so those cases run again.
6. **Estimate, then run.** Try 3 cases, look at the cost, then estimate the rest before you spend:
   ```bash
   uv run python labs/evals/start/run_evals.py --limit 3
   uv run python labs/evals/start/run_evals.py --estimate
   uv run python labs/evals/start/run_evals.py
   ```
   Each line is one case: PASS/FAIL and every check (`ok`, `FAIL`, or `-` when it doesn't apply). Then the pass rate by category. Run it again: 50 from cache, $0.
7. **Checkpoint:** `LAB=start uv run pytest labs/evals -q -k "todo1 or todo2 or todo3 or todo4 or todo5"`

## Part 2: the judge and the report

8. **TODO 6, a typed verdict** (`judge.py`). The rubric has three pass/fail checks: `grounded` (every claim is in the policies or the order), `follows_policy` (matches the reference notes and the expected action) and `answers_question`. The reason comes first, so the model explains before it decides. Length earns no points, and the answer is wrapped in tags as data, not instructions. No 1-to-10 score.
   ```bash
   uv run python labs/evals/start/judge.py              # or --limit 20 to stay on budget
   ```
9. **Label 10 answers yourself**, before you look at the judge's verdicts:
   ```bash
   uv run python labs/evals/start/calibrate.py --template --labels my_labels.jsonl
   ```
   Open the file, read each answer with the rubric, and set `label` to `pass` or `fail`.
10. **TODO 7, calibrate.** Agreement alone flatters a judge: a lazy judge that passes everything agrees with every good answer. So also count how many of *your* failures the judge caught, and its false alarms.
    ```bash
    uv run python labs/evals/start/calibrate.py --labels my_labels.jsonl
    ```
11. **TODO 8, the report** (`report.py`): pass rate by category (code checks, judge, overall), by check, and every failure with the reason. Overall pass means every code check passes and the judge passes it.
    ```bash
    uv run python labs/evals/start/report.py             # out/report.md and out/report.html
    ```
12. **Read the failures** before you change anything: note the first thing that went wrong, group, count, then fix at the right layer. Sometimes the test is wrong, not the Copilot.
13. **Checkpoint:** `LAB=start uv run pytest labs/evals -q`

## Good to know

- **Use a judge from another family** when you can (`judge.py --provider openai` if the Copilot runs on Claude): judges score their own family a little higher. We use the same small model here to stay inside the lab budget.
- **10 labels is a start, not a calibration.** With 10 answers, one disagreement moves agreement by 10 points. The lesson used 50, tuned on 25 and checked on the other 25. Add labels whenever you change the judge's prompt or model.
- **Cost**: with the policies cached, 50 answers cost about $0.012 and 50 judge calls about $0.016 on `claude-haiku-5-5`. Without prompt caching the same run is about $0.18. Re-runs from the disk cache are free.
- Results, the cache and the reports are gitignored (`labs/evals/out/`, `.shopkart/eval-cache/`).
