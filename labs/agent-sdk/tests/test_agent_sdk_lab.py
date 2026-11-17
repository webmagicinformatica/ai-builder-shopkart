"""The SDK lab's checkpoints, offline (no key, no network, no cost).

Needs the SDKs:   uv sync --group agents
Then:             uv run pytest labs/agent-sdk -q        (LAB=start for your copy)

The OpenAI Agents SDK runs end to end against a fake Responses server.
The Claude Agent SDK needs its CLI and the real API to run the loop, so here we
test the parts we wrote: the tools, the approval callback and the hooks.
"""

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

import httpx2
import pytest

pytest.importorskip("claude_agent_sdk", reason="uv sync --group agents")
pytest.importorskip("agents", reason="uv sync --group agents")

import openai  # noqa: E402
from agents import OpenAIProvider, set_tracing_disabled  # noqa: E402
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny  # noqa: E402

from shopkart import budget  # noqa: E402
from tests.fakes import FakeServer, openai_response  # noqa: E402

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")
HAND_BUILT = LAB.parent / "agent-tools" / "done"

set_tracing_disabled(True)  # traces would go to OpenAI: not in tests


def _load(name: str):
    for p in (str(HAND_BUILT), str(FOLDER)):
        sys.path.insert(0, p)
    try:
        spec = importlib.util.spec_from_file_location(f"agent_sdk_lab_{FOLDER.name}_{name}", FOLDER / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(HAND_BUILT))
        sys.path.remove(str(FOLDER))


claude_sdk = _load("claude_sdk_agent")
openai_sdk = _load("openai_sdk_agent")
compare = _load("compare")
tools = claude_sdk.tools
hand_built = claude_sdk.hand_built


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")
    monkeypatch.delenv("SHOPKART_AUTO_REFUND_UP_TO", raising=False)


# ---- the same agent ------------------------------------------------------

def test_same_tools_same_descriptions():
    sdk_tools = claude_sdk.build_tools(tools.Session("C1001"), {})
    assert [(t.name, t.description) for t in sdk_tools] == [(t["name"], t["description"]) for t in tools.TOOLS]
    oa = {t.name: t for t in (openai_sdk.lookup_order, openai_sdk.check_policy, openai_sdk.draft_refund)}
    assert all(oa[t["name"]].description == t["description"] for t in tools.TOOLS)
    assert oa["draft_refund"].params_json_schema["properties"]["reason"]["enum"] == tools.REASONS


def test_lines_of_code_are_counted_without_comments(tmp_path):
    f = tmp_path / "x.py"
    f.write_text('"""doc"""\n\n# comment\nx = 1  # note\ndef f():\n    """doc"""\n    return x\n')
    assert compare.code_lines(f) == 3


# ---- Claude Agent SDK: our tools, approval callback and hooks -----------

def test_claude_reads_run_without_asking_and_refunds_ask_first():
    options = claude_sdk.make_options(tools.Session("C1001"), hand_built.Run("", ""), hand_built.Limits(),
                                      "claude-haiku-5-5", ask=input, trace=print, approver="lead")
    assert options.allowed_tools == ["mcp__shopkart__lookup_order", "mcp__shopkart__check_policy"]
    assert options.tools == [] and options.max_turns == 10 and options.max_budget_usd == 0.10
    assert options.system_prompt == hand_built.SYSTEM and options.setting_sources == []


def test_claude_tool_errors_keep_our_wording():
    handler = {t.name: t for t in claude_sdk.build_tools(tools.Session("C1001"), {})}["lookup_order"].handler
    out = asyncio.run(handler({"order_id": "48213"}))
    assert out["is_error"] is True and "SK48213" in out["content"][0]["text"]


def test_claude_approval_callback_asks_a_person_then_issues():
    session = tools.Session("C1001")
    run = hand_built.Run(answer="", stop="")
    shown: list = []
    options = claude_sdk.make_options(session, run, hand_built.Limits(), "claude-haiku-5-5",
                                      ask=lambda _: "a", trace=shown.append, approver="lead")
    args = {"order_id": "SK48213", "amount_inr": 1299, "reason": "damaged"}
    decision = asyncio.run(options.can_use_tool("mcp__shopkart__draft_refund", args, None))
    assert isinstance(decision, PermissionResultAllow) and any("Refund ₹1,299" in l for l in shown)


