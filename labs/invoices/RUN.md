# Live run: invoice pipeline lab

Recorded 2026-11-17 in this repo with real keys (`set -a; source <keys>; set +a`), on `claude-haiku-5-5` for all 8 invoices, plus one OpenAI smoke run on 1 invoice with `gpt-6-luna`.
Commands as typed and exactly what they printed. Latency and token counts will differ a little on your run, and a model can misread a value: that is what the checks are for.

## Anthropic (main video)

### Part 1: document to validated JSON

What the model will see, and what it costs (no call yet):

```text
$ uv run python labs/invoices/done/pages.py
file                                  original        sent  ~tokens  sharpness
inv-01-sunrise-textiles.pdf          1241x1754    1077x873     1248        601
inv-02-voltedge-electronics.pdf      1241x1754    1077x876     1248        646
inv-03-kalpana-kitchenware.png         910x797     802x625      667        892
inv-04-stride-footwear.pdf           1241x1754    1077x835     1170        625
inv-05-greenleaf-packaging.pdf       1241x1754    1077x873     1248        606
inv-06-nimbus-devices.png              940x833     940x833     1020         33
inv-07-pulse-wearables.png             910x797     802x656      696        962
inv-08-desi-dryfruits.pdf            1241x1754    1077x793     1131        574

The images the model will see are in .shopkart/pages/
```

```text
$ uv run python labs/invoices/done/extract.py --estimate
file                               pages  ~in tokens         ~$
inv-01-sunrise-textiles.pdf            1        3348   0.000485
inv-02-voltedge-electronics.pdf        1        3348   0.000485
inv-03-kalpana-kitchenware.png         1        2767   0.000427
inv-04-stride-footwear.pdf             1        3270   0.000477
inv-05-greenleaf-packaging.pdf         1        3348   0.000485
inv-06-nimbus-devices.png              1        3120   0.000462
inv-07-pulse-wearables.png             1        2796   0.000430
inv-08-desi-dryfruits.pdf              1        3231   0.000473

8 invoices on claude-haiku-5-5: about $0.0037 (₹0.33), assuming ~300 output tokens each
```

One invoice, the blurred phone photo. Bengaluru (29) to a Maharashtra (27) warehouse, so IGST, not CGST + SGST:

```text
$ uv run python labs/invoices/done/extract.py inv-06
{
  "supplier_name": "Nimbus Devices Pvt Ltd",
  "supplier_gstin": "29AAECN6604H1ZD",
  "buyer_name": "ShopKart Retail Pvt Ltd",
  "buyer_gstin": "27AAKCS4821M1ZW",
  "invoice_number": "NDP/26/11/0091",
  "invoice_date": "2026-11-06",
  "place_of_supply": "Maharashtra (27)",
  "line_items": [
    {
      "description": "Nimbus Tab 10 Tablet",
      "hsn": "8471",
      "qty": 25.0,
      "unit_price_inr": 6900.0,
      "taxable_value_inr": 172500.0,
      "gst_rate_pct": 18.0
    }
  ],
  "taxable_value_inr": 172500.0,
  "cgst_inr": 0.0,
  "sgst_inr": 0.0,
  "igst_inr": 31050.0,
  "total_inr": 203550.0
}

inv-06-nimbus-devices.png · 1 page · ~1020 image tokens · 3107 in / 275 out · $0.000448 (₹0.0394) · 2.2s
Today: $0.005012 of $0.50 daily budget
```

### Part 2: rules, the review queue, accuracy

The GSTIN check by hand: a real one, a 6 misread as a 5, an S misread as a 5.

```text
$ uv run python labs/invoices/done/checks.py
29AAECN6604H1ZD   valid
29AAECN5604H1ZD   check character is D, should be F: a digit was probably misread
33AAQF55532D1Z8   not in GSTIN format (2 digits, PAN, entity, Z, check)
```

All 8. `inv-06` comes from the cache (read above), so it costs nothing:

```text
$ uv run python labs/invoices/done/pipeline.py
Estimate: 8 invoices on claude-haiku-5-5, about $0.0037 (limit $0.05)

#1  inv-01-sunrise-textiles.pdf         3335 in  339 out  $0.000503  -> approved
#2  inv-02-voltedge-electronics.pdf     3335 in  401 out  $0.000534  -> approved
#3  inv-03-kalpana-kitchenware.png      2754 in  327 out  $0.000439  -> approved
#4  inv-04-stride-footwear.pdf          3257 in  336 out  $0.000494  -> review
       total_mismatch: ₹2,49,200.00 + tax ₹29,904.00 = ₹2,79,104.00, but the total says ₹2,83,604.00
#5  inv-05-greenleaf-packaging.pdf      3335 in  331 out  $0.000499  -> review
       missing_supplier_gstin: no supplier gstin on the invoice
#6  inv-06-nimbus-devices.png           3107 in  275 out     cached  -> review
       low_quality_scan: blurred or tilted photo (sharpness 33, limit 100): check every number against the page
#7  inv-07-pulse-wearables.png          2783 in  409 out  $0.000483  -> approved
#8  inv-08-desi-dryfruits.pdf           3218 in  272 out  $0.000458  -> review
       tax_mismatch: tax charged is ₹9,840.00, but the line rates give ₹4,100.00

8 invoices: 4 straight through, 4 to review, 0 held as duplicates
This run: $0.003409 (₹0.3000) on claude-haiku-5-5 · today $0.008421 of $0.50
```

