# ShopKart data

Shared fixtures for every lab. All of it is fictional. Labs read it through `shopkart/data.py`; please don't edit these files inside a lab.

**"Today" is Tuesday 17 November 2026** for every fixture (`shopkart.data.TODAY`). Delivery dates and return windows are counted from that date, so the labs give the same answers whenever you run them. Override it with `SHOPKART_TODAY=YYYY-MM-DD` if you need to.

| Path | What | Used in |
| --- | --- | --- |
| `policies/*.md` | 13 current policy documents, with front matter (`doc_id`, `version`, `effective`, `status`) | prompts, RAG, chains, evals |
| `policies/archive/` | Old and withdrawn policies (30-day returns from 2024, 7-day footwear, price match). `status: archived` or `withdrawn`. Never answer from them. | RAG freshness and filters |
| `policies/pdf/` | The same policies as PDFs: a normal PDF with tables and page furniture, a two-column PDF, and a scanned PDF with no text layer | parsing lab |
| `products/` | A few product pages and guides (Stride RN220/RN210, SonicBuds X2, shoe care) | hybrid search |
| `orders.json` | 40 orders (IDs like `SK48213`), Indian cities, ₹ amounts, statuses, payment methods | tools, chains, agents, MCP |
| `customers.json` | 24 customers (e.g. Meera Nair, `C1042`) | access control, memory |
| `tickets.json` | Support tickets: everyday, angry, Hinglish, PII, prompt injection | chains, tools, MCP, red team |
| `golden/golden-150.jsonl` | The golden test set: 90 everyday, 35 hard, 25 must-hand-over | evals |
| `golden/rag-50.jsonl` | The 50 policy questions with answer, source doc and section | RAG evals |
| `invoices/` | 8 supplier GST invoices (PDF and PNG), some with errors, plus `expected.json` | document extraction |
| `workload.jsonl` | 200 customer questions with repeats and easy/hard labels | cost lab |

## Key facts (match the lessons)

- Return window 14 days from delivery; footwear 10 days; electronics 7 days, unopened unless faulty or damaged.
- Refunds go to the original payment method within 5–7 working days of pickup.
- Any refund above ₹5,000 needs a human.
- Clearance items are final sale (exchange only for a defect). Sale items get no price-drop refund.
- Delivery: ₹499 and above is free in metro cities and ₹49 in other cities (Kochi ₹799 order → ₹49).
- Nothing in the policies covers returning a product received as a gift. Those questions must be handed over.
