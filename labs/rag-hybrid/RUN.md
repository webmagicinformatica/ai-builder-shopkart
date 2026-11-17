# Live run: hybrid search and reranking, measured

Recorded 2026-11-17 in this repo with real keys, after building the index in the [RAG lab](../rag/RUN.md), on a 2-core CPU, with `claude-haiku-5-5`, plus one small OpenAI smoke run on `gpt-6-luna`.
Retrieval is deterministic, so your retrieval tables will match (the ms column won't); the answers are the model's and can vary by a question. The reranker model (about 80 MB) downloads once on the first run; not shown.

## Anthropic (main video)

```text
$ uv run python labs/rag-hybrid/done/hybrid.py "Can I return my Stride RN220 running shoes?"

vector  (50 ms)
  1.   0.760  product-stride-rn210§intro         Stride RN210 Running Shoes
  2.   0.752  product-stride-rn220§intro         Stride RN220 Running Shoes (Men and Wo
  3.   0.721  footwear§3                         Sale and clearance footwear
  4.   0.700  footwear§1                         Return window
  5.   0.690  electronics§7                      Model numbers

keyword  (1 ms)
  1.  13.695  product-stride-rn220§intro         Stride RN220 Running Shoes (Men and Wo
  2.  12.583  product-stride-rn210§intro         Stride RN210 Running Shoes
  3.  10.508  footwear§3                         Sale and clearance footwear
  4.   9.482  electronics§7                      Model numbers
  5.   7.702  guide-running-shoes§intro          Choosing Running Shoes

hybrid  (51 ms)
  1.   0.033  product-stride-rn210§intro         Stride RN210 Running Shoes
  2.   0.033  product-stride-rn220§intro         Stride RN220 Running Shoes (Men and Wo
  3.   0.032  footwear§3                         Sale and clearance footwear
  4.   0.031  electronics§7                      Model numbers
  5.   0.030  footwear§1                         Return window

rerank  (873 ms)
  1.   0.999  product-stride-rn220§intro         Stride RN220 Running Shoes (Men and Wo
  2.   0.998  footwear§3                         Sale and clearance footwear
  3.   0.994  product-stride-rn210§intro         Stride RN210 Running Shoes
  4.   0.856  electronics§7                      Model numbers
  5.   0.002  guide-running-shoes§intro          Choosing Running Shoes

$ uv run python labs/rag-hybrid/done/measure.py --answers 10
Retrieval on 50 questions (no LLM, $0). Right section = source_doc + section in rag-50.jsonl

search                  hit@1  hit@3  hit@5    MRR   found   ms/q
vector only             35/50  49/50  49/50  0.830   50/50     49
keyword only (BM25)     25/50  40/50  45/50  0.659   50/50      2
hybrid (RRF)            35/50  46/50  50/50  0.826   50/50     36
hybrid + rerank         37/50  48/50  49/50  0.848   50/50    739

Reranker best score on the 50 answerable questions: lowest 0.020, median 0.997
  floor 0.5  would hand over 5 of them without calling the model
  floor 0.1  would hand over 3 of them without calling the model
  floor 0.01 would hand over 0 of them without calling the model

Rank of the right section, where it changed (17 of 50):
  id      vector keyword hybrid rerank  question
  rag-06       3      12      5      2  Where will my refund be credited?
  rag-08       2       1      2      1  I bought a TV in the sale and now the price has dropped. Can
  rag-09       2       1      2      1  Do you refund the difference if a price drops after I buy?
  rag-13       2       1      1      1  Above what amount is delivery free everywhere?
  rag-14       3       5      2      2  What time do you deliver?
  rag-15       6       1      1      1  How much does express delivery cost?
  rag-17       2       2      2      1  How many times will the courier try to deliver?
  rag-23       1       2      1      2  How long do UPI refunds take?
  rag-26       1       8      3      3  Is there a charge for cash on delivery?
  rag-28       1       3      1      2  What is the minimum order for EMI?
  rag-29       2       1      2      1  My UPI payment is showing pending. Should I pay again?
  rag-30       1       2      1      2  How long is the warranty on a phone?
  rag-37       1       7      4      4  I opened my laptop box and the screen is cracked. Can I stil
  rag-39       3       1      2      1  My clearance shoes have a split sole. What can I do?
  rag-47       2       1      1      1  You match lower prices, right?
  rag-49       2       3      1      6  Can I return a lipstick I opened?
  rag-50       1       3      1      3  What are your support hours?

Answers on 10 questions (the ones vector search ranks worst), claude-haiku-5-5:
  id      before: vector top 5         after: hybrid + rerank top 5
  rag-04  answered ✓ source ✓ facts ✓  answered ✓ source ✓ facts ✓ 
  rag-06  answered ✓ source ✓ facts ✓  answered ✓ source ✓ facts ✓ 
  rag-08  answered ✓ source ✓ facts ✓  answered ✓ source ✓ facts ✓ 
  rag-09  answered ✓ source ✓ facts ✓  answered ✓ source ✓ facts ✓ 
  rag-13  answered ✓ source ✓ facts ✓  answered ✓ source ✓ facts ✓ 
  rag-14  answered ✓ source ✓ facts ✓  answered ✓ source ✓ facts ✓ 
  rag-15  handed over (not answerable) answered ✓ source ✓ facts ✓ 
  rag-17  answered ✓ source ✓ facts ✓  answered ✓ source ✓ facts ✓ 
  rag-39  answered ✓ source ✓ facts ✓  answered ✓ source ✓ facts ✓ 
  rag-41  answered ✓ source ✓ facts ✓  answered ✓ source ✓ facts ✓ 

                        answered  right source  facts right
before (vector)             9/10          9/10         9/10
after (hybrid+rerank)      10/10         10/10        10/10

LLM: 20 paid calls, 0 from cache · $0.004780 this run

$ uv run python labs/rag-hybrid/done/measure.py --answers 10 | tail -3
after (hybrid+rerank)      10/10         10/10        10/10

LLM: 0 paid calls, 20 from cache · $0.000000 this run

$ uv run pytest labs/rag-hybrid -q
..........                                                               [100%]
10 passed in 2.79s
```

How to read it:
- On 50 short, plain-English policy questions, vector search is already strong (49/50 in the top 5). Keyword search alone is weaker (45/50), but it wins on exact words and codes: the Stride RN220 above, and "express delivery" (rag-15: vector rank 6, keyword rank 1).
- Hybrid (RRF) puts the right section in the top 5 for all 50 questions.
- The reranker improves the order at the top (hit@1 35 → 37, MRR 0.830 → 0.848) but drops one question out of the top 5 (rag-49, the lipstick, rank 6). Measure on your own questions before you assume.
- A reranker score floor of 0.5 (the textbook number) would hand over 5 answerable questions on this data. Tune it on your test set.
- Answers: rag-15 is the story. With vector search, the express-delivery row never reached the model, so it honestly said it couldn't answer. With hybrid + rerank it answered, with the right source.

## OpenAI (short video)

```text
$ uv run python labs/rag-hybrid/done/measure.py --answers 3 --provider openai | tail -12

Answers on 3 questions (the ones vector search ranks worst), gpt-6-luna:
  id      before: vector top 5         after: hybrid + rerank top 5
  rag-06  answered ✓ source ✓ facts ✓  answered ✓ source ✓ facts ✓ 
  rag-14  answered ✓ source ✓ facts ✓  answered ✓ source ✓ facts ✓ 
  rag-15  handed over (not answerable) answered ✓ source ✓ facts ✗ 

                        answered  right source  facts right
before (vector)             2/3          2/3         2/3
after (hybrid+rerank)       3/3          3/3         2/3

LLM: 6 paid calls, 0 from cache · $0.000498 this run
```

## Spend

| Provider | Shown above | Both RAG labs, all live runs incl. development | Budget (this lab pair) |
| --- | --- | --- | --- |
| Anthropic (claude-haiku-5-5) | $0.0048 (20 calls; the re-run is all cache, $0) | about $0.017 | $0.05 |
| OpenAI (gpt-6-luna) | $0.0005 (6 calls) | about $0.0033 | $0.02 |

Retrieval on all 50 questions: $0 (local models).
