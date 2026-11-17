---
name: decide
version: v1
model_anthropic: claude-haiku-5-5
model_openai: gpt-6-luna
max_tokens: 400
changelog: first version
---
TODO (step 4): one job only. Decide what ShopKart can do about this request, from the policies and
the order facts. Do not write to the customer.

Say:
- that the order facts come from the database, so they win over what the customer says
- what "allowed", "denied" and "handover" mean (handover: a rule in the Escalation and Human Handover Policy applies)
- to give the rule, with its numbers, and where it is, as doc_id §section, like "footwear §1"
- which policy wins when a category policy and the general one differ

<policies>
{{policies}}
</policies>
<!-- user -->
<order_facts>
{{order_facts}}
</order_facts>

<request>
Issue: {{issue}}
In the customer's words: {{issue_summary}}
</request>