def test_claude_approval_callback_rejects_with_a_reason():
    run = hand_built.Run(answer="", stop="")
    answers = iter(["r", "Photo needed"])
    options = claude_sdk.make_options(tools.Session("C1008"), run, hand_built.Limits(), "claude-haiku-5-5",
                                      ask=lambda _: next(answers), trace=lambda _: None, approver="lead")
    args = {"order_id": "SK48488", "amount_inr": 9499, "reason": "damaged"}
    decision = asyncio.run(options.can_use_tool("mcp__shopkart__draft_refund", args, None))
    assert isinstance(decision, PermissionResultDeny) and "Photo needed" in decision.message
    assert tools.load_refunds() == []


def test_claude_blocked_refund_needs_no_person():
    options = claude_sdk.make_options(tools.Session("C1007"), hand_built.Run("", ""), hand_built.Limits(),
                                      "claude-haiku-5-5", ask=lambda _: pytest.fail("asked a person"),
                                      trace=lambda _: None, approver="lead")
    args = {"order_id": "SK48450", "amount_inr": 18999, "reason": "damaged"}
    assert isinstance(asyncio.run(options.can_use_tool("x", args, None)), PermissionResultAllow)


def test_claude_hook_denies_the_third_identical_call():
    run = hand_built.Run(answer="", stop="")
    options = claude_sdk.make_options(tools.Session("C1001"), run, hand_built.Limits(), "claude-haiku-5-5",
                                      ask=input, trace=lambda _: None, approver="lead")
    hook = options.hooks["PreToolUse"][0].hooks[0]
    call = {"tool_name": "mcp__shopkart__lookup_order", "tool_input": {"order_id": "SK48213"}}
    outs = [asyncio.run(hook(call, "t", None)) for _ in range(3)]
    assert outs[:2] == [{}, {}] and outs[2]["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert run.stop == "repeat"


# ---- OpenAI Agents SDK: the whole run against a fake server -------------

def function_call(name, args, n=1):
    resp = openai_response("", 500, 40)
    resp["output"] = [{"type": "function_call", "id": f"fc_{n}", "call_id": f"call_{n}", "name": name,
                       "arguments": json.dumps(args), "status": "completed"}]
    return resp


def run_openai(replies, customer="C1001", answers=("a",), **limits):
    server = FakeServer("openai", replies)
    client = openai.AsyncOpenAI(api_key="sk-fake", max_retries=0,
                                http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(server)))
    ans = iter(answers)
    shown: list = []
    run = asyncio.run(openai_sdk.run_openai_sdk(
        "My smartwatch SK48213 arrived cracked", tools.Session(customer), ask=lambda _: next(ans),
        trace=shown.append, limits=hand_built.Limits(**limits),
        model_provider=OpenAIProvider(openai_client=client, use_responses=True)))
    return run, server, shown


def test_openai_sdk_runs_the_loop_and_we_count_the_cost():
    run, server, shown = run_openai([function_call("lookup_order", {"order_id": "SK48213"}),
                                     openai_response("Sorry! Your order was delivered on 13 Nov.")])
    assert run.stop == "end" and run.steps == 2 and run.tool_calls == ["lookup_order"]
    assert run.cost_usd > 0 and budget.spent_today() == pytest.approx(run.cost_usd)
    assert any("lookup_order" in line for line in shown)


def test_openai_sdk_passes_our_error_wording():
    run, server, _ = run_openai([function_call("lookup_order", {"order_id": "48213"}),
                                 openai_response("Could you confirm your order ID?")])
    out = next(i for i in server.requests[1]["input"] if i.get("type") == "function_call_output")
    assert out["output"].startswith("ERROR:") and "SK48213" in out["output"]


def test_openai_sdk_pauses_for_approval_then_issues():
    args = {"order_id": "SK48213", "amount_inr": 1299, "reason": "damaged"}
    run, server, shown = run_openai([function_call("draft_refund", args),
                                     openai_response("Your refund has been approved and started.")])
    assert run.stop == "end" and any("Approval needed" in l for l in shown)
    row = tools.load_refunds()[0]
    assert row["status"] == "issued" and row["approved_by"] == "support.lead"


def test_openai_sdk_rejection_reaches_the_model():
    args = {"order_id": "SK48213", "amount_inr": 1299, "reason": "damaged"}
    run, server, _ = run_openai([function_call("draft_refund", args),
                                 openai_response("A colleague will contact you.")], answers=("r", "Photo needed"))
    out = next(i for i in server.requests[-1]["input"] if i.get("type") == "function_call_output")
    assert "Photo needed" in out["output"] and tools.load_refunds() == []


def test_openai_sdk_turn_limit_hands_over():
    replies = [function_call("lookup_order", {"order_id": f"SK4821{i}"}, i) for i in range(5)]
    run, server, _ = run_openai(replies, max_steps=2)
    assert run.stop == "max_steps" and run.answer == hand_built.HANDOVER
