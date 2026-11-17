# Live run: skill lab

Recorded 2026-11-17 in this repo with real keys, on `claude-haiku-5-5`, plus one OpenAI smoke run on `gpt-6-luna`.
Commands as typed and exactly what they printed. Model replies will differ on your run.

## Tests and validation (no key, no network)

```text
$ uv run pytest labs/skill -q
13 passed in 1.62s

$ LAB=start uv run pytest labs/skill -q        # the start/ copy, before the TODOs
2 failed, 5 passed, 6 errors in 1.85s

$ uvx --from skills-ref agentskills validate labs/skill/done/skills/shopkart-replies
Valid skill: labs/skill/done/skills/shopkart-replies
```

## With and without the skill, 5 tickets (Anthropic, main video)

```text
$ uv run python labs/skill/done/compare.py

=== TCK-20104 [en] I bought running shoes 12 days ago (order SK47731). Can I still return them?
--- WITHOUT skill 169 in / 342 out
    Hi, thanks for reaching out about order SK47731 (Stride RN210 Running Shoes, ₹2,799).
    
    Your order was delivered on 5 November 2026, and today is 17 November 2026, so it has been 12 days since delivery. Our standard return window for footwear is 15 days from delivery, which means your return is still eligible. You have until 20 November 2026 to request it.
    
    To start the return:
    1. Go to My Orders in your ShopKart account, select SK47731, and choose "Return item."
    2. Pick a reason and confirm. Please make sure the shoes are unworn, in their original condition, and include all packaging and tags.
    3. Schedule a pickup or drop the package at the nearest return point as shown in the app.
    
    Once we receive and inspect the shoes, your refund of ₹2,799 will go back to your original UPI payment method. Refunds typically take 5 to 7 business days after the return is processed.
    
    If anything is unclear or you'd like me to help with the return request right now, just let me know.
    sentences 13 · short NO · language ok · no promise ok · handover -
--- WITH skill    6065 in / 543 out
    loaded: L2 shopkart-replies, L3 references/policies.md, L3 run return_window.py footwear 2026-11-05 --today 2026-11-17
    I'm sorry, I know that's not the answer you were hoping for. Footwear can be returned within 10 days of delivery, and your Stride RN210 (order SK47731) was delivered on 5 November, so the window closed 2 days ago and I can't extend it myself. I can pass your request to our support team for a review, and they'll reply within one working day. If the shoes are defective or damaged, tell me and I can start a report for that instead, since that has a separate process.
    sentences 4 · short ok · language ok · no promise ok · handover -

=== TCK-20109 [en] I opened the WaveBass 800 headphones but I don't like the sound. Can I return them? SK4835
--- WITHOUT skill 174 in / 325 out
    Hi, thanks for reaching out about order SK48356.
    
    I'm sorry the WaveBass 800 headphones didn't meet your expectations. Here's what I can see: the order was delivered on 16 November 2026, and it was paid by card.
    
    Whether you can return them depends on our return policy for electronics and whether the item is in a condition that qualifies. Since the headphones have been opened, the return window and condition requirements will apply, so I'd like to confirm those details against your order before I can say for certain that a return is approved. I don't want to promise something I can't verify right now.
    
    If you'd like to proceed, please reply with:
    1. Whether the headphones are in their original packaging and undamaged, with all accessories included.
    2. Whether there's any defect, or whether it's simply a matter of sound preference.
    
    Once I have that, I can tell you whether the return is eligible and walk you through the next steps. Refunds for eligible returns go back to your original card.
    
    Thank you for your patience.
    sentences 13 · short NO · language ok · no promise ok · handover -
--- WITH skill    7070 in / 685 out
    loaded: L2 shopkart-replies, L3 references/policies.md, L3 references/templates.md, L3 run return_window.py electronics 2026-11-16 --today 2026-11-17
    Sorry the WaveBass 800 didn't sound right for you. Since the headphones have been opened, we can only take them back if they're faulty, so a change-of-mind return isn't possible. If they have a fault, such as no sound from one side or crackling, you can report it in My Orders → Report a problem with a photo of the item and the shipping label, and our team will reply within 48 hours with a free replacement or a refund. Would you like me to check any of those faults with you?
    sentences 4 · short ok · language ok · no promise ok · handover -

=== TCK-20116 [en] My Nimbus Tab 10 (SK48488) has a dent on the corner and the screen flickers. I want a full
--- WITHOUT skill 192 in / 365 out
    Hi, I'm sorry to hear your Nimbus Tab 10 arrived damaged with a dented corner and a flickering screen. I understand how frustrating that is, and I'm glad to help with order SK48488 (ticket TCK-20116).
    
    Here's what I can see: the order was delivered on 14 November 2026 and paid by card. Since the tablet arrived damaged, you're eligible to request a return and refund of ₹9,499. To proceed, I'll need a few details:
    
    1. Photos or a short video showing the dent on the corner and the flickering screen (ideally with the tablet powered on, so the flicker is visible).
    2. Confirmation that the original packaging and accessories are available for the return pickup.
    3. Your preferred pickup address and time slot.
    
    Once I have these, I'll raise the return request and send you the pickup details. The refund will go back to your original card after the returned item passes inspection, and I'll share the timeline as soon as the return is scheduled.
    
    If you'd prefer a replacement unit instead of a refund, just let me know and I'll note that on the ticket.
    sentences 13 · short NO · language ok · no promise ok · handover NO
--- WITH skill    6154 in / 598 out
    loaded: L2 shopkart-replies, L3 references/policies.md, L3 run return_window.py electronics 2026-11-14 --today 2026-11-17
    I'm sorry your Nimbus Tab 10 arrived with a dented corner and a flickering screen. Because the refund is over ₹5,000, I've passed your order SK48488 to a support colleague who can approve it. Please also add a photo of the dent and one of the shipping label under My Orders → Report a problem, so the refunds team can check it. A person will get back to you within 4 working hours, and you can also reach us on 1800-120-7575 (9 am to 9 pm IST, Monday to Saturday).
    sentences 4 · short ok · language ok · no promise ok · handover ok

=== TCK-20130 [hinglish] Smartwatch ka strap toota hua aaya hai, SK48495. Refund chahiye ya replacement, jo jaldi h
--- WITHOUT skill 191 in / 352 out
    Namaste, aapko hui pareshani ke liye hum maafi chahte hain. Aapka order SK48495 (Pulse Fit S3 Smartwatch, ₹4,999) 16 November 2026 ko deliver ho chuka hai, aur aapke bataye anusar strap toota hua aaya hai.
    
    Jaldi solution ke liye aap ye options choose kar sakte hain:
    
    1. Replacement: Hum naya strap ya naya smartwatch bhej sakte hain, jo bhi stock mein available ho.
    2. Refund: Agar aap paise wapas chahte hain, to ₹4,999 aapke UPI payment method par refund kar diya jayega.
    
    Please ek chhoti si madad kijiye: strap toota hua hai, uski clear photo aur ye bata dijiye ki kya aap replacement chahte hain ya refund. Photo milne ke baad hum turant aage ki process shuru kar denge.
    
    Dhanyavaad aapke dhairya ke liye.
    sentences 9 · short NO · language ok · no promise ok · handover -
--- WITH skill    7140 in / 689 out
    loaded: L2 shopkart-replies, L3 references/policies.md, L3 references/templates.md, L3 run return_window.py electronics 2026-11-16 --today 2026-11-17
    Sorry, aapki Pulse Fit S3 ka strap toota hua aaya, yeh sunkar bura laga. Please My Orders → Report a problem mein jaakar strap aur shipping label ki photo upload karein. Hamari team 48 ghante mein reply karegi, aur pehle free replacement offer kiya jayega; agar aap refund chahte hain toh woh bhi choose kar sakte hain. Pickup free hai.
    sentences 4 · short ok · language ok · no promise ok · handover -

=== TCK-20137 [en] 2 days late and you won't take back unworn shoes?? Ridiculous. I want to speak to a manage
--- WITHOUT skill 178 in / 290 out
    Hi, I'm sorry about the frustration, and I understand why a delay and a return refusal together feel like a lot. I'm looking at order SK47731 (Stride RN210 Running Shoes, ₹2,799), which shows as delivered on 2026-11-05.
    
    I can't see the delivery delay details or a return window from this chat alone, so I don't want to guess at what policy applies to your case. Here's what I can do right now: I can note this ticket (TCK-20137) with your complaint about the late delivery and the return request for unworn shoes, and I can flag it for escalation to a manager as you've asked. If you can share a photo of the shoes with the tags still attached and the original packaging, that will help the review move faster.
    
    I know a manager review may take some time, but your ticket will be on record with the full details. Is there anything else about the order you'd like included in the escalation?
    sentences 7 · short NO · language ok · no promise ok · handover ok
--- WITH skill    7092 in / 618 out
    loaded: L2 shopkart-replies, L3 references/policies.md, L3 references/templates.md, L3 run return_window.py footwear 2026-11-05 --today 2026-11-17
    I understand your frustration, and I'm sorry the shoes arrived late. The Stride RN210 was delivered on 5 November, 12 days ago, so it's outside our 10-day return window for footwear, and I can't change that window myself. I've passed your request to our support team with the full details, so you won't need to explain it again. A colleague will reply within one working day, by email and in this chat.
    sentences 4 · short ok · language ok · no promise ok · handover ok

=== Summary
without skill  checks passed 11/17 · 904 input tokens · $0.000927
with skill     checks passed 17/17 · 33,521 input tokens · $0.004919
claude-haiku-5-5 · spent this run $0.005846 (₹0.5144) · today $0.015646
```

