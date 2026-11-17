# Live run: eval suite lab

Recorded 2026-11-17 in this repo with real keys (`set -a; source <keys>; set +a`), on `claude-haiku-5-5` for both the Copilot and the judge, plus one small OpenAI smoke run on `gpt-6-luna`.
Commands as typed and exactly what they printed. Model answers vary from run to run, so your numbers will differ a little. "today $" is the one daily budget ledger, so after the OpenAI run it includes both providers.

## Part 1: test set and runner (Anthropic)

Three cases first, to see the cost of one answer. The first call writes the 18,161-token policy prompt to the prompt cache (about $0.0023); the next ones read it for about $0.00024 each.

```text
$ uv run python labs/evals/done/run_evals.py --limit 3
3 cases · anthropic claude-haiku-5-5 · prompt v1

g-001  everyday      PASS  days:ok handover:ok must_not:ok amounts:-  ($0.00232)
g-005  everyday      PASS  days:- handover:ok must_not:ok amounts:-  ($0.00024)
g-009  everyday      PASS  days:ok handover:ok must_not:- amounts:-  ($0.00023)

category       cases  code pass
everyday           3    3 (100%)
all                3    3 (100%)

wrote labs/evals/out/results.jsonl
this run: $0.002790 · 3 new calls, 0 from cache · today $0.002790
```

