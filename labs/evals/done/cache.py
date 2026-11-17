"""A disk cache for LLM calls, so re-running the same eval is free.

The key is a hash of everything that decides the answer: provider, model,
system prompt, messages, schema and max_tokens. Change any of them (a new
prompt version, a new model) and the key changes, so those cases run again.
Nothing else does.

    llm = CachedLLM(LLM())          # same .complete() as shopkart.llm.LLM
    result = llm.complete(...)       # result.cached is True on a hit, and costs $0
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from shopkart import budget
from shopkart.llm import Result

CACHE_DIR = budget.LEDGER_DIR / "eval-cache"  # .shopkart/ is gitignored


class CachedLLM:
    def __init__(self, llm: Any, cache_dir: Path | None = None):
        self.llm = llm
        self.provider = llm.provider
        self.model = llm.model
        self.dir = Path(cache_dir or CACHE_DIR)
        self.hits = 0
        self.misses = 0

    def key(self, messages: Any, system: str | None, max_tokens: int, schema: Any) -> str:
        blob = json.dumps({
            "provider": self.provider, "model": self.model, "system": system,
            "messages": messages, "max_tokens": max_tokens,
            "schema": schema.model_json_schema() if schema is not None else None,
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()[:24]

    def complete(self, messages: Any, *, system: str | None = None, max_tokens: int = 1024,
                 schema: Any = None, cache_system: bool = False) -> Result:
        path = self.dir / f"{self.key(messages, system, max_tokens, schema)}.json"
        if path.exists():
            self.hits += 1
            saved = json.loads(path.read_text(encoding="utf-8"))
            result = Result(**{**saved, "parsed": None, "cost_usd": 0.0, "cost_inr": 0.0, "latency_s": 0.0})
            result.cached = True  # type: ignore[attr-defined]
            result.original_cost_usd = saved["cost_usd"]  # type: ignore[attr-defined]
            if schema is not None:
                result.parsed = schema.model_validate_json(result.text)
            return result

        self.misses += 1
        result = self.llm.complete(messages, system=system, max_tokens=max_tokens,
                                   schema=schema, cache_system=cache_system)
        saved = {k: v for k, v in vars(result).items() if k != "parsed"}
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
        result.cached = False  # type: ignore[attr-defined]
        return result
