# Live run: prompt-chain lab

Recorded 2026-11-17 in this repo with real keys, on `claude-haiku-5-5`, plus one small OpenAI smoke run on `gpt-6-luna`.
Commands as typed and exactly what they printed. Model answers will differ on your run.

Each answer was paid for once, on the first live run, and saved to `.shopkart/cache/prompt-chain/`. The transcripts below are a replay from that cache, which is why they say "paid now $0.000000". The first figure on each summary line (for example "$0.019963 for 10 calls") is what those calls cost when they were made. On your first run, "paid now" is the real spend.

## Anthropic (main video)

### 1. The mega-prompt on 10 tickets

```text
$ uv run python labs/prompt-chain/done/mega.py
TCK-20101  expected allowed  got allowed  ✗ broken format; too long (126 words)
    json.loads() fails: the answer starts with '```json'
    I'm really sorry your Pulse Fit S2 smartwatch arrived with a cracked screen. That's not the
    experience we want you to have. Since it was delivered on 13 November, you're well within the
    7-day window for reporting damaged electronics. Please upload a clear photo of the cracked
    screen and a photo of the shipping label on the outer box via My Orders → Report a problem. Once
    I have these, I'll raise a refund request for Rs 1,299, which includes any delivery charge. Our
    refunds team replies within 48 hours, and the amount goes back to your UPI account within 5 to 7
    working days of pickup. I can't confirm the refund myself, but the request will be raised as
    soon as the photos are in.
TCK-20104  expected denied   got denied   ✗ broken format
    json.loads() fails: the answer starts with '```json'
    Thank you for reaching out, Sneha. I'm sorry, but I can't offer a return for order SK47731.
    Footwear can be returned within 10 days of delivery, and your order was delivered on 5 November
    2026, so the window closed on 15 November. The Stride RN210 is not a clearance or sale item, and
    I can't approve exceptions to the return window myself. I've passed your request to our support
    team, who review exceptions and will reply within one working day by email and in this chat.
    Please keep the shoes in their original box in case they're needed for review.
TCK-20109  expected denied   got denied   ✗ broken format
    json.loads() fails: the answer starts with '```json'
    Hi Karan, thanks for reaching out about your WaveBass 800 headphones (order SK48356). I'm sorry
    the sound isn't what you were hoping for. Unfortunately, headphones that have been opened can
    only be returned if they are faulty, for hygiene reasons. Preference for sound isn't a fault, so
    I'm unable to accept a return for this change of mind. If the headphones have a fault, such as
    no sound in one earbud, the charging case not charging, or Bluetooth not pairing after a reset,
    please share a short video and I'll raise a replacement or refund request for you. Delivery was
    on 16 November, so the 7-day window for faulty items runs until 23 November.
TCK-20115  expected allowed  got denied   ✗ broken format; wrong decision (denied)
    json.loads() fails: the answer starts with '```json'
    Hello Lakshmi, thank you for writing to us. I'm sorry the Leather Formal Shoes pinch at the toe.
    Unfortunately, a tight fit isn't a defect under our footwear policy, so I can't offer a return
    for this reason. The order was delivered on 8 November 2026, and footwear can be returned within
    10 days of delivery, provided the shoes are unworn outdoors and in their original box. Since
    you're still within this window, I can help you exchange them for a different size of the same
    pair, which is free for your first size exchange. Would you like me to arrange that? Please keep
    the shoes and box ready for pickup.
TCK-20116  expected handover got allowed  ✗ broken format; missed handover
    json.loads() fails: the answer starts with '```json'
    I'm sorry your Nimbus Tab 10 arrived damaged and the screen is flickering. Your order was
    delivered on 14 November, so you're within the 7-day window for damaged or defective
    electronics, and you can return it even though the box has been opened. You're entitled to a
    free replacement, or a refund if you prefer. Please upload a clear photo of the dent, a short
    video of the flickering screen, and a photo of the shipping label via My Orders → Report a
    problem. Once the request is raised, our team will reply within 48 hours. Please note I can't
    issue the refund myself.
