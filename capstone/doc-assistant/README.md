# Capstone: a document assistant on real data

**AI Builder · dabeer.ai**

Build an assistant that answers questions from ShopKart's policy documents, shows the source of every claim, says "I don't know" when the documents don't cover the question, and comes with an eval report that proves all of it with numbers.

This is the project you show in an interview. Anyone can demo a chatbot that answers five questions well. You will show *how often* it is right, how it fails, and what you did about it.

You have built every piece in the labs already. The capstone is about putting them together, choosing the settings with data, and measuring the result honestly.

## The goal

A ShopKart customer asks a question in plain English. Your assistant either:

1. **answers** from the current policies, every sentence linked to the section it came from, or
2. **hands over** to a human with a polite "I don't know", without guessing.

And you can prove how well it does both, on 60 test questions, in one command.

## What you build on

| You need | Where you built it |
|---|---|
| Parsing PDFs, tables and scans; chunking by heading; local embeddings; the SQLite index | Lab: the Copilot's knowledge base, Part 1 (`labs/rag`) |
| Citations, the JSON answer with `answerable`, the grounding check, the handover | Lab: the Copilot's knowledge base, Part 2 (`labs/rag`) |
| Keyword search (BM25), rank fusion, the reranker, hit@k and MRR | Lab: hybrid search and reranking, measured (`labs/rag-hybrid`) |
| A frozen test set, code checks, an LLM judge, a report | Lab: a 50-question eval suite (`labs/evals`) |

Lessons to revisit: *Answers you can trust* (citations, "I don't know", grounding checks), *Better retrieval* (both parts), *Measuring RAG* (hit rate vs faithfulness), *LLM as judge*, and *Error analysis*.

## The data

- `data/policies/` (13 current policies, plus `archive/` with old and withdrawn ones, plus three PDFs in `pdf/`) and `data/products/`.
- `data/golden/rag-50.jsonl`: 50 policy questions. Every one is answerable, and each is labelled with the document and section the answer lives in, plus the expected answer.
- You write your own **"I don't know" set**: at least 10 questions the documents do not cover. Check each one: search the policies by hand, so you're sure the answer really isn't there.

## Requirements

1. **Retrieval.** Search only current documents (the filter runs inside the search, not after it). Use hybrid search and a reranker, or show with numbers that you don't need them.
2. **Citations.** Every claim in an answer ends with the label of the chunk it came from, like `[returns-and-refunds § 2.1]`. The customer can see the document and section.
3. **Grounding check, in code.** Before an answer is shown: every claim cites a source you actually sent, and every number in it appears in that source. A failed check means a handover, never an unchecked answer.
4. **"I don't know".** At least two layers: a score floor before the model (no call when nothing relevant was found) and an `answerable` field in the model's JSON. Every "I don't know" is the same polite handover to a human.
5. **The eval report.** One command runs all 60 questions and writes a report: retrieval hit@1, hit@5 and MRR; answered, right source cited, expected facts present; faithfulness (a small LLM judge checks each claim against the chunks it cites); the "I don't know" score; and **every failure listed with its reason**.
6. **Cost control.** Every call goes through the budget check and is logged. Print an estimate before the first paid run. Cache answers and verdicts on disk, so a re-run costs $0. Use a small model.
7. **Tests** that run without a key or the network (fake LLM, fake embedder), plus a README.

## Acceptance criteria

Your project is done when all of these hold on the full 60 questions:

| | Criterion |
|---|---|
| 1 | The right section is in the top 5 for at least **45 of 50** questions |
| 2 | At least **40 of 50** answered with the right source cited and the expected facts |
| 3 | At least **90%** of claims supported by their cited source (judge) |
| 4 | At least **9 of 10** "I don't know" questions handed over |
| 5 | No answer reaches the customer without passing the grounding check |
| 6 | One full eval run costs at most **$0.05**; a re-run costs $0 |
| 7 | The offline tests pass |

## Rubric (100 points)