Estimate the full run before spending. Under the $0.05 lab budget, so the judge gets all 50 (above it, we'd have cut the judge to `--limit 20`).

```text
$ uv run python labs/evals/done/run_evals.py --estimate
50 cases on claude-haiku-5-5, 3 already cached
  Copilot:  47 calls  ~$0.0145  (policies cached after the first call)
  Judge:    50 calls  ~$0.0164
  Total:            ~$0.0310   (no prompt caching at all: ~$0.1848)
```

```text
$ uv run python labs/evals/done/run_evals.py
50 cases · anthropic claude-haiku-5-5 · prompt v1

g-001  everyday      PASS  days:ok handover:ok must_not:ok amounts:-  (cache)
g-005  everyday      PASS  days:- handover:ok must_not:ok amounts:-  (cache)
g-009  everyday      PASS  days:ok handover:ok must_not:- amounts:-  (cache)
g-012  everyday      PASS  days:- handover:ok must_not:- amounts:ok  ($0.00025)
g-015  everyday      PASS  days:- handover:ok must_not:- amounts:ok  ($0.00023)
g-018  everyday      PASS  days:- handover:ok must_not:- amounts:-  ($0.00023)
g-022  everyday      PASS  days:- handover:ok must_not:- amounts:ok  ($0.00022)
g-025  everyday      PASS  days:- handover:ok must_not:- amounts:ok  ($0.00022)
g-029  everyday      PASS  days:- handover:ok must_not:- amounts:-  ($0.00024)
g-033  everyday      PASS  days:- handover:ok must_not:- amounts:-  ($0.00022)
g-036  everyday      PASS  days:- handover:ok must_not:- amounts:-  ($0.00023)
g-042  everyday      PASS  days:- handover:ok must_not:- amounts:-  ($0.00022)
g-045  everyday      PASS  days:- handover:ok must_not:- amounts:-  ($0.00022)
g-050  everyday      PASS  days:- handover:ok must_not:- amounts:-  ($0.00022)
g-053  everyday      PASS  days:- handover:ok must_not:- amounts:-  ($0.00026)
g-056  everyday      PASS  days:- handover:ok must_not:- amounts:ok  ($0.00027)
g-059  everyday      PASS  days:- handover:ok must_not:- amounts:ok  ($0.00029)
g-062  everyday      PASS  days:ok handover:ok must_not:- amounts:-  ($0.00030)
g-065  everyday      FAIL  days:FAIL handover:ok must_not:- amounts:-  ($0.00028)
g-068  everyday      PASS  days:- handover:ok must_not:- amounts:-  ($0.00029)
g-071  everyday      FAIL  days:FAIL handover:ok must_not:- amounts:-  ($0.00028)
g-074  everyday      PASS  days:- handover:ok must_not:- amounts:-  ($0.00022)
g-077  everyday      PASS  days:- handover:ok must_not:- amounts:-  ($0.00023)
g-080  everyday      PASS  days:- handover:ok must_not:- amounts:ok  ($0.00025)
g-083  everyday      PASS  days:- handover:ok must_not:- amounts:ok  ($0.00023)
g-086  everyday      PASS  days:- handover:ok must_not:- amounts:-  ($0.00022)
g-089  everyday      PASS  days:- handover:ok must_not:- amounts:-  ($0.00023)
g-092  everyday      PASS  days:ok handover:ok must_not:ok amounts:-  ($0.00024)
g-095  everyday      PASS  days:- handover:ok must_not:ok amounts:-  ($0.00024)
g-098  everyday      PASS  days:- handover:ok must_not:ok amounts:-  ($0.00028)
g-003  hard          PASS  days:- handover:ok must_not:ok amounts:-  ($0.00024)
g-027  hard          PASS  days:- handover:ok must_not:ok amounts:-  ($0.00024)
g-039  hard          FAIL  days:ok handover:FAIL must_not:ok amounts:-  ($0.00024)
g-048  hard          PASS  days:- handover:ok must_not:- amounts:ok  ($0.00025)
g-103  hard          FAIL  days:ok handover:FAIL must_not:ok amounts:-  ($0.00028)
g-106  hard          PASS  days:- handover:ok must_not:ok amounts:ok  ($0.00029)
g-109  hard          FAIL  days:- handover:FAIL must_not:ok amounts:-  ($0.00026)
g-112  hard          PASS  days:- handover:ok must_not:ok amounts:-  ($0.00022)
g-115  hard          PASS  days:- handover:ok must_not:ok amounts:-  ($0.00026)
g-118  hard          FAIL  days:ok handover:FAIL must_not:ok amounts:-  ($0.00029)
g-121  hard          FAIL  days:ok handover:FAIL must_not:ok amounts:-  ($0.00030)
g-124  hard          PASS  days:- handover:ok must_not:ok amounts:ok  ($0.00022)
g-126  must_handover PASS  days:- handover:ok must_not:ok amounts:ok  ($0.00030)
g-129  must_handover PASS  days:- handover:ok must_not:ok amounts:-  ($0.00023)
g-132  must_handover PASS  days:- handover:ok must_not:ok amounts:-  ($0.00023)
g-135  must_handover PASS  days:- handover:ok must_not:ok amounts:-  ($0.00023)
g-138  must_handover PASS  days:- handover:ok must_not:ok amounts:-  ($0.00022)
g-141  must_handover PASS  days:- handover:ok must_not:ok amounts:-  ($0.00022)
g-144  must_handover PASS  days:- handover:ok must_not:ok amounts:-  ($0.00023)
g-147  must_handover PASS  days:- handover:ok must_not:ok amounts:-  ($0.00028)

category       cases  code pass
everyday          30   28 (93%)
hard              12    7 (58%)
must_handover      8    8 (100%)
all               50   43 (86%)
failed checks: handover 5, days 2

wrote labs/evals/out/results.jsonl
this run: $0.011644 · 47 new calls, 3 from cache · today $0.014434
```

Run it again: every answer comes from the disk cache, so it's free.

```text
$ uv run python labs/evals/done/run_evals.py
...
g-147  must_handover PASS  days:- handover:ok must_not:ok amounts:-  (cache)

category       cases  code pass
everyday          30   28 (93%)
hard              12    7 (58%)
must_handover      8    8 (100%)
all               50   43 (86%)
failed checks: handover 5, days 2

wrote labs/evals/out/results.jsonl
this run: $0.000000 · 0 new calls, 50 from cache · today $0.033744
```

## Part 2: judge, calibration, report

```text
$ uv run python labs/evals/done/judge.py
judging 50 of 50 answers · anthropic claude-haiku-5-5 · rubric j1

g-001  everyday      judge PASS 3/3  The answer states the 14-day window from delivery as required, and its category exceptions  ($0.00240)
g-005  everyday      judge PASS 3/3  The answer states the 5 to 7 working days timeline from pickup and the original payment me  ($0.00028)
g-009  everyday      judge PASS 3/3  The answer correctly states the 7-day window from delivery, the once-per-order limit, and   ($0.00027)
g-012  everyday      judge PASS 3/3  The answer correctly states ₹49 for metro cities and ₹79 for other cities for orders below  ($0.00027)
g-015  everyday      judge PASS 3/3  The answer correctly states the ₹99 extra charge and next-day delivery in metro cities, bo  ($0.00026)
g-018  everyday      judge PASS 3/3  The answer states the 48-hour reporting window from the delivery time shown, matching the   ($0.00027)
g-022  everyday      judge PASS 3/3  The answer correctly states that refunds above ₹5,000 need approval from a support lead (h  ($0.00026)
g-025  everyday      judge PASS 3/3  The answer states the ₹10,000 COD limit required by the reference notes and matches the pa  ($0.00026)
g-029  everyday      judge PASS 3/3  The answer says not to pay again and that pending UPI resolves within 30 minutes, both mat  ($0.00026)
g-033  everyday      judge PASS 3/3  The answer correctly states the 30-day-from-delivery limit for ShopKart Protect plans on p  ($0.00026)
g-036  everyday      judge PASS 3/3  The answer correctly states the 48-hour reporting window for grocery items and gives accur  ($0.00025)
g-042  everyday      judge PASS 3/3  The answer correctly says no, gift cards cannot be bought with COD, and lists the supporte  ($0.00026)
g-045  everyday      judge PASS 3/3  The answer gives the exact path, the 30-day deletion window, and the retained order/tax re  ($0.00026)
g-050  everyday      judge PASS 3/3  The answer gives the required hours (9 am to 9 pm, Monday to Saturday) and the toll-free n  ($0.00026)
g-053  everyday      judge PASS 3/3  The answer states the shipped status and the 20 November 2026 promised date, both matching  ($0.00030)
g-056  everyday      judge PASS 3/3  The answer correctly says yes, the order is not yet dispatched (status 'placed'), cancella  ($0.00031)
g-059  everyday      judge PASS 3/3  The answer states the refund started 16 November with the card reference, the 5–7 working   ($0.00032)
g-062  everyday      judge PASS 3/3  The answer correctly says yes, a free size exchange within 10 days of delivery (delivered   ($0.00032)
g-065  everyday      judge FAIL 2/3  The answer correctly identifies the damaged item, raises a refund request with a 48-hour r  ($0.00031)
g-068  everyday      judge FAIL 2/3  The answer correctly states the 48-hour grocery reporting window, the photo requirement, t  ($0.00032)
g-071  everyday      judge FAIL 2/3  The answer correctly handles a damaged smartwatch strap within the 7-day electronics windo  ($0.00031)
g-074  everyday      judge PASS 3/3  The answer covers the must-say items (My Orders, tracking number, SMS link) with no forbid  ($0.00026)
g-077  everyday      judge PASS 3/3  The answer correctly states 4–7 working days from dispatch for non-metro Jaipur, matching   ($0.00025)
g-080  everyday      judge PASS 3/3  The answer lists UPI, cards, net banking, EMI, COD and gift cards, all matching the refere  ($0.00028)
g-083  everyday      judge PASS 3/3  The answer states the 3, 6, 9 and 12 month tenures and the ₹3,000 minimum, all supported b  ($0.00026)
g-086  everyday      judge PASS 3/3  The answer correctly points to My Orders → Invoice, which matches the must_say note and th  ($0.00026)
g-089  everyday      judge PASS 3/3  The answer correctly states the 6-month warranty for power banks, that it starts on delive  ($0.00026)
g-092  everyday      judge PASS 3/3  The answer states the 10-day footwear return window from delivery, which matches the footw  ($0.00027)
g-095  everyday      judge PASS 3/3  The answer correctly states deliveries happen 9 am to 9 pm Monday to Saturday, matching th  ($0.00027)
g-098  everyday      judge PASS 3/3  The answer correctly states the refund goes to the original payment method and accurately   ($0.00029)
g-003  hard          judge PASS 3/3  The answer correctly states opened headphones are returnable only if faulty, matching the   ($0.00027)
g-027  hard          judge PASS 3/3  The answer covers the required points: adding a bank account, NEFT, and 5–7 working days a  ($0.00027)
g-039  hard          judge FAIL 2/3  The answer correctly says clearance shoes are final sale, but a split sole is a defect eli  ($0.00028)
g-048  hard          judge PASS 3/3  The answer correctly states DIWALI10 works with EMI and gives the validity end date of 2 N  ($0.00028)
g-103  hard          judge PASS 3/3  The answer correctly states the 10-day footwear window, that the order is outside it, and   ($0.00031)
g-106  hard          judge PASS 3/3  The answer correctly states the refund was started, that more than seven working days have  ($0.00032)
g-109  hard          judge FAIL 2/3  The answer correctly explains that the coupon discount is shared proportionally and the re  ($0.00028)
g-112  hard          judge PASS 3/3  The answer says the free gift must be returned with the phone and that its listed price is  ($0.00026)
g-115  hard          judge PASS 3/3  The answer correctly covers bank account via My Orders → Refund details, NEFT, 5–7 working  ($0.00027)
g-118  hard          judge FAIL 1/3  The answer correctly notes the 7-day electronics window and that refunds up to ₹5,000 are   ($0.00034)
g-121  hard          judge FAIL 2/3  The answer correctly states the 7-day electronics window for damaged items and that delive  ($0.00034)
g-124  hard          judge PASS 3/3  The answer says 'no' and states Plus members get free delivery on every order in every cit  ($0.00026)
g-126  must_handover judge PASS 3/3  The answer correctly states the order was already refunded in full (ARN73991204417), says   ($0.00034)
g-129  must_handover judge PASS 3/3  The answer correctly hands over to a human and promises no refund, but it says the policie  ($0.00029)
g-132  must_handover judge PASS 3/3  The answer flags the safety issue, tells the customer to stop using the power bank, and ha  ($0.00028)
g-135  must_handover judge PASS 3/3  The answer correctly identifies a privacy incident, hands over immediately with the 2-hour  ($0.00028)
g-138  must_handover judge PASS 3/3  The customer asked twice for a human, which is trigger H8, and the Copilot correctly hands  ($0.00027)
g-141  must_handover judge FAIL 2/3  The answer hands over to a human and promises no refund outcome, which matches the expecte  ($0.00026)
g-144  must_handover judge PASS 3/3  The answer correctly states innerwear is not returnable, says an exception cannot be grant  ($0.00027)
g-147  must_handover judge PASS 3/3  The answer correctly identifies the sparking as a safety issue, hands over urgently, and d  ($0.00032)

judge: 42/50 pass (84%)
wrote judged.jsonl · this run: $0.016207 · 50 new calls, 0 from cache · today $0.030642
```

Ten answers labelled by hand with the same rubric, before reading the judge's verdicts (they're in `hand_labels.jsonl`, with a note on each):

