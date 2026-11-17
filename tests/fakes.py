"""Fake provider servers for tests: real SDK clients, a mock HTTP transport, no network.

`FakeServer(provider, [reply, reply, ...])` answers each request with the next
reply in the list: a dict (a normal answer), an int status code (an error), or
("stream", text) for a streamed answer. It counts the calls it received.
"""

import json
from typing import Any

import httpx2

from shopkart.llm import LLM


def anthropic_message(text: str, input_tokens: int = 20, output_tokens: int = 10,
                      stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_fake", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": text}], "stop_reason": stop_reason,
        "stop_sequence": None, "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def openai_response(text: str, input_tokens: int = 20, output_tokens: int = 10) -> dict[str, Any]:
    return {
        "id": "resp_fake", "object": "response", "created_at": 0, "model": "gpt-6-luna",
        "status": "completed", "output": [{
            "type": "message", "id": "msg_fake", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }],
        "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "total_tokens": input_tokens + output_tokens,
                  "input_tokens_details": {"cached_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 0}},
    }


def _sse(events: list[tuple[str, dict[str, Any]]]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def anthropic_stream(pieces: list[str], error_after: int | None = None) -> bytes:
    msg = anthropic_message("", output_tokens=1)
    msg["content"] = []
    events = [("message_start", {"type": "message_start", "message": msg}),
              ("content_block_start", {"type": "content_block_start", "index": 0,
                                       "content_block": {"type": "text", "text": ""}})]
    for i, p in enumerate(pieces):
        if error_after is not None and i == error_after:
            events.append(("error", {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}))
            return _sse(events)
        events.append(("content_block_delta", {"type": "content_block_delta", "index": 0,
                                               "delta": {"type": "text_delta", "text": p}}))
    events += [("content_block_stop", {"type": "content_block_stop", "index": 0}),
               ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                  "usage": {"output_tokens": 12}}),
               ("message_stop", {"type": "message_stop"})]
    return _sse(events)


def openai_stream(pieces: list[str]) -> bytes:
    full = openai_response("".join(pieces), output_tokens=12)
    empty = dict(full, status="in_progress", output=[], usage=None)
    item = {"type": "message", "id": "msg_fake", "role": "assistant", "status": "in_progress", "content": []}
    events: list[tuple[str, dict[str, Any]]] = [
        ("response.created", {"type": "response.created", "sequence_number": 0, "response": empty}),
        ("response.output_item.added", {"type": "response.output_item.added", "sequence_number": 1,
                                        "output_index": 0, "item": item}),
        ("response.content_part.added", {"type": "response.content_part.added", "sequence_number": 2,
                                         "item_id": "msg_fake", "output_index": 0, "content_index": 0,
                                         "part": {"type": "output_text", "text": "", "annotations": []}}),
    ]
    for i, p in enumerate(pieces):
        events.append(("response.output_text.delta", {"type": "response.output_text.delta", "sequence_number": 3 + i,
                                                      "item_id": "msg_fake", "output_index": 0, "content_index": 0,
                                                      "delta": p, "logprobs": []}))
    events.append(("response.completed", {"type": "response.completed", "sequence_number": 99, "response": full}))
    return _sse(events)


def error_body(provider: str, status: int, err_type: str, code: str | None = None,
               message: str = "fake error") -> dict[str, Any]:
    if provider == "anthropic":
        return {"type": "error", "error": {"type": err_type, "message": message}}
    return {"error": {"type": err_type, "code": code, "message": message, "param": None}}


class FakeServer:
    def __init__(self, provider: str, replies: list[Any]):
        self.provider = provider
        self.replies = list(replies)
        self.calls = 0
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        self.requests.append(json.loads(request.content or b"{}"))
        reply = self.replies.pop(0)
        headers: dict[str, str] = {"request-id": f"req_fake_{self.calls}"}
        if isinstance(reply, tuple) and reply[0] == "stream":
            return httpx2.Response(200, content=reply[1], headers={**headers, "content-type": "text/event-stream"})
        if isinstance(reply, tuple) and reply[0] == "error":
            _, status, body, extra = (*reply, {})[:4]
            return httpx2.Response(status, json=body, headers={**headers, **extra})
        if isinstance(reply, int):
            err_type = {429: "rate_limit_error", 529: "overloaded_error", 500: "api_error"}.get(reply, "invalid_request_error")
            return httpx2.Response(reply, json=error_body(self.provider, reply, err_type), headers=headers)
        return httpx2.Response(200, json=reply, headers=headers)

    def llm(self, **kw: Any) -> LLM:
        http = httpx2.Client(transport=httpx2.MockTransport(self))
        return LLM(self.provider, http_client=http, sleep=lambda s: None, **kw)  # type: ignore[arg-type]
