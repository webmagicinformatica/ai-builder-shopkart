# Lab: add hybrid search and reranking, and measure the improvement

The Copilot from the [knowledge base lab](../rag/README.md) searches by meaning only. Here you add keyword search (BM25), merge the two lists with reciprocal rank fusion, rerank the top 20 with a local cross-encoder, and then **measure** whether it helped, on the 50 policy questions of the golden set.

Retrieval runs locally and costs nothing, so we measure it on all 50 questions. Only the answer step uses the LLM: we run it on 10 questions, before and after, and cache every answer.

```text
labs/rag-hybrid/
  start/
    hybrid.py    keyword search, fusion, rerank          (TODO 1, 2, 3)
    measure.py   hit@k and MRR, answers before/after     (TODO 4)
  done/          the finished answer
  tests/         the checkpoints (fake embedder, fake reranker, fake LLM)
```

You need the index from the previous lab: `uv run python labs/rag/done/ingest.py`.
The reranker (`Xenova/ms-marco-MiniLM-L-6-v2`, about 80 MB) downloads on first use into `.shopkart/models/`.
Runs on Anthropic by default; add `--provider openai` for OpenAI.

## Part 1: hybrid search

1. **TODO 1, keyword search.** SQLite has a full-text index built in, FTS5, and its ranking function is BM25. `build_keyword_index()` fills it from the same `chunks` table. Write the query: the question's words minus stopwords, OR-ed, filtered to current documents **inside** the search (a JOIN on `status`).
2. **TODO 2, reciprocal rank fusion.** Ignore the scores, use the ranks: each list gives a chunk `1 / (60 + rank)`. First for keywords and fourth for vectors is about 0.032; first for vectors only is 0.016.
   ```bash
   uv run python labs/rag-hybrid/start/hybrid.py "Can I return my Stride RN220 running shoes?"
   ```
   Vector search puts the RN**210** first. Keyword search finds the exact model number.

## Part 2: rerank

3. **TODO 3, rerank.** Twenty candidates in, five out (on a 2-core Codespace, fifty took three times as long for the same hit@5). A cross-encoder reads the question and each chunk together and gives one score (0 to 1). The score can also tell you when nothing matches. But don't copy a threshold: `measure.py` shows that a floor of 0.5 would hand over answerable questions on our data, so we tune it on the 50 questions (0.01) and let the model's `answerable` field do the rest.

## Part 3: measure

4. **TODO 4, the metrics.** For every question, find the rank of the right section (`source_doc` + `section` in `data/golden/rag-50.jsonl`). hit@k: how often it is in the top k. MRR: the average of 1/rank. Found: is it in the list at all (the top 50, or the 20 the reranker reads)? That's the search's job; the order in the top 5 is the reranker's job.
   ```bash
   uv run python labs/rag-hybrid/start/measure.py                  # all 50, free
   uv run python labs/rag-hybrid/start/measure.py --answers 10     # + answers before/after, cached
   ```
5. **Checkpoint:** a before/after table, and an honest reading of it. On 50 short, plain-English policy questions, vector search is already strong; keyword search alone is weaker, hybrid helps on exact codes, and the reranker improves the order. Measure on your own questions before you assume.
   ```bash
   LAB=start uv run pytest labs/rag-hybrid -q
   ```

The real output of a live run is in [RUN.md](RUN.md).
