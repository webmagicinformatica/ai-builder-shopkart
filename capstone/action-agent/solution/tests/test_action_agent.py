"""Offline checks for the capstone model solution: no key, no network, no cost.

    uv run pytest capstone/action-agent -q
"""

import copy
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

SOLUTION = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SOLUTION))
for name in ("tools", "agent", "rules", "store", "approve", "evals"):  # other labs use the same names
    sys.modules.pop(name, None)

import agent  # noqa: E402
import approve  # noqa: E402
import evals  # noqa: E402
import rules  # noqa: E402
import store  # noqa: E402
import tools  # noqa: E402
from shopkart import budget, data  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")
    monkeypatch.delenv("SHOPKART_ACTIONS_OFF", raising=False)


def order(oid):
    return copy.deepcopy(data.get_order(oid))


def run(message, customer, script, **limits):
    brain = evals.ScriptedBrain(script)
    r = agent.run_agent(message, tools.Session(customer), brain, agent.Limits(**limits), trace=lambda s: None)
    return r, brain


L = lambda o: {"tool": "lookup_order", "args": {"order_id": o}}  # noqa: E731
R = lambda o, why="damaged": {"tool": "request_refund", "args": {"order_id": o, "reason": why, "opened": True}}  # noqa: E731


# ---------------------------------------------------------------- the rules, in code


def test_windows_14_footwear_10_electronics_7():
    assert rules.window_days("clothing") == 14
    assert rules.window_days("footwear") == 10
    assert rules.window_days("electronics") == 7


def test_small_damaged_item_in_window_refunds_automatically():
    d = rules.decide(order("SK48213"), "damaged")
    assert (d.outcome, d.amount_inr) == ("refund", 1299)


def test_above_5000_always_needs_a_person():
    d = rules.decide(order("SK48488"), "damaged")
    assert (d.outcome, d.amount_inr) == ("needs_approval", 9499)
    assert "₹5,000" in d.why[0]


def test_footwear_after_10_days_is_not_eligible():
    d = rules.decide(order("SK47731"), "changed_mind")  # delivered 12 days ago
    assert d.outcome == "not_eligible" and d.amount_inr == 0 and "10 days" in d.why[0]


def test_damaged_electronics_after_7_days_is_not_eligible():
    o = order("SK48213")
    assert rules.decide(o, "damaged", on=data.today() + timedelta(days=3)).outcome == "refund"  # day 7
    assert rules.decide(o, "damaged", on=data.today() + timedelta(days=4)).outcome == "not_eligible"  # day 8


def test_opened_electronics_only_if_faulty():
    assert rules.decide(order("SK48344"), "changed_mind", opened=True).outcome == "not_eligible"
    assert rules.decide(order("SK48344"), "changed_mind", opened=False).outcome == "refund"
    assert rules.decide(order("SK48344"), "defective", opened=True).outcome == "refund"


def test_never_more_than_was_paid():
    assert rules.decide(order("SK48450"), "damaged").outcome == "not_eligible"  # the Friday test
    d = rules.decide(order("SK48213"), "damaged", issued_here=1000)
    assert d.amount_inr == 299


def test_third_request_and_daily_cap_go_to_a_person():
    assert rules.decide(order("SK48213"), "damaged", refunds_last_30_days=2).outcome == "needs_approval"
    assert rules.decide(order("SK48213"), "damaged", auto_today_inr=49_000).outcome == "needs_approval"


def test_clearance_and_undelivered():
    assert rules.decide(order("SK48102"), "damaged").outcome == "not_eligible"  # clearance: exchange first
    o = order("SK48213")
    o["delivered_on"] = None
    assert rules.decide(o, "damaged").outcome == "not_eligible"


# ---------------------------------------------------------------- tools


def test_someone_elses_order_looks_like_a_missing_one():
    s = tools.Session("C1001")
    mine_missing, err1 = tools.run_tool(s, "lookup_order", {"order_id": "SK99999"})
    theirs, err2 = tools.run_tool(s, "lookup_order", {"order_id": "SK48488"})
    assert err1 and err2 and theirs.replace("SK48488", "X") == mine_missing.replace("SK99999", "X")


def test_amount_comes_from_code_and_asking_twice_queues_once():
    s = tools.Session("C1008")
    first = json.loads(tools.run_tool(s, "request_refund", {"order_id": "SK48488", "reason": "damaged", "opened": True})[0])
    again = json.loads(tools.run_tool(s, "request_refund", {"order_id": "SK48488", "reason": "damaged", "opened": True})[0])
    assert first["outcome"] == "needs_approval" and first["amount_inr"] == 9499
    assert again["id"] == first["id"] and len(store.load()) == 1


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("SHOPKART_ACTIONS_OFF", "1")
    text, err = tools.run_tool(tools.Session("C1001"), "request_refund",
                               {"order_id": "SK48213", "reason": "damaged", "opened": True})
    assert err and "switched off" in text and store.load() == []


