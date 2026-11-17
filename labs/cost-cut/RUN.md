# Live run: cost lab

Recorded 2026-11-17 in this repo with real keys (`set -a; source <keys>; set +a`): the main run on Anthropic (`claude-sonnet-5-5` large, `claude-haiku-5-5` small, the first 20 questions of `data/workload.jsonl`), plus one small OpenAI smoke run (`gpt-6.2-sol` large, `gpt-6-luna` small, 5 questions).
Commands as typed and exactly what they printed. Answers, output tokens and times will differ a little on your run.
Every step saves its run in `.shopkart/cost-cut/`; running the same step again replays it for $0 (add `--fresh` to call the API again).

The "in" column counts uncached input tokens. In steps 3 and 4 it includes the router's call (about 400 tokens on the small model).

## Anthropic (main video)

```text
$ uv run python labs/cost-cut/done/cost_cut.py baseline
1. baseline (large model) · anthropic · 20 questions
  # q    path        in  write   read  out     cost $  question
  1 easy sonnet    2155      0      0  177   0.006080  how long can i return stuff
  2 hard sonnet    2175      0      0  102   0.005370  I'm ordering shoes for ₹799 to Kochi. Is del
  3 hard sonnet    2165      0      0  171   0.006040  cancelled 10 days back, refund nahi aaya
  4 hard sonnet    2157      0      0  127   0.005584  opened earbuds return possible?
  5 easy sonnet    2151      0      0   55   0.004852  when is support open
  6 easy sonnet    2157      0      0   59   0.004904  How do I change my delivery address?
  7 easy sonnet    2156      0      0  111   0.005422  How do I cancel my order?
  8 easy sonnet    2155      0      0  106   0.005370  How long does a refund take?
  9 easy sonnet    2157      0      0   55   0.004864  How do I change my delivery address?
 10 easy sonnet    2156      0      0  186   0.006172  What is the delivery charge?
 11 easy sonnet    2154      0      0  111   0.005418  track order kaise karu
 12 hard sonnet    2175      0      0  138   0.005730  I opened my laptop and the screen is cracked
 13 hard sonnet    2160      0      0  149   0.005810  Can I return headphones I've already opened?
 14 easy sonnet    2159      0      0   43   0.004748  What is the minimum order for EMI?
 15 easy sonnet    2153      0      0   66   0.004966  shoes return days?
 16 easy sonnet    2154      0      0  137   0.005678  when will i get my refund
 17 hard sonnet    2165      0      0  148   0.005810  cancelled 10 days back, refund nahi aaya
 18 easy sonnet    2158      0      0  149   0.005806  How many days do I have to return a product?
 19 easy sonnet    2154      0      0   59   0.004898  How do I track my order?
 20 easy sonnet    2157      0      0   61   0.004924  How do I change my delivery address?

baseline: 20 answered (20 sonnet) · 20 API calls · $0.108446 (₹9.5432) · 35.4s
tokens: 43173 input, 0 cache write, 0 cache read, 2210 output
Today: $0.108596 of $0.50 daily budget

$ uv run python labs/cost-cut/done/cost_cut.py cache
2. + prompt caching · anthropic · 20 questions
  # q    path        in  write   read  out     cost $  question
  1 easy sonnet      14   2141      0  154   0.006920  how long can i return stuff
  2 hard sonnet      34      0   2141   83   0.001112  I'm ordering shoes for ₹799 to Kochi. Is del
  3 hard sonnet      24      0   2141  144   0.001702  cancelled 10 days back, refund nahi aaya
  4 hard sonnet      16      0   2141  144   0.001686  opened earbuds return possible?
  5 easy sonnet      10      0   2141   55   0.000784  when is support open
  6 easy sonnet      16      0   2141   58   0.000826  How do I change my delivery address?
  7 easy sonnet      15      0   2141  106   0.001304  How do I cancel my order?
  8 easy sonnet      14      0   2141  165   0.001892  How long does a refund take?
  9 easy sonnet      16      0   2141   55   0.000796  How do I change my delivery address?
 10 easy sonnet      15      0   2141  164   0.001884  What is the delivery charge?
 11 easy sonnet      13      0   2141  100   0.001240  track order kaise karu
 12 hard sonnet      34      0   2141  187   0.002152  I opened my laptop and the screen is cracked
 13 hard sonnet      19      0   2141  149   0.001742  Can I return headphones I've already opened?
 14 easy sonnet      18      0   2141   43   0.000680  What is the minimum order for EMI?
 15 easy sonnet      12      0   2141   71   0.000948  shoes return days?
 16 easy sonnet      13      0   2141  168   0.001920  when will i get my refund
 17 hard sonnet      24      0   2141  135   0.001612  cancelled 10 days back, refund nahi aaya
 18 easy sonnet      17      0   2141  119   0.001438  How many days do I have to return a product?
 19 easy sonnet      13      0   2141   62   0.000860  How do I track my order?
 20 easy sonnet      16      0   2141   59   0.000836  How do I change my delivery address?

cache: 20 answered (20 sonnet) · 20 API calls · $0.032336 (₹2.8456) · 36.2s
tokens: 353 input, 2141 cache write, 40679 cache read, 2221 output
Today: $0.140932 of $0.50 daily budget

$ uv run python labs/cost-cut/done/cost_cut.py route
3. + routing easy -> small · anthropic · 20 questions
  # q    path        in  write   read  out     cost $  question
  1 easy haiku      414   2141      0   95   0.000357  how long can i return stuff
  2 hard haiku      454      0   2141  115   0.000124  I'm ordering shoes for ₹799 to Kochi. Is del
  3 hard sonnet     434      0   2141  134   0.001548  cancelled 10 days back, refund nahi aaya
  4 hard sonnet     418      0   2141  161   0.001801  opened earbuds return possible?
  5 easy haiku      406      0   2141   64   0.000094  when is support open
  6 easy haiku      418      0   2141   78   0.000102  How do I change my delivery address?
  7 easy haiku      416      0   2141   87   0.000107  How do I cancel my order?
  8 easy haiku      414      0   2141   98   0.000112  How long does a refund take?
  9 easy haiku      418      0   2141   78   0.000102  How do I change my delivery address?
 10 easy haiku      416      0   2141  170   0.000148  What is the delivery charge?
 11 easy haiku      412      0   2141  113   0.000119  track order kaise karu
 12 hard sonnet     454      0   2141  182   0.002049  I opened my laptop and the screen is cracked
 13 hard sonnet     424      0   2141  150   0.001698  Can I return headphones I've already opened?
 14 easy haiku      422      0   2141   53   0.000090  What is the minimum order for EMI?
 15 easy haiku      410      0   2141   63   0.000094  shoes return days?
 16 easy sonnet     412      0   2141  179   0.001975  when will i get my refund
 17 hard sonnet     434      0   2141  168   0.001888  cancelled 10 days back, refund nahi aaya
 18 easy haiku      420      0   2141   99   0.000113  How many days do I have to return a product?
 19 easy haiku      412      0   2141   75   0.000100  How do I track my order?
 20 easy haiku      418      0   2141   79   0.000103  How do I change my delivery address?

route: 20 answered (14 haiku, 6 sonnet) · 40 API calls · $0.012724 (₹1.1197) · 52.5s
tokens: 8426 input, 2141 cache write, 40679 cache read, 2241 output
Today: $0.153656 of $0.50 daily budget

$ uv run python labs/cost-cut/done/cost_cut.py final
4. + local response cache · anthropic · 20 questions
  # q    path        in  write   read  out     cost $  question
  1 easy haiku      414      0   2141   91   0.000108  how long can i return stuff
  2 hard haiku      454      0   2141  100   0.000117  I'm ordering shoes for ₹799 to Kochi. Is del
  3 hard sonnet     434      0   2141  146   0.001668  cancelled 10 days back, refund nahi aaya
  4 hard sonnet     418      0   2141  145   0.001641  opened earbuds return possible?
  5 easy haiku      406      0   2141   65   0.000095  when is support open
  6 easy haiku      418      0   2141   78   0.000102  How do I change my delivery address?
  7 easy haiku      416      0   2141   85   0.000106  How do I cancel my order?
  8 easy haiku      414      0   2141  142   0.000134  How long does a refund take?
  9 easy cache        0      0      0    0   0.000000  How do I change my delivery address?
 10 easy haiku      416      0   2141  129   0.000128  What is the delivery charge?
 11 easy haiku      412      0   2141  114   0.000120  track order kaise karu
 12 hard sonnet     454      0   2141  141   0.001639  I opened my laptop and the screen is cracked
 13 hard sonnet     424      0   2141  165   0.001848  Can I return headphones I've already opened?
 14 easy haiku      422      0   2141   53   0.000090  What is the minimum order for EMI?
 15 easy haiku      410      0   2141   66   0.000095  shoes return days?
 16 easy sonnet     412      0   2141  127   0.001455  when will i get my refund
 17 hard cache        0      0      0    0   0.000000  cancelled 10 days back, refund nahi aaya
 18 easy haiku      420      0   2141  106   0.000116  How many days do I have to return a product?
 19 easy haiku      412      0   2141   77   0.000101  How do I track my order?
 20 easy cache        0      0      0    0   0.000000  How do I change my delivery address?

final: 20 answered (12 haiku, 5 sonnet, 3 cache) · 34 API calls · $0.009562 (₹0.8415) · 42.5s
tokens: 7156 input, 0 cache write, 36397 cache read, 1830 output
Today: $0.163218 of $0.50 daily budget

$ uv run python labs/cost-cut/done/cost_cut.py table
Before/after · anthropic · 20 questions (large claude-sonnet-5-5, small claude-haiku-5-5)

step                        calls   input c.write  c.read output    cost $  cost ₹   time  cheaper  facts ok
1. baseline (large model)      20   43173       0       0   2210   0.10845   9.543  35.4s       0%     20/20
2. + prompt caching            20     353    2141   40679   2221   0.03234   2.846  36.2s      70%     20/20
3. + routing easy -> small     40    8426    2141   40679   2241   0.01272   1.120  52.5s      88%     20/20
4. + local response cache      34    7156       0   36397   1830   0.00956   0.841  42.5s      91%     20/20

Target: at least 50% cheaper. Result: 91% cheaper -> target met.
Quality: 0 answer(s) lost a key fact compared with the baseline.

Batch API (not run here): the same calls at half price, about $0.00478, with results within 24 hours.
Good for nightly jobs nobody waits for; never for a customer in the chat.

$ uv run python labs/cost-cut/done/cost_cut.py spot
w-001 [easy] how long can i return stuff
   ok  sonnet  It depends on the item, and the days count from the delivery date. Most products can be returned within 14 days (this includes laptop bags, phone case
   ok  haiku   The return window depends on the item: most products can be returned within 14 days of delivery, footwear within 10 days, and electronics within 7 day

w-002 [hard] I'm ordering shoes for ₹799 to Kochi. Is delivery free?
   ok  sonnet  No, it won't be free. Kochi counts as an "other city," so a ₹799 order pays a ₹49 delivery charge (free delivery in other cities starts at ₹2,999). St
   ok  haiku   No, delivery is not free for a ₹799 order to Kochi. Kochi is an "other city," and orders below ₹2,999 are charged ₹49 there, so you'd pay ₹49 for deli

w-003 [hard] cancelled 10 days back, refund nahi aaya
   ok  sonnet  Aapka cancelled prepaid order ka refund 5–7 working days mein aana chahiye tha, aur 10 calendar days usually 7 working days hi hote hain, toh ab Help 
   ok  sonnet  10 din matlab roughly 7 working days ho gaye hain, isliye ab ticket raise kar sakte hain. Help → Refunds mein ticket banaiye aur UPI reference number 

w-004 [hard] opened earbuds return possible?
   ok  sonnet  Opened earbuds can be returned only if they're faulty (for example no sound, one side not working, case not charging, or Bluetooth not pairing after a
   ok  sonnet  Opened earbuds can be returned only if they're faulty (for example no sound, one side not working, case not charging, or Bluetooth not pairing after a

w-005 [easy] when is support open
   ok  sonnet  Our support team is available from 9 am to 9 pm IST, Monday to Saturday. You can also call us toll-free on 1800-120-7575 during these hours.
   ok  haiku   Our support team is available 9 am to 9 pm IST, Monday to Saturday. You can also call our toll-free number, 1800-120-7575, during those hours.

w-006 [easy] How do I change my delivery address?
   ok  sonnet  You can change the address once, before dispatch, in My Orders → Change address. If your order has already been dispatched, let me know and a colleagu
   ok  haiku   You can change your delivery address once, as long as the order hasn't been dispatched yet: go to My Orders → Change address. If the order has already

w-007 [easy] How do I cancel my order?
   ok  sonnet  Go to My Orders → Cancel. It's free, and it works until the order status changes to Shipped. After it ships, it can't be cancelled, but you can refuse
   ok  haiku   You can cancel for free in My Orders → Cancel, as long as the order status is still before "Shipped." Once it has shipped, cancellation isn't possible

w-008 [easy] How long does a refund take?
   ok  sonnet  Refunds go to your original payment method (UPI, card or net banking) within 5-7 working days of pickup. For gift card payments, it's back to the gift
   ok  haiku   Refunds go back to your original payment method within 5–7 working days of pickup (UPI, card or net banking). For cash on delivery, add your bank acco

w-009 [easy] How do I change my delivery address?
   ok  sonnet  You can change your address once, before dispatch, in My Orders → Change address. If your order has already been dispatched, a colleague from the supp
   ok  cache   You can change your delivery address once, as long as the order hasn't been dispatched yet: go to My Orders → Change address. If the order has already

w-010 [easy] What is the delivery charge?
   ok  sonnet  It depends on your order value and city. Orders of ₹2,999 and above get free delivery everywhere. For ₹499 and above, delivery is free in metro cities
   ok  haiku   The delivery charge depends on your order value and city. Orders of ₹2,999 and above are free everywhere; orders of ₹499 and above are free in metro c

w-011 [easy] track order kaise karu
   ok  sonnet  Order track karne ke liye My Orders mein jaakar apna order chuniye, ya dispatch par bheje gaye SMS ke link par click kijiye. Pehla scan aane mein 24 g
   ok  haiku   Aap My Orders mein jaakar apna order select kar sakte hain, wahan tracking number dikhega. Aap dispatch ke baad aaye SMS mein diye link se bhi track k

w-012 [hard] I opened my laptop and the screen is cracked. Can I return it even though it's opened?
   ok  sonnet  If the screen was already cracked when it arrived, it counts as a damaged item, so you can return or replace it even though it's opened, within 7 days
   ok  sonnet  If the screen was already cracked when it arrived, that counts as a damaged item, so it can be returned or replaced within 7 days of delivery even tho

w-013 [hard] Can I return headphones I've already opened?
   ok  sonnet  Opened headphones can be returned only if they're faulty (for example no sound, sound on one side only, or Bluetooth not pairing even after a reset). 
   ok  sonnet  Opened headphones can only be returned if they're faulty (for example no sound, one side not working, or Bluetooth not pairing even after a reset), an

w-014 [easy] What is the minimum order for EMI?
   ok  sonnet  Card EMI is available on orders of ₹3,000 and above, with tenures of 3, 6, 9 or 12 months.
   ok  haiku   Card EMI is available on orders of ₹3,000 and above, with tenures of 3, 6, 9 or 12 months.

w-015 [easy] shoes return days?
   ok  sonnet  Footwear can be returned within 10 days of delivery (counted from the delivery date). The shoes must be unworn outdoors and in the original box. To re
   ok  haiku   Footwear can be returned within 10 days of delivery, if unworn outdoors and in the original box. To start a return, go to My Orders, choose the item a

w-016 [easy] when will i get my refund
   ok  sonnet  Refunds go to your original payment method within 5–7 working days of the pickup (UPI, card and net banking). If you paid with a gift card, it goes ba
   ok  sonnet  Refunds go to your original payment method within 5-7 working days of pickup (UPI, card or net banking). For gift card payments it's within 24 hours, 

w-017 [hard] cancelled 10 days back, refund nahi aaya
   ok  sonnet  10 din matlab usually 7 working days ho chuke hain, toh ab Help → Refunds mein ticket raise kar sakte hain. Ticket mein UPI reference number (UTR) ya 
   ok  cache   10 din matlab roughly 7 working days ho gaye hain, isliye ab ticket raise kar sakte hain. Help → Refunds mein ticket banaiye aur UPI reference number 

w-018 [easy] How many days do I have to return a product?
   ok  sonnet  Most products can be returned within 14 days of delivery (counted from the delivery date, not the order date), if unused and in original packaging. So
   ok  haiku   Most products can be returned within 14 days of delivery, counted from the delivery date. Some categories have shorter windows: footwear 10 days, elec

w-019 [easy] How do I track my order?
   ok  sonnet  You can track your order in **My Orders** or by using the **SMS link** you received at dispatch. If you've just received the tracking number, the firs
   ok  haiku   Every order gets a tracking number once it's dispatched. You can track it in **My Orders** or through the link in your dispatch SMS. The first scan ca

w-020 [easy] How do I change my delivery address?
   ok  sonnet  You can change your address once, before your order is dispatched, in My Orders → Change address. If the order has already been dispatched, a colleagu
   ok  cache   You can change your delivery address once, as long as the order hasn't been dispatched yet: go to My Orders → Change address. If the order has already

```

