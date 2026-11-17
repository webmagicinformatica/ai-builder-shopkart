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
        # TODO 5: make re-runs free.
        #   Hit (the file exists): count self.hits, rebuild the Result from the JSON with
        #     cost_usd = cost_inr = 0 (nothing was spent), set result.cached = True, and
        #     re-validate result.parsed with the schema. No API call.
        #   Miss: count self.misses, call self.llm.complete(...), save vars(result) without
        #     "parsed" as JSON (write a .tmp file, then rename it), set result.cached = False.
        raise NotImplementedError("TODO 5: CachedLLM.complete")
