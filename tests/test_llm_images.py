"""Image input in shopkart.llm: one neutral block, the right shape for each API."""

import base64

import pytest

from shopkart import budget, llm as llm_mod
from shopkart.llm import image_block, user_message
from tests.fakes import FakeServer, anthropic_message, openai_response

PNG = b"\x89PNG\r\n\x1a\nfake"
B64 = base64.b64encode(PNG).decode()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr(llm_mod, "CALL_LOG", tmp_path / "calls.csv")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.50")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")


def test_image_block_is_base64():
    block = image_block(PNG)
    assert block == {"type": "image", "media_type": "image/png", "detail": "high", "data": B64}
    assert user_message("Read it", [block])["content"][-1] == {"type": "text", "text": "Read it"}


def test_anthropic_gets_a_base64_image_source():
    server = FakeServer("anthropic", [anthropic_message("ok")])
    server.llm().complete([user_message("Read this invoice", [image_block(PNG, "image/jpeg")])])
    content = server.requests[0]["messages"][0]["content"]
    assert content[0] == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": B64}}
    assert content[1] == {"type": "text", "text": "Read this invoice"}


def test_openai_gets_a_data_url_and_input_text():
    server = FakeServer("openai", [openai_response("ok")])
    server.llm().complete([user_message("Read this invoice", [image_block(PNG, detail="low")])])
    content = server.requests[0]["input"][0]["content"]
    assert content[0] == {"type": "input_image", "detail": "low", "image_url": f"data:image/png;base64,{B64}"}
    assert content[1] == {"type": "input_text", "text": "Read this invoice"}


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_text_only_messages_are_sent_unchanged(provider):
    reply = anthropic_message("ok") if provider == "anthropic" else openai_response("ok")
    server = FakeServer(provider, [reply])
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
            {"role": "user", "content": [{"type": "text", "text": "again"}]}]
    server.llm().complete(msgs)
    sent = server.requests[0]["messages" if provider == "anthropic" else "input"]
    assert sent == msgs
