"""One way to call a versioned prompt: render it, use its pinned model, cache the answer.

Every real call goes through shopkart.llm.LLM, so it is budget-checked and
cost-logged. Answers are also saved to .shopkart/cache/prompt-chain/, keyed by
everything that was sent: run the same prompt version on the same ticket
again and it costs nothing. Change one word of the prompt and the key changes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

import facts  # noqa: F401  (puts the repo root on sys.path)
from promptfiles import Prompt
from shopkart import budget

CACHE_DIR = budget.LEDGER_DIR / "cache" / "prompt-chain"


@dataclass
class Answer:
    prompt_id: str
    model: str
    text: str
    parsed: BaseModel | None
    cost_usd: float          # 0 when it came from the cache
    input_tokens: int
    output_tokens: int
    latency_s: float
    cached: bool
    list_cost_usd: float = 0.0  # what the call cost when it was made (same as cost_usd if not cached)


@dataclass
class Caller:
    provider: str = "anthropic"
    fresh: bool = False                       # True: ignore the cache, call the API again
    make_llm: Callable[[str, str], Any] | None = None   # (provider, model) -> LLM; tests pass a fake
    cache_dir: Path | None = None
    answers: list[Answer] = field(default_factory=list)
    _llms: dict[str, Any] = field(default_factory=dict)

    def llm(self, model: str) -> Any:
        if model not in self._llms:
            if self.make_llm is not None:
                self._llms[model] = self.make_llm(self.provider, model)
            else:
                from shopkart.llm import LLM

                self._llms[model] = LLM(self.provider, model)
        return self._llms[model]

    def ask(self, prompt: Prompt, values: dict[str, object], *, schema: type[BaseModel] | None = None,
            feedback: list[dict[str, str]] | None = None) -> Answer:
        """Fill the prompt, call its pinned model (or read the cache), return the answer."""
        system, user = prompt.render(**values)
        messages = [{"role": "user", "content": user}] + (feedback or [])
        model = prompt.model(self.provider)
        key = hashlib.sha256(json.dumps({
            "provider": self.provider, "model": model, "max_tokens": prompt.max_tokens,
            "system": system, "messages": messages,
            "schema": schema.model_json_schema() if schema else None,
        }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
        path = (self.cache_dir or CACHE_DIR) / f"{prompt.id}-{key}.json"

        if path.exists() and not self.fresh:
            saved = json.loads(path.read_text())
            answer = Answer(prompt.id, model, saved["text"],
                            schema.model_validate_json(saved["text"]) if schema else None,
                            0.0, saved["input_tokens"], saved["output_tokens"], saved["latency_s"], True,
                            saved["cost_usd"])
        else:
            r = self.llm(model).complete(messages, system=system, max_tokens=prompt.max_tokens, schema=schema)
            answer = Answer(prompt.id, model, r.text, r.parsed, r.cost_usd,
                            r.input_tokens, r.output_tokens, r.latency_s, False, r.cost_usd)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"text": r.text, "input_tokens": r.input_tokens,
                                        "output_tokens": r.output_tokens, "latency_s": r.latency_s,
                                        "cost_usd": r.cost_usd}, ensure_ascii=False))
        self.answers.append(answer)
        return answer

    @property
    def spent_usd(self) -> float:
        return sum(a.cost_usd for a in self.answers)

    @property
    def cached_calls(self) -> int:
        return sum(a.cached for a in self.answers)

    def summary(self) -> str:
        """'$0.0200 for 10 calls (paid now $0.000000, 10 from cache)'."""
        listed = sum(a.list_cost_usd for a in self.answers)
        return (f"${listed:.6f} for {len(self.answers)} calls "
                f"(paid now ${self.spent_usd:.6f}, {self.cached_calls} from cache)")