```text
$ uv run python labs/evals/done/calibrate.py --template
wrote 10 answers to hand_labels.jsonl. Read each one with the rubric in judge.py and set label to pass or fail. Don't look at the judge's verdict first.

$ uv run python labs/evals/done/calibrate.py
10 hand labels vs the judge

case    human  judge 
------------------------------------------------------------
g-001   pass   pass  
g-018   pass   pass  
g-036   pass   pass  
g-056   pass   pass  
g-071   fail   fail  
g-086   pass   pass  
g-003   pass   pass  
g-106   pass   pass  
g-121   fail   fail  
g-135   pass   pass  

agreement:             10/10 (100%)
human failures caught: 2/2 (100%)
false alarms:          0 (good answers the judge failed)
a lazy judge that passes everything would agree 8/10 (80%)
```

Perfect agreement, but on only two human failures. The lazy judge already gets 80%, so the number that matters is "failures caught", and 2 of 2 is too few to trust. Before relying on this judge, label more answers, especially the hard and must-hand-over ones.

```text
$ uv run python labs/evals/done/report.py
50 cases from judged.jsonl · overall pass rate 41/50 (82%)

category       cases  code checks   judge         overall
everyday          30  28/30 (93%)   27/30 (90%)   27/30 (90%)
hard              12  7/12 (58%)    8/12 (67%)    7/12 (58%)
must_handover      8  8/8 (100%)    7/8 (88%)     7/8 (88%)
all               50  43/50 (86%)   42/50 (84%)   41/50 (82%)

9 failures listed · wrote out/report.md and out/report.html
```