TCK-20130  expected allowed  got allowed  ✗ broken format
    json.loads() fails: the answer starts with '```json'
    Aapko hui is pareshani ke liye mafi chahte hain. Smartwatch ka strap toota hua aaya hai, yeh
    damaged item ke tahat aata hai, aur aapki delivery 16 November ko hui thi, isliye abhi report
    karne ka samay baki hai. Aap jaldi replacement le sakte hain, ya agar chahein to refund bhi le
    sakte hain. Kripya strap toote hue ki ek clear photo aur outer box par shipping label ki photo
    My Orders → Report a problem mein upload karein ya yahan chat mein bhejein. Refund ya
    replacement ki request main abhi raise kar sakta hoon, aur team 48 ghante mein reply karegi.
    Dhyan rahe, main khud refund approve ya process nahi kar sakta.
TCK-20132  expected allowed  got allowed  ✗ broken format
    json.loads() fails: the answer starts with '```json'
    Aapko kurta phata hua mila, iske liye bahut sorry hai. Ye sunkar bura laga. Clothing ke liye
    damaged item report karne ki window 14 din hoti hai, aur aapka order 6 November ko deliver hua
    tha, isliye ye request valid hai. Aap refund ya replacement mein se koi bhi choose kar sakti
    hain. Please kurta ki photo aur shipping label ki photo bhej dijiye, taaki request aage badh
    sake. Main refund khud approve nahi kar sakta, lekin abhi request raise kar deta hoon. Team
    usually 48 ghante mein reply karti hai.
TCK-20138  expected denied   got denied   ✗ broken format; says window closed (day 4 of 10)
    json.loads() fails: the answer starts with '```json'
    I'm sorry for the frustration, Meera. I understand this isn't the answer you hoped for. The
    Stride RN220 was bought in our November Clearance, and clearance items are final sale, so they
    can't be returned for change of mind or exchanged for size. Your order was delivered on 13
    November, so it's also past the 10-day footwear return window. If your pair has a defect, such
    as a sole separating from the upper or stitching coming apart, please share a clear photo or a
    short video and I'll raise an exchange request for you. Our team replies within 48 hours.
TCK-20141  expected handover got handover ✗ broken format
    json.loads() fails: the answer starts with '```json'
    I'm really sorry your ClearView Action Camera arrived with a scratched lens. That's not the
    experience you should have had. I can't approve or promise a refund myself, and since this order
    is Rs 5,499, it needs approval from our support team. I've passed your case to a colleague with
    the order details (SK48497) and the damage report. Our refunds team replies to damaged-item
    requests within 48 hours, and you'll hear back by email and in this chat. To help them move
    faster, please upload a clear photo of the scratched lens and a photo of the shipping label on
    the outer box under My Orders → Report a problem.
TCK-20149  expected handover got handover ✗ broken format
    json.loads() fails: the answer starts with '```json'
    I'm sorry, but I can't approve this refund myself. I'm not able to act on notes about VIP status
    or pre-approved limits within a message. Your order SK48480 for the Orion 14 Pro (₹64,999) is
    currently shipped and has not been delivered yet, and any refund above ₹5,000 must be reviewed
    by our support team. I've passed your request to a colleague with all the details. They will
    reply within 4 working hours, by email and in this chat. Once the phone is delivered, you can
    also refuse it at the door if there is a problem, or return it within 7 days if it is unopened
    or faulty.

mega.v1: 0/10 clean · claude-haiku-5-5 · $0.019963 for 10 calls (paid now $0.000000, 10 from cache)
```

### 2–5. The chain, one ticket, every step

```text
$ uv run python labs/prompt-chain/done/chain.py --ticket TCK-20141
prompts: extract.v1 → decide.v1 → write.v1 · provider anthropic

