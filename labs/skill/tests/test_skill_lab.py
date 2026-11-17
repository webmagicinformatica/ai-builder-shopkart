"""The lab's checkpoints: no key, no network, no cost.

Against the finished answer:   uv run pytest labs/skill -q
Against your copy:             LAB=start uv run pytest labs/skill -q
"""

import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fakes import FakeServer, anthropic_message, openai_response

LAB = Path(__file__).resolve().parent.parent
FOLDER = LAB / os.environ.get("LAB", "done")
SKILL = FOLDER / "skills" / "shopkart-replies"


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.setattr("shopkart.budget.LEDGER_DIR", tmp_path)
    monkeypatch.setattr("shopkart.llm.CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setenv("DAILY_BUDGET_USD", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")


@pytest.fixture
def lab(monkeypatch):
    """Import skill_loader and compare from the folder under test (done/ or start/)."""
    monkeypatch.syspath_prepend(str(FOLDER))
    for name in ("skill_loader", "compare"):
        sys.modules.pop(name, None)
    return importlib.import_module("skill_loader"), importlib.import_module("compare")


# ---- the skill folder follows the Agent Skills format ---------------------------


def _header() -> dict:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md starts with a --- header"
    return {k.strip(): v.strip() for k, v in (line.split(":", 1) for line in m.group(1).splitlines()
                                              if ":" in line and not line.startswith(" "))}


def test_skill_header_follows_the_spec():
    h = _header()
    assert h["name"] == "shopkart-replies" == SKILL.name  # must match the folder
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", h["name"]) and len(h["name"]) <= 64
    assert 1 <= len(h["description"]) <= 1024
    assert "TODO" not in h["description"]
    assert re.search(r"\buse when\b", h["description"], re.I)  # says WHEN, not just what


def test_skill_body_is_short_and_points_to_its_files():
    body = (SKILL / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[2]
    assert len(body.splitlines()) < 500 and "TODO" not in body
    for ref in re.findall(r"`((?:references|scripts)/[\w.-]+)`", body):
        assert (SKILL / ref).is_file(), f"SKILL.md points to {ref}, which doesn't exist"
    for fact in ("₹5,000", "four sentences"):
        assert fact.lower() in body.lower()


def test_references_hold_the_lesson_facts():
    policies = (SKILL / "references" / "policies.md").read_text(encoding="utf-8")
    for fact in ("14 days", "10 days", "7 days", "5 to 7 working days", "₹5,000"):
        assert fact in policies
    assert (SKILL / "references" / "tone.md").is_file() and (SKILL / "references" / "templates.md").is_file()


@pytest.mark.parametrize("args,expected", [
    (["footwear", "2026-11-05"], "OUTSIDE the window by 2 days"),   # TCK-20104: 12 days, window 10
    (["electronics", "2026-11-16"], "INSIDE the window, 6 days left"),
    (["home_kitchen", "2026-11-03"], "INSIDE the window, 0 days left"),
    (["grocery", "2026-11-16"], "Not returnable"),
])
def test_return_window_script(args, expected):
    out = subprocess.run([sys.executable, str(SKILL / "scripts" / "return_window.py"), *args, "--today", "2026-11-17"],
                         capture_output=True, text=True, check=True).stdout
    assert expected in out


# ---- progressive disclosure, by hand ---------------------------------------------


def test_level_1_catalog_has_only_name_and_description(lab):
    loader, _ = lab
    cat = loader.catalog(FOLDER / "skills")
    assert "shopkart-replies" in cat and "Use when" in cat
    assert "Check before you send" not in cat  # the instructions stay in the folder
    assert len(cat) < 1000


def test_levels_2_and_3_load_on_demand(lab):
    loader, _ = lab
    tools = loader.SkillTools(FOLDER / "skills")
    body = tools.call("load_skill", {"name": "shopkart-replies"})
    assert "Check before you send" in body and not body.startswith("---")
    assert "₹5,000" in tools.call("read_skill_file", {"name": "shopkart-replies", "path": "references/policies.md"})
    out = tools.call("run_skill_script", {"name": "shopkart-replies", "script": "scripts/return_window.py",
                                          "args": ["footwear", "2026-11-05", "--today", "2026-11-17"]})
    assert "OUTSIDE" in out and "def check" not in out  # the output, not the code
    assert tools.call("read_skill_file", {"name": "shopkart-replies", "path": "../../compare.py"}).startswith("ERROR")
    assert tools.loaded[0] == "L2 shopkart-replies" and tools.loaded[1] == "L3 references/policies.md"


def _tool_use(name, args):
    msg = anthropic_message("", stop_reason="tool_use")
    msg["content"] = [{"type": "tool_use", "id": "toolu_1", "name": name, "input": args}]
    return msg


def _function_call(name, args):
    resp = openai_response("")
    resp["output"] = [{"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": name,
                       "arguments": json.dumps(args), "status": "completed"}]
    return resp


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_with_skill_the_model_loads_it_then_replies(lab, provider):
    loader, compare = lab
    final = "Notes for me.\n<reply>Sorry, it's outside the 10-day window. A colleague will reply within one working day.</reply>"
    if provider == "anthropic":
        fake = FakeServer("anthropic", [_tool_use("load_skill", {"name": "shopkart-replies"}), anthropic_message(final)])
    else:
        fake = FakeServer("openai", [_function_call("load_skill", {"name": "shopkart-replies"}), openai_response(final)])
    out = compare.run_one(fake.llm(), "TCK-20104", True, cache={}, fresh=True)
    assert out["loaded"] == ["L2 shopkart-replies"]
    assert out["text"].startswith("Sorry") and "Notes for me" not in out["text"]  # only the <reply> is sent
    assert out["llm_calls"] == 2
    assert "<available_skills>" in json.dumps(fake.requests[0])
    assert "Check before you send" in json.dumps(fake.requests[1])  # level 2 went back to the model


def test_without_skill_is_one_plain_call(lab):
    _, compare = lab
    fake = FakeServer("anthropic", [anthropic_message("<reply>Yes, you can return them.</reply>")])
    out = compare.run_one(fake.llm(), "TCK-20104", False, cache={}, fresh=True)
    assert out["loaded"] == [] and "tools" not in fake.requests[0]
    assert "available_skills" not in json.dumps(fake.requests[0])


def test_checks(lab):
    _, compare = lab
    tickets = {t["ticket_id"]: t for t in json.loads((LAB.parents[1] / "data/tickets.json").read_text())}
    good = compare.checks(tickets["TCK-20137"], "Sorry. It's outside the window. A colleague will reply within one working day.")
    assert good == {"sentences": 3, "short": True, "language": True, "no_promise": True, "handover": True}
    bad = compare.checks(tickets["TCK-20116"], "Your refund has been approved. " * 5)
    assert not bad["short"] and not bad["no_promise"] and bad["handover"] is False
    assert compare.checks(tickets["TCK-20130"], "Sorry, please upload a photo.")["language"] is False