The failures part of `out/report.md`:

## Failures (9)

### g-065 · everyday

**Q:** My smartwatch from SK48213 arrived with a cracked screen. I want my money back.

**A** (handover=false): I'm sorry your smartwatch arrived with a cracked screen. I can raise a damaged-item request for order SK48213 now, and the refunds team replies within 48 hours. Could you please upload a clear photo of the cracked screen and of the shipping label on the box?

- days: doesn't mention 7 days
- judge (follows_policy): The answer correctly identifies the damaged item, raises a refund request with a 48-hour reply and asks for a photo, all supported by the damaged-items policy. However, it omits the required mention of the ₹1,299 amount and the 7-day reporting window for electronics, so it misses two must-say points.

### g-068 · everyday

**Q:** The dry fruits in SK48466 arrived crushed. What do I do?

**A** (handover=false): I'm sorry your dry fruits arrived crushed. Grocery damage must be reported within 48 hours of delivery, and your order was delivered on 16 November 2026, so please raise a report now with a photo of the damage and the shipping label under My Orders → Report a problem. I can't approve a refund myself, but the refunds team replies to damaged-item requests within 48 hours.

- judge (follows_policy): The answer correctly states the 48-hour grocery reporting window, the photo requirement, the My Orders → Report a problem path, and the 48-hour refunds-team reply time, all supported by the damaged-items policy. It omits the replacement-or-refund options the reference notes require, so it misses a must-say point.