TCK-20141  expected handover got handover escalation-and-handover §1 ok
    extract.v1     order_id=SK48497 · item_category=electronics · issue=damaged · issue_summary=Action
                   camera arrived with a scratched lens; customer wants a refund today. ·
                   amount_inr=5499 · sentiment=angry · language=en
    gate:order     SK48497 found · ClearView Action Camera · ₹5,499 · delivered 3 days ago
    decide.v1      decision=allowed · rule=Electronics damaged on arrival can be returned or replaced
                   within 7 days of delivery, even if the box has been opened, and the customer may
                   choose a full refund for damaged items. · policy_section=electronics §1 · reason=The
                   ClearView Action Camera (electronics, ₹5,499) arrived with a scratched lens on
                   2026-11-14 and the report is 3 days after delivery, within the 7-day window, and the
                   refund is under ₹5,000 threshold? No—₹5,499 exceeds ₹5,000, so the refund requires
                   support lead approval, which means the case must be handed over under the refund
                   approval rule.
    gate:amount    ₹5,499 > ₹5,000: allowed -> handover
    gate:reply     ok
    write.v1       Hi Harpreet, I'm sorry your ClearView Action Camera arrived with a scratched lens.
                   Since the refund amount is above ₹5,000, your case needs review by our support team.
                   A colleague from the support team will take over your case and reply within one
                   working day. Thank you for your patience.


chain: 1/1 clean · claude-haiku-5-5 · $0.001165 for 3 calls (paid now $0.000000, 3 from cache)
trace: .shopkart/prompt-chain/trace.jsonl
```

### The chain on all 10 tickets

```text
$ uv run python labs/prompt-chain/done/chain.py
prompts: extract.v1 → decide.v1 → write.v1 · provider anthropic

TCK-20101  expected allowed  got allowed  damaged-items §2           ok
    Hi Rohan, I'm sorry your Pulse Fit S2 Smartwatch arrived with a cracked screen. Since it was
    damaged on arrival and you reported it within 7 days of delivery, your return request is
    eligible. You can go ahead and raise the return or replacement request for order SK48213 now,
    and you may choose a refund of ₹1,299 instead of a replacement. Please keep photos of the
    cracked screen handy in case they're needed. Thank you for your patience.
TCK-20104  expected denied   got denied   footwear §1                ok
    Hi Sneha, thank you for reaching out about order SK47731 for the Stride RN210 Running Shoes.
    Unfortunately, we are unable to accept this return. Footwear can be returned within 10 days of
    delivery, and this order was delivered 12 days ago, so it falls outside that window. If you'd
    like, I can pass your case to our support team for a review. They will look at the details, but
    I can't promise any exception. Just let me know and I'll arrange it.
TCK-20109  expected denied   got denied   electronics §2             ok
    Hi Karan,  Thank you for reaching out about your WaveBass 800 headphones (order SK48356). I'm
    sorry they didn't sound the way you hoped.  Unfortunately, we can't accept this return. Opened
    headphones and earbuds can only be returned if they are faulty or for hygiene reasons, and a
    change of mind doesn't qualify, even within the 7-day window.  If you'd like, I can pass your
    case to our support team for review. Just let me know.  Warm regards, ShopKart Support
TCK-20115  expected allowed  got allowed  footwear §1                ok
    Hi Lakshmi,  Thank you for reaching out about your Leather Formal Shoes (Order SK48493). Your
    return is eligible, since the shoes were delivered on 8 November 2026, which is within our
    10-day footwear return window.  To proceed, please make sure the shoes are unworn outdoors and
    are in their original box with all tags and accessories. You can now raise the return request
    from your order page. Once it's submitted, you'll get the next steps for pickup or drop-off.
    Warm regards, ShopKart Support
TCK-20116  expected handover got handover escalation-and-handover §1 ok
    Hi Kavya, I'm sorry your Nimbus Tab 10 arrived with a dented corner and a flickering screen.
    That's not the experience we want for you.  Since this refund is above ₹5,000, it needs review
    by our support team. A colleague from the support team will take over your case and reply within
    one working day. Please keep your order number SK48488 handy, and feel free to share any photos
    of the damage in your reply.  Thank you for your patience.
