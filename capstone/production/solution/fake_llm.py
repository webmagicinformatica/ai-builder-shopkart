"""Fake mode for load tests: no model, no key, no cost. Everything else is real.

Retrieval (hybrid search + the local reranker), the score floor, the grounding check, the
limits and the metrics all run as in production. Only the model call is replaced: after a
model-like pause, it answers with the first sentence of the best chunk, cited. So the answer
passes the grounding check, and a load test measures the real CPU work of every request.

It counts pretend tokens at Haiku's price, so the per-user limits and the daily cap fill up
like real spend, and nothing is recorded in the real spend ledger.
"""

from __future__ import annotations

import json
import os
import re
import time

from shopkart.llm import Result, call_cost_usd
from shopkart.pricing import usd_to_inr

SOURCE = re.compile(r"^\[([a-z0-9-]+ § [\w.-]+)\] \(.*?\)\n(.*?)(?=\n\n---\n\n|\n\nCustomer question:)", re.S | re.M)


def first_sentence(text: str) -> str:
    """The first plain sentence of a chunk: not its heading path, a table row or a bullet marker."""
    for line in text.splitlines():
        line = line.strip().lstrip("-*• ").strip()
        if not line or line.startswith(("#", "|", ">")) or " > " in line:
            continue
        sentence = re.split(r"(?<=[.!?])\s+", line)[0].rstrip(".!?")
        if len(sentence.split()) >= 4:
            return sentence
    return ""


class FakeDocLLM:
    provider = "fake"
    model = "fake"
    price_model = "claude-haiku-5-5"  # what the pretend tokens are priced at

    def __init__(self, latency_s: float | None = None):
        self.latency_s = float(os.environ.get("FAKE_LATENCY_S", "1.0")) if latency_s is None else latency_s

    def complete(self, prompt, *, system=None, max_tokens=400, schema=None, cache_system=False) -> Result:
        start = time.monotonic()
        time.sleep(self.latency_s)  # a model-like wait: this thread waits, the server keeps serving
        match = SOURCE.search(prompt)
        sentence = first_sentence(match.group(2)) if match else ""
        if sentence:
            body = {"answerable": True, "answer": f"{sentence} [{match.group(1)}].", "citations": [match.group(1)]}
        else:
            body = {"answerable": False, "answer": "", "citations": []}
        text = json.dumps(body, ensure_ascii=False)
        tokens_in, tokens_out = (len(system or "") + len(prompt)) // 4, len(text) // 4
        cost = call_cost_usd(self.price_model, tokens_in, tokens_out, 0, 0)
        result = Result(text=text, parsed=None, input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=cost,
                        cost_inr=usd_to_inr(cost), latency_s=time.monotonic() - start, model="fake",
                        provider="fake", request_id=None)
        if schema is not None:
            result.parsed = schema.model_validate_json(text)
        return result
