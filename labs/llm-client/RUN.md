# Live run: LLM client lab

Recorded 2026-11-17 in this repo with real keys (`set -a; source <keys>; set +a`), on `claude-haiku-5-5`, plus one small OpenAI smoke run on `gpt-6-luna`.
Commands as typed and exactly what they printed. Model answers and wait times (jitter is random) will differ on your run.

## Anthropic (main video)

```text
$ uv run python -m shopkart.llm "When will my order arrive?"
I'm sorry, I don't have access to your order details, so I can't say when it will arrive. Please share your order number, or check the tracking link in your confirmation email for the latest delivery estimate.

claude-haiku-5-5 · 67 in / 63 out · $0.000038 (₹0.0034) · 1.14s
Today: $0.000038 of $0.50 daily budget

$ uv run python -m shopkart.llm "What is your return window for shoes?" --stream
Footwear can be returned within 10 days of delivery. Let me know if you'd like help starting a return.

claude-haiku-5-5 · 69 in / 35 out · $0.000024 (₹0.0021) · 0.94s (first token 0.69s)
Today: $0.000063 of $0.50 daily budget

$ uv run python labs/llm-client/done/triage.py
 #  intent         order    urgency summary
 1  where_is_order SK48213  high    Customer says order SK48213 has not arrived and it is a gift needed for a wedding this Saturday.
 2  where_is_order SK51027  high    Customer asks when order SK51027 will arrive; it is needed for a wedding on Saturday.
 3  where_is_order -        normal  Customer asks where their parcel is; no order number provided.
 4  refund         SK40518  normal  Customer wants to return running shoes from order SK40518 because they are too small.
 5  refund         SK47302  normal  Customer received headphones in order SK47302 with a cracked case and wants a refund.
 6  cancel         SK49911  normal  Customer wants to cancel order SK49911 because they ordered the wrong colour by mistake.
 7  product        -        normal  Customer asks whether the Prestige pressure cooker is compatible with induction stoves.
 8  refund         SK45120  normal  Customer asks for the refund status of order SK45120; the return pickup was completed last week.
 9  refund         SK48876  high    Customer was charged twice for order SK48876 and requests a fix today due to an urgent rent payment.
10  other          -        low     Customer asks what time ShopKart delivers in Pune.
11  other          SK50233  normal  Customer wants to change the delivery address for order SK50233 to their office.
12  cancel         SK46655  normal  Customer wants to cancel order SK46655, which has not yet been shipped.
13  product        -        low     Customer asks whether the Samsung 55 inch TV is available with a wall mount.
14  where_is_order SK43390  high    Customer says order SK43390 is marked delivered but they never received it and no one came to their door.
15  refund         -        low     Customer asks how many days they have to return a kurta.
16  other          SK44781  high    Customer received wrong size jeans in order SK44781 and needs a replacement before Diwali.
17  product        -        low     Customer is asking whether ShopKart sells gift cards.
18  refund         SK42019  high    Customer reports Rs 7,200 refund for order SK42019 has not arrived in their account after 10 days.
19  cancel         SK48213  normal  Customer requests cancellation of order SK48213.
20  refund         SK41876  normal  Customer's blender from order SK41876 stopped working after two days and they are requesting a refund.

20 classified, 0 need review, 0 crashes · claude-haiku-5-5 · $0.001650 (₹0.1452)

$ uv run python labs/llm-client/demo_errors.py

=== 1. A model that doesn't exist ===============================
  [ERROR] stop: 404 not_found, not retrying (attempt 1), request req_011Ch9CZED1DuscdwccTeK2d
Stopped: 404 not_found: model: no-such-model-2026 (request req_011Ch9CZED1DuscdwccTeK2d)
         attempts=1 retryable=False

=== 2. A 0.01 second timeout, with a fallback ===================
  [WARNING] retry 1/2: timeout, waiting 1.1s (backoff+jitter)
  [WARNING] retry 2/2: timeout, waiting 2.2s (backoff+jitter)
  [ERROR] give up: timeout after 3 attempts
  [WARNING] fallback: claude-haiku-5-5 failed (timeout), trying anthropic claude-haiku-5-5
Answer: A ShopKart customer has 14 days to return a kurta.
        claude-haiku-5-5 · 63 in / 22 out · $0.000017 (₹0.0015) · 0.82s

=== 3. Fake 429, then fake overloaded, then the real API ========
  [WARNING] retry 1/3: 429 rate_limit, waiting 0.8s (backoff+jitter)
  [WARNING] retry 2/3: 529 overloaded, waiting 2.4s (backoff+jitter)
Answer: A ShopKart customer has 14 days to return a kurta.
        claude-haiku-5-5 · 63 in / 22 out · $0.000017 (₹0.0015) · 4.07s · 3 attempts

=== 4. Fake spending limit ======================================
  [ERROR] stop: 400 spend_limit (invalid_request_error), not retrying (attempt 1), request req_fake_spend_limit
Stopped: 400 spend_limit (invalid_request_error): You have reached your specified workspace API usage limits. (request req_fake_spend_limit)
         attempts=1 retryable=False

$ uv run pytest -q
.....................................................                    [100%]
53 passed in 1.90s
```

## OpenAI smoke run (short OpenAI video)

```text
$ uv run python -m shopkart.llm "What is your return window for shoes?" --stream --provider openai
Shoes can be returned within 10 days of purchase.

gpt-6-luna · 51 in / 16 out · $0.000013 (₹0.0012) · 1.65s (first token 0.91s)
Today: $0.001760 of $0.50 daily budget

$ uv run python labs/llm-client/done/triage.py --provider openai --limit 3
 #  intent         order    urgency summary
 1  where_is_order SK48213  high    Customer's order has not arrived and is needed as a wedding gift by Saturday.
 2  where_is_order SK51027  high    The customer needs the delivery date for order SK51027 before a wedding on Saturday.
 3  where_is_order -        normal  Customer asks for the location of their parcel.

3 classified, 0 need review, 0 crashes · gpt-6-luna · $0.000123 (₹0.0108)
```

What differs on OpenAI: the schema goes in `text.format` (strict JSON schema) instead of `output_config.format`, the system prompt goes in `instructions`, streaming events are `response.output_text.delta`, and its spend limit is a **429** with code `insufficient_quota` / `project_spend_limit_exceeded` (Anthropic: 400 at a workspace limit). A bad model name is a 404 on Anthropic.

## The cost log

```text
$ head -1 .shopkart/calls.csv; tail -4 .shopkart/calls.csv
time,provider,model,input_tokens,output_tokens,cost_usd,cost_inr,latency_s,attempts,outcome
2026-11-17T21:20:36,anthropic,claude-haiku-5-5,534,63,0.000085,0.0075,1.50,1,ok
2026-11-17T21:20:42,anthropic,claude-haiku-5-5,63,22,0.000017,0.0015,0.82,1,ok
2026-11-17T21:20:46,anthropic,claude-haiku-5-5,63,22,0.000017,0.0015,4.07,3,ok
2026-11-17T21:20:52,openai,gpt-6-luna,51,16,0.000013,0.0012,1.65,1,ok
```

Row 3 is the injected-429 scene: 3 attempts, 4.07 s, one paid call.

## Total live spend for this lab

| Provider | Calls | Spend |
| --- | --- | --- |
| Anthropic (`claude-haiku-5-5`) | 56, incl. development tries | $0.0039 (₹0.35) |
| OpenAI (`gpt-6-luna`) | 5 | $0.00015 (₹0.013) |

Limits for this lab: $0.05 Anthropic, $0.02 OpenAI. Failed attempts (404, timeouts, injected errors) cost nothing here: no tokens were billed.
