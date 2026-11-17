"""Prompts as code: one file per prompt and version, loaded by name and version.

    prompts/extract.v1.md      prompts/chain.json  {"extract": "v1", "decide": "v1", "write": "v1"}

A prompt file has a small header (front matter) that pins the model and the
settings to the words, then the system prompt, then the user template:

    ---
    name: extract
    version: v1
    model_anthropic: claude-haiku-5-5
    model_openai: gpt-6-luna
    max_tokens: 300
    changelog: first version
    ---
    The fixed instructions (the system prompt).
    <!-- user -->
    The per-request part, with {{placeholders}} at the end.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent / "prompts"
USER_MARK = "<!-- user -->"
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


class PromptError(Exception):
    pass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    system: str
    user: str
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.name}.{self.version}"

    @property
    def max_tokens(self) -> int:
        return int(self.meta.get("max_tokens", 1024))

    def model(self, provider: str) -> str:
        """The model this version was tested with: words, model and settings travel together."""
        try:
            return self.meta[f"model_{provider}"]
        except KeyError:
            raise PromptError(f"{self.id} pins no model for {provider!r}") from None

    def placeholders(self) -> set[str]:
        return set(PLACEHOLDER.findall(self.system + self.user))

    def render(self, **values: object) -> tuple[str, str]:
        """(system, user) with every {{placeholder}} filled. Missing or unused values are errors."""
        needed = self.placeholders()
        missing = needed - values.keys()
        extra = values.keys() - needed
        if missing or extra:
            raise PromptError(f"{self.id}: missing {sorted(missing)}, unused {sorted(extra)}")

        def fill(text: str) -> str:
            return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), text)

        return fill(self.system), fill(self.user)


def parse(text: str, source: str = "<prompt>") -> Prompt:
    if not text.startswith("---\n"):
        raise PromptError(f"{source}: no front matter")
    head, _, body = text[4:].partition("\n---\n")
    meta = {}
    for line in head.splitlines():
        if line.strip():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    for key in ("name", "version"):
        if key not in meta:
            raise PromptError(f"{source}: front matter needs {key!r}")
    system, mark, user = body.partition(USER_MARK)
    if not mark:
        raise PromptError(f"{source}: no {USER_MARK} line between the system prompt and the user template")
    return Prompt(meta["name"], meta["version"], system.strip(), user.strip(), meta)


def load_prompt(name: str, version: str, folder: Path | None = None) -> Prompt:
    """prompts/<name>.<version>.md, checked against its own header."""
    path = (folder or PROMPTS) / f"{name}.{version}.md"
    if not path.exists():
        have = sorted(p.name for p in (folder or PROMPTS).glob(f"{name}.*.md"))
        raise PromptError(f"no prompt {path.name}; available: {', '.join(have) or 'none'}")
    prompt = parse(path.read_text(), path.name)
    if (prompt.name, prompt.version) != (name, version):
        raise PromptError(f"{path.name} says it is {prompt.id}")
    return prompt


def chain_versions(overrides: list[str] | None = None, folder: Path | None = None) -> dict[str, str]:
    """Which version of each step runs together: prompts/chain.json, plus --use step=version."""
    versions = json.loads(((folder or PROMPTS) / "chain.json").read_text())
    for item in overrides or []:
        step, _, version = item.partition("=")
        if step not in versions or not version:
            raise PromptError(f"--use takes step=version with step in {sorted(versions)}, got {item!r}")
        versions[step] = version
    return versions
