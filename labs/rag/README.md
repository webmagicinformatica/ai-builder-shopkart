# Lab: the Copilot's knowledge base, with citations

Build the ShopKart Copilot's knowledge base from its policies (Markdown and PDF), then answer customer questions from it, citing a source for every claim, and saying "I don't know" (and handing over to a human) when the documents don't cover the question.

Everything before the answer runs on your machine for free: parsing, chunking, local embeddings (`fastembed`, no torch) and a SQLite index. Only the answer uses the LLM, through `shopkart/llm.py`, so every call checks the budget and logs its cost.

```text
labs/rag/
  start/          your copy, with TODO 1–8
    parse.py      PDF and Markdown → clean Markdown            (TODO 1, 2)
    chunker.py    chunks by heading, stable ids                (TODO 3)
    index.py      local embeddings, SQLite, vector search      (TODO 4, 5)
    ingest.py     Part 1: runs parse → chunk → embed → save
    ask.py        Part 2: retrieve → answer with sources       (TODO 6, 7, 8)
  done/           the finished answer
  tests/          the checkpoints (fake embedder, fake LLM: no key, no network)
```

Runs on Anthropic by default (`claude-haiku-5-5`). For OpenAI add `--provider openai` (or set `LLM_PROVIDER=openai`).
The first run downloads the embedding model (about 70 MB) into `.shopkart/models/`. The index lives in `.shopkart/rag/index.sqlite`. Both are gitignored.

## Part 1: ingest and index

1. **Look at the sources.** `data/policies/*.md` (13 current policies, with front matter: `doc_id`, `version`, `effective`, `status`), `data/policies/archive/` (old and withdrawn ones), `data/products/`, and three PDFs in `data/policies/pdf/`: one with tables, one in two columns, and one scan.
2. **TODO 1, route each PDF page.** Count the characters on the page. Almost none means a scan: flag it, don't let it disappear silently. A gap down the middle means two columns: read the left one, then the right one.
3. **TODO 2, tables.** Turn each table row into one sentence, with the headers repeated: `Order value: ₹499 and above; Metro cities: Free; Other cities: ₹49.`
   ```bash
   uv run python labs/rag/start/parse.py data/policies/pdf/shipping-and-delivery.pdf
   ```
4. **TODO 3, chunk by heading.** One chunk per section, with the heading path on top (`Returns and Refunds Policy > 2. Returns > 2.1 Return window`). Split a long section only at paragraph breaks. Each chunk gets a stable id like `returns-and-refunds§2.1` and its metadata: source file, page, status, effective date, and a hash of its text.
5. **TODO 4, embed and save.** Embed every chunk locally and write it, with its vector, to SQLite. A chunk whose hash didn't change keeps its old vector.
   ```bash
   uv run python labs/rag/start/ingest.py
   uv run python labs/rag/start/ingest.py --sample 3          # read some chunks: would a person understand them?
   uv run python labs/rag/start/ingest.py --show 'shipping-and-delivery§1'
   ```
6. **Checkpoint:** the two text PDFs are parsed with every number intact (`numbers check 16/16`, `23/23`), the scan is flagged and replaced by its web version, and running the ingest again embeds 0 chunks.

The PDF that parses cleanly replaces its Markdown twin, so you see real parsing. In real life, when a clean web version of a PDF exists, parse that instead. We use the Markdown twins as the expected output to check the parse.

## Part 2: retrieve and answer with sources

7. **TODO 5, vector search with a filter.** Embed the question, score every chunk (a dot product), and filter **inside** the search: archived and withdrawn chunks never take a place in the top 5.
   ```bash
   uv run python labs/rag/start/ask.py --search "You match lower prices, right?" -k 3
   ```
8. **TODO 6, the prompt.** Label every chunk `[doc § section]`, put the question last, and ask for JSON: `answerable`, `answer`, `citations`. If even the best chunk scores below 0.55, don't call the model at all.
9. **TODO 7, check before you send.** Every sentence must cite a source we actually sent, and every number in it must appear in that source. If not, the customer never sees it.
10. **TODO 8, "I don't know".** `answerable = false`, a failed check or a low score all lead to the same polite handover to a human.
    ```bash
    uv run python labs/rag/start/ask.py "How many days do I have to return a product?"
    uv run python labs/rag/start/ask.py --demo
    ```
11. **Checkpoint:** five demo questions, four answers with sources, and one honest handover (the gift question), for well under a cent. Answers are cached in `.shopkart/cache/rag/`, so a second run is free.
    ```bash
    LAB=start uv run pytest labs/rag -q
    ```

The real output of a live run is in [RUN.md](RUN.md). Next lab: [hybrid search and reranking](../rag-hybrid/README.md).
