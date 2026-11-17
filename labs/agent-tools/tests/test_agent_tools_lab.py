"""The lab's checkpoints, with fake servers (no key, no network, no cost).

Against the finished answer:   uv run pytest labs/agent-tools -q
Against your copy:             LAB=start uv run pytest labs/agent-tools -q
"""

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import anthropic
import httpx2
import openai
import pytest

from shopkart import budget
from tests.fakes import FakeServer, anthropic_message, openai_response

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")


def _load(name: str):
    """Load start/ or done/ under a unique name, with its own `tools` module."""
    sys.path.insert(0, str(FOLDER))
    saved = sys.modules.pop("tools", None)
    try:
        spec = importlib.util.spec_from_file_location(f"agent_tools_lab_{FOLDER.name}_{name}", FOLDER / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(FOLDER))
        sys.modules.pop("tools", None)
        if saved is not None:
            sys.modules["tools"] = saved


agent = _load("agent")
tools = agent.tools


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")
    monkeypatch.delenv("SHOPKART_AUTO_REFUND_UP_TO", raising=False)
    monkeypatch.delenv("SHOPKART_ACTIONS_OFF", raising=False)


def claude_tool_use(*calls, stop="tool_use", in_tok=500, out_tok=40):
    msg = anthropic_message("", in_tok, out_tok, stop_reason=stop)
    msg["content"] = [{"type": "tool_use", "id": f"toolu_{i}", "name": n, "input": a}
                      for i, (n, a) in enumerate(calls, 1)]
    return msg


def openai_function_calls(*calls):
    resp = openai_response("", 500, 40)
    resp["output"] = [{"type": "function_call", "id": f"fc_{i}", "call_id": f"call_{i}", "name": n,
                       "arguments": json.dumps(a), "status": "completed"} for i, (n, a) in enumerate(calls, 1)]
    return resp


def client_for(server: FakeServer):
    http = httpx2.Client(transport=httpx2.MockTransport(server))
    cls = anthropic.Anthropic if server.provider == "anthropic" else openai.OpenAI
    return cls(api_key="sk-fake", http_client=http, max_retries=0)


def run(server, message="Order SK48213 arrived broken", customer="C1001", **limits):
    quiet = []
    result = agent.run_agent(message, tools.Session(customer), provider=server.provider,
                             client=client_for(server), limits=agent.Limits(**limits), trace=quiet.append)
    return result, quiet


# ---- Part 1: the tools ---------------------------------------------------

def test_part1_three_tools_with_verb_object_names():
    assert [t["name"] for t in tools.TOOLS] == ["lookup_order", "check_policy", "draft_refund"]


@pytest.mark.parametrize("spec", tools.TOOLS, ids=lambda t: t["name"])
def test_part1_descriptions_brief_a_new_teammate(spec):
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", spec["description"]) if s.strip()]
    assert len(sentences) >= 3, "what it does, when to use it, what it returns, its limits"
    schema = spec["input_schema"]
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])


def test_part1_inputs_make_mistakes_hard():
    refund = tools.TOOLS[2]["input_schema"]["properties"]
    assert "amount_inr" in refund and refund["amount_inr"]["type"] == "integer"  # rupees, said in the name
    assert "enum" in refund["reason"] and "damaged" in refund["reason"]["enum"]
    assert "customer_id" not in json.dumps(tools.TOOLS)  # comes from the login, never from the model


def test_part1_lookup_returns_a_small_readable_result():
    r = tools.lookup_order(tools.Session("C1001"), "sk-48213")
    assert r["order_id"] == "SK48213" and r["paid_inr"] == 1299 and r["days_since_delivery"] == 4
    assert "7 days" in r["return_window"] and len(json.dumps(r)) < 600


def test_part1_errors_say_what_happened_and_what_to_do():
    text, is_error = tools.run_tool(tools.Session("C1001"), "lookup_order", {"order_id": "48213"})
    assert is_error and "SK48213" in text and "Ask the customer" in text
    # Someone else's order looks exactly like a missing one.
    text, is_error = tools.run_tool(tools.Session("C1001"), "lookup_order", {"order_id": "SK48450"})
    assert is_error and "No order SK48450 for this customer" in text


def test_part1_check_policy_cites_its_source():
    r = tools.check_policy(tools.Session("C1001"), "return_window")
    assert "Returns and Refunds Policy" in r["source"] and "14 days" in r["text"] and "10 days" in r["text"]