| Area | Points | Full marks | Half marks |
|---|---|---|---|
| Retrieval | 20 | Filter inside the search, hybrid + rerank (or numbers showing you don't need them), hit@5 ≥ 45/50 | Works, but settings copied, not measured |
| Citations and grounding | 20 | Every claim cited; the check runs in code; nothing unchecked is shown | Citations asked for in the prompt only |
| "I don't know" | 20 | Score floor tuned on data + `answerable` field + handover; ≥ 9/10 | One layer only, or the floor copied from a tutorial |
| Eval report | 25 | All the numbers above, every failure with a reason, and your reading of them: what you fixed, what you didn't and why | A pass rate with no failures listed |
| Engineering | 15 | Offline tests, budget and caching, estimate before spending, a clear README | Works on your machine only |

A project at 80 or more is portfolio-ready.

## Suggested plan (about 8 hours)

1. **Hour 1, read.** Your data, and the labs' code. Write the "I don't know" set.
2. **Hours 2–3, wire it up.** One `DocAssistant` that retrieves, answers and checks. Run five questions by hand.
3. **Hour 4, measure retrieval** (free): hit@5 on all 50. Choose the score floor from the scores of the answerable and the unanswerable questions.
4. **Hours 5–6, the eval runner and report.** `--estimate` first, then 5 questions, then all 60.
5. **Hour 7, error analysis.** Read every failure. Group them. Fix at the right layer (retrieval, prompt, check, or the test itself). Re-run.
6. **Hour 8, tests and README.** Including "what broke and how I fixed it".

## Common traps

- **A threshold copied from a tutorial.** A reranker floor of 0.5 sounds safe; on this data it hands over answerable questions. Print the scores and choose.
- **"Answer only from the context" in the prompt, and nothing in code.** A prompt is a request, not a guarantee.
- **A check so strict it rejects good answers.** Watch the handover rate on *answerable* questions, not just the "I don't know" score.
- **Grading only the happy path.** Without unanswerable questions, a bot that never says "I don't know" scores perfectly.
- **Changing the prompt for one failure.** Every prompt change re-runs (and re-pays) the whole set. Batch fixes, and fix in code when the problem is in code.
- **Reporting one number.** 47/50 tells nobody what broke. List every failure and its reason.

## Stretch goals

- Run the same eval on OpenAI (`--provider openai`) and compare.
- Use a judge from another model family, and check it against 10 answers you label yourself.
- Put today's date in the prompt, so expired offers are answered correctly (see the model solution's open failure).
- Add Hindi and Hinglish questions to the test sets.
- Run the eval in GitHub Actions on every pull request (the evals-in-CI lab).

## What to submit

1. A link to your repo (public, or shared with your reviewer), with the code in its own folder.
2. Your `README.md`: how to run it, your design decisions, and **what broke and how you fixed it**.
3. The eval report (`report.md`) from a full run, and your "I don't know" set.
4. The live run's output, with the total cost.
5. Optional: a 3-minute screen recording of five questions, including one "I don't know".

---

## The model solution

`solution/` is one way to meet the brief, in about 650 lines (most of it the report), reusing the labs' finished code. Try the project yourself first.

```text
capstone/doc-assistant/
  solution/
    assistant.py    retrieve (hybrid + rerank) → floor → answer → grounding check, per passage
    judge.py        faithfulness: a small judge checks each claim against the chunks it cites
    evaluate.py     the 60 questions → the numbers, every failure, the criteria → out/report.md
    idk-10.jsonl    10 questions the policies don't cover
  tests/            offline tests (fake embedder, fake reranker, fake LLM)
  RUN.md            the real output of a live run on claude-haiku-5-5
  sample-report.md  the report that run wrote (yours goes to out/report.md)
```

```bash
uv run python labs/rag/done/ingest.py                                   # the index, once (free)
uv run python capstone/doc-assistant/solution/assistant.py --demo
uv run python capstone/doc-assistant/solution/evaluate.py --estimate    # free
uv run python capstone/doc-assistant/solution/evaluate.py               # about $0.02, then $0 from cache
uv run pytest capstone -q
```

Runs on Anthropic by default (`claude-haiku-5-5`); add `--provider openai` for OpenAI. The real numbers, what broke and how it was fixed are in [RUN.md](RUN.md).
