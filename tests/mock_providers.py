"""Mock Anthropic- and OpenAI-shaped endpoints for offline SDK tests.

No network, no keys: real provider SDKs are pointed here via base_url.
"""

from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()

ANTHROPIC_MESSAGE = {
    "id": "msg_mock_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-5-5",
    "content": [{"type": "text", "text": "Hello from mock Claude."}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 25, "output_tokens": 12},
}

CHAT_RESPONSE = {
    "id": "chatcmpl-mock",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "gpt-4o",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello from mock GPT."},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 9, "completion_tokens": 12, "total_tokens": 21},
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/anthropic/v1/messages")
async def anthropic_messages(request: Request):
    body = await request.json()
    if not body.get("stream"):
        return JSONResponse(ANTHROPIC_MESSAGE)

    def gen():
        start = dict(ANTHROPIC_MESSAGE, content=[], stop_reason=None,
                     usage={"input_tokens": 25, "output_tokens": 1})
        yield _sse("message_start", {"type": "message_start", "message": start})
        yield _sse("content_block_start",
                   {"type": "content_block_start", "index": 0,
                    "content_block": {"type": "text", "text": ""}})
        for piece in ("Hello ", "from mock ", "Claude."):
            yield _sse("content_block_delta",
                       {"type": "content_block_delta", "index": 0,
                        "delta": {"type": "text_delta", "text": piece}})
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": 0})
        yield _sse("message_delta",
                   {"type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 12}})
        yield _sse("message_stop", {"type": "message_stop"})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/openai/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    if not body.get("stream"):
        return JSONResponse(CHAT_RESPONSE)
    include_usage = bool((body.get("stream_options") or {}).get("include_usage"))

    def chunk(delta: dict, finish=None) -> dict:
        return {
            "id": "chatcmpl-mock", "object": "chat.completion.chunk",
            "created": 1700000000, "model": "gpt-4o",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }

    def gen():
        yield "data: " + json.dumps(chunk({"role": "assistant", "content": ""})) + "\n\n"
        for piece in ("Hello ", "from mock ", "GPT."):
            yield "data: " + json.dumps(chunk({"content": piece})) + "\n\n"
        yield "data: " + json.dumps(chunk({}, finish="stop")) + "\n\n"
        if include_usage:
            yield "data: " + json.dumps({
                "id": "chatcmpl-mock", "object": "chat.completion.chunk",
                "created": 1700000000, "model": "gpt-4o", "choices": [],
                "usage": {"prompt_tokens": 9, "completion_tokens": 12, "total_tokens": 21},
            }) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