## OpenAI (short separate video)

Only `baseline` and `final` (final = steps 2 to 4 together), on 5 questions, to stay inside the OpenAI test budget. There is no `cache` step to run on OpenAI: it caches prompts of 1,024+ tokens by itself, and `cache_system` changes nothing there.

```text
$ uv run python labs/cost-cut/done/cost_cut.py baseline --provider openai --limit 5
1. baseline (large model) · openai · 5 questions
  # q    path        in  write   read  out     cost $  question
  1 easy sol       1417      0      0  112   0.003954  how long can i return stuff
  2 hard sol       1425      0      0   37   0.003220  I'm ordering shoes for ₹799 to Kochi. Is del
  3 hard sol       1422      0      0   80   0.003644  cancelled 10 days back, refund nahi aaya
  4 hard sol       1416      0      0   49   0.003322  opened earbuds return possible?
  5 easy sol       1415      0      0   36   0.003190  when is support open

baseline: 5 answered (5 sol) · 5 API calls · $0.017330 (₹1.5250) · 11.6s
tokens: 7095 input, 0 cache write, 0 cache read, 314 output
Today: $0.180760 of $0.50 daily budget

$ uv run python labs/cost-cut/done/cost_cut.py final --provider openai --limit 5
4. + local response cache · openai · 5 questions
  # q    path        in  write   read  out     cost $  question
  1 easy luna       171      0   1414   55   0.000059  how long can i return stuff
  2 hard luna       179      0   1422   37   0.000051  I'm ordering shoes for ₹799 to Kochi. Is del
  3 hard sol       1595      0      0  126   0.004007  cancelled 10 days back, refund nahi aaya
  4 hard sol       1583      0      0   64   0.003375  opened earbuds return possible?
  5 easy luna       169      0   1412   44   0.000053  when is support open

final: 5 answered (3 luna, 2 sol) · 10 API calls · $0.007544 (₹0.6639) · 17.7s
tokens: 3697 input, 0 cache write, 4248 cache read, 326 output
Today: $0.188305 of $0.50 daily budget

$ uv run python labs/cost-cut/done/cost_cut.py table --provider openai
Before/after · openai · 5 questions (large gpt-6.2-sol, small gpt-6-luna)

step                        calls   input c.write  c.read output    cost $  cost ₹   time  cheaper  facts ok
1. baseline (large model)       5    7095       0       0    314   0.01733   1.525  11.6s       0%       5/5
2. + prompt caching             (not run)
3. + routing easy -> small      (not run)
4. + local response cache      10    3697       0    4248    326   0.00754   0.664  17.7s      56%       5/5

Target: at least 50% cheaper. Result: 56% cheaper -> target met.
Quality: 0 answer(s) lost a key fact compared with the baseline.

Batch API (not run here): the same calls at half price, about $0.00377, with results within 24 hours.
Good for nightly jobs nobody waits for; never for a customer in the chat.
```

What differs on OpenAI:
- No cache write and no switch: `gpt-6-luna` read 1,404 to 1,422 cached tokens on every call. `gpt-6.2-sol` showed **0 cached tokens** in all 7 calls (baseline and final), so OpenAI's automatic cache is best-effort: always check `cached_tokens` instead of assuming it.
- `gpt-6.2-sol` does not accept reasoning effort `none`; its lowest setting is `low` (set in `shopkart/llm.py`).
- OpenAI's tokenizer counts the same policy sheet as about 1,415 tokens (Claude: about 2,150).

## Total spend

| Provider | This lab's live calls |
| --- | --- |
| Anthropic | $0.163065 (₹14.35) |
| OpenAI | $0.025239 (₹2.22), incl. 2 test calls and a first run that failed with a 400 |
