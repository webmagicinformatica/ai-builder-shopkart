"""Steps 2-5: Extract -> Decide -> Write, each with its own versioned prompt, and code in between.

Run:  uv run python labs/prompt-chain/done/chain.py                      # the 10 lab tickets
      uv run python labs/prompt-chain/done/chain.py --ticket TCK-20141   # one ticket, every step
      uv run python labs/prompt-chain/done/chain.py --use write=v2       # try a new prompt version
      add --provider openai for OpenAI, --fresh to skip the cache
"""

from __future__ import annotations

import argparse
import json
import os
import textwrap
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

import facts
from calls import Caller
from checks import PROMISES, language_ok, problems
from promptfiles import chain_versions, load_prompt
from shopkart import budget

HUMAN_LIMIT_INR = 5_000          # any refund above this goes to a human (refunds §1, escalation H1)
MAX_WORDS = 80                   # what write.v* promises
TRACE = budget.LEDGER_DIR / "prompt-chain" / "trace.jsonl"

Category = Literal["footwear", "electronics", "clothing", "accessories", "home_kitchen", "books",
                   "beauty", "grocery", "large_appliances", "gift_card", "other"]


# ---- the three typed steps --------------------------------------------------

class Extraction(BaseModel):
    """Step 1: what the message says. Nothing is decided here."""

    order_id: str | None = Field(description="like SK48213, exactly as written, or null")
    item_category: Category
    issue: Literal["damaged", "defective", "wrong_item", "change_of_mind", "size_or_fit",
                   "not_delivered", "other"]
    issue_summary: str = Field(description="one short line, in English")
    amount_inr: int | None = Field(description="a rupee amount written in the message, or null")
    sentiment: Literal["calm", "upset", "angry"]
    language: Literal["en", "hi", "hinglish"]


class Decision(BaseModel):
    """Step 2: what the policy allows, and which rule says so."""

    decision: Literal["allowed", "denied", "handover"]
    rule: str = Field(description="the one rule applied, one sentence, with its numbers")
    policy_section: str = Field(description='doc_id and section, like "footwear §1"')
    reason: str = Field(description="one sentence applying the rule to this order")


def policies_for(category: str, issue: str) -> list[str]:
    """Only the policies this decision needs (a small, clean context per step)."""
    docs = ["returns-and-refunds", "refunds", "escalation-and-handover"]
    if issue in ("damaged", "defective", "wrong_item"):
        docs.append("damaged-items")
    if category in ("footwear", "electronics"):
        docs.append(category)
    return docs


