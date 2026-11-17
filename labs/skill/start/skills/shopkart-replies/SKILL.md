---
name: shopkart-replies
description: TODO 1. What this skill does AND when to use it, in one or two sentences (max 1024 characters). The agent sees only this line until it decides to load the skill, so name the situations, e.g. "Use when drafting or reviewing a reply to a ShopKart customer, especially about returns, refunds, ...".
license: MIT
---

# ShopKart replies

TODO 2. Brief a new support colleague, in plain steps:

## 1. Read the message
(language: English, Hindi or Hinglish; order ID; ask for it if missing)

## 2. Decide: answer, or hand over
(the main handover cases; "when unsure, hand over"; the full list is in `references/policies.md`)

## 3. Check the facts
(read `references/policies.md`; for a return window, run `python scripts/return_window.py <category> <delivered_on> --today <today>`)

## 4. Write the reply
(warm and short; templates in `references/templates.md`; examples in `references/tone.md`)

## 5. Check before you send
(four sentences at most; the customer's language; never promise a refund before it's approved;
a handover says who and when; never ask for card numbers or OTPs; no internal words)
