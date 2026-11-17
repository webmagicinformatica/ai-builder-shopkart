"""Step 1: the fragile mega-prompt. One call does everything, for 10 tickets.

Run:  uv run python labs/prompt-chain/done/mega.py [--ticket TCK-20116] [--provider openai] [--fresh]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import textwrap

import facts
from calls import Caller
from checks import problems
from promptfiles import load_prompt

DECISIONS = {"allowed", "denied", "handover"}
KEYS = {"order_id", "decision", "policy_section", "reply"}


def order_record(order_id: str | None) -> str:
    """The raw order, as the old app pasted it (minus our fixture notes, which give the answer away)."""
    order = facts.orders().get(order_id or "")
    if order is None:
        return "(no order found)"
    return json.dumps({k: v for k, v in order.items() if k != "note"}, indent=1, ensure_ascii=False)


def parse(text: str) -> tuple[dict, bool]:
    """(answer, format_ok). The app does json.loads on the raw text, so anything else is broken.
    We still dig the JSON out of a broken answer, to see what it decided."""
    try:
        data = json.loads(text)
        ok = isinstance(data, dict) and set(data) == KEYS and data.get("decision") in DECISIONS
        return (data if isinstance(data, dict) else {}), ok
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, flags=re.S)
    try:
        return (json.loads(m.group(0)) if m else {}), False
    except json.JSONDecodeError:
        return {}, False


def run_mega(caller: Caller, case: dict, version: str = "v1") -> dict:
    ticket = facts.tickets()[case["ticket_id"]]
    prompt = load_prompt("mega", version)
    answer = caller.ask(prompt, {
        "policies": facts.policy_block(sorted(facts.policies())),   # everything we have
        "today": facts.today().strftime("%A %d %B %Y"),
        "order": order_record(ticket["order_id"]),
        "message": ticket["message"],
    })
    data, ok = parse(answer.text)
    decision = data.get("decision")
    reply = str(data.get("reply", ""))
    return {"ticket_id": case["ticket_id"], "expected": case["expected"], "decision": decision,
            "policy_section": data.get("policy_section"), "reply": reply, "format_ok": ok,
            "raw": answer.text, "problems": problems(case, decision, reply, format_ok=ok, max_words=120),
            "versions": {"mega": version}, "cost_usd": answer.cost_usd}


def show(row: dict) -> None:
    mark = "ok" if not row["problems"] else "✗ " + "; ".join(row["problems"])
    print(f"{row['ticket_id']}  expected {row['expected']:<8} got {str(row['decision']):<8} {mark}")
    if not row["format_ok"]:
        first = row["raw"].strip().splitlines()[0] if row["raw"].strip() else ""
        print(f"    json.loads() fails: the answer starts with {first[:40]!r}")
    print(textwrap.indent(textwrap.fill(row["reply"] or row["raw"][:300], 96), "    "))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provider", default=None, choices=["anthropic", "openai"])
    ap.add_argument("--ticket", help="run one ticket only")
    ap.add_argument("--fresh", action="store_true", help="ignore the cache and call the API again")
    args = ap.parse_args(argv)

    caller = Caller(provider=args.provider or os.environ.get("LLM_PROVIDER", "anthropic"), fresh=args.fresh)
    cases = [c for c in facts.cases() if args.ticket in (None, c["ticket_id"])]
    if not cases:
        ap.error(f"{args.ticket} is not one of the lab's tickets (see cases.json)")
    rows = [run_mega(caller, case) for case in cases]
    for row in rows:
        show(row)
    bad = sum(bool(r["problems"]) for r in rows)
    print(f"\nmega.v1: {len(rows) - bad}/{len(rows)} clean · {caller.answers[0].model} · {caller.summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