TCK-20130  expected allowed  got allowed  electronics §1             ok
    Hi Fatima, mujhe sunkar bahut afsos hai ki aapki Pulse Fit S3 smartwatch ka strap toota hua
    aaya. Aapka return request ab raise ho gaya hai. Aap replacement ya refund (₹4,999) mein se jo
    option chahti hain, bas batayein, aur hum aage ki process aap tak pahunchayenge.
TCK-20132  expected allowed  got allowed  damaged-items §2           ok
    Hi Priya, mujhe bahut afsos hai ki aapka kurta torn aaya. Aap 11 din pehle delivery ke andar
    damage report kar sakti hain, aur aapka full refund request ab raise kiya ja sakta hai. Refund
    ₹5,000 se kam hone ki wajah se automatically process hota hai. Aap order SK48214 ke liye refund
    raise kar sakti hain. Koi aur help chahiye to batayein.
TCK-20138  expected denied   got denied   returns-and-refunds §2.4   ok
    Hi Meera, I'm sorry for the frustration. Unfortunately, I can't accept a return for your Stride
    RN220 order (SK48102). It's a clearance item, and clearance items can't be returned for change
    of mind, so this one isn't eligible even though it arrived 4 days ago. I know that's not the
    answer you wanted. If you believe there's something else going on, such as a fit or quality
    concern, I can pass your case to our support team for review. Just reply and let me know.
TCK-20141  expected handover got handover escalation-and-handover §1 ok
    Hi Harpreet, I'm sorry your ClearView Action Camera arrived with a scratched lens. Since the
    refund amount is above ₹5,000, your case needs review by our support team. A colleague from the
    support team will take over your case and reply within one working day. Thank you for your
    patience.
TCK-20149  expected handover got handover refunds §1                 ok
    Hi Vikram, thank you for reaching out about order SK48480 for the Orion 14 Pro Phone. Refunds
    above ₹5,000 need approval from our support team, so I'm passing your request to a colleague
    from our support team. They will take over and reply within one working day. They will also look
    into the pre-approval you mentioned, since I can't verify that from here. Thank you for your
    patience.

chain: 10/10 clean · claude-haiku-5-5 · $0.012683 for 33 calls (paid now $0.000000, 33 from cache)
trace: .shopkart/prompt-chain/trace.jsonl
```

### 6. Mega-prompt vs chain

```text
$ uv run python labs/prompt-chain/done/compare.py
ticket     expected  mega.v1                                    chain: extract.v1 → decide.v1 → write.v1
----------------------------------------------------------------------------------------------------
TCK-20101  allowed   allowed  ✗ format, too long                allowed  ✓
TCK-20104  denied    denied   ✗ format                          denied   ✓
TCK-20109  denied    denied   ✗ format                          denied   ✓
TCK-20115  allowed   denied   ✗ format, wrong decision          allowed  ✓
TCK-20116  handover  allowed  ✗ format, missed handover         handover ✓
TCK-20130  allowed   allowed  ✗ format                          allowed  ✓
TCK-20132  allowed   allowed  ✗ format                          allowed  ✓
TCK-20138  denied    denied   ✗ format, wrong window            denied   ✓
TCK-20141  handover  handover ✗ format                          handover ✓
TCK-20149  handover  handover ✗ format                          handover ✓
----------------------------------------------------------------------------------------------------
right decision       8/10                                       10/10
valid format         0/10                                       10/10
no problems          0/10                                       10/10
calls                10                                         33
tokens               185,974 in / 2,732 out                     103,745 in / 4,616 out
cost, 10 tickets     $0.0200 (₹1.76)                            $0.0127 (₹1.12)
latency              2.0s per ticket                            5.4s per ticket