# ---------------------------------------------------------------- the loop and its exits


def test_end_to_end_small_refund():
    r, _ = run("Watch SK48213 cracked, refund please", "C1001", [[L("SK48213")], [R("SK48213")], "Done, ₹1,299."])
    assert r.stop == "end" and r.outcome == "refund" and r.steps == 3
    assert [x["status"] for x in store.load()] == ["issued"]


def test_max_steps_hands_over():
    r, _ = run("hi", "C1001", [[L("SK48213")], [{"tool": "check_policy", "args": {"topic": "exceptions"}}]] * 3, max_steps=2)
    assert r.stop == "max_steps" and r.answer == agent.HANDOVER


def test_spend_cap_hands_over():
    r, _ = run("hi", "C1001", [[L("SK48213")]], max_usd=0.0002)  # ~$0.00011 a call
    assert r.stop == "spend_cap" and r.steps == 2


def test_repeat_is_a_loop_not_progress():
    r, _ = run("hi", "C1001", [[L("SK48213")]])
    assert r.stop == "repeat" and r.steps == 3


def test_daily_budget(monkeypatch):
    monkeypatch.setenv("DAILY_BUDGET_USD", "0")
    r, _ = run("hi", "C1001", ["never called"])
    assert r.stop == "daily_budget" and r.steps == 0


def test_cut_off_reply_never_runs_a_tool():
    class CutOff(evals.ScriptedBrain):
        def turn(self, max_tokens):
            return agent.Turn([("c1", "request_refund", {"order_id": "SK48213"})], "", "max_tokens", 900, 600)
    r = agent.run_agent("hi", tools.Session("C1001"), CutOff([]), trace=lambda s: None)
    assert r.stop == "cut_off" and store.load() == []


def test_one_refund_request_per_conversation():
    r, brain = run("refund", "C1001", [[R("SK48213")], [R("SK48305")], "ok"])
    assert len(store.load()) == 1 and "already requested" in brain.seen[-1]


def test_guards_mask_pii_and_block_false_promises():
    r, brain = run("SK48488 broken. Card 4111 1111 1111 1111", "C1008",
                   [[R("SK48488")], "Your refund is approved and processed."])
    assert "4111" not in brain.seen[0] and "<customer_message>" in brain.seen[0]
    assert "false promise" in r.flags and not agent.PROMISE.search(r.answer)


# ---------------------------------------------------------------- approval desk and audit trail


def queued():
    tools.run_tool(tools.Session("C1008"), "request_refund", {"order_id": "SK48488", "reason": "damaged", "opened": True})
    return store.load()[0]["id"]


def test_approve_pays_once():
    rid = queued()
    assert approve.approve(rid, "priya.lead")["status"] == "issued"
    approve.approve(rid, "priya.lead")
    assert store.issued_on("SK48488") == 9499


def test_approval_needs_a_person_and_expires():
    rid = queued()
    with pytest.raises(approve.NotAllowed):
        approve.approve(rid, "agent")
    old = (datetime.now() - timedelta(hours=49)).isoformat()
    store.update(rid, created=old)
    with pytest.raises(approve.NotAllowed):
        approve.approve(rid, "priya.lead")
    assert store.get(rid)["status"] == "expired" and store.issued_on("SK48488") == 0


def test_reject():
    rid = queued()
    assert approve.reject(rid, "priya.lead", "no photo")["status"] == "rejected"
    assert approve.approve(rid, "priya.lead")["status"] == "rejected"


def test_audit_chain_catches_an_edit():
    queued()
    approve.approve(store.load()[0]["id"], "priya.lead")
    assert store.verify()[0]
    path = store.store_dir() / "audit.jsonl"
    lines = path.read_text().splitlines()
    row = json.loads(lines[0])
    row["amount_inr"] = 1
    lines[0] = json.dumps(row, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n")
    ok, msg = store.verify()
    assert not ok and "line 1" in msg


# ---------------------------------------------------------------- the eval and red-team set


def test_offline_eval_all_tasks_correct_all_attacks_held():
    for case in agent.load_cases():
        _, problems = evals.run_case(case, evals.ScriptedBrain(case["script"]))
        assert problems == [], (case["id"], problems)
