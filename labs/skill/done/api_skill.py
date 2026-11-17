"""The same skill on the Claude API: upload it once, attach it to a request with code execution.

    uv run python labs/skill/done/api_skill.py --upload        # once: prints the skill ID
    uv run python labs/skill/done/api_skill.py TCK-20104       # a reply, with the skill loaded on demand
    uv run python labs/skill/done/api_skill.py --delete        # clean up

Claude only. The skill runs inside the code execution tool's sandbox (no internet there).
Code execution is billed by container time: each organisation gets 1,550 free hours a month.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from compare import BASE, the_reply, ticket_context
from skill_loader import ROOT, SKILLS_DIR

from shopkart import budget
from shopkart.llm import LLM, _anthropic_stop, _anthropic_usage
from shopkart.pricing import usd_to_inr

SKILL = SKILLS_DIR / "shopkart-replies"
ID_FILE = ROOT / ".shopkart" / "api-skill.json"
TOOLS = [{"type": "code_execution_20250825", "name": "code_execution"}]


def skill_files() -> list[tuple[str, bytes]]:
    """Every file in the skill folder, with paths like shopkart-replies/SKILL.md."""
    return [(p.relative_to(SKILL.parent).as_posix(), p.read_bytes())
            for p in sorted(SKILL.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]


def upload(client) -> None:
    skill = client.skills.create(files=skill_files(), display_name="ShopKart replies")
    ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    ID_FILE.write_text(json.dumps({"skill_id": skill.id}) + "\n")
    print(f"Uploaded {SKILL.name}: {skill.id} (version {skill.latest_version_id})")


def delete(client) -> None:
    skill_id = json.loads(ID_FILE.read_text())["skill_id"]
    client.skills.delete(skill_id=skill_id)
    ID_FILE.unlink()
    print(f"Deleted {skill_id}")


def show_step(block) -> None:
    """Print what Claude did inside the sandbox: the commands, not the file contents."""
    if block.type != "server_tool_use":
        return
    inp = block.input or {}
    what = inp.get("command") or f"{inp.get('command', 'view')} {inp.get('path', '')}"
    if block.name == "text_editor_code_execution":
        what = f"{inp.get('command')} {inp.get('path')}"
    print(f"  [sandbox] {block.name}: {str(what).strip()[:110]}")


def reply(llm: LLM, ticket_id: str) -> None:
    skill_id = json.loads(ID_FILE.read_text())["skill_id"]
    _, user = ticket_context(ticket_id)
    messages: list = [{"role": "user", "content": user}]
    container: dict = {"skills": [{"type": "custom", "skill_id": skill_id, "version": "latest"}]}
    cost = 0.0
    for _ in range(4):  # a long sandbox turn can pause; we send it back to continue
        def once():
            start = time.monotonic()
            args = llm._anthropic_args(messages, BASE, 1500, None, False)
            resp = llm._client.messages.create(**args, container=container, tools=TOOLS)
            once.resp = resp
            text = "".join(b.text for b in resp.content if b.type == "text")
            return llm._finish(text, _anthropic_usage(resp.usage), _anthropic_stop(resp.stop_reason),
                               start, getattr(resp, "_request_id", None))

        result = llm._with_retries(once)
        resp = once.resp
        cost += result.cost_usd
        for block in resp.content:
            show_step(block)
        if resp.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": resp.content})
        container = {"id": resp.container.id, "skills": container["skills"]}
    text = "".join(b.text for b in resp.content if b.type == "text")
    print(f"\nReply: {the_reply(text) or '(no text)'}\n")
    print(f"{llm.model} · {result.input_tokens} in / {result.output_tokens} out (last turn) · "
          f"${cost:.6f} (₹{usd_to_inr(cost):.4f}) · container {resp.container.id if resp.container else '-'}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("ticket", nargs="?", default="TCK-20104")
    p.add_argument("--upload", action="store_true")
    p.add_argument("--delete", action="store_true")
    p.add_argument("--model", default=None)
    args = p.parse_args(argv)
    llm = LLM("anthropic", args.model)
    try:
        if args.upload:
            upload(llm._client)
        elif args.delete:
            delete(llm._client)
        else:
            reply(llm, args.ticket)
    except budget.BudgetExceeded as exc:
        print(exc, file=sys.stderr)
        return 2
    except FileNotFoundError:
        print("Upload the skill first: uv run python labs/skill/done/api_skill.py --upload", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