Again: nothing is paid for, nothing is stored twice.

```text
$ uv run python labs/invoices/done/pipeline.py
Estimate: 8 invoices on claude-haiku-5-5, about $0.0037 (limit $0.05)

#1  inv-01-sunrise-textiles.pdf         3335 in  339 out     cached  (already stored: approved)
#2  inv-02-voltedge-electronics.pdf     3335 in  401 out     cached  (already stored: approved)
#3  inv-03-kalpana-kitchenware.png      2754 in  327 out     cached  (already stored: approved)
#4  inv-04-stride-footwear.pdf          3257 in  336 out     cached  (already stored: review)
#5  inv-05-greenleaf-packaging.pdf      3335 in  331 out     cached  (already stored: review)
#6  inv-06-nimbus-devices.png           3107 in  275 out     cached  (already stored: review)
#7  inv-07-pulse-wearables.png          2783 in  409 out     cached  (already stored: approved)
#8  inv-08-desi-dryfruits.pdf           3218 in  272 out     cached  (already stored: review)

8 invoices: 4 straight through, 4 to review, 0 held as duplicates
This run: $0.000000 (₹0.0000) on claude-haiku-5-5 · today $0.008421 of $0.50
```

The person's turn:

```text
$ uv run python labs/invoices/done/review.py list
#4  inv-04-stride-footwear.pdf           ₹2,83,604.00  review
     - total_mismatch: ₹2,49,200.00 + tax ₹29,904.00 = ₹2,79,104.00, but the total says ₹2,83,604.00
#5  inv-05-greenleaf-packaging.pdf         ₹71,648.00  review
     - missing_supplier_gstin: no supplier gstin on the invoice
#6  inv-06-nimbus-devices.png            ₹2,03,550.00  review
     - low_quality_scan: blurred or tilted photo (sharpness 33, limit 100): check every number against the page
#8  inv-08-desi-dryfruits.pdf              ₹91,840.00  review
     - tax_mismatch: tax charged is ₹9,840.00, but the line rates give ₹4,100.00

4 waiting for review (--all shows every invoice)
```

```text
$ uv run python labs/invoices/done/review.py show 4
#4  inv-04-stride-footwear.pdf           ₹2,83,604.00  review
  - total_mismatch: ₹2,49,200.00 + tax ₹29,904.00 = ₹2,79,104.00, but the total says ₹2,83,604.00
{
  "supplier_name": "Stride Footwear India LLP",
  "supplier_gstin": "33AAQFS5532D1Z8",
  "buyer_name": "ShopKart Retail Pvt Ltd",
  "buyer_gstin": "27AAKCS4821M1ZW",
  "invoice_number": "SFI-2611-077",
  "invoice_date": "2026-11-08",
  "place_of_supply": "Maharashtra (27)",
  "line_items": [
    {
      "description": "Stride RN220 Running Shoes",
      "hsn": "6404",
      "qty": 120.0,
      "unit_price_inr": 1150.0,
      "taxable_value_inr": 138000.0,
      "gst_rate_pct": 12.0
    },
    {
      "description": "Stride RN210 Running Shoes",
      "hsn": "6404",
      "qty": 80.0,
      "unit_price_inr": 1390.0,
      "taxable_value_inr": 111200.0,
      "gst_rate_pct": 12.0
    }
  ],
  "taxable_value_inr": 249200.0,
  "cgst_inr": 0.0,
  "sgst_inr": 0.0,
  "igst_inr": 29904.0,
  "total_inr": 283604.0
}
model claude-haiku-5-5 · prompt inv-v1 · sha256 dc1af78bec5e…
```

```text
$ uv run python labs/invoices/done/review.py approve 4 --set total_inr=279104 --note "printed total is wrong, supplier confirmed 2,79,104"
#4  inv-04-stride-footwear.pdf           ₹2,79,104.00  approved by person · note: printed total is wrong, supplier confirmed 2,79,104
  corrected total_inr: 283604.0 -> 279104.0
```

```text
$ uv run python labs/invoices/done/review.py approve 6 --note "checked every number against the photo"
#6  inv-06-nimbus-devices.png            ₹2,03,550.00  approved by person · note: checked every number against the photo
```

```text
$ uv run python labs/invoices/done/review.py reject 8 --note "GST charged at 12% on 5% goods, asked for a corrected invoice"
#8  inv-08-desi-dryfruits.pdf              ₹91,840.00  rejected by person · note: GST charged at 12% on 5% goods, asked for a corrected invoice
```