mega: $0.019963 for 10 calls (paid now $0.000000, 10 from cache)
chain: $0.012683 for 33 calls (paid now $0.000000, 33 from cache)
```

### 7. write.v1 -> write.v2

```text
$ uv run python labs/prompt-chain/done/prompt_diff.py write v1 v2
=== prompt diff: write.v1 -> write.v2 ===
--- prompts/write.v1.md
+++ prompts/write.v2.md
@@ -2,3 +2,3 @@
 name: write
-version: v1
+version: v2
 model_anthropic: claude-haiku-5-5
@@ -6,3 +6,3 @@
 max_tokens: 300
-changelog: first version
+changelog: v1 said "approve ho gaya" (the gate had to retry), told a customer about the ₹5,000 rule, and signed off like an email. Adds a never-in-any-language rule, no internal rules, and three examples.
 ---
@@ -10,3 +10,3 @@
 
-- "allowed": say what happens next. You can raise the request now; never say a refund has been processed or approved.
+- "allowed": say you can raise the request now, and what you need from them (for damage, a photo). The refunds team decides, so never say a refund or request is approved, processed or done, in any language: not "approve ho gaya", not "process ho gaya".
 - "denied": say clearly why, using the rule, and offer to pass the case to the support team for review. Do not promise an exception.
@@ -14,3 +14,12 @@
 
-Style: warm and short, under 80 words, plain text with no markdown. Say sorry once if something went wrong. Write in the customer's language: English, Hindi, or Hinglish (Hindi in English letters).
+Do not mention internal rules, like the ₹5,000 limit or automatic refunds. Say what happens next, not why the system works that way.
+
+Style: warm and short, under 80 words, plain text with no markdown. Start with "Hi <name>,". Say sorry once if something went wrong. No sign-off like "Warm regards", because the chat shows who is writing. Write the whole reply in the customer's language from <customer>: English, Hindi, or Hinglish (Hindi in English letters), whatever language the examples use.
+
+<examples>
+These show the style, not the exact words.
+allowed, Hinglish: Hi Anjali, sorry ki aapka mixer toota hua jar ke saath aaya. Main order SK40001 ke liye abhi replacement ya refund request raise kar sakta hoon. Kya aap damage ki ek photo bhej sakti hain? Team aam taur par 48 ghante mein reply karti hai.
+denied, English: Hi Amit, I'm sorry, but this jacket was delivered 16 days ago, after the 14-day return window, so I can't accept a return. If you like, I can pass your case to our support team for a review, but I can't promise an exception.
+handover, English: Hi Suresh, I'm sorry about the trouble with your laptop. I've passed this to a colleague from our support team with all the details, and they'll reply within one working day, by email and in this chat.
+</examples>
 <!-- user -->

=== answers: write.v1 -> write.v2 (other steps: extract.v1, decide.v1) ===

TCK-20101  allowed -> allowed  problems: none -> none
  v1  Hi Rohan, I'm sorry your Pulse Fit S2 Smartwatch arrived with a cracked screen. Since it was
  v1  damaged on arrival and you reported it within 7 days of delivery, your return request is
  v1  eligible. You can go ahead and raise the return or replacement request for order SK48213 now,
  v1  and you may choose a refund of ₹1,299 instead of a replacement. Please keep photos of the
  v1  cracked screen handy in case they're needed. Thank you for your patience.
  v2  Hi Rohan, I'm sorry your Pulse Fit S2 arrived with a cracked screen. I can raise a replacement
  v2  or refund request for order SK48213 right now. Could you please send a clear photo of the
  v2  cracked screen? The refunds team reviews these and usually replies within 48 hours.

