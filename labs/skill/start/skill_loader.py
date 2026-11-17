"""Agent skills in your own app, by hand: progressive disclosure with two small tools.

  Level 1  catalog():        name + description of each skill, in the system prompt (~100 tokens each)
  Level 2  load_skill:       the model calls it when a task matches; returns SKILL.md's instructions
  Level 3  read_skill_file:  a reference file, only when a step needs it
           run_skill_script: runs a bundled script; the model gets the OUTPUT, not the code

Works the same on Claude and OpenAI, because it's only tool calling.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from shopkart.llm import LLM, Result, _anthropic_stop, _anthropic_usage, _openai_stop, _openai_usage  # noqa: E402

SKILLS_DIR = Path(__file__).resolve().parent / "skills"


# --------------------------------------------------------------------------
# Reading a skill folder
# --------------------------------------------------------------------------


def front_matter(skill_md: str) -> tuple[dict[str, str], str]:
    """The `name` and `description` from the header, and the body below it."""
    if not skill_md.startswith("---"):
        raise ValueError("SKILL.md must start with a --- header")
    _, header, body = skill_md.split("---", 2)
    meta = {}
    for line in header.strip().splitlines():
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, body.strip()


def skills(skills_dir: Path = SKILLS_DIR) -> dict[str, Path]:
    return {p.parent.name: p.parent for p in sorted(skills_dir.glob("*/SKILL.md"))}


def catalog(skills_dir: Path = SKILLS_DIR) -> str:
    """Level 1: what goes in the system prompt. Only names and descriptions."""
    # TODO 5: for every skill folder, read SKILL.md, take name and description from its header
    #   (front_matter), and return them inside <available_skills> ... </available_skills>, one
    #   <skill name="...">description</skill> per line. Nothing else from the skill goes here.
    raise NotImplementedError("TODO 5")


def _inside(folder: Path, rel: str) -> Path:
    path = (folder / rel).resolve()
    if not path.is_relative_to(folder.resolve()) or not path.is_file():
        raise FileNotFoundError(f"{rel} is not a file in this skill")
    return path


class SkillTools:
    """The three tools the model can call, plus a log of what it loaded."""

    def __init__(self, skills_dir: Path = SKILLS_DIR):
        self.skills = skills(skills_dir)
        self.loaded: list[str] = []  # e.g. "L2 shopkart-replies", "L3 references/tone.md"

    def _skill(self, name: str) -> Path:
        if name not in self.skills:
            raise KeyError(f"No skill {name!r}. Available: {', '.join(self.skills)}")
        return self.skills[name]

    def load_skill(self, name: str) -> str:
        # TODO 6: level 2. Return the BODY of the skill's SKILL.md (front_matter gives it, without
        #   the header), and record self.loaded.append(f"L2 {name}") so the run shows what loaded.
        raise NotImplementedError("TODO 6")

    def read_skill_file(self, name: str, path: str) -> str:
        text = _inside(self._skill(name), path).read_text(encoding="utf-8")
        self.loaded.append(f"L3 {path}")
        return text

    def run_skill_script(self, name: str, script: str, args: list[str]) -> str:
        path = _inside(self._skill(name), script if script.startswith("scripts/") else f"scripts/{script}")
        out = subprocess.run([sys.executable, str(path), *map(str, args)], capture_output=True,
                             text=True, timeout=10)
        self.loaded.append(f"L3 run {path.name} {' '.join(map(str, args))}")
        return (out.stdout + out.stderr).strip()

    specs = [
        ("load_skill", "Load a skill's full instructions. Call this first when the task matches a skill's description.",
         {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}),
        ("read_skill_file", "Read a reference file from a loaded skill, e.g. references/policies.md.",
         {"type": "object", "properties": {"name": {"type": "string"}, "path": {"type": "string"}},
          "required": ["name", "path"]}),
        ("run_skill_script", "Run a script from a loaded skill, e.g. scripts/return_window.py, and get its output.",
         {"type": "object", "properties": {"name": {"type": "string"}, "script": {"type": "string"},
                                           "args": {"type": "array", "items": {"type": "string"}}},
          "required": ["name", "script", "args"]}),
    ]

    def call(self, tool: str, args: dict) -> str:
        try:
            return getattr(self, tool)(**args)
        except Exception as exc:  # the model reads the error and can try again
            return f"ERROR: {exc}"


# --------------------------------------------------------------------------
# Tool calling through shopkart.llm (budget check, retries, cost log)
# --------------------------------------------------------------------------


def _turn(llm: LLM, system: str, messages: list, tools: list[dict], max_tokens: int) -> tuple[Result, Any]:
    raw: dict[str, Any] = {}

    def once() -> Result:
        start = time.monotonic()
        if llm.provider == "anthropic":
            args = llm._anthropic_args(messages, system, max_tokens, None, False)
            if tools:
                args["tools"] = tools
            resp = raw["resp"] = llm._client.messages.create(**args)
            text = "".join(b.text for b in resp.content if b.type == "text")
            return llm._finish(text, _anthropic_usage(resp.usage), _anthropic_stop(resp.stop_reason),
                               start, getattr(resp, "_request_id", None))
        args = llm._openai_args(messages, system, max_tokens, None)
        if tools:
            args["tools"] = tools
        resp = raw["resp"] = llm._client.responses.create(**args)
        return llm._finish(resp.output_text, _openai_usage(resp.usage), _openai_stop(resp),
                           start, getattr(resp, "_request_id", None))

    return llm._with_retries(once), raw["resp"]


def chat(llm: LLM, system: str, user: str, *, specs=(), run_tool: Callable[[str, dict], str] | None = None,
         max_tokens: int = 600, max_turns: int = 8) -> dict:
    """Ask once; if the model calls tools, run them and ask again. Returns text, tokens, cost."""
    if llm.provider == "anthropic":
        tools = [{"name": n, "description": d, "input_schema": s} for n, d, s in specs]
    else:
        tools = [{"type": "function", "name": n, "description": d, "parameters": s, "strict": False}
                 for n, d, s in specs]
    messages: list = [{"role": "user", "content": user}]
    total = {"text": "", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "llm_calls": 0}
    for _ in range(max_turns):
        result, resp = _turn(llm, system, messages, tools, max_tokens)
        total["input_tokens"] += result.input_tokens
        total["output_tokens"] += result.output_tokens
        total["cost_usd"] += result.cost_usd
        total["llm_calls"] += 1
        if llm.provider == "anthropic":
            calls = [(b.id, b.name, b.input) for b in resp.content if b.type == "tool_use"]
        else:
            calls = [(i.call_id, i.name, json.loads(i.arguments or "{}")) for i in resp.output
                     if i.type == "function_call"]
        if not calls or run_tool is None:
            total["text"] = result.text.strip()
            return total
        outputs = [(cid, run_tool(name, args)) for cid, name, args in calls]
        if llm.provider == "anthropic":
            messages.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]})
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": cid, "content": out} for cid, out in outputs]})
        else:
            messages.extend(i.model_dump(exclude_none=True) for i in resp.output)
            messages.extend({"type": "function_call_output", "call_id": cid, "output": out} for cid, out in outputs)
    total["text"] = "[stopped: too many tool calls]"
    return total
