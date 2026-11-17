# Lab: an invoice pipeline with validation and a human review queue

ShopKart's finance team gets supplier GST invoices as PDFs and phone photos.
Build the pipeline that reads them into data they can trust: **the model reads, your code checks, and a person decides anything the checks don't trust.**

```text
document -> page images -> vision call + schema -> validated JSON -> rules -> approved, or the review queue (SQLite)
```

```text
labs/invoices/
  start/        your copy, with TODO 1–8
    pages.py      PDF/photo -> page images, trimmed and capped; token estimate; sharpness
    extract.py    the Invoice schema and the vision call (cached by file hash)
    checks.py     the rules: required fields, GSTIN, line sums, GST maths, total, scan quality
    review.py     the SQLite review queue, and a CLI to approve or reject
    pipeline.py   runs it all over data/invoices/
    score.py      field accuracy against data/invoices/expected.json
  done/         the finished answer
  tests/        the checkpoints, with fake servers
```

Data: `data/invoices/` has 8 supplier invoices to ShopKart Retail (5 PDFs, 3 photos) and `expected.json` with the right values. Four of them have a problem on purpose.

Runs on Anthropic (`claude-haiku-5-5`) by default. For OpenAI add `--provider openai` (or set `LLM_PROVIDER=openai`).
All 8 invoices cost well under a cent. Every call goes through the budget check and the cost log, and results are cached in `.shopkart/`, so a second run is free.

## Part 1: document to validated JSON

1. **TODO 1, page images.** In `pages.py`, render each PDF page with `pypdfium2` (a pip wheel, nothing to install in Codespaces) at 150 dpi; a photo is one page already. `prepare()` then trims the white margins and caps the long side at 1568 px.
2. **TODO 2, what an image costs.** About one token per 28 × 28 pixel patch. Look at the images the model will get:
   ```bash
   uv run python labs/invoices/start/pages.py
   ```
   The blank half of an A4 page is gone (fewer tokens), and the blurred photo scores 33 on sharpness against 570+ for the rest. Open `.shopkart/pages/` and look: that is what the model sees.
3. **TODO 3, the schema.** Finish `Invoice` in `extract.py`: GSTINs, invoice number and date, place of supply, line items, subtotal, CGST/SGST/IGST and total. Every field allows null: null, not a guess. Dates and GSTINs are normalised in code.
4. **Estimate before you spend.**
   ```bash
   uv run python labs/invoices/start/extract.py --estimate
   ```
5. **TODO 4, the vision call.** One `image_block()` per page in a `user_message()`, sent with `llm.complete(..., schema=Invoice)`. The client turns the block into each provider's own format. A bad answer is retried once with the error, then becomes `ex.error`, not a crash.
   ```bash
   uv run python labs/invoices/start/extract.py inv-06
   ```
6. **Checkpoint:** `LAB=start uv run pytest labs/invoices -q -k part1`

## Part 2: rules, a review queue, and accuracy

7. **TODO 5, the GSTIN check character.** A mod-36 checksum over the first 14 characters. A misread digit fails it at once:
   ```bash
   uv run python labs/invoices/start/checks.py
   ```
8. **TODO 6, the arithmetic.** Lines add up to the subtotal, the tax equals each line × its own GST rate, subtotal + tax = total, within ₹1. Already there: required fields, GSTIN format, CGST + SGST in the same state or IGST across states, billed to ShopKart's GSTIN, and a sharpness check on the image itself, because the model's own confidence isn't a check.
9. **TODO 7, route it.** In `review.py`: no issues → approved by the pipeline; any issue → the review queue, with the reasons. Two keys keep it safe to repeat: the file's hash (the same file twice is stored once), and supplier GSTIN + invoice number (the same invoice as a PDF and a photo is held as a duplicate).
10. Run the pipeline. Run it twice: the second run costs nothing and stores nothing new.
    ```bash
    uv run python labs/invoices/start/pipeline.py
    ```
11. **TODO 8, the person.** Approve (optionally correcting a field: saved as a correction, your labelled examples) or reject:
    ```bash
    uv run python labs/invoices/start/review.py list
    uv run python labs/invoices/start/review.py show 4
    uv run python labs/invoices/start/review.py approve 4 --set total_inr=279104 --note "supplier confirmed the total"
    uv run python labs/invoices/start/review.py reject 8 --note "GST at 12% on 5% goods"
    ```
12. **Measure,** field by field, against `expected.json`, plus straight-through rate and wrong values that slipped past every check:
    ```bash
    uv run python labs/invoices/start/score.py
    ```
13. **Checkpoint:** `LAB=start uv run pytest labs/invoices -q`

The real output of a live run is in [RUN.md](RUN.md).

## On OpenAI

```bash
uv run python labs/invoices/done/pipeline.py inv-06 --provider openai --db .shopkart/invoices-openai.db
uv run python labs/invoices/done/score.py --db .shopkart/invoices-openai.db
```

The same code: `image_block()` becomes an `input_image` with a base64 data URL and `detail: "high"`. OpenAI counts image tokens its own way (32 px patches and a multiplier), so the estimate is Claude's patch maths: the real count prints after the call.

## Try next

- A second look: when the GSTIN check fails, crop the header from the original page and read just that strip again, with the error message.
- Make the blur limit stricter or looser, re-run `score.py`, and watch straight-through against slipped-through values.
- Run the 8 invoices through the provider's batch API: about half the price, results within a day.