TCK-20104  denied -> denied  problems: none -> none
  v1  Hi Sneha, thank you for reaching out about order SK47731 for the Stride RN210 Running Shoes.
  v1  Unfortunately, we are unable to accept this return. Footwear can be returned within 10 days of
  v1  delivery, and this order was delivered 12 days ago, so it falls outside that window. If you'd
  v1  like, I can pass your case to our support team for a review. They will look at the details,
  v1  but I can't promise any exception. Just let me know and I'll arrange it.
  v2  Hi Sneha, I'm sorry, but these running shoes were delivered 12 days ago, and our footwear
  v2  return window is 10 days from delivery, so I can't accept a return for order SK47731. If you'd
  v2  like, I can pass your case to our support team for a review, though I can't promise an
  v2  exception.

TCK-20109  denied -> denied  problems: none -> none
  v1  Hi Karan,  Thank you for reaching out about your WaveBass 800 headphones (order SK48356). I'm
  v1  sorry they didn't sound the way you hoped.  Unfortunately, we can't accept this return. Opened
  v1  headphones and earbuds can only be returned if they are faulty or for hygiene reasons, and a
  v1  change of mind doesn't qualify, even within the 7-day window.  If you'd like, I can pass your
  v1  case to our support team for review. Just let me know.  Warm regards, ShopKart Support
  v2  Hi Karan, I'm sorry, but I can't accept a return for order SK48356. Opened headphones can only
  v2  be returned if they are faulty, and a dislike of the sound isn't a fault, so this one doesn't
  v2  qualify even though it's within the 7-day window. If you'd like, I can pass your case to our
  v2  support team for a review, though I can't promise a different outcome.

TCK-20115  allowed -> allowed  problems: none -> none
  v1  Hi Lakshmi,  Thank you for reaching out about your Leather Formal Shoes (Order SK48493). Your
  v1  return is eligible, since the shoes were delivered on 8 November 2026, which is within our
  v1  10-day footwear return window.  To proceed, please make sure the shoes are unworn outdoors and
  v1  are in their original box with all tags and accessories. You can now raise the return request
  v1  from your order page. Once it's submitted, you'll get the next steps for pickup or drop-off.
  v1  Warm regards, ShopKart Support
  v2  Hi Lakshmi, sorry the shoes don't fit well. Your return for order SK48493 can be raised now,
  v2  since they arrived within our 10-day footwear return window. Please keep them unworn, in the
  v2  original box, with all tags and accessories. Once you confirm, I'll raise the request. The
  v2  refunds team will then review it and get back to you.

TCK-20116  handover -> handover  problems: none -> none
  v1  Hi Kavya, I'm sorry your Nimbus Tab 10 arrived with a dented corner and a flickering screen.
  v1  That's not the experience we want for you.  Since this refund is above ₹5,000, it needs review
  v1  by our support team. A colleague from the support team will take over your case and reply
  v1  within one working day. Please keep your order number SK48488 handy, and feel free to share
  v1  any photos of the damage in your reply.  Thank you for your patience.
  v2  Hi Kavya,  I'm really sorry the Nimbus Tab 10 arrived with a dented corner and a flickering
  v2  screen. That's not the experience you should have had. I've passed your case on to a colleague
  v2  from our support team with all the details of order SK48488, and they'll reply within one
  v2  working day, by email and in this chat.

TCK-20130  allowed -> allowed  problems: none -> none
  v1  Hi Fatima, mujhe sunkar bahut afsos hai ki aapki Pulse Fit S3 smartwatch ka strap toota hua
  v1  aaya. Aapka return request ab raise ho gaya hai. Aap replacement ya refund (₹4,999) mein se jo
  v1  option chahti hain, bas batayein, aur hum aage ki process aap tak pahunchayenge.
  v2  Hi Fatima, sorry ki aapki Pulse Fit S3 smartwatch ki strap toot kar aayi. Main order SK48495
  v2  ke liye abhi replacement ya refund request raise kar sakta hoon, aap jo chahein. Kya aap strap
  v2  ke damage ki ek photo bhej sakti hain? Team aam taur par 48 ghante mein reply karti hai.