class Chain:
    def __init__(self, caller: Caller, versions: dict[str, str]):
        self.caller = caller
        self.versions = versions
        self.prompts = {step: load_prompt(step, v) for step, v in versions.items()}
        self.steps: list[dict] = []
        self.handed_over = False  # set when a gate gives up and a human takes over

    def log(self, step: str, **data: object) -> None:
        self.steps.append({"step": step, **data})

    # ---- step 1 + gate 1 ----------------------------------------------------
    def extract(self, ticket: dict) -> Extraction:
        a = self.caller.ask(self.prompts["extract"], {"message": ticket["message"]}, schema=Extraction)
        self.log(a.prompt_id, model=a.model, output=a.parsed.model_dump(), cost_usd=a.cost_usd, cached=a.cached)
        return a.parsed

    def gate_order(self, x: Extraction, ticket: dict) -> dict | None:
        """Facts come from the database, never from the model. No order: stop and ask."""
        order_id, source = x.order_id, "message"
        if order_id is None and ticket.get("order_id"):
            order_id, source = ticket["order_id"], "the order this chat was opened from"
        if order_id is None or not facts.ORDER_ID.match(order_id):
            self.log("gate:order", result=f"stop: no valid order id ({order_id!r}), ask the customer")
            return None
        order = facts.orders().get(order_id)
        if order is None:
            self.log("gate:order", result=f"stop: {order_id} not found, ask the customer")
            return None
        f = facts.order_facts(order, x.item_category)
        note = "" if f["category"] == x.item_category else f" (message said {x.item_category}, database says {f['category']})"
        n = f["days_since_delivery"]
        days = f"delivered {n} day{'s' * (n != 1)} ago" if f["delivered_on"] else f"status {f['status']}"
        via = "" if source == "message" else f" (no id in the message: {source})"
        self.log("gate:order", result=f"{order_id} found{via} · {f['item']} · ₹{f['order_total_inr']:,} · {days}{note}")
        return f

    # ---- step 2 + gate 2 ----------------------------------------------------
    def decide(self, x: Extraction, f: dict) -> Decision:
        docs = policies_for(f["category"], x.issue)
        values = {"policies": facts.policy_block(docs),
                  "order_facts": json.dumps(f, indent=1, ensure_ascii=False),
                  "issue": x.issue, "issue_summary": x.issue_summary}
        a = self.caller.ask(self.prompts["decide"], values, schema=Decision)
        d = a.parsed
        error = facts.citation_error(d.policy_section, docs)
        if error:  # one retry, with the exact error, like a schema retry
            self.log("gate:citation", result=f"retry: {error}")
            a = self.caller.ask(self.prompts["decide"], values, schema=Decision, feedback=[
                {"role": "assistant", "content": a.text},
                {"role": "user", "content": f"{error}. Answer again with a real section."}])
            d = a.parsed
            if facts.citation_error(d.policy_section, docs):
                self.log("gate:citation", result="stop: still no real section, hand over")
                d = Decision(decision="handover", rule="When unsure, hand over.",
                             policy_section="escalation-and-handover §1", reason="The decision step could not cite a policy.")
        self.log(a.prompt_id, model=a.model, output=d.model_dump(), cost_usd=a.cost_usd, cached=a.cached)
        return d

    def gate_amount(self, d: Decision, f: dict) -> Decision:
        """A business rule, in code: the model can't talk its way past it."""
        amount = f["order_total_inr"]
        if d.decision == "allowed" and amount > HUMAN_LIMIT_INR:
            self.log("gate:amount", result=f"₹{amount:,} > ₹{HUMAN_LIMIT_INR:,}: allowed -> handover")
            return Decision(decision="handover", policy_section="escalation-and-handover §1",
                            rule="Any refund above ₹5,000 needs a human (H1).",
                            reason=f"The order is ₹{amount:,}, above ₹5,000. {d.reason}")
        self.log("gate:amount", result=f"₹{amount:,}: {'under' if amount <= HUMAN_LIMIT_INR else 'over'} the limit, "
                                       f"{d.decision} stands")
        return d

    # ---- step 3 + gate 3 ----------------------------------------------------
    def reply_errors(self, d: Decision, reply: str, language: str) -> list[str]:
        errors = []
        if PROMISES.search(reply):
            errors.append("it says the refund is processed or approved; it may only say a request is raised")
        if len(reply.split()) > MAX_WORDS + 10:
            errors.append(f"it has {len(reply.split())} words; keep it under {MAX_WORDS}")
        if d.decision == "handover" and not any(w in reply.lower() for w in ("team", "colleague", "human")):
            errors.append("it must say a colleague from the support team will take over")
        if "**" in reply or reply.lstrip().startswith("#"):
            errors.append("it uses markdown; write plain text")
        if not language_ok(language, reply):
            errors.append(f"the customer wrote in {language}; reply in {language}")
        return errors

    def write(self, x: Extraction, d: Decision, f: dict, name: str) -> str:
        values = {"decision": d.decision, "rule": d.rule, "reason": d.reason, "first_name": name,
                  "language": x.language, "sentiment": x.sentiment,
                  "order_id": f["order_id"], "item": f["item"]}
        a = self.caller.ask(self.prompts["write"], values)
        reply, errors = a.text.strip(), self.reply_errors(d, a.text, x.language)
        if errors:  # the last gate: the reply may not promise more than the decision
            self.log("gate:reply", result="retry: " + "; ".join(errors))
            a = self.caller.ask(self.prompts["write"], values, feedback=[
                {"role": "assistant", "content": a.text},
                {"role": "user", "content": "Rewrite the reply: " + "; ".join(errors) + "."}])
            reply, errors = a.text.strip(), self.reply_errors(d, a.text, x.language)
            if errors:
                self.log("gate:reply", result="stop: still failing, hand over with a safe reply")
                self.handed_over = True
                reply = (f"Hi {name}, I've passed your request about order {f['order_id']} to our support team. "
                         "A colleague will reply within one working day.")
        else:
            self.log("gate:reply", result="ok")
        self.log(a.prompt_id, model=a.model, output=reply, cost_usd=a.cost_usd, cached=a.cached)
        return reply


