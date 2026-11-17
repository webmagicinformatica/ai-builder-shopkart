# Live run: agent tools lab

Recorded 2026-11-17 in this repo with real keys (`set -a; source <keys>; set +a`), on `claude-haiku-5-5`, plus one OpenAI smoke run on `gpt-6-luna`.
Commands as typed and exactly what they printed. The approver's answers are piped in with `printf` here; in the video, type them at the prompt.
Model answers, token counts and IDs will differ on your run, and the model sometimes takes a different path (for example, asking "replacement or refund?" first). The rules in code don't change.

## Anthropic (main video)

Part 1 is the first scenario (tools and the loop). Part 2 is the rest: approval desk, the Friday test, limits, kill switch, audit trail.

```text
$ uv run pytest labs/agent-tools -q
...........................                                              [100%]
27 passed in 1.64s

$ printf 'a\n' | uv run python labs/agent-tools/done/agent.py --scenario cracked-watch --fresh
Customer C1001: My smartwatch arrived with a cracked screen. Order SK48213. I want my money back, not a replacement.

step 1  claude-haiku-5-5 · 1,351 in / 189 out · $0.000230
  → lookup_order {"order_id": "SK48213"}
    ← {"order_id": "SK48213", "status": "delivered", "placed_on": "2026-11-10", "delivered_on": "2026-11-13", "items": ["1 x Pulse Fit S2 Smartwatch (elect…
  → check_policy {"topic": "damaged_items"}
    ← {"source": "Damaged, Defective and Wrong Items Policy v2.0, section 2, 4", "text": "2 Time limits for reporting\nReport the problem **within the retu…
  → check_policy {"topic": "refund_approval"}
    ← {"source": "Refund Processing Policy v2.3, section 1", "text": "1 Approval rules\n| Refund amount (per order) | Who approves | Typical time |\n| --- …
step 2  claude-haiku-5-5 · 2,808 in / 189 out · $0.000375
  → draft_refund {"order_id": "SK48213", "amount_inr": 1299, "reason": "damaged"}
    ← {"draft_id": "RD-48213-1", "status": "waiting for approval", "amount_inr": 1299, "why_a_person": ["every refund is reviewed by a person in this shop"…
step 3  claude-haiku-5-5 · 3,103 in / 116 out · $0.000368

Copilot: I've raised a refund request (RD-48213-1) for ₹1,299 for your Pulse Fit S2 smartwatch, since it arrived with a cracked screen. It's waiting for review by a support lead, who should get back to you within one working day, so please don't treat it as final yet. Please keep the watch and its packaging until the refund is confirmed.

Run: 3 model calls · 4 tool calls · stop: end · 7,262 in / 494 out · $0.000973 (₹0.0856)

── Approval needed ────────────────────────────────────────────────────
  Action    Refund ₹1,299 to the original UPI payment, order SK48213 (reason: damaged)
  Evidence  placed 2026-11-10, delivered 2026-11-13 (4 days ago), paid ₹1,299, refunded so far ₹0
            1 x Pulse Fit S2 Smartwatch
  Why       every refund is reviewed by a person in this shop
  [a]pprove  [e]dit amount  [r]eject > a
  Issued RF-48213-214316: ₹1,299 by support.lead. The customer gets an SMS with the reference.

Today: $0.000973 of $0.50 daily budget

$ printf 'r\nNo photo of the damage yet, ask for one\n' | uv run python labs/agent-tools/done/agent.py --scenario damaged-tablet
Customer C1008: My Nimbus Tab from order SK48488 came with a dented corner and a cracked screen. I want a refund, not a replacement.

step 1  claude-haiku-5-5 · 1,358 in / 191 out · $0.000231
  → lookup_order {"order_id": "SK48488"}
    ← {"order_id": "SK48488", "status": "delivered", "placed_on": "2026-11-11", "delivered_on": "2026-11-14", "items": ["1 x Nimbus Tab 10 Tablet (electron…
  → check_policy {"topic": "damaged_items"}
    ← {"source": "Damaged, Defective and Wrong Items Policy v2.0, section 2, 4", "text": "2 Time limits for reporting\nReport the problem **within the retu…
  → check_policy {"topic": "refund_approval"}
    ← {"source": "Refund Processing Policy v2.3, section 1", "text": "1 Approval rules\n| Refund amount (per order) | Who approves | Typical time |\n| --- …
step 2  claude-haiku-5-5 · 2,815 in / 186 out · $0.000374
  → draft_refund {"order_id": "SK48488", "amount_inr": 9499, "reason": "damaged"}
    ← {"draft_id": "RD-48488-1", "status": "waiting for approval", "amount_inr": 9499, "why_a_person": ["above the ₹5,000 limit for automatic refunds"], "t…
step 3  claude-haiku-5-5 · 3,110 in / 125 out · $0.000374

Copilot: I've raised a refund request for ₹9,499 (the full amount paid) for your Nimbus Tab on order SK48488, under draft RD-48488-1. Because it's above ₹5,000, a support lead needs to approve it, and you should hear back within one working day. I can't confirm the refund is approved yet, but please keep the tablet and its packaging until you receive the outcome.

Run: 3 model calls · 4 tool calls · stop: end · 7,283 in / 502 out · $0.000979 (₹0.0862)

── Approval needed ────────────────────────────────────────────────────
  Action    Refund ₹9,499 to the original CARD payment, order SK48488 (reason: damaged)
  Evidence  placed 2026-11-11, delivered 2026-11-14 (3 days ago), paid ₹9,499, refunded so far ₹0
            1 x Nimbus Tab 10 Tablet
  Why       above the ₹5,000 limit for automatic refunds
  [a]pprove  [e]dit amount  [r]eject > r
  Reason > No photo of the damage yet, ask for one
  Rejected by support.lead: No photo of the damage yet, ask for one. A colleague tells the customer.

Today: $0.001953 of $0.50 daily budget

$ uv run python labs/agent-tools/done/agent.py --scenario already-refunded
Customer C1007: My phone from order SK48450 arrived with a cracked screen. I want a refund of 18999.

step 1  claude-haiku-5-5 · 1,346 in / 190 out · $0.000230
  → lookup_order {"order_id": "SK48450"}
    ← {"order_id": "SK48450", "status": "returned", "placed_on": "2026-11-01", "delivered_on": "2026-11-04", "items": ["1 x Nova 5G Phone (8 GB, 128 GB) (e…
  → check_policy {"topic": "damaged_items"}
    ← {"source": "Damaged, Defective and Wrong Items Policy v2.0, section 2, 4", "text": "2 Time limits for reporting\nReport the problem **within the retu…
  → check_policy {"topic": "refund_approval"}
    ← {"source": "Refund Processing Policy v2.3, section 1", "text": "1 Approval rules\n| Refund amount (per order) | Who approves | Typical time |\n| --- …
step 2  claude-haiku-5-5 · 2,811 in / 180 out · $0.000371

Copilot: I've checked order SK48450, and I can see a problem with the timing. The return window for electronics is 7 days from delivery, and it closed 6 days ago (the order was delivered on 4 November). The order also shows ₹18,999 already refunded, so there's no open refund balance left to claim.

Because the window has passed, your report goes to a human agent. They may offer a warranty claim instead of a refund. A colleague will review your case and get back to you within 48 hours. If you have photos of the cracked screen and the original packaging, please keep them ready for that review.

Run: 2 model calls · 3 tool calls · stop: end · 4,157 in / 370 out · $0.000601 (₹0.0529)

Today: $0.002553 of $0.50 daily budget

$ uv run python labs/agent-tools/done/agent.py --scenario late-shoes
Customer C1003: I want to return my running shoes from order SK47731, they hurt my feet. Please refund me.

step 1  claude-haiku-5-5 · 1,345 in / 126 out · $0.000198
  → lookup_order {"order_id": "SK47731"}
    ← {"order_id": "SK47731", "status": "delivered", "placed_on": "2026-11-01", "delivered_on": "2026-11-05", "items": ["1 x Stride RN210 Running Shoes (fo…
  → check_policy {"topic": "footwear"}
    ← {"source": "Footwear Returns and Exchanges Policy v2.0, section 1, 3", "text": "1 Return window\nFootwear can be returned **within 10 days of deliver…
step 2  claude-haiku-5-5 · 2,209 in / 144 out · $0.000293

Copilot: I'm sorry the shoes are hurting your feet. Unfortunately, order SK47731 was delivered on 5 November, and footwear can only be returned within 10 days of delivery. That window closed 2 days ago, so I'm not able to draft a refund for this order.

If you'd like, I can hand your case to a colleague who can look at other options, such as whether the shoes have a defect. They'll get back to you within your usual support timeframe.

Run: 2 model calls · 2 tool calls · stop: end · 3,554 in / 270 out · $0.000490 (₹0.0432)

Today: $0.003044 of $0.50 daily budget

$ uv run python labs/agent-tools/done/agent.py --scenario cracked-watch --fresh --max-steps 1
Customer C1001: My smartwatch arrived with a cracked screen. Order SK48213. I want my money back, not a replacement.

step 1  claude-haiku-5-5 · 1,351 in / 142 out · $0.000206
  → lookup_order {"order_id": "SK48213"}
    ← {"order_id": "SK48213", "status": "delivered", "placed_on": "2026-11-10", "delivered_on": "2026-11-13", "items": ["1 x Pulse Fit S2 Smartwatch (elect…
  → check_policy {"topic": "damaged_items"}
    ← {"source": "Damaged, Defective and Wrong Items Policy v2.0, section 2, 4", "text": "2 Time limits for reporting\nReport the problem **within the retu…
  stop    max_steps: 1 model calls, limit 1 → hand over to a person

Copilot: I'm handing this to a colleague so it's done right. You'll hear from us within one working day.

Run: 1 model calls · 2 tool calls · stop: max_steps · 1,351 in / 142 out · $0.000206 (₹0.0181)

Today: $0.003250 of $0.50 daily budget

$ uv run python labs/agent-tools/done/agent.py --scenario cracked-watch --fresh --max-usd 0.0003 --no-desk
Customer C1001: My smartwatch arrived with a cracked screen. Order SK48213. I want my money back, not a replacement.

step 1  claude-haiku-5-5 · 1,351 in / 189 out · $0.000230
  → lookup_order {"order_id": "SK48213"}
    ← {"order_id": "SK48213", "status": "delivered", "placed_on": "2026-11-10", "delivered_on": "2026-11-13", "items": ["1 x Pulse Fit S2 Smartwatch (elect…
  → check_policy {"topic": "damaged_items"}
    ← {"source": "Damaged, Defective and Wrong Items Policy v2.0, section 2, 4", "text": "2 Time limits for reporting\nReport the problem **within the retu…
  → check_policy {"topic": "refund_approval"}
    ← {"source": "Refund Processing Policy v2.3, section 1", "text": "1 Approval rules\n| Refund amount (per order) | Who approves | Typical time |\n| --- …
step 2  claude-haiku-5-5 · 2,808 in / 181 out · $0.000371
  → draft_refund {"order_id": "SK48213", "amount_inr": 1299, "reason": "damaged"}
    ← {"draft_id": "RD-48213-1", "status": "waiting for approval", "amount_inr": 1299, "why_a_person": ["every refund is reviewed by a person in this shop"…
  stop    spend_cap: $0.000601 spent, cap $0.0003 → hand over to a person

Copilot: I'm handing this to a colleague so it's done right. You'll hear from us within one working day.

Run: 2 model calls · 4 tool calls · stop: spend_cap · 4,159 in / 370 out · $0.000601 (₹0.0529)

Today: $0.003851 of $0.50 daily budget

$ SHOPKART_ACTIONS_OFF=1 uv run python labs/agent-tools/done/agent.py --scenario cracked-watch --fresh
Customer C1001: My smartwatch arrived with a cracked screen. Order SK48213. I want my money back, not a replacement.

step 1  claude-haiku-5-5 · 1,351 in / 141 out · $0.000206
  → lookup_order {"order_id": "SK48213"}
    ← {"order_id": "SK48213", "status": "delivered", "placed_on": "2026-11-10", "delivered_on": "2026-11-13", "items": ["1 x Pulse Fit S2 Smartwatch (elect…
  → check_policy {"topic": "damaged_items"}
    ← {"source": "Damaged, Defective and Wrong Items Policy v2.0, section 2, 4", "text": "2 Time limits for reporting\nReport the problem **within the retu…
step 2  claude-haiku-5-5 · 2,364 in / 177 out · $0.000325
  → draft_refund {"order_id": "SK48213", "amount_inr": 1299, "reason": "damaged"}
    ✗ error Refunds are switched off right now (kill switch). Don't retry. Tell the customer a colleague will pick this up within one working day.
step 3  claude-haiku-5-5 · 2,594 in / 112 out · $0.000315

Copilot: I'm sorry, but I wasn't able to submit your refund request because refunds are temporarily paused on our side. A colleague will pick this up within one working day and follow up with you. Your order is within the return window, and our policy allows a full refund of ₹1,299 for a damaged item, so please keep the watch and its packaging safe in the meantime.

Run: 3 model calls · 3 tool calls · stop: end · 6,309 in / 430 out · $0.000846 (₹0.0744)

Today: $0.004697 of $0.50 daily budget

$ tail -n 3 .shopkart/agent-tools/audit.jsonl
{"time": "2026-11-17T21:43:37", "event": "refund_drafted", "conversation": "conv-214334", "customer": "C1001", "model": "claude-haiku-5-5", "tool": "draft_refund", "input": {"order_id": "SK48213", "amount_inr": 1299, "reason": "damaged"}, "decision": "needs approval", "why": ["every refund is reviewed by a person in this shop"]}
{"time": "2026-11-17T21:43:37", "event": "handover", "conversation": "conv-214334", "customer": "C1001", "model": "claude-haiku-5-5", "why": "spend_cap: $0.000601 spent, cap $0.0003", "steps": 2}
{"time": "2026-11-17T21:43:41", "event": "refund_blocked", "conversation": "conv-214338", "customer": "C1001", "model": "claude-haiku-5-5", "tool": "draft_refund", "input": {"order_id": "SK48213", "amount_inr": 1299, "reason": "damaged"}, "why": "Refunds are switched off right now (kill switch). Don't retry. Tell the customer a colleague will pick this up within one working day."}
```