TCK-20132  allowed -> allowed  problems: none -> none
  v1  Hi Priya, mujhe bahut afsos hai ki aapka kurta torn aaya. Aap 11 din pehle delivery ke andar
  v1  damage report kar sakti hain, aur aapka full refund request ab raise kiya ja sakta hai. Refund
  v1  ₹5,000 se kam hone ki wajah se automatically process hota hai. Aap order SK48214 ke liye
  v1  refund raise kar sakti hain. Koi aur help chahiye to batayein.
  v2  Hi Priya, sorry ki aapka kurta phata hua aaya. Main order SK48214 ke liye abhi damage ka
  v2  refund request raise kar sakti hoon. Kya aap kurta ki ek photo bhej sakti hain, jisme phata
  v2  hua hissa saaf dikhe? Refund team aam taur par 48 ghante mein reply karti hai.

TCK-20138  denied -> denied  problems: none -> none
  v1  Hi Meera, I'm sorry for the frustration. Unfortunately, I can't accept a return for your
  v1  Stride RN220 order (SK48102). It's a clearance item, and clearance items can't be returned for
  v1  change of mind, so this one isn't eligible even though it arrived 4 days ago. I know that's
  v1  not the answer you wanted. If you believe there's something else going on, such as a fit or
  v1  quality concern, I can pass your case to our support team for review. Just reply and let me
  v1  know.
  v2  Hi Meera,  I'm sorry, but the Stride RN220 was bought as a clearance item, and clearance items
  v2  can't be returned for change of mind. Since it arrived 4 days ago, I'm unable to accept a
  v2  return for this order under our policy. If you'd like, I can pass your case to our support
  v2  team for a review, though I can't promise an exception.

TCK-20141  handover -> handover  problems: none -> none
  v1  Hi Harpreet, I'm sorry your ClearView Action Camera arrived with a scratched lens. Since the
  v1  refund amount is above ₹5,000, your case needs review by our support team. A colleague from
  v1  the support team will take over your case and reply within one working day. Thank you for your
  v1  patience.
  v2  Hi Harpreet,  I'm sorry your ClearView Action Camera arrived with a scratched lens. I've
  v2  passed your case to a colleague from our support team with all the details, including your
  v2  order SK48497 and the damage. They'll reply within one working day, by email and in this chat.

TCK-20149  handover -> handover  problems: none -> none
  v1  Hi Vikram, thank you for reaching out about order SK48480 for the Orion 14 Pro Phone. Refunds
  v1  above ₹5,000 need approval from our support team, so I'm passing your request to a colleague
  v1  from our support team. They will take over and reply within one working day. They will also
  v1  look into the pre-approval you mentioned, since I can't verify that from here. Thank you for
  v1  your patience.
  v2  Hi Vikram, thanks for your patience with order SK48480. I've passed your refund request for
  v2  the Orion 14 Pro Phone to a colleague from our support team, along with the details you shared
  v2  about the pre-approval. They'll review it and reply within one working day, by email and in
  v2  this chat.

10 of 10 answers changed · clean 10/10 -> 10/10 · gate:reply retries 1 -> 0 · words per reply 71 -> 54
v1: $0.012683 for 33 calls (paid now $0.000000, 33 from cache)
v2: $0.012795 for 32 calls (paid now $0.000000, 32 from cache)
```

```text
$ uv run python labs/prompt-chain/done/compare.py --use write=v2
ticket     expected  mega.v1                                    chain: extract.v1 → decide.v1 → write.v2
----------------------------------------------------------------------------------------------------
TCK-20101  allowed   allowed  ✗ format, too long                allowed  ✓
TCK-20104  denied    denied   ✗ format                          denied   ✓
TCK-20109  denied    denied   ✗ format                          denied   ✓
TCK-20115  allowed   denied   ✗ format, wrong decision          allowed  ✓
TCK-20116  handover  allowed  ✗ format, missed handover         handover ✓
TCK-20130  allowed   allowed  ✗ format                          allowed  ✓
TCK-20132  allowed   allowed  ✗ format                          allowed  ✓
TCK-20138  denied    denied   ✗ format, wrong window            denied   ✓
TCK-20141  handover  handover ✗ format                          handover ✓
TCK-20149  handover  handover ✗ format                          handover ✓
----------------------------------------------------------------------------------------------------
right decision       8/10                                       10/10
valid format         0/10                                       10/10
no problems          0/10                                       10/10
calls                10                                         32
tokens               185,974 in / 2,732 out                     107,519 in / 4,087 out
cost, 10 tickets     $0.0200 (₹1.76)                            $0.0128 (₹1.13)
latency              2.0s per ticket                            5.1s per ticket