# ---- Part 1: the loop ----------------------------------------------------

def test_part1_claude_loop_sends_request_then_result_with_matching_id():
    server = FakeServer("anthropic", [claude_tool_use(("lookup_order", {"order_id": "SK48213"})),
                                      anthropic_message("Sorry about that! Your order was delivered on 13 Nov.")])
    result, trace = run(server)
    assert result.stop == "end" and result.steps == 2 and result.tool_calls == ["lookup_order"]
    second = server.requests[1]["messages"]
    assert second[1]["role"] == "assistant" and second[1]["content"][0]["type"] == "tool_use"
    block = second[2]["content"][0]
    assert block["type"] == "tool_result" and block["tool_use_id"] == "toolu_1" and block["is_error"] is False
    assert "input_schema" in server.requests[0]["tools"][0]
    assert budget.spent_today() == pytest.approx(result.cost_usd) and result.cost_usd > 0


def test_part1_openai_loop_sends_function_call_then_output():
    server = FakeServer("openai", [openai_function_calls(("lookup_order", {"order_id": "SK48213"})),
                                   openai_response("Your order was delivered on 13 Nov.")])
    result, _ = run(server)
    assert result.stop == "end" and result.steps == 2
    items = server.requests[1]["input"]
    assert any(i.get("type") == "function_call" and i["call_id"] == "call_1" for i in items)
    out = next(i for i in items if i.get("type") == "function_call_output")
    assert out["call_id"] == "call_1" and "SK48213" in out["output"]
    assert "parameters" in server.requests[0]["tools"][0]


def test_part1_several_tools_in_one_turn_go_back_together():
    server = FakeServer("anthropic", [claude_tool_use(("lookup_order", {"order_id": "SK48213"}),
                                                      ("check_policy", {"topic": "damaged_items"})),
                                      anthropic_message("Done.")])
    run(server)
    results = server.requests[1]["messages"][2]["content"]
    assert [r["tool_use_id"] for r in results] == ["toolu_1", "toolu_2"]


def test_part1_tool_errors_go_back_to_the_model():
    server = FakeServer("anthropic", [claude_tool_use(("lookup_order", {"order_id": "48213"})),
                                      anthropic_message("Could you confirm the order ID?")])
    run(server)
    block = server.requests[1]["messages"][2]["content"][0]
    assert block["is_error"] is True and "SK48213" in block["content"]
    server = FakeServer("openai", [openai_function_calls(("lookup_order", {"order_id": "48213"})),
                                   openai_response("Could you confirm the order ID?")])
    run(server)
    out = next(i for i in server.requests[1]["input"] if i.get("type") == "function_call_output")
    assert out["output"].startswith("ERROR:")


# ---- Part 2: stopping conditions -----------------------------------------

def test_part2_turn_limit_hands_over():
    replies = [claude_tool_use(("lookup_order", {"order_id": f"SK4821{i}"})) for i in range(5)]
    result, trace = run(FakeServer("anthropic", replies), max_steps=3)
    assert result.stop == "max_steps" and result.steps == 3 and result.answer == agent.HANDOVER


def test_part2_repeat_check_stops_the_same_call_the_third_time():
    replies = [claude_tool_use(("lookup_order", {"order_id": "SK48213"})) for _ in range(5)]
    server = FakeServer("anthropic", replies)
    result, _ = run(server)
    assert result.stop == "repeat" and server.calls == 3


def test_part2_spend_cap_stops_before_the_next_call():
    server = FakeServer("anthropic", [claude_tool_use(("lookup_order", {"order_id": "SK48213"}), in_tok=5000),
                                      anthropic_message("never sent")])
    result, _ = run(server, max_usd=0.0001)
    assert result.stop == "spend_cap" and server.calls == 1


def test_part2_cut_off_reply_is_not_done_and_its_tool_never_runs():
    server = FakeServer("anthropic", [claude_tool_use(("draft_refund", {"order_id": "SK48213", "amount_inr": 1299,
                                                                        "reason": "damaged"}), stop="max_tokens")])
    result, _ = run(server)
    assert result.stop == "cut_off" and result.tool_calls == [] and tools.load_refunds() == []


def test_part2_daily_budget_blocks_the_call(monkeypatch):
    monkeypatch.setenv("DAILY_BUDGET_USD", "0")
    server = FakeServer("anthropic", [anthropic_message("never sent")])
    result, _ = run(server)
    assert result.stop == "daily_budget" and server.calls == 0