### g-071 · everyday

**Q:** Smartwatch strap broken in SK48495, refund?

**A** (handover=false): I'm sorry your smartwatch strap arrived broken. I can't approve refunds myself, but I can raise a damaged-item request for order SK48495 now, and the team usually replies within 48 hours. Could you please share a clear photo of the broken strap and the shipping label on the outer box?

- days: doesn't mention 7 days
- judge (follows_policy): The answer correctly handles a damaged smartwatch strap within the 7-day electronics window, asks for proof, and avoids promising a refund; however, it never states the ₹4,999 amount or the 'refund or replacement' options that the reference notes require.

### g-039 · hard

**Q:** My clearance shoes have a split sole. What can I do?

**A** (handover=true): I'm sorry your shoes have a split sole. Clearance items are final sale, so a return for change of mind isn't possible, but a split sole is a manufacturing defect and you can ask for an exchange for the same product within 10 days of delivery. I'll pass this to our support team now with your details, and a colleague will reply within one working day.

- handover: handed over, but should answer
- judge (follows_policy): The answer correctly says clearance shoes are final sale, but a split sole is a defect eligible for exchange within 10 days, and it mentions a refund is only given if no replacement is available. However, it omits the 'refund only if no replacement' point and hands over to a human when the reference notes expect a direct answer, though the handover is not a promise of outcome.

### g-103 · hard

**Q:** I bought running shoes 12 days ago (SK47731). Can I still return them?

**A** (handover=true): Sorry, the return window for footwear is 10 days from delivery, and your order (SK47731) was delivered on 5 November, so it is now outside that window. I can't approve exceptions myself, so I've passed your request to our support team, who will reply within one working day by email and in this chat. I can't promise the outcome.

- handover: handed over, but should answer

### g-109 · hard

**Q:** I paid ₹1,499 for an order with a ₹150 FIRSTKART coupon and want to return one item. Do I get the full price back?

**A** (handover=true): Refunds for a partial return are based on the price you actually paid for that item after discounts. If a coupon was used, its discount is shared across the items in proportion to their prices, so the refund for the returned item will be reduced by its share, not the full sticker price. Since I can't calculate the exact amount or approve refunds myself, I'm passing this to our support team, who will confirm the exact figure with you.

- handover: handed over, but should answer
- judge (follows_policy): The answer correctly explains that the coupon discount is shared proportionally and the refund is reduced by that share, matching the policy, but it does not explicitly say the coupon is recalculated and the difference deducted as the notes require, and it hands over to a human when the expected action is to answer directly.

### g-118 · hard

**Q:** The smartwatch SK48495 cost ₹4,999. Can the refund be approved automatically?

**A** (handover=true): Thanks for checking. Refunds are approved automatically only when the order is within policy, and I can't approve or promise a refund myself. Your order SK48495 was delivered on 16 November 2026, and the smartwatch is an electronics item with a 7-day window for faulty or unopened returns, so I'll pass this to our support team to review your request.

- handover: handed over, but should answer
- judge (follows_policy, answers_question): The answer correctly notes the 7-day electronics window and that refunds up to ₹5,000 are automatic only within policy, but it fails to state the must-say point clearly that refunds up to ₹5,000 are automatic if inside policy, and instead hands over without answering whether this refund would be automatic. It does not mention 30 days (good), but the handover framing and lack of the automatic-approval explanation for this amount leave the question partly unanswered.

### g-121 · hard

**Q:** SK48213 was delivered on the 13th and the watch screen is cracked. Am I still inside the return window?

**A** (handover=true): I'm sorry your Pulse Fit S2 arrived with a cracked screen. Electronics damaged on arrival can be reported within 7 days of delivery, and delivery was on 13 November 2026, so you are within the window. I'm passing this to our support team so they can raise a replacement or refund request with your photos; they will reply within 48 hours, and I can't promise the outcome. Please share a photo of the crack and the shipping label on the box.

- handover: handed over, but should answer
- judge (follows_policy): The answer correctly states the 7-day electronics window for damaged items and that delivery was 13 November, so the customer is within it, and it asks for the expected photos. It does not state 'delivered 4 days ago' explicitly, but the date is supported; it also hands over appropriately without promising an outcome, though the reference expects an 'answer' action rather than a handover, which is a minor mismatch.

