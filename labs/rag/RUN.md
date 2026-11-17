# Live run: the Copilot's knowledge base with citations

Recorded 2026-11-17 in this repo with real keys (`set -a; source <keys>; set +a`), on `claude-haiku-5-5`, plus one small OpenAI smoke run on `gpt-6-luna`.
Commands as typed and exactly what they printed. Parsing, chunking and retrieval are deterministic, so yours will match; the model's wording and the timings will differ.
The first `ingest.py` also downloads the embedding model (about 70 MB) once; that download is not shown.

## Anthropic (main video)

```text
$ uv run python labs/rag/done/parse.py data/policies/pdf/shipping-and-delivery.pdf | head -24
# --- data/policies/pdf/shipping-and-delivery.pdf → doc_id shipping-and-delivery · {'title': 'Shipping and Delivery Policy', 'type': 'policy', 'status': 'current', 'format': 'pdf'}
<!-- page 1 -->

# Shipping and Delivery Policy

ShopKart delivers to more than 19,000 PIN codes across India. This policy covers delivery charges, delivery times, tracking, address changes and failed deliveries.

## 1. Delivery charges

Delivery charges depend on the order value (after discounts) and the delivery city.

- Order value: Below ₹499; Metro cities: ₹49; Other cities: ₹79.

- Order value: ₹499 and above; Metro cities: Free; Other cities: ₹49.

- Order value: ₹2,999 and above; Metro cities: Free; Other cities: Free.

Metro cities are Mumbai, Delhi NCR, Bengaluru, Chennai, Hyderabad, Kolkata, Pune and Ahmedabad. Every other city, including Kochi, Jaipur, Lucknow, Indore and Chandigarh, counts as "other cities".

Example: an order of ₹799 delivered in Kochi pays ₹49 delivery. The same order in Pune is free.

ShopKart Plus members get free delivery on every order, in every city.

## 2. Delivery times

$ uv run python labs/rag/done/ingest.py
Parsing
  returns-and-refunds.pdf      parsed: 742 words, numbers check 16/16
  shipping-and-delivery.pdf    parsed: 656 words, numbers check 23/23
  warranty-scanned.pdf         pages [1, 2] have no text: a scan, needs OCR → using the web version data/policies/warranty.md
Chunking: 21 documents → 126 chunks (9 archived, 113 current, 4 withdrawn), 12–295 words, median 75
Embedding with BAAI/bge-small-en-v1.5 (local, free)
Saved 126 chunks to .shopkart/rag/index.sqlite: 126 embedded, 0 unchanged, 0 removed · 7.5s

$ uv run python labs/rag/done/ingest.py
Parsing
  returns-and-refunds.pdf      parsed: 742 words, numbers check 16/16
  shipping-and-delivery.pdf    parsed: 656 words, numbers check 23/23
  warranty-scanned.pdf         pages [1, 2] have no text: a scan, needs OCR → using the web version data/policies/warranty.md
Chunking: 21 documents → 126 chunks (9 archived, 113 current, 4 withdrawn), 12–295 words, median 75
Embedding with BAAI/bge-small-en-v1.5 (local, free)
Saved 126 chunks to .shopkart/rag/index.sqlite: 0 embedded, 126 unchanged, 0 removed · 0.9s

$ uv run python labs/rag/done/ingest.py --show 'returns-and-refunds§2.2'
── returns-and-refunds§2.2   (data/policies/pdf/returns-and-refunds.pdf, page 1, current)
Returns and Refunds Policy > 2. Returns > 2.2 Category return windows

Some categories have their own window. When a category is listed here, its window replaces the 14 days in section 2.1.

- Category: Clothing and accessories; Return window: 14 days; Condition: Unworn, tags attached; Notes: Innerwear and swimwear not returnable.

- Category: Footwear; Return window: 10 days; Condition: Unworn, original box; Notes: See the Footwear Policy for size exchanges.

- Category: Electronics; Return window: 7 days; Condition: Unopened, seal intact; Notes: Opened items only if faulty or damaged.

- Category: Home and kitchen; Return window: 14 days; Condition: Unused; Notes: Large appliances: see section 2.5.

- Category: Books; Return window: 14 days; Condition: No markings.

- Category: Beauty and personal care; Return window: 7 days; Condition: Unopened only; Notes: Not returnable once opened.

- Category: Grocery and gourmet; Return window: Not returnable; Notes: Damaged on arrival: report within 48 hours.

- Category: Gift cards; Return window: Not returnable; Notes: See the Gift Card Policy.

Electronics includes phones, laptops, tablets, smartwatches, headphones, earbuds, chargers, cables and power banks. Opened headphones and earbuds can be returned only if they are faulty, for hygiene reasons.


$ uv run python labs/rag/done/ask.py --search "You match lower prices, right?" -k 3

Q: You match lower prices, right?
   current only:
     0.66  returns-and-refunds§2.4          current
     0.65  sale-and-offers§5                current
     0.64  sale-and-offers§7                current
   no filter:
     0.74  price-match§3                    withdrawn
     0.72  price-match§1                    withdrawn
     0.68  price-match§2                    withdrawn

$ uv run python labs/rag/done/ask.py --demo

Q: How many days do I have to return a product?
   retrieved (vector search, current documents only):
     0.87  returns-and-refunds§2.1          Return window
     0.82  footwear§5                       Refunds
     0.81  electronics§1                    Return window
     0.80  damaged-items§2                  Time limits for reporting
     0.80  footwear§1                       Return window
A: Most products can be returned within 14 days of delivery, counted from the delivery date shown in your order details [returns-and-refunds § 2.1]. Electronics can be returned within 7 days of delivery if unopened, or if faulty or damaged [electronics § 1]. Footwear can be returned within 10 days of delivery [footwear § 1].
   source: [returns-and-refunds § 2.1] Returns and Refunds Policy > 2. Returns > 2.1 Return window  (data/policies/pdf/returns-and-refunds.pdf, page 1)
   source: [electronics § 1] Electronics Returns Policy > 1. Return window  (data/policies/electronics.md)
   source: [footwear § 1] Footwear Returns and Exchanges Policy > 1. Return window  (data/policies/footwear.md)
   check: every sentence cited, every number found in its source ✓
   claude-haiku-5-5 · 1831 in / 165 out · $0.000266 (₹0.0234)

Q: What is the delivery charge on a ₹799 order to Kochi?
   retrieved (vector search, current documents only):
     0.76  shipping-and-delivery§1          Delivery charges
     0.74  shipping-and-delivery§7          Open-box delivery
     0.72  shipping-and-delivery§2          Delivery times
     0.71  payments§3                       Cash on delivery
     0.69  shipping-and-delivery§6          Marked as delivered but not received
A: A ₹799 order delivered to Kochi, which is an other city, pays a ₹49 delivery charge. [shipping-and-delivery § 1]
   source: [shipping-and-delivery § 1] Shipping and Delivery Policy > 1. Delivery charges  (data/policies/pdf/shipping-and-delivery.pdf, page 1)
   check: every sentence cited, every number found in its source ✓
   claude-haiku-5-5 · 1862 in / 86 out · $0.000229 (₹0.0202)

Q: Can I return headphones I've already opened?
   retrieved (vector search, current documents only):
     0.84  electronics§2                    Headphones and earbuds
     0.72  electronics§1                    Return window
     0.71  electronics§3                    Category details
     0.70  electronics§intro                Electronics Returns Policy
     0.70  returns-and-refunds§2.2          Category return windows
A: Opened headphones and earbuds can be returned only if they are faulty, for hygiene reasons; fit or comfort is not a fault [electronics § 2]. Opened working electronics are not returnable, so any later fault is handled under the manufacturer's warranty [electronics § 1].
   source: [electronics § 2] Electronics Returns Policy > 2. Headphones and earbuds  (data/policies/electronics.md)
   source: [electronics § 1] Electronics Returns Policy > 1. Return window  (data/policies/electronics.md)
   check: every sentence cited, every number found in its source ✓
   claude-haiku-5-5 · 2084 in / 130 out · $0.000273 (₹0.0241)

Q: You match lower prices, right?
   retrieved (vector search, current documents only):
     0.66  returns-and-refunds§2.4          Sale and clearance items
     0.65  sale-and-offers§5                Price match
     0.64  sale-and-offers§7                Mistakes in prices
     0.64  sale-and-offers§4                Clearance
     0.63  sale-and-offers§3                Bank offers
A: No, ShopKart does not match prices from other websites or shops, and the price match programme ended on 27 October 2026 [sale-and-offers § 5]. Earlier price match promises are not valid for new orders [sale-and-offers § 5].
   source: [sale-and-offers § 5] Sale Events, Coupons and Offers Terms > 5. Price match  (data/policies/sale-and-offers.md)
   check: every sentence cited, every number found in its source ✓
   claude-haiku-5-5 · 1366 in / 112 out · $0.000193 (₹0.0169)

Q: I got this as a gift. Can I return it without the buyer's order number?
   retrieved (vector search, current documents only):
     0.74  electronics§4                    Before a pickup
     0.72  gift-cards§5                     Lost or stolen cards
     0.71  electronics§5                    Bundles and free gifts
     0.70  cancellations§2                  Cancelling after dispatch
     0.69  gift-cards§4                     Refunds and cancellations
A: I couldn't find this in our policies, so I don't want to guess. I've passed your question to our support team, and an agent will continue right here, in this chat.
   → handed over to a human. Why: the model says the sources don't cover it (answerable = false)
   claude-haiku-5-5 · 1688 in / 21 out · $0.000179 (₹0.0158)

This run: $0.001140 (₹0.1003) · today $0.001140 of $0.50

$ uv run python labs/rag/done/ask.py "How many days do I have to return a product?"

Q: How many days do I have to return a product?
   retrieved (vector search, current documents only):
     0.87  returns-and-refunds§2.1          Return window
     0.82  footwear§5                       Refunds
     0.81  electronics§1                    Return window
     0.80  damaged-items§2                  Time limits for reporting
     0.80  footwear§1                       Return window
A: Most products can be returned within 14 days of delivery, counted from the delivery date shown in your order details [returns-and-refunds § 2.1]. Electronics can be returned within 7 days of delivery if unopened, or if faulty or damaged [electronics § 1]. Footwear can be returned within 10 days of delivery [footwear § 1].
   source: [returns-and-refunds § 2.1] Returns and Refunds Policy > 2. Returns > 2.1 Return window  (data/policies/pdf/returns-and-refunds.pdf, page 1)
   source: [electronics § 1] Electronics Returns Policy > 1. Return window  (data/policies/electronics.md)
   source: [footwear § 1] Footwear Returns and Exchanges Policy > 1. Return window  (data/policies/footwear.md)
   check: every sentence cited, every number found in its source ✓
   claude-haiku-5-5 · 1831 in / 165 out · cached, $0

This run: $0.000000 (₹0.0000) · today $0.001140 of $0.50

$ uv run pytest labs/rag -q
.................                                                        [100%]
17 passed in 3.37s
```

