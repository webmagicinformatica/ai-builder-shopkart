# Eval report: ShopKart document assistant

Model `claude-haiku-5-5` · retrieval hybrid (BM25 + vectors) + local reranker, top 5 · score floor 0.01 · judge rubric f1 · 28 s · this run $0.0000 (0 paid calls, 102 from cache)

## Acceptance criteria

| Criterion | Result | |
|---|---|---|
| Right section in the top 5 ≥ 45/50 | 49/50 | pass |
| Answered with the right source and facts ≥ 40/50 | 47/50 | pass |
| Claims supported by their source ≥ 90% | 99.5% | pass |
| Honest "I don't know" ≥ 9/10 | 10/10 | pass |
| One full run ≤ $0.05 | $0.0203 | pass |

## Answerable questions (50, data/golden/rag-50.jsonl)

| Metric | Value |
|---|---|
| Right section ranked first (hit@1) | 37/50 |
| Right section in the top 5 (hit@5) | 49/50 |
| Mean reciprocal rank | 0.848 |
| Answered | 48/50 |
| Right source cited | 48/50 |
| Expected numbers present | 47/50 |
| Claims supported (judge) | 181/182 (99.5%) |
| Answers fully supported (judge) | 47/48 |
| Handed over although answerable | 2 |
| **Passed every check** | **46/50** |

## Questions the documents don't cover (10, solution/idk-10.jsonl)

Handed over 10/10: 6 by the score floor (no model call), 4 by the model (answerable = false), 0 by the grounding check.

## Every failure (4)

- `rag-10` handed over (check failed) · rank 1 · What is the delivery charge on a ₹799 order to Kochi
- `rag-32` unsupported: Cracked-on-arrival is within the return window · My phone screen cracked after I dropped it. Is that 
- `rag-48` missing numbers from: 'DIWALI10 could be used with EMI, but it was valid ' · Can I use the Diwali coupon on EMI?
- `rag-49` handed over (model: answerable = false) · rank 6 · Can I return a lipstick I opened?

## Every question

| id | rank | best score | result | why / sources |
|---|---|---|---|---|
| rag-01 | 1 | 1.000 | pass | returns-and-refunds§2.1, electronics§1, footwear§1 |
| rag-02 | 1 | 0.989 | pass | footwear§1 |
| rag-03 | 1 | 0.999 | pass | electronics§2, electronics§1 |
| rag-04 | 2 | 0.970 | pass | electronics§1, electronics§3 |
| rag-05 | 1 | 0.997 | pass | returns-and-refunds§2.3, footwear§5 |
| rag-06 | 2 | 0.326 | pass | payments§3.1, returns-and-refunds§2.3 |
| rag-07 | 1 | 1.000 | pass | sale-and-offers§4, returns-and-refunds§2.4 |
| rag-08 | 1 | 0.649 | pass | refunds§4, returns-and-refunds§2.4 |
| rag-09 | 1 | 0.999 | pass | refunds§4, returns-and-refunds§2.4 |
| rag-10 | 1 | 0.998 | FAIL | handover: check failed |
| rag-11 | 1 | 0.999 | pass | shipping-and-delivery§1 |
| rag-12 | 1 | 1.000 | pass | shipping-and-delivery§1 |
| rag-13 | 1 | 0.945 | pass | shipping-and-delivery§1 |
| rag-14 | 2 | 0.982 | pass | shipping-and-delivery§2 |
| rag-15 | 1 | 0.798 | pass | shipping-and-delivery§2 |
| rag-16 | 1 | 1.000 | pass | shipping-and-delivery§4 |
| rag-17 | 1 | 1.000 | pass | shipping-and-delivery§5 |
| rag-18 | 1 | 0.999 | pass | shipping-and-delivery§6 |
| rag-19 | 1 | 1.000 | pass | cancellations§2, cancellations§2 |
| rag-20 | 1 | 0.999 | pass | cancellations§1 |
| rag-21 | 2 | 1.000 | pass | cancellations§7, cancellations§4 |
| rag-22 | 1 | 0.999 | pass | refunds§1 |
| rag-23 | 2 | 0.998 | pass | refunds§2 |
| rag-24 | 1 | 0.999 | pass | payments§5, refunds§6 |
| rag-25 | 1 | 0.937 | pass | payments§3 |
| rag-26 | 3 | 0.997 | pass | payments§3 |
| rag-27 | 1 | 0.999 | pass | payments§3.1 |
| rag-28 | 2 | 0.936 | pass | payments§4 |
| rag-29 | 1 | 0.999 | pass | payments§2, payments§5 |
| rag-30 | 2 | 0.983 | pass | warranty§1 |
| rag-31 | 1 | 0.976 | pass | warranty§2 |
| rag-32 | 1 | 0.993 | FAIL | warranty§5, damaged-items§1 |
| rag-33 | 1 | 0.999 | pass | warranty§6 |
| rag-34 | 1 | 0.996 | pass | damaged-items§3 |
| rag-35 | 1 | 0.960 | pass | refunds§7 |
| rag-36 | 1 | 0.974 | pass | damaged-items§2 |
| rag-37 | 4 | 0.047 | pass | damaged-items§2, warranty§5, electronics§6 |
| rag-38 | 1 | 0.999 | pass | footwear§2 |
| rag-39 | 1 | 0.961 | pass | footwear§3, footwear§4 |
| rag-40 | 2 | 0.970 | pass | guide-shoe-care§intro, footwear§4 |
| rag-41 | 3 | 1.000 | pass | gift-cards§1 |
| rag-42 | 1 | 1.000 | pass | gift-cards§2 |
| rag-43 | 1 | 0.999 | pass | gift-cards§3, gift-cards§8 |
| rag-44 | 1 | 0.994 | pass | gift-cards§4 |
| rag-45 | 1 | 0.830 | pass | privacy§3 |
| rag-46 | 1 | 0.586 | pass | privacy§1 |
| rag-47 | 1 | 0.020 | pass | sale-and-offers§5 |
| rag-48 | 1 | 0.984 | FAIL | sale-and-offers§2.1, sale-and-offers§2 |
| rag-49 | 6 | 0.052 | FAIL | handover: model: answerable = false |
| rag-50 | 3 | 0.167 | pass | escalation-and-handover§3 |
| idk-01 | - | 0.008 | pass | handover: score floor (no model call) |
| idk-02 | - | 0.206 | pass | handover: model: answerable = false |
| idk-03 | - | 0.440 | pass | handover: model: answerable = false |
| idk-04 | - | 0.003 | pass | handover: score floor (no model call) |
| idk-05 | - | 0.003 | pass | handover: score floor (no model call) |
| idk-06 | - | 0.379 | pass | handover: model: answerable = false |
| idk-07 | - | 0.000 | pass | handover: score floor (no model call) |
| idk-08 | - | 0.000 | pass | handover: score floor (no model call) |
| idk-09 | - | 0.007 | pass | handover: score floor (no model call) |
| idk-10 | - | 0.220 | pass | handover: model: answerable = false |