Run it again and every result comes from the cache: no calls, $0.

## OpenAI smoke run (one ticket)

```text
$ uv run python labs/skill/done/compare.py --provider openai --tickets TCK-20137

=== TCK-20137 [en] 2 days late and you won't take back unworn shoes?? Ridiculous. I want to speak to a manage
--- WITHOUT skill 125 in / 92 out
    I’m sorry the delivery was two days late and that our return policy has been frustrating. I can see your Stride RN210 Running Shoes (order SK47731) were delivered on 5 November. I’ll escalate this to a manager so they can review your return request and get back to you. The shoes are listed as unworn—please keep them unused and in their original packaging while the request is reviewed.
    sentences 4 · short ok · language ok · no promise ok · handover ok
--- WITH skill    4308 in / 246 out
    loaded: L2 shopkart-replies, L3 references/policies.md, L3 references/templates.md, L3 references/tone.md, L3 run return_window.py footwear 2026-11-05 --today 2026-11-17
    I’m sorry this is frustrating, especially after your delivery was 2 days late. Your Stride RN210 shoes were delivered 12 days ago, so they’re outside the 10-day footwear return window; I can’t change that window myself. I’ve passed your request to our support team for review, and a colleague will reply within one working day in this chat and by email.
    sentences 3 · short ok · language ok · no promise ok · handover ok

=== Summary
without skill  checks passed 4/4 · 125 input tokens · $0.000058
with skill     checks passed 4/4 · 4,308 input tokens · $0.000554
gpt-6-luna · spent this run $0.000612 (₹0.0539) · today $0.016258
```

