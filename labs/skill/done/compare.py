"""Replies with and without the shopkart-replies skill, on 5 tickets.

    uv run python labs/skill/done/compare.py                  # Anthropic, claude-haiku-5-5
    uv run python labs/skill/done/compare.py --provider openai
    uv run python labs/skill/done/compare.py --fresh          # ignore the cache, call the model again

Without: a one-line system prompt. With: the same prompt plus the skill catalog (level 1),
and tools that load the skill (level 2) and its files or script (level 3) when the model wants them.
Results are cached in .shopkart/cache/, so a re-run costs nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys

from skill_loader import ROOT, SKILLS_DIR, SkillTools, catalog, chat

from shopkart import budget
from shopkart.llm import LLM
from shopkart.pricing import usd_to_inr

TODAY = "2026-11-17"  # the fixtures' "today"
TICKETS = ["TCK-20104", "TCK-20109", "TCK-20116", "TCK-20130", "TCK-20137"]
CACHE = ROOT / ".shopkart" / "cache" / "skill-compare.json"

BASE = ("You are ShopKart's support Copilot. Write the reply to the customer between <reply> and </reply>. "
        "Only the text inside the tags is sent.")
WITH_SKILL = BASE + (
    "\n\nYou have these skills. When a task matches a skill's description, call load_skill first, "
    "then follow its instructions.\n" + catalog()
)


def ticket_context(ticket_id: str) -> tuple[dict, str]:
    tickets = {t["ticket_id"]: t for t in json.loads((ROOT / "data/tickets.json").read_text(encoding="utf-8"))}
    orders = {o["order_id"]: o for o in json.loads((ROOT / "data/orders.json").read_text(encoding="utf-8"))}
    t = tickets[ticket_id]
    lines = [f"Today is {TODAY}. Ticket {ticket_id}, by {t['channel']}."]
    if (o := orders.get(t["order_id"])):
        items = ", ".join(f"{i['name']} ({i['category']}, ₹{i['unit_price_inr']:,}"
                          f"{', clearance' if i['clearance'] else ''})" for i in o["items"])
        lines.append(f"Order {o['order_id']}: {items}. Status {o['status']}, delivered {o['delivered_on']}, "
                     f"paid by {o['payment_method']}.")
    lines.append(f"Customer: {t['message']}")
    return t, "\n".join(lines)


# ---- simple checks: the same rules the skill states ------------------------------

PROMISE = re.compile(r"refund (has been|is|was) (approved|processed)|we('ll| will) refund|i('ve| have) (approved|refunded)"
                     r"|will be refunded|your refund is confirmed", re.I)
HANDOVER = re.compile(r"colleague|support team|our team|support lead|specialist|human|escalat|team (will|ko)", re.I)
HINGLISH = re.compile(r"\b(aap|aapka|aapki|hai|hain|kar|kijiye|hum|ji|mein|bhej|ghante)\b", re.I)


def the_reply(text: str) -> str:
    """Only what's inside <reply>...</reply> goes to the customer (all of it, if the tags are missing)."""
    m = re.search(r"<reply>(.*?)(</reply>|$)", text, re.S)
    return (m.group(1) if m else text).strip()


def sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.?!।])\s+", text.strip()) if re.search(r"\w", s)])


def checks(ticket: dict, reply: str) -> dict:
    lang_ok = True
    if ticket["language"] in ("hinglish", "hi"):
        lang_ok = bool(HINGLISH.search(reply) or re.search(r"[ऀ-ॿ]", reply))
    needs_handover = ticket["labels"]["expected_action"] == "handover"
    return {
        "sentences": sentences(reply),
        "short": sentences(reply) <= 4 and "\n-" not in reply and "#" not in reply,
        "language": lang_ok,
        "no_promise": not PROMISE.search(reply),
        "handover": (bool(HANDOVER.search(reply)) if needs_handover else None),
    }


# ---- run --------------------------------------------------------------------------


def skill_digest() -> str:
    h = hashlib.sha256()
    for p in sorted(SKILLS_DIR.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def run_one(llm: LLM, ticket_id: str, with_skill: bool, cache: dict, fresh: bool) -> dict:
    key = f"{llm.provider}|{llm.model}|{ticket_id}|{'with' if with_skill else 'without'}|{skill_digest()}"
    if key in cache and not fresh:
        return {**cache[key], "cached": True}
    _, user = ticket_context(ticket_id)
    if with_skill:
        tools = SkillTools()
        out = chat(llm, WITH_SKILL, user, specs=SkillTools.specs, run_tool=tools.call)
        out["loaded"] = tools.loaded
    else:
        out = chat(llm, BASE, user)
        out["loaded"] = []
    out["text"] = the_reply(out["text"])
    cache[key] = out
    return {**out, "cached": False}


def mark(v) -> str:
    return "-" if v is None else ("ok" if v else "NO")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--tickets", nargs="*", default=TICKETS)
    p.add_argument("--fresh", action="store_true", help="ignore the cache")
    args = p.parse_args(argv)

    llm = LLM(args.provider, args.model)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    totals = {False: [0, 0, 0.0], True: [0, 0, 0.0]}  # input tokens, passed checks, cost
    n_checks = {False: 0, True: 0}
    spent_now = 0.0
    try:
        for tid in args.tickets:
            ticket, user = ticket_context(tid)
            print(f"\n=== {tid} [{ticket['language']}] {ticket['message'][:90]}")
            for with_skill in (False, True):
                r = run_one(llm, tid, with_skill, cache, args.fresh)
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
                c = checks(ticket, r["text"])
                passed = [v for k, v in c.items() if k != "sentences" and v is not None]
                totals[with_skill][0] += r["input_tokens"]
                totals[with_skill][1] += sum(passed)
                totals[with_skill][2] += r["cost_usd"]
                n_checks[with_skill] += len(passed)
                if not r["cached"]:
                    spent_now += r["cost_usd"]
                label = "WITH skill   " if with_skill else "WITHOUT skill"
                print(f"--- {label} {r['input_tokens']} in / {r['output_tokens']} out"
                      f"{' (cached)' if r['cached'] else ''}")
                if with_skill:
                    print(f"    loaded: {', '.join(r['loaded']) or 'nothing'}")
                print("    " + r["text"].replace("\n", "\n    "))
                print(f"    sentences {c['sentences']} · short {mark(c['short'])} · language {mark(c['language'])}"
                      f" · no promise {mark(c['no_promise'])} · handover {mark(c['handover'])}")
    except budget.BudgetExceeded as exc:
        print(exc, file=sys.stderr)
        return 2

    print("\n=== Summary")
    for with_skill in (False, True):
        tok, ok, cost = totals[with_skill]
        print(f"{'with skill   ' if with_skill else 'without skill'}  checks passed {ok}/{n_checks[with_skill]}"
              f" · {tok:,} input tokens · ${cost:.6f}")
    print(f"{llm.model} · spent this run ${spent_now:.6f} (₹{usd_to_inr(spent_now):.4f}) · "
          f"today ${budget.spent_today():.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