```text
$ uv run python labs/invoices/done/review.py reject 5 --note "no supplier GSTIN, no input tax credit: asked the supplier to reissue"
#5  inv-05-greenleaf-packaging.pdf         ₹71,648.00  rejected by person · note: no supplier GSTIN, no input tax credit: asked the supplier to reissue
```

```text
$ uv run python labs/invoices/done/review.py list --all
#1  inv-01-sunrise-textiles.pdf            ₹44,940.00  approved by pipeline
#2  inv-02-voltedge-electronics.pdf      ₹1,65,318.00  approved by pipeline
#3  inv-03-kalpana-kitchenware.png       ₹1,55,898.00  approved by pipeline
#4  inv-04-stride-footwear.pdf           ₹2,79,104.00  approved by person
#5  inv-05-greenleaf-packaging.pdf         ₹71,648.00  rejected by person
#6  inv-06-nimbus-devices.png            ₹2,03,550.00  approved by person
#7  inv-07-pulse-wearables.png           ₹3,70,520.00  approved by pipeline
#8  inv-08-desi-dryfruits.pdf              ₹91,840.00  rejected by person

0 waiting for review
```

Measure. The model's own reading is scored, before the corrections:

```text
$ uv run python labs/invoices/done/score.py
file                                fields  flags (expected)
inv-01-sunrise-textiles.pdf         12/12   - (-)
inv-02-voltedge-electronics.pdf     12/12   - (-)
inv-03-kalpana-kitchenware.png      12/12   - (-)
inv-04-stride-footwear.pdf          12/12   total_mismatch (total_mismatch)
inv-05-greenleaf-packaging.pdf      12/12   missing_supplier_gstin (missing_supplier_gstin)
inv-06-nimbus-devices.png           12/12   low_quality_scan (low_quality_scan)
inv-07-pulse-wearables.png          12/12   - (-)
inv-08-desi-dryfruits.pdf           12/12   tax_mismatch (tax_mismatch)

Field accuracy, 8 invoices:
  supplier_name         100%
  supplier_gstin        100%
  buyer_gstin           100%
  invoice_number        100%
  invoice_date          100%
  place_of_supply       100%
  taxable_value_inr     100%
  cgst_inr              100%
  sgst_inr              100%
  igst_inr              100%
  total_inr             100%
  line_items            100%
  all fields            100%

Straight through: 4 of 8
Flags as expected: 8 of 8
Wrong values that slipped past every check: 0
```

On these 8 clean, generated invoices Haiku read every field right. The checks still matter: 4 of the 8 invoices are wrong *on paper* (a total that doesn't add up, tax at the wrong rate, no supplier GSTIN, an unreadable photo), and valid JSON can't tell you that. On real invoices, expect misreads too, which is why the score also counts wrong values that slipped past every check.

## OpenAI (short video)

One smoke run, on the blurred photo, into its own queue:

```text
$ uv run python labs/invoices/done/pipeline.py inv-06 --provider openai --db .shopkart/invoices-openai.db
Estimate: 1 invoices on gpt-6-luna, about $0.0005 (limit $0.05)

#1  inv-06-nimbus-devices.png           1701 in  170 out  $0.000255  -> review
       low_quality_scan: blurred or tilted photo (sharpness 33, limit 100): check every number against the page

1 invoices: 0 straight through, 1 to review, 0 held as duplicates
This run: $0.000255 (₹0.0224) on gpt-6-luna · today $0.004564 of $0.50

$ uv run python labs/invoices/done/score.py --db .shopkart/invoices-openai.db
file                                fields  flags (expected)
inv-06-nimbus-devices.png           11/12   low_quality_scan (low_quality_scan)  wrong: invoice_number

Field accuracy, 1 invoices:
  supplier_name         100%
  supplier_gstin        100%
  buyer_gstin           100%
  invoice_number          0%
  invoice_date          100%
  place_of_supply       100%
  taxable_value_inr     100%
  cgst_inr              100%
  sgst_inr              100%
  igst_inr              100%
  total_inr             100%
  line_items            100%
  all fields             92%

Straight through: 0 of 1
Flags as expected: 1 of 1
Wrong values that slipped past every check: 0
```

The difference worth showing: `gpt-6-luna` read the blurred invoice number `NDP/26/11/0091` as `NDP/26/1/0091`. No arithmetic or GSTIN rule could see that, but the sharpness check on the image had already sent the photo to a person, so it slipped past nothing. (`review.py show 1 --db .shopkart/invoices-openai.db` shows the reading.)
Also: OpenAI billed 1,701 input tokens for the same page Claude billed 3,107 for, and the estimate (Claude's patch maths) doesn't know that. This run printed "1 invoices"; the wording has since been fixed to "1 invoice".

## Spend

| Provider | Calls | Cost |
| --- | --- | --- |
| Anthropic, `claude-haiku-5-5` | 17 (incl. a first test pass of all 8) | $0.008167 (₹0.72) |
| OpenAI, `gpt-6-luna` | 1 | $0.000255 (₹0.02) |
| **Total** | 18 | **$0.008422 (₹0.74)** |

Budget for this lab's live tests: $0.05 Anthropic, $0.02 OpenAI.
