"""The lab's checkpoints, with fake models (no key, no network, no cost).

Against the finished answer:   uv run pytest labs/prompt-chain -q
Against your copy:             LAB=start uv run pytest labs/prompt-chain -q
Prompt changed on purpose?     UPDATE_SNAPSHOTS=1 uv run pytest labs/prompt-chain -q   (then review the diff)
"""

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

from shopkart import budget
from shopkart.llm import Result
from tests.fakes import FakeServer, anthropic_message

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")
SNAPSHOTS = Path(__file__).resolve().parent / "snapshots"
NAMES = ["facts", "promptfiles", "calls", "checks", "mega", "chain"]


def _load_lab():
    """Import the lab's modules from start/ or done/, then forget their short names
    (other labs may have their own `chain.py`)."""
    sys.path.insert(0, str(FOLDER))
    try:
        for name in NAMES:
            sys.modules.pop(name, None)
        return {name: importlib.import_module(name) for name in NAMES}
    finally:
        sys.path.remove(str(FOLDER))
        for name in NAMES:
            sys.modules.pop(name, None)


m = _load_lab()
facts, promptfiles, calls, checks, mega, chain = (m[n] for n in NAMES)
CASES = {c["ticket_id"]: c for c in facts.cases()}
V1 = {"extract": "v1", "decide": "v1", "write": "v1"}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setattr(chain, "TRACE", tmp_path / "trace.jsonl")
    monkeypatch.setattr(calls, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.delenv("SHOPKART_TODAY", raising=False)


class FakeLLM:
    """Answers each call with the next reply in the list; remembers what it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def complete(self, messages, *, system=None, max_tokens=1024, schema=None):
        self.sent.append({"messages": messages, "system": system, "schema": schema})
        text = self.replies.pop(0)
        if not isinstance(text, str):
            text = json.dumps(text)
        return Result(text=text, parsed=schema.model_validate_json(text) if schema else None,
                      input_tokens=1000, output_tokens=50, cost_usd=0.000125, cost_inr=0.011,
                      latency_s=0.01, model="claude-haiku-5-5", provider="anthropic")


def caller_with(replies):
    fake = FakeLLM(replies)
    return calls.Caller(make_llm=lambda provider, model: fake), fake


def extraction(order_id="SK48213", category="electronics", issue="damaged", language="en", **kw):
    return {"order_id": order_id, "item_category": category, "issue": issue,
            "issue_summary": "It arrived broken.", "amount_inr": None, "sentiment": "upset",
            "language": language, **kw}


def decision(d="allowed", section="damaged-items §2", rule="Damaged electronics: report within 7 days."):
    return {"decision": d, "rule": rule, "policy_section": section, "reason": "Delivered 4 days ago."}


# ---- prompts as files ------------------------------------------------------

def test_prompts_load_by_name_and_version_with_their_model():
    for name in ("mega", "extract", "decide", "write"):
        p = promptfiles.load_prompt(name, "v1")
        assert p.id == f"{name}.v1" and p.system and p.user
        assert p.model("anthropic") == "claude-haiku-5-5" and p.model("openai") == "gpt-6-luna"
        assert p.max_tokens > 0


def test_unknown_version_lists_what_exists():
    with pytest.raises(promptfiles.PromptError, match="write.v1.md"):
        promptfiles.load_prompt("write", "v9")


def test_render_refuses_missing_or_unused_values():
    p = promptfiles.load_prompt("extract", "v1")
    assert "My parcel" in p.render(message="My parcel")[1]
    with pytest.raises(promptfiles.PromptError, match="missing"):
        p.render()
    with pytest.raises(promptfiles.PromptError, match="unused"):
        p.render(message="hi", today="Tuesday")


def test_chain_config_and_overrides():
    assert promptfiles.chain_versions() == V1
    assert promptfiles.chain_versions(["write=v2"])["write"] == "v2"
    with pytest.raises(promptfiles.PromptError):
        promptfiles.chain_versions(["polish=v1"])


def test_customer_text_sits_last_and_marked_as_data():
    for name in ("extract", "mega"):
        p = promptfiles.load_prompt(name, "v1")
        assert "{{message}}" not in p.system, "customer text goes in the user part, after the fixed part"
        assert p.user.rstrip().splitlines()[-1].strip() in ("{{message}}", "</customer_message>")


SAMPLE = {"message": "<MESSAGE>", "policies": "<POLICIES>", "today": "<TODAY>", "order": "<ORDER>",
          "order_facts": "<ORDER_FACTS>", "issue": "<ISSUE>", "issue_summary": "<ISSUE_SUMMARY>",
          "decision": "<DECISION>", "rule": "<RULE>", "reason": "<REASON>", "first_name": "<NAME>",
          "language": "<LANGUAGE>", "sentiment": "<SENTIMENT>", "order_id": "<ORDER_ID>", "item": "<ITEM>"}


@pytest.mark.parametrize("prompt_file", sorted(p.name for p in (FOLDER / "prompts").glob("*.md")))
def test_snapshot_of_what_the_model_actually_sees(prompt_file):
    """Fill each prompt with sample values and compare with the saved snapshot.
    Any change to what the model reads shows up here, as a diff to review."""
    name, version, _ = prompt_file.split(".")
    p = promptfiles.load_prompt(name, version, FOLDER / "prompts")
    system, user = p.render(**{k: SAMPLE[k] for k in p.placeholders()})
    seen = f"# model: {p.model('anthropic')} / {p.model('openai')} · max_tokens {p.max_tokens}\n" \
           f"# system\n{system}\n# user\n{user}\n"
    snap = SNAPSHOTS / FOLDER.name / f"{p.id}.txt"   # start/ gets its own: your first run is your baseline
    if os.environ.get("UPDATE_SNAPSHOTS") or not snap.exists():
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_text(seen)
    assert seen == snap.read_text(), f"{p.id} changed: review it, then UPDATE_SNAPSHOTS=1"


# ---- the chain, step by step ----------------------------------------------

def test_happy_path_runs_three_steps_and_logs_versions():
    caller, fake = caller_with([extraction(), decision(), "Hi Rohan, I can raise a refund request now."])
    row = chain.run_chain(caller, CASES["TCK-20101"], V1)
    assert row["decision"] == "allowed" and row["problems"] == []
    assert len(fake.sent) == 3
    assert [s["step"] for s in row["steps"]] == ["extract.v1", "gate:order", "decide.v1", "gate:amount",
                                                 "gate:reply", "write.v1"]
    assert row["versions"] == V1
    logged = json.loads(chain.TRACE.read_text().splitlines()[-1])
    assert logged["versions"] == V1 and logged["steps"][0]["step"] == "extract.v1"


def test_facts_come_from_the_database_not_the_model():
    caller, fake = caller_with([extraction(category="other"), decision(), "Hi Rohan, I can raise a request now."])
    chain.run_chain(caller, CASES["TCK-20101"], V1)
    facts_sent = fake.sent[1]["messages"][0]["content"]
    assert '"days_since_delivery": 4' in facts_sent and '"order_total_inr": 1299' in facts_sent
    assert '"category": "electronics"' in facts_sent


def test_decide_sees_only_the_policies_it_needs():
    caller, fake = caller_with([extraction(order_id="SK47731", category="footwear", issue="change_of_mind"),
                                decision("denied", "footwear §1"), "Hi Sneha, sorry, footwear is 10 days."])
    chain.run_chain(caller, CASES["TCK-20104"], V1)
    system = fake.sent[1]["system"]
    assert 'doc_id="footwear"' in system and 'doc_id="privacy"' not in system and 'doc_id="damaged-items"' not in system


def test_no_order_id_stops_the_chain_and_asks():
    case = {"ticket_id": "TCK-20103", "expected": "ask_order_id", "window_days": 14}
    caller, fake = caller_with([extraction(order_id=None, category="other", issue="not_delivered")])
    row = chain.run_chain(caller, case, V1)
    assert row["decision"] == "ask_order_id" and "order number" in row["reply"]
    assert len(fake.sent) == 1, "no Decide or Write call once a gate stops the chain"


def test_missing_id_falls_back_to_the_order_the_chat_was_opened_from():
    caller, _ = caller_with([extraction(order_id=None, category="footwear", issue="change_of_mind"),
                             decision("denied", "returns-and-refunds §2.4"), "Hi Meera, sorry, clearance is final sale."])
    row = chain.run_chain(caller, CASES["TCK-20138"], V1)
    assert "SK48102 found" in row["steps"][1]["result"]


@pytest.mark.parametrize("ticket, order, expected", [
    ("TCK-20141", "SK48497", "handover"),   # ₹5,499: just above
    ("TCK-20130", "SK48495", "allowed"),    # ₹4,999: just under
])
def test_refunds_above_5000_go_to_a_human_whatever_the_model_says(ticket, order, expected):
    lang = "hinglish" if ticket == "TCK-20130" else "en"
    reply = ("Hi, main aapke liye abhi request raise kar sakta hoon, kya aap photo bhej sakti hain?"
             if lang == "hinglish" else "Hi, a colleague from our support team will reply within one working day.")
    caller, _ = caller_with([extraction(order_id=order, language=lang), decision("allowed"), reply])
    row = chain.run_chain(caller, CASES[ticket], V1)
    assert row["decision"] == expected


def test_a_made_up_policy_section_is_sent_back_once():
    caller, fake = caller_with([extraction(), decision(section="electronics §1; damaged-items §2"),
                                decision(section="damaged-items §2"), "Hi Rohan, I can raise a request now."])
    row = chain.run_chain(caller, CASES["TCK-20101"], V1)
    assert row["policy_section"] == "damaged-items §2" and len(fake.sent) == 4
    assert "policy_section must look like" in fake.sent[2]["messages"][-1]["content"]


def test_a_section_that_does_not_exist_twice_means_handover():
    caller, _ = caller_with([extraction(), decision(section="damaged-items §9"), decision(section="damaged-items §9"),
                             "Hi Rohan, a colleague from our support team will reply soon."])
    assert chain.run_chain(caller, CASES["TCK-20101"], V1)["decision"] == "handover"


def test_reply_that_promises_a_refund_is_rewritten():
    caller, fake = caller_with([extraction(order_id="SK48495", language="hinglish"), decision(),
                                "Hi Fatima, aapka refund approve ho gaya hai.",
                                "Hi Fatima, main abhi aapke liye request raise kar sakta hoon. Kya aap photo bhej sakti hain?"])
    row = chain.run_chain(caller, CASES["TCK-20130"], V1)
    assert "approve ho gaya" not in row["reply"] and len(fake.sent) == 4
    assert "processed or approved" in fake.sent[3]["messages"][-1]["content"]


def test_reply_that_fails_twice_hands_over_safely():
    caller, _ = caller_with([extraction(), decision(), "Your refund has been processed!",
                             "Good news: your refund has been approved."])
    row = chain.run_chain(caller, CASES["TCK-20101"], V1)
    assert row["decision"] == "handover" and "colleague" in row["reply"]


def test_english_reply_to_a_hinglish_customer_is_sent_back():
    caller, fake = caller_with([extraction(order_id="SK48214", category="clothing", language="hinglish"), decision(),
                                "Hi Priya, sorry your kurta arrived torn. I can raise a refund request now.",
                                "Hi Priya, sorry ki aapka kurta phata hua aaya. Main abhi refund request raise kar sakti hoon."])
    row = chain.run_chain(caller, CASES["TCK-20132"], V1)
    assert row["reply"].startswith("Hi Priya, sorry ki") and "reply in hinglish" in fake.sent[3]["messages"][-1]["content"]


# ---- the mega-prompt and the checks -----------------------------------------

def test_mega_answer_in_code_fences_is_a_broken_format():
    good = json.dumps({"order_id": "SK48213", "decision": "allowed", "policy_section": "damaged-items §2", "reply": "Hi"})
    assert mega.parse(good) == (json.loads(good), True)
    data, ok = mega.parse("```json\n" + good + "\n```")
    assert not ok and data["decision"] == "allowed"
    assert mega.parse("Sure! Here you go.") == ({}, False)


def test_mega_prompt_gets_every_policy_and_the_raw_order():
    caller, fake = caller_with(['{"order_id": "SK47731", "decision": "denied", "policy_section": "footwear §1", '
                                '"reply": "Hi Sneha, footwear can be returned within 10 days of delivery."}'])
    row = mega.run_mega(caller, CASES["TCK-20104"])
    assert row["problems"] == []
    assert fake.sent[0]["system"].count("<policy doc_id=") == len(facts.policies())
    assert "Delivered 12 days ago" not in fake.sent[0]["messages"][0]["content"], "fixture notes give the answer away"


def test_checks_catch_the_mega_prompts_failures():
    shoes, clearance = CASES["TCK-20104"], CASES["TCK-20138"]
    assert "wrong window 14d (is 10d)" in checks.problems(shoes, "denied", "You can return within 14 days.")
    assert checks.problems(clearance, "denied", "It's past the 10-day footwear return window.") == [
        "says window closed (day 4 of 10)"]
    assert checks.problems(CASES["TCK-20116"], "allowed", "Hi") == ["missed handover"]
    assert "promised refund" in checks.problems(CASES["TCK-20101"], "allowed", "I have processed your refund.")
    assert checks.language_ok("hinglish", "Main aapke liye abhi request raise kar sakta hoon, kya aap photo bhej sakti hain")
    assert not checks.language_ok("hinglish", "I can raise a refund request for you right now.")
    assert checks.language_ok("hi", "आपका ऑर्डर")


# ---- cost: cache and the real client ---------------------------------------

def test_same_prompt_same_input_is_served_from_the_cache():
    p = promptfiles.load_prompt("extract", "v1")
    caller, fake = caller_with([extraction()])
    first = caller.ask(p, {"message": "hi"}, schema=chain.Extraction)
    again = calls.Caller(make_llm=lambda *_: FakeLLM([])).ask(p, {"message": "hi"}, schema=chain.Extraction)
    assert not first.cached and again.cached and again.cost_usd == 0 and again.list_cost_usd == first.cost_usd
    assert again.parsed == first.parsed and len(fake.sent) == 1


def test_one_ticket_through_the_real_client_with_a_fake_server():
    server = FakeServer("anthropic", [anthropic_message(json.dumps(extraction()), 300, 60),
                                      anthropic_message(json.dumps(decision()), 5000, 80),
                                      anthropic_message("Hi Rohan, I can raise a refund request right now.", 400, 30)])
    caller = calls.Caller(make_llm=lambda provider, model: server.llm())
    row = chain.run_chain(caller, CASES["TCK-20101"], V1)
    assert row["decision"] == "allowed" and server.calls == 3
    assert server.requests[0]["model"] == "claude-haiku-5-5" and "output_config" in server.requests[0]
    assert "output_config" not in server.requests[2], "Write returns plain text"
    assert budget.spent_today() == pytest.approx(caller.spent_usd) and caller.spent_usd > 0
