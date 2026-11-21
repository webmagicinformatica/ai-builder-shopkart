# Live run: the document assistant, measured

Recorded 2026-11-21 in this repo with a real key, on `claude-haiku-5-5`, after building the index with `uv run python labs/rag/done/ingest.py` (126 chunks, free). The embedder and reranker models were already downloaded.
Retrieval is deterministic, so your retrieval numbers will match. The answers are the model's, so a question or two may differ.

**Total spend for everything on this page: $0.020553** (103 paid calls). A re-run from the cache costs $0.

## 1. Retrieval and the score floor (free)

```text
$ uv run python capstone/doc-assistant/solution/evaluate.py --retrieval-only
Retrieval on 50: hit@1 37 · hit@5 49 · MRR 0.848 · found in the 20 the reranker reads 50/50

$ uv run python capstone/doc-assistant/solution/assistant.py --search "Do you sell refurbished phones?"

Q: Do you sell refurbished phones?
   0.007  warranty§2                         Phone warranty claims
   0.001  electronics§6                      High-value electronics
   0.000  warranty§6                         Extended warranty
   0.000  warranty§3                         Dead on arrival (DOA)
   0.000  electronics§3                      Category details
   best 0.007 → below 0.01: hand over, no model call
```

Choosing the floor: the lowest best-chunk score of any of the 50 **answerable** questions is 0.020 (rag-47, "You match lower prices, right?"). Six of the ten "I don't know" questions score below 0.01 (0.000 to 0.008); the other four score 0.206 to 0.440, too close to real questions for a floor, so the model's `answerable` field has to catch them. The floor is 0.01. A textbook floor of 0.5 would have handed over 5 answerable questions.

## 2. Five questions

```text
$ uv run python capstone/doc-assistant/solution/assistant.py --demo

Q: How many days do I have to return a product?
   retrieved (hybrid + rerank, current documents only):
     1.000  returns-and-refunds§2.1          Return window
     0.988  electronics§1                    Return window
     0.973  damaged-items§2                  Time limits for reporting
     0.973  returns-and-refunds§2.3          Refunds
     0.973  footwear§1                       Return window
A: Most products can be returned within 14 days of delivery, counted from the delivery date shown in your order details [returns-and-refunds § 2.1]. Electronics can be returned within 7 days of delivery if unopened, or within 7 days if faulty or damaged [electronics § 1]. Footwear can be returned within 10 days of delivery [footwear § 1].
   source: [returns-and-refunds § 2.1] Returns and Refunds Policy > 2. Returns > 2.1 Return window  (data/policies/pdf/returns-and-refunds.pdf, page 1)
   source: [electronics § 1] Electronics Returns Policy > 1. Return window  (data/policies/electronics.md)
   source: [footwear § 1] Footwear Returns and Exchanges Policy > 1. Return window  (data/policies/footwear.md)
   check: every sentence cited, every number found in its source ✓
   claude-haiku-5-5 · 1976 in / 166 out · $0.000281

Q: Can I return my Stride RN220 running shoes after a run?
   retrieved (hybrid + rerank, current documents only):
     0.996  product-stride-rn220§intro       Stride RN220 Running Shoes (Men and Wome
     0.990  footwear§3                       Sale and clearance footwear
     0.970  product-stride-rn210§intro       Stride RN210 Running Shoes
     0.228  electronics§7                    Model numbers
     0.003  guide-running-shoes§intro        Choosing Running Shoes
A: The Stride RN220 running shoes are in the November Clearance and are final sale, so they cannot be returned or exchanged for size or change of mind [footwear § 3]. If your pair has a defect, you can ask for an exchange for the same product within 10 days of delivery, and a refund is given only if no replacement is available [product-stride-rn220 § intro].
   source: [footwear § 3] Footwear Returns and Exchanges Policy > 3. Sale and clearance footwear  (data/policies/footwear.md)
   source: [product-stride-rn220 § intro] Stride RN220 Running Shoes (Men and Women)  (data/products/stride-rn220.md)
   check: every sentence cited, every number found in its source ✓
   claude-haiku-5-5 · 1623 in / 159 out · $0.000242

Q: How much does express delivery cost?
   retrieved (hybrid + rerank, current documents only):
     0.798  shipping-and-delivery§2          Delivery times
     0.468  shipping-and-delivery§1          Delivery charges
     0.267  shipping-and-delivery§7          Open-box delivery
     0.027  payments§4                       EMI
     0.022  payments§3                       Cash on delivery
A: Express delivery costs ₹99 extra on top of the standard delivery charge in section 1 [shipping-and-delivery § 2]. Express delivery is next day in metro cities and 2–3 days in other cities [shipping-and-delivery § 2].
   source: [shipping-and-delivery § 2] Shipping and Delivery Policy > 2. Delivery times  (data/policies/pdf/shipping-and-delivery.pdf, page 1)
   check: every sentence cited, every number found in its source ✓
   claude-haiku-5-5 · 1879 in / 117 out · $0.000246

Q: Do you sell refurbished phones?
   retrieved (hybrid + rerank, current documents only):
     0.007  warranty§2                       Phone warranty claims
     0.001  electronics§6                    High-value electronics
     0.000  warranty§6                       Extended warranty
     0.000  warranty§3                       Dead on arrival (DOA)
     0.000  electronics§3                    Category details
A: I couldn't find this in our policies, so I don't want to guess. I've passed your question to our support team, and an agent will continue right here, in this chat.
   → handed over to a human. Why: best chunk scores 0.01, below 0.01: no model call

Q: I got this as a gift. Can I return it without the buyer's order number?
   retrieved (hybrid + rerank, current documents only):
     0.379  returns-and-refunds§2.1          Return window
     0.151  refunds§3                        Partial refunds
     0.131  gift-cards§4                     Refunds and cancellations
     0.075  electronics§5                    Bundles and free gifts
     0.034  gift-cards§intro                 ShopKart Gift Card Policy
A: I couldn't find this in our policies, so I don't want to guess. I've passed your question to our support team, and an agent will continue right here, in this chat.
   → handed over to a human. Why: the model says the sources don't cover it (answerable = false)
   claude-haiku-5-5 · 1564 in / 21 out · $0.000167

This run: $0.000936 (₹0.0823) · today $0.000936 of $0.50
```