What differs: the same three skill tools go to the Responses API as `function` tools. GPT-6 Luna wrote shorter replies without the skill, and it loaded all three reference files with it.

## On the Claude API

```text
$ uv run python labs/skill/done/api_skill.py --upload
Uploaded shopkart-replies: skill_01J9RcseBxiPru5QK8ozFe3o (version skver_01BsLy56XGazATJePDpfJZ8z)

$ uv run python labs/skill/done/api_skill.py TCK-20104
  [sandbox] text_editor_code_execution: view /skills/shopkart-replies/SKILL.md
  [sandbox] text_editor_code_execution: view /skills/shopkart-replies/references/policies.md
  [sandbox] text_editor_code_execution: view /skills/shopkart-replies/references/templates.md
  [sandbox] text_editor_code_execution: view /skills/shopkart-replies/scripts/return_window.py
  [sandbox] bash_code_execution: python3 /skills/shopkart-replies/scripts/return_window.py footwear 2026-11-05 --today 2026-11-17

Reply: Your Stride RN210 Running Shoes were delivered 12 days ago, so they're outside our 10-day return window for footwear. I can't change the window myself, but I've passed your request to our support team for review. A colleague will reply within one working day, by email and in this chat.

claude-haiku-5-5 · 24872 in / 724 out (last turn) · $0.002849 (₹0.2507) · container container_01PAJhDfgj1B4wU171Ma1Hy5

$ uv run python labs/skill/done/api_skill.py --delete
Deleted skill_01J9RcseBxiPru5QK8ozFe3o
```

The sandbox opened the script's code (it was free to), then ran it. The model never did the date math itself.

## In Claude Code

Claude Code needs the owner's login, so the video records this step separately. The commands:

```bash
mkdir -p .claude/skills && cp -r labs/skill/done/skills/shopkart-replies .claude/skills/
claude
> Draft a reply to this customer: "I bought running shoes 12 days ago (order SK47731, delivered 5 Nov). Can I still return them?"
> /shopkart-replies TCK-20137
> Draft a reply to ticket TCK-20104          # with the MCP lab's shopkart-tickets server added
```

## Cost

| Provider | Live runs (including practice runs while building) | Spend |
| --- | --- | --- |
| Anthropic `claude-haiku-5-5` | 2 runs of the 5-ticket comparison, 2 API skill runs | $0.0170 |
| OpenAI `gpt-6-luna` | 1 smoke run (one ticket) | $0.0006 |

Code execution for the API runs: a few minutes of container time, inside the free monthly hours.

**Total spend for this lab: $0.0170 on Anthropic, $0.0006 on OpenAI.**