### g-141 · must_handover

**Q:** This is my third refund request this month.

**A** (handover=true): I understand this is frustrating, and I'm passing your request to our support team so a colleague can review your refund requests with you. They will reply within one working day, by email and in this chat. Thank you for your patience.

- judge (follows_policy): The answer hands over to a human and promises no refund outcome, which matches the expected handover action. However, it does not mention the third-refund-in-30-days rule or that a support lead will review it, both of which the notes require.

New spend for this run: $0.027851 (cached answers cost $0).

### Reading the failures (error analysis)

Nine failures, grouped by the first thing that went wrong:

| Group | Cases | Layer |
| --- | --- | --- |
| Hands over when it should answer ("I'll pass this to our support team") | g-039, g-103, g-109, g-118, g-121 | prompt: the hand-over rule is too broad |
| Damaged-item answers skip the window or the refund/replacement options | g-065, g-068, g-071 | prompt |
| Hands over correctly but doesn't say why (third refund in 30 days) | g-141 | prompt (judge is strict here) |

Five of nine come from one cause, so the next prompt version starts there: hand over only for the triggers in the escalation policy, otherwise answer and offer the next step. Two cases also point at the eval itself:

- **g-103**: the golden notes say "offer to pass to the team for an exception", but `must_handover` is false. The code check fails the handover; the judge passes it. One of them is wrong, and a person decides which.
- **g-005 on OpenAI** (below): `must_not: "24 hours"` also forbids a true fact, gift card refunds in 24 hours (refunds policy, section 2). That's a test to fix, not a Copilot bug.

## OpenAI smoke run (3 cases)

```text
$ uv run python labs/evals/done/run_evals.py --provider openai --limit 3 --estimate --judge-cases 3
3 cases on gpt-6-luna, 0 already cached
  Copilot:   3 calls  ~$0.0028  (policies cached after the first call)
  Judge:     3 calls  ~$0.0029
  Total:            ~$0.0058   (no prompt caching at all: ~$0.0114)

$ uv run python labs/evals/done/run_evals.py --provider openai --limit 3
3 cases · openai gpt-6-luna · prompt v1

g-001  everyday      PASS  days:ok handover:ok must_not:ok amounts:-  ($0.00122)
g-005  everyday      FAIL  days:- handover:ok must_not:FAIL amounts:-  ($0.00015)
g-009  everyday      PASS  days:ok handover:ok must_not:- amounts:-  ($0.00015)

category       cases  code pass
everyday           3    2 (67%)
all                3    2 (67%)
failed checks: must_not 1

wrote labs/evals/out/openai/results.jsonl
this run: $0.001526 · 3 new calls, 0 from cache · today $0.032167
$ uv run python labs/evals/done/judge.py --provider openai --results labs/evals/out/openai/results.jsonl
judging 3 of 3 answers · openai gpt-6-luna · rubric j1

g-001  everyday      judge PASS 3/3  The answer gives the required general window of 14 days from delivery and accurately notes  ($0.00125)
g-005  everyday      judge FAIL 2/3  The answer gives the standard return-refund timing and original payment method, but adds e  ($0.00016)
g-009  everyday      judge PASS 3/3  The answer correctly states the 7-day window from delivery, once-per-order limit, and excl  ($0.00017)

judge: 2/3 pass (67%)
wrote judged.jsonl · this run: $0.001577 · 3 new calls, 0 from cache · today $0.033744
```

What differs on OpenAI:
- Prompt caching is automatic: no `cache_control`. The first call paid for 11,883 input tokens, the next two read 11,863 of them from the cache.
- The same policies are about 11,900 tokens on OpenAI against 18,161 on Claude: different tokenizers, so compare cost, not token counts.
- g-005 fails `must_not` on "24 hours": `gpt-6-luna` added the gift-card case, which is true. Same eval, different model, and a weak test shows up.

## Spend

| Provider | What | Cost |
| --- | --- | --- |
| Anthropic | 50 answers (3 + 47) | $0.014434 |
| Anthropic | judge on 50 | $0.016207 |
| Anthropic | re-run from cache | $0.000000 |
| **Anthropic total (this lab)** | | **$0.030641** |
| OpenAI | 3 answers + 3 judge calls | **$0.003103** |

The CI lab's live `act` run spent another $0.0095 on Anthropic (see `labs/evals-ci/RUN.md`), so both eval labs together: Anthropic $0.040, OpenAI $0.003.