The refurbished-phones line reads "0.01, below 0.01": the lab's message rounds to 2 decimals (the real score is 0.007). A small thing that confuses a reader, so the solution now prints 3 decimals: `Why: best chunk scores 0.007, below the floor of 0.01: no model call`.

## 3. Estimate, then a small slice

```text
$ uv run python capstone/doc-assistant/solution/evaluate.py --estimate
Estimate on claude-haiku-5-5 ($0.1/$0.5 per million tokens):
  60 questions: 54 answer calls + up to 54 judge calls, 6 skipped by the score floor (no call)
  about 104,044 input and 16,200 output tokens → about $0.0185
  Re-runs read the disk cache: $0.

$ uv run python capstone/doc-assistant/solution/evaluate.py --limit 5 | head -11
Evaluating 5 answerable + 5 "I don't know" questions on claude-haiku-5-5
  rag-01  pass  answered ($0.00021)
  rag-02  pass  answered ($0.00042)
  rag-03  pass  answered ($0.00044)
  rag-04  pass  answered ($0.00048)
  rag-05  pass  answered ($0.00040)
  idk-01  pass  handover (no call)
  idk-02  pass  handover ($0.00014)
  idk-03  pass  handover ($0.00018)
  idk-04  pass  handover (no call)
  idk-05  pass  handover (no call)

$ uv run python capstone/doc-assistant/solution/evaluate.py --limit 5 | tail -1
Wrote capstone/doc-assistant/out/report.md · this run $0.002285 (11 paid calls, 1 from cache) · a full run from empty: $0.0026
```

## 4. The first full run: what broke

```text
$ uv run python capstone/doc-assistant/solution/evaluate.py | tail -32

Answers (claude-haiku-5-5)
  answered 39/50 · right source cited 39/50 · expected numbers present 38/50
  faithfulness (judge): 147/148 claims supported (99.3%) · 38/39 answers fully supported
  handed over although answerable: 11

"I don't know" on 10 questions the documents don't cover
  handed over 10/10: 6 by the score floor (no call), 4 by the model (answerable = false), 0 by the grounding check

Failures (13):
  rag-10  handed over (check failed) · rank 1 · What is the delivery charge on a ₹799 order to Kochi
  rag-14  handed over (check failed) · rank 2 · What time do you deliver?
  rag-16  handed over (check failed) · rank 1 · Can I change my delivery address after the order has
  rag-19  handed over (check failed) · rank 1 · Can I cancel an order that has already shipped?
  rag-26  handed over (check failed) · rank 3 · Is there a charge for cash on delivery?
  rag-27  handed over (check failed) · rank 1 · How do I get my refund for a COD order?
  rag-29  handed over (check failed) · rank 1 · My UPI payment is showing pending. Should I pay agai
  rag-31  handed over (check failed) · rank 1 · Do I need my bill for a phone warranty claim?
  rag-32  unsupported: Cracked-on-arrival is within the return window · My phone screen cracked after I dropped it. Is that 
  rag-38  handed over (check failed) · rank 1 · Is a size exchange for shoes free?
  rag-47  handed over (check failed) · rank 1 · You match lower prices, right?
  rag-48  missing numbers from: 'DIWALI10 could be used with EMI, but it was valid ' · Can I use the Diwali coupon on EMI?
  rag-49  handed over (model: answerable = false) · rank 6 · Can I return a lipstick I opened?

Acceptance criteria
  ✓ Right section in the top 5 ≥ 45/50                   49/50
  ✗ Answered with the right source and facts ≥ 40/50     38/50
  ✓ Claims supported by their source ≥ 90%               99.3%
  ✓ Honest "I don't know" ≥ 9/10                         10/10
  ✓ One full run ≤ $0.05                                 $0.0190

Wrote capstone/doc-assistant/out/report.md · this run $0.015974 (79 paid calls, 14 from cache) · a full run from empty: $0.0190
```