def run_chain(caller: Caller, case: dict, versions: dict[str, str]) -> dict:
    ticket = facts.tickets()[case["ticket_id"]]
    chain = Chain(caller, versions)
    x = chain.extract(ticket)
    f = chain.gate_order(x, ticket)
    if f is None:
        decision, reply, section = "ask_order_id", "Could you share your order number? It looks like SK48213.", None
    else:
        d = chain.gate_amount(chain.decide(x, f), f)
        name = facts.orders()[f["order_id"]]["customer_name"].split()[0]
        reply = chain.write(x, d, f, name)
        decision, section = ("handover", d.policy_section) if chain.handed_over else (d.decision, d.policy_section)
    row = {"ticket_id": case["ticket_id"], "expected": case["expected"], "decision": decision,
           "policy_section": section, "reply": reply, "format_ok": True,
           "problems": problems(case, decision, reply, max_words=MAX_WORDS + 10),
           "versions": versions, "steps": chain.steps}
    TRACE.parent.mkdir(parents=True, exist_ok=True)
    with TRACE.open("a") as fh:  # every step's input and output, with the prompt versions
        fh.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), **row}, ensure_ascii=False) + "\n")
    return row


def show(row: dict, verbose: bool = False) -> None:
    mark = "ok" if not row["problems"] else "✗ " + "; ".join(row["problems"])
    print(f"{row['ticket_id']}  expected {row['expected']:<8} got {row['decision']:<8} "
          f"{row['policy_section'] or '':<26} {mark}")
    if verbose:
        for s in row["steps"]:
            label = s["step"]
            body = s.get("result") or s.get("output")
            if isinstance(body, dict):
                body = " · ".join(f"{k}={v}" for k, v in body.items())
            print(textwrap.indent(textwrap.fill(f"{label:<14} {body}", 100, subsequent_indent=" " * 15), "    "))
        print()
    else:
        print(textwrap.indent(textwrap.fill(row["reply"], 96), "    "))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", default=None, choices=["anthropic", "openai"])
    ap.add_argument("--ticket", help="run one ticket and show every step")
    ap.add_argument("--use", action="append", default=[], metavar="STEP=VERSION",
                    help="override prompts/chain.json, e.g. --use write=v2")
    ap.add_argument("-v", "--verbose", action="store_true", help="show every step for every ticket")
    ap.add_argument("--fresh", action="store_true", help="ignore the cache and call the API again")
    args = ap.parse_args(argv)

    versions = chain_versions(args.use)
    caller = Caller(provider=args.provider or os.environ.get("LLM_PROVIDER", "anthropic"), fresh=args.fresh)
    cases = [c for c in facts.cases() if args.ticket in (None, c["ticket_id"])]
    if not cases:
        ap.error(f"{args.ticket} is not one of the lab's tickets (see cases.json)")
    print("prompts: " + " → ".join(f"{s}.{v}" for s, v in versions.items()) + f" · provider {caller.provider}\n")
    rows = [run_chain(caller, c, versions) for c in cases]
    for row in rows:
        show(row, verbose=args.verbose or args.ticket is not None)
    clean = sum(not r["problems"] for r in rows)
    models = sorted({a.model for a in caller.answers})
    print(f"\nchain: {clean}/{len(rows)} clean · {', '.join(models)} · {caller.summary()}")
    print(f"trace: {TRACE.relative_to(facts.REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