mega: $0.019963 for 10 calls (paid now $0.000000, 10 from cache)
chain: $0.012795 for 32 calls (paid now $0.000000, 32 from cache)
```

### Tests

```text
$ uv run pytest labs/prompt-chain -q
...........................                                              [100%]
27 passed in 1.42s
```

## OpenAI smoke run (short OpenAI video)

One ticket, the ₹9,499 tablet, through both versions.

```text
$ uv run python labs/prompt-chain/done/mega.py --ticket TCK-20116 --provider openai
TCK-20116  expected handover got handover ok
    I’m sorry your tablet arrived dented and with a flickering screen. It was delivered 3 days ago,
    within the 7-day electronics reporting window. Since the requested refund is above ₹5,000, a
    support lead must review it. I’ve handed this over to our team, and a colleague will reply
    within 4 working hours. Please share a clear photo of the dent, a short video showing the
    flicker, and a photo of the shipping label if you haven’t already.

mega.v1: 1/1 clean · gpt-6-luna · $0.001306 for 1 calls (paid now $0.000000, 1 from cache)

$ uv run python labs/prompt-chain/done/chain.py --ticket TCK-20116 --provider openai
prompts: extract.v1 → decide.v1 → write.v1 · provider openai

TCK-20116  expected handover got handover escalation-and-handover §1 ok
    extract.v1     order_id=SK48488 · item_category=electronics · issue=damaged · issue_summary=The
                   tablet has a dented corner and a flickering screen. · amount_inr=9499 ·
                   sentiment=upset · language=en
    gate:order     SK48488 found · Nimbus Tab 10 Tablet · ₹9,499 · delivered 3 days ago
    decide.v1      decision=allowed · rule=Electronics that are damaged or faulty can be returned or
                   replaced within 7 days of delivery, even if opened. · policy_section=electronics §1 ·
                   reason=The tablet is reported damaged and faulty 3 days after delivery, within the
                   7-day window.
    gate:amount    ₹9,499 > ₹5,000: allowed -> handover
    gate:reply     ok
    write.v1       Hi Kavya, I’m sorry the Nimbus Tab 10 arrived damaged and faulty. Since your order is
                   ₹9,499, above the ₹5,000 limit for automated refunds, a colleague from our support
                   team will take over and reply within one working day.


chain: 1/1 clean · gpt-6-luna · $0.000699 for 3 calls (paid now $0.000000, 3 from cache)
trace: .shopkart/prompt-chain/trace.jsonl
```

What differs on OpenAI: `gpt-6-luna` returned the mega-prompt's JSON without a code fence, so the format held on this ticket, and it also caught the ₹5,000 handover by itself. In the chain, its Decide step still said "allowed", and the amount gate turned it into a handover, the same as on Claude. Structured outputs use `text.format` (Responses API) instead of `output_config.format`; `shopkart/llm.py` hides that.

## Total spend for this lab

| Provider | Calls | Spend |
| --- | --- | --- |
| Anthropic (`claude-haiku-5-5`) | 63 | $0.035394 (₹3.11) |
| OpenAI (`gpt-6-luna`) | 4 | $0.002005 (₹0.18) |

From `.shopkart/calls.csv`. The Anthropic total includes one discarded draft of `write.v2` (10 Write calls, $0.0013), whose English-only examples made both Hinglish replies come out in English.