## OpenAI (short video)

Same code, `--provider openai`. What differs: gpt-6-luna often puts all its citations together at the end of the answer (`... 7 days. [a § 1] [b § 2] [c § 3]`), so the checker attaches a group of labels to the sentence before it. OpenAI also caches long prompt prefixes by itself: from the second question on, the shared instructions are read from cache, so `in` counts only the uncached tokens (3), and the cost is lower.

```text
$ uv run python labs/rag/done/ask.py --demo --provider openai

Q: How many days do I have to return a product?
   retrieved (vector search, current documents only):
     0.87  returns-and-refunds§2.1          Return window
     0.82  footwear§5                       Refunds
     0.81  electronics§1                    Return window
     0.80  damaged-items§2                  Time limits for reporting
     0.80  footwear§1                       Return window
A: Most products can be returned within 14 days of delivery; footwear within 10 days, and electronics within 7 days. [returns-and-refunds § 2.1] [footwear § 1] [electronics § 1]
   source: [returns-and-refunds § 2.1] Returns and Refunds Policy > 2. Returns > 2.1 Return window  (data/policies/pdf/returns-and-refunds.pdf, page 1)
   source: [footwear § 1] Footwear Returns and Exchanges Policy > 1. Return window  (data/policies/footwear.md)
   source: [electronics § 1] Electronics Returns Policy > 1. Return window  (data/policies/electronics.md)
   check: every sentence cited, every number found in its source ✓
   gpt-6-luna · 3 in / 90 out · $0.000056 (₹0.0049)

Q: What is the delivery charge on a ₹799 order to Kochi?
   retrieved (vector search, current documents only):
     0.76  shipping-and-delivery§1          Delivery charges
     0.74  shipping-and-delivery§7          Open-box delivery
     0.72  shipping-and-delivery§2          Delivery times
     0.71  payments§3                       Cash on delivery
     0.69  shipping-and-delivery§6          Marked as delivered but not received
A: Delivery charges depend on order value and city; Kochi is an other city, so a ₹799 order has a ₹49 delivery charge. [shipping-and-delivery § 1]
   source: [shipping-and-delivery § 1] Shipping and Delivery Policy > 1. Delivery charges  (data/policies/pdf/shipping-and-delivery.pdf, page 1)
   check: every sentence cited, every number found in its source ✓
   gpt-6-luna · 3 in / 65 out · $0.000043 (₹0.0038)

Q: Can I return headphones I've already opened?
   retrieved (vector search, current documents only):
     0.84  electronics§2                    Headphones and earbuds
     0.72  electronics§1                    Return window
     0.71  electronics§3                    Category details
     0.70  electronics§intro                Electronics Returns Policy
     0.70  returns-and-refunds§2.2          Category return windows
A: Opened headphones can be returned only if they are faulty, such as having no sound, sound in only one side, a charging case that will not charge, or Bluetooth that will not pair after a reset; fit or comfort is not considered a fault [electronics § 2]. Faulty headphones can be returned or replaced within 7 days of delivery [electronics § 1].
   source: [electronics § 2] Electronics Returns Policy > 2. Headphones and earbuds  (data/policies/electronics.md)
   source: [electronics § 1] Electronics Returns Policy > 1. Return window  (data/policies/electronics.md)
   check: every sentence cited, every number found in its source ✓
   gpt-6-luna · 3 in / 105 out · $0.000065 (₹0.0057)

Q: You match lower prices, right?
   retrieved (vector search, current documents only):
     0.66  returns-and-refunds§2.4          Sale and clearance items
     0.65  sale-and-offers§5                Price match
     0.64  sale-and-offers§7                Mistakes in prices
     0.64  sale-and-offers§4                Clearance
     0.63  sale-and-offers§3                Bank offers
A: No. ShopKart does not match prices from other websites or shops; its price match programme ended on 27 October 2026. [sale-and-offers § 5]
   source: [sale-and-offers § 5] Sale Events, Coupons and Offers Terms > 5. Price match  (data/policies/sale-and-offers.md)
   check: every sentence cited, every number found in its source ✓
   gpt-6-luna · 769 in / 64 out · $0.000109 (₹0.0096)

Q: I got this as a gift. Can I return it without the buyer's order number?
   retrieved (vector search, current documents only):
     0.74  electronics§4                    Before a pickup
     0.72  gift-cards§5                     Lost or stolen cards
     0.71  electronics§5                    Bundles and free gifts
     0.70  cancellations§2                  Cancelling after dispatch
     0.69  gift-cards§4                     Refunds and cancellations
A: I couldn't find this in our policies, so I don't want to guess. I've passed your question to our support team, and an agent will continue right here, in this chat.
   → handed over to a human. Why: the model says the sources don't cover it (answerable = false)
   gpt-6-luna · 984 in / 19 out · $0.000108 (₹0.0095)

This run: $0.000381 (₹0.0335) · today $0.013438 of $0.50
```

## Spend

| Provider | Shown above | Both RAG labs, all live runs incl. development | Budget (this lab pair) |
| --- | --- | --- | --- |
| Anthropic (claude-haiku-5-5) | $0.0011 (5 calls, then 1 cached at $0) | about $0.017 | $0.05 |
| OpenAI (gpt-6-luna) | $0.0004 (5 calls) | about $0.0033 | $0.02 |

Embeddings, parsing and search cost $0: they run locally. A repeated question costs $0 too: answers are cached in `.shopkart/cache/rag/`.