# ---- Part 2: approvals and spending limits -------------------------------

def draft(customer, order_id, amount, reason="damaged"):
    return tools.run_tool(tools.Session(customer), "draft_refund",
                          {"order_id": order_id, "amount_inr": amount, "reason": reason})


def test_part2_every_refund_waits_for_a_person_in_the_lab():
    text, is_error = draft("C1001", "SK48213", 1299)
    assert not is_error and json.loads(text)["status"] == "waiting for approval"
    assert tools.load_refunds()[0]["status"] == "pending"


def test_part2_above_5000_always_goes_to_a_person(monkeypatch):
    monkeypatch.setenv("SHOPKART_AUTO_REFUND_UP_TO", "20000")  # someone raised the limit too far
    text, _ = draft("C1008", "SK48488", 9499)
    assert "above the ₹5,000 limit" in " ".join(json.loads(text)["why_a_person"])
    text, _ = draft("C1001", "SK48213", 1299)  # small and inside policy: runs automatically
    assert json.loads(text)["status"].startswith("refund started")


def test_part2_already_refunded_order_is_blocked_and_logged():
    text, is_error = draft("C1007", "SK48450", 18999)
    assert is_error and "already refunded in full" in text and tools.load_refunds() == []
    audit = (tools.store_dir() / "audit.jsonl").read_text()
    assert '"event": "refund_blocked"' in audit


def test_part2_never_more_than_was_paid():
    text, is_error = draft("C1001", "SK48213", 1499)
    assert is_error and "Maximum refundable ₹1,299" in text


def test_part2_outside_the_window_needs_a_person():
    text, _ = draft("C1003", "SK47731", 2799, "other")
    assert "outside the 10-day return window" in " ".join(json.loads(text)["why_a_person"])


def test_part2_drafting_twice_returns_the_same_draft():
    first, _ = draft("C1001", "SK48213", 1299)
    second, _ = draft("C1001", "SK48213", 1299)
    assert json.loads(first)["draft_id"] == json.loads(second)["draft_id"] and len(tools.load_refunds()) == 1


def test_part2_kill_switch_turns_off_actions(monkeypatch):
    monkeypatch.setenv("SHOPKART_ACTIONS_OFF", "1")
    text, is_error = draft("C1001", "SK48213", 1299)
    assert is_error and "switched off" in text
    assert not tools.run_tool(tools.Session("C1001"), "lookup_order", {"order_id": "SK48213"})[1]


def test_part2_approving_twice_pays_once():
    draft_id = json.loads(draft("C1001", "SK48213", 1299)[0])["draft_id"]
    first = tools.approve(draft_id, "lead")
    second = tools.approve(draft_id, "lead")
    assert first["refund_id"] == second["refund_id"]
    assert sum(r["status"] == "issued" for r in tools.load_refunds()) == 1


def test_part2_desk_approves_edits_and_rejects():
    a = json.loads(draft("C1001", "SK48213", 1299)[0])["draft_id"]
    b = json.loads(draft("C1008", "SK48488", 9499)[0])["draft_id"]
    answers = iter(["e", "999", "r", "No photo of the damage yet"])
    shown = []
    rows = agent.approval_desk([a, b], ask=lambda _: next(answers), show=shown.append)
    assert [r["status"] for r in rows] == ["issued", "rejected"] and rows[0]["amount_inr"] == 999
    screen = "\n".join(shown)
    assert "Refund ₹1,299" in screen and "paid ₹9,499" in screen and "above the ₹5,000 limit" in screen
    events = [json.loads(l)["event"] for l in (tools.store_dir() / "audit.jsonl").read_text().splitlines()]
    assert "refund_edited" in events and "refund_issued" in events and "refund_rejected" in events


def test_part2_whole_run_drafts_then_waits():
    server = FakeServer("anthropic", [
        claude_tool_use(("lookup_order", {"order_id": "SK48488"}), ("check_policy", {"topic": "damaged_items"})),
        claude_tool_use(("draft_refund", {"order_id": "SK48488", "amount_inr": 9499, "reason": "damaged"})),
        anthropic_message("A support lead will review your refund request within one working day."),
    ])
    result, trace = run(server, customer="C1008")
    assert result.stop == "end" and result.drafts == ["RD-48488-1"] and result.steps == 3
    assert any("draft_refund" in line for line in trace) and tools.find_draft("RD-48488-1")["status"] == "pending"
