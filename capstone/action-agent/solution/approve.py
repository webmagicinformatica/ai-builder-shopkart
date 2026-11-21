"""The approval desk: a support lead decides, our code runs exactly that, once.

    uv run python capstone/action-agent/solution/approve.py list
    uv run python capstone/action-agent/solution/approve.py approve AP-48488-1 --by priya.lead
    uv run python capstone/action-agent/solution/approve.py reject AP-48488-1 --by priya.lead --why "no photo yet"
    uv run python capstone/action-agent/solution/approve.py audit

No model is called here. Approving re-checks the order against the rules (it may
have changed since the request), runs the saved action, and a second click pays nothing.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE.parents[2], HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import rules  # noqa: E402
import store  # noqa: E402
from shopkart import data  # noqa: E402


class NotAllowed(Exception):
    pass


def screen(row: dict) -> list[str]:
    """What the approver sees: the exact action, evidence from OUR order system, and why."""
    o = data.get_order(row["order_id"])
    left = rules.refundable_left(o, store.issued_on(o["order_id"]))
    return [
        f"{row['id']}  Refund ₹{row['amount_inr']:,} to the original {o['payment_method'].upper()} payment "
        f"· order {o['order_id']} · reason {row['reason']}",
        f"   Evidence  delivered {o['delivered_on']} ({data.days_since_delivery(o)} days ago) · "
        f"paid ₹{o['total_inr']:,} · still refundable ₹{left:,} · "
        + "; ".join(f"{i['qty']} x {i['name']}" for i in o["items"]),
        f"   Why       {'; '.join(row['why'])}",
    ]


def approve(row_id: str, by: str) -> dict:
    row = store.get(row_id)
    if row is None:
        raise NotAllowed(f"No request {row_id}.")
    if row["status"] != "pending":
        return row  # already decided: approving twice must not pay twice
    if not by or by in ("auto", "agent"):
        raise NotAllowed("An approval needs a person's name.")
    order = data.get_order(row["order_id"])
    age = datetime.now() - datetime.fromisoformat(row["created"])
    left = rules.refundable_left(order, store.issued_on(row["order_id"]))
    if age > store.APPROVAL_EXPIRES or row["amount_inr"] > left:
        store.update(row_id, status="expired")
        store.audit("approval_expired", id=row_id, by=by, refundable_now=left, age_hours=round(age.total_seconds() / 3600, 1))
        raise NotAllowed(f"{row_id} is stale (₹{left:,} refundable now). Ask the agent to check again.")
    row = store.update(row_id, status="issued", approved_by=by, decided=store.now().isoformat())
    store.audit("refund_issued", id=row_id, order_id=row["order_id"], amount_inr=row["amount_inr"],
                decision="approved", by=by)
    return row


def reject(row_id: str, by: str, why: str) -> dict:
    row = store.get(row_id)
    if row is None:
        raise NotAllowed(f"No request {row_id}.")
    if row["status"] == "pending":
        row = store.update(row_id, status="rejected", approved_by=by, rejected_because=why)
        store.audit("refund_rejected", id=row_id, order_id=row["order_id"], by=by, why=why)
    return row


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Approve or reject refunds the agent couldn't run on its own.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in ("approve", "reject"):
        s = sub.add_parser(name)
        s.add_argument("id")
        s.add_argument("--by", required=True, help="the approver's name")
        if name == "reject":
            s.add_argument("--why", default="rejected")
    sub.add_parser("audit")
    a = p.parse_args(argv)

    if a.cmd == "list":
        pending = [r for r in store.load() if r["status"] == "pending"]
        print(f"{len(pending)} waiting for a person")
        for r in pending:
            print("\n".join(screen(r)))
        return 0
    if a.cmd == "audit":
        for r in store.read_audit():
            extra = {k: v for k, v in r.items() if k not in ("time", "event", "prev", "hash")}
            print(f"{r['time'][11:]}  {r['event']:<20} {r['hash'][:8]}  "
                  + " ".join(f"{k}={v}" for k, v in extra.items() if v not in (None, [], ""))[:150])
        ok, msg = store.verify()
        print(f"\nAudit chain: {msg}" if ok else f"\nAudit chain BROKEN: {msg}")
        return 0 if ok else 1
    before = (store.get(a.id) or {}).get("status")
    try:
        row = approve(a.id, a.by) if a.cmd == "approve" else reject(a.id, a.by, a.why)
    except NotAllowed as err:
        print(f"Not done: {err}")
        return 1
    if before != "pending":
        print(f"{row['id']}: already {row['status']} by {row['approved_by']}. Nothing paid again.")
        return 0
    print(f"{row['id']}: {row['status']} by {row['approved_by']} · ₹{row['amount_inr']:,} · order {row['order_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