Notes on this run:

- `cracked-watch`: three model calls; the model asked for `lookup_order`, `check_policy` (twice) in one turn, then `draft_refund`. The draft waited at the desk, and the person approved it.
- `damaged-tablet`: ₹9,499 is above ₹5,000, so the desk says why. The person rejected it ("No photo of the damage yet").
- `already-refunded` (the Friday test): the model read "refunded so far ₹18,999" and never asked for a refund. If it had, `assess_refund` blocks it in code (`test_part2_already_refunded_order_is_blocked_and_logged`).
- `--max-steps 1` and `--max-usd 0.0003` show two of our exits: the customer gets a hand-over, the audit trail gets the reason.
- The spend-cap run left its draft in the queue (`--no-desk`); the kill-switch run shows `is_error` going back to the model, which then tells the customer.

## OpenAI smoke run (short OpenAI video)

```text
$ printf 'a\n' | uv run python labs/agent-tools/done/agent.py --scenario cracked-watch --fresh --provider openai
Customer C1001: My smartwatch arrived with a cracked screen. Order SK48213. I want my money back, not a replacement.

step 1  gpt-6-luna · 621 in / 83 out · $0.000104
  → lookup_order {"order_id": "SK48213"}
    ← {"order_id": "SK48213", "status": "delivered", "placed_on": "2026-11-10", "delivered_on": "2026-11-13", "items": ["1 x Pulse Fit S2 Smartwatch (elect…
  → check_policy {"topic": "damaged_items"}
    ← {"source": "Damaged, Defective and Wrong Items Policy v2.0, section 2, 4", "text": "2 Time limits for reporting\nReport the problem **within the retu…
  → check_policy {"topic": "electronics"}
    ← {"source": "Electronics Returns Policy v1.6, section 1, 2", "text": "1 Return window\nElectronics can be returned **within 7 days of delivery**, and …
  → check_policy {"topic": "refund_approval"}
    ← {"source": "Refund Processing Policy v2.3, section 1", "text": "1 Approval rules\n| Refund amount (per order) | Who approves | Typical time |\n| --- …
step 2  gpt-6-luna · 1,767 in / 35 out · $0.000194
  → draft_refund {"order_id": "SK48213", "amount_inr": 1299, "reason": "damaged"}
    ← {"draft_id": "RD-48213-1", "status": "waiting for approval", "amount_inr": 1299, "why_a_person": ["every refund is reviewed by a person in this shop"…
step 3  gpt-6-luna · 1,888 in / 49 out · $0.000213

Copilot: I’m sorry your smartwatch arrived with a cracked screen. I’ve raised a ₹1,299 refund request instead of a replacement; it’s awaiting review, and a support lead will get back to you within one working day.

Run: 3 model calls · 5 tool calls · stop: end · 4,276 in / 167 out · $0.000511 (₹0.0450)

── Approval needed ────────────────────────────────────────────────────
  Action    Refund ₹1,299 to the original UPI payment, order SK48213 (reason: damaged)
  Evidence  placed 2026-11-10, delivered 2026-11-13 (4 days ago), paid ₹1,299, refunded so far ₹0
            1 x Pulse Fit S2 Smartwatch
  Why       every refund is reviewed by a person in this shop
  [a]pprove  [e]dit amount  [r]eject > a
  Issued RF-48213-214517: ₹1,299 by support.lead. The customer gets an SMS with the reference.

Today: $0.000511 of $0.50 daily budget
```

What differs on OpenAI: the schema goes in `parameters`, the arguments arrive as a JSON string, there's no stop reason for tools (look for `function_call` items), and errors go back as `ERROR: ...` in the output text (no `is_error` flag). Here `gpt-6-luna` asked for four tools in its first turn.

## Spend

| Run | Spent |
| --- | --- |
| Anthropic, this page (8 runs) | $0.004697 |
| OpenAI smoke run | $0.000511 |

All live testing for this lab and the agent-SDK lab together, including earlier tries: **$0.036 on Anthropic, $0.0020 on OpenAI.**