Ten answerable questions were handed over by the grounding check. Reading `reply.reason` and the hidden answer for each:

```text
rag-29  check failed: no citation: 'No, do not pay again if your UPI payment shows pending.'
    No, do not pay again if your UPI payment shows pending. Wait 30 minutes, as the order will be confirmed
    or the money reversed automatically [payments § 2]. If it is still pending after 24 hours, raise a ticket
    with your order ID and UPI reference number [payments § 5].
rag-26  check failed: no citation: 'Yes, a ₹30 COD fee is added at checkout for cash on delivery'
    Yes, a ₹30 COD fee is added at checkout for cash on delivery orders. It is not refunded if the order is
    returned, except for damaged, defective or wrong items. [payments § 3]
rag-10  check failed: number 2,998, is not in ['shipping-and-delivery § 1']
    A ₹799 order delivered to Kochi, which counts as another city, pays a delivery charge of ₹79 for orders
    below ₹499 or ₹49 for orders from ₹499 to ₹2,998, so at ₹799 it pays ₹49 [shipping-and-delivery § 1]. ...
```

- **9 of the 10 were correct answers.** The model often cites once, after two sentences. The lab's check wants a citation on *every* sentence, so it rejected them. Fix (in code, `check_passages` in `assistant.py`): an uncited sentence belongs to the next citation, as one passage, and every number in the passage must still be in that source. A trailing sentence with no citation still fails. The prompt didn't change, so every answer came from the cache: the fix cost only the judge calls for the 9 new answers.
- **rag-10 was a real catch.** The source says "₹2,999 and above"; the model invented a "₹2,998" boundary. The check worked as intended: the customer got a handover, not a made-up number.

## 5. After the fix

```text
$ uv run python capstone/doc-assistant/solution/evaluate.py | tail -27

Retrieval (hybrid + rerank, free) on 50 answerable questions
  right section first 37/50 · in the top 5 49/50 · MRR 0.848
  lowest best-chunk score of an answerable question: 0.020 (score floor 0.01)

Answers (claude-haiku-5-5)
  answered 48/50 · right source cited 48/50 · expected numbers present 47/50
  faithfulness (judge): 181/182 claims supported (99.5%) · 47/48 answers fully supported
  handed over although answerable: 2

"I don't know" on 10 questions the documents don't cover
  handed over 10/10: 6 by the score floor (no call), 4 by the model (answerable = false), 0 by the grounding check

Failures (4):
  rag-10  handed over (check failed) · rank 1 · What is the delivery charge on a ₹799 order to Kochi
  rag-32  unsupported: Cracked-on-arrival is within the return window · My phone screen cracked after I dropped it. Is that 
  rag-48  missing numbers from: 'DIWALI10 could be used with EMI, but it was valid ' · Can I use the Diwali coupon on EMI?
  rag-49  handed over (model: answerable = false) · rank 6 · Can I return a lipstick I opened?

Acceptance criteria
  ✓ Right section in the top 5 ≥ 45/50                   49/50
  ✓ Answered with the right source and facts ≥ 40/50     47/50
  ✓ Claims supported by their source ≥ 90%               99.5%
  ✓ Honest "I don't know" ≥ 9/10                         10/10
  ✓ One full run ≤ $0.05                                 $0.0203

Wrote capstone/doc-assistant/out/report.md · this run $0.001358 (9 paid calls, 93 from cache) · a full run from empty: $0.0203

$ uv run python capstone/doc-assistant/solution/evaluate.py | tail -1
Wrote capstone/doc-assistant/out/report.md · this run $0.000000 (0 paid calls, 102 from cache) · a full run from empty: $0.0203

$ uv run pytest capstone -q
...........                                                              [100%]
11 passed in 2.06s
```

The four failures that are left, read one by one:

| Case | What happened | Layer | Decision |
|---|---|---|---|
| rag-10 | Invented "₹2,998" boundary, caught by the check | generation | Correct behaviour: handed over. Leave it. |
| rag-32 | "Cracked on arrival is handled as a return" cited to a section that only *defines* damage. No number in it, so only the judge caught it | generation | A true judge catch. The code check can't see it. |
| rag-48 | "DIWALI10 can be used with EMI": faithful to the source, but the coupon expired on 2 November. The model doesn't know today's date | prompt | Fix: put today's date in the prompt. That changes every prompt, so all 54 answers would be paid again: batched with the next prompt change. |
| rag-49 | The lipstick rule is at rank 6, outside the top 5; the model honestly said it couldn't answer | retrieval | A retrieval miss, handled safely. Next: try top 6, or a cosmetics keyword boost, and measure. |

The estimate said $0.0185; one full run from an empty cache cost $0.0203 (the judge's answers were longer than the estimate assumed).
