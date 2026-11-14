"""Offline end-to-end test for gateway (proxy) mode: zero-code logging.

Plain anthropic/openai SDKs — no Veekshana SDK, no init() — point their
base_url at the Veekshana gateway, which forwards to local mock vendors and
records spans. Run directly:

    python tests/test_gateway.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

MOCK_PORT = 9672
VK_PORT = 8792

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["VEEKSHANA_DATABASE_URL"] = (
    "sqlite:///" + os.path.join(tempfile.mkdtemp(prefix="vk-gwtest-"), "test.db").replace("\\", "/")
)
os.environ["VEEKSHANA_GATEWAY_ANTHROPIC_URL"] = f"http://127.0.0.1:{MOCK_PORT}/anthropic"
os.environ["VEEKSHANA_GATEWAY_OPENAI_URL"] = f"http://127.0.0.1:{MOCK_PORT}/openai"


def _start_uvicorn(app, port: int):
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.1)
    raise RuntimeError(f"server on :{port} did not start")


def _get(path: str):
    req = urllib.request.Request(
        f"http://127.0.0.1:{VK_PORT}{path}", headers={"x-api-key": "dev-key"}
    )
    return json.loads(urllib.request.urlopen(req).read())


def main() -> None:
    from mock_providers import app as mock_app
    from veekshana_server.main import app as vk_app

    _start_uvicorn(mock_app, MOCK_PORT)
    _start_uvicorn(vk_app, VK_PORT)

    from anthropic import Anthropic
    from openai import OpenAI

    gateway_headers = {"x-veekshana-key": "dev-key"}
    anthropic_client = Anthropic(
        api_key="vendor-key",
        base_url=f"http://127.0.0.1:{VK_PORT}/gateway/anthropic",
        default_headers=gateway_headers,
    )
    openai_client = OpenAI(
        api_key="vendor-key",
        base_url=f"http://127.0.0.1:{VK_PORT}/gateway/openai/v1",
        default_headers=gateway_headers,
    )
    messages = [{"role": "user", "content": "Say hello."}]

    # 1. Anthropic non-streaming through the gateway
    msg = anthropic_client.messages.create(
        model="claude-sonnet-5-5", max_tokens=100, messages=messages
    )
    assert msg.content[0].text == "Hello from mock Claude."

    # 2. Anthropic streaming through the gateway
    stream = anthropic_client.messages.create(
        model="claude-sonnet-5-5", max_tokens=100, messages=messages, stream=True
    )
    text = "".join(
        e.delta.text for e in stream if getattr(e, "type", "") == "content_block_delta"
    )
    assert text == "Hello from mock Claude."

    # 3. OpenAI non-streaming through the gateway
    chat = openai_client.chat.completions.create(model="gpt-4o", messages=messages)
    assert chat.choices[0].message.content == "Hello from mock GPT."

    # 4. OpenAI streaming (with usage) through the gateway
    chunks = openai_client.chat.completions.create(
        model="gpt-4o", messages=messages, stream=True,
        stream_options={"include_usage": True},
    )
    text = "".join(c.choices[0].delta.content or "" for c in chunks if c.choices)
    assert text == "Hello from mock GPT."

    # 5. Wrong Veekshana key -> 401, call rejected before touching the vendor
    import httpx

    denied = httpx.post(
        f"http://127.0.0.1:{VK_PORT}/gateway/openai/v1/chat/completions",
        json={"model": "gpt-4o", "messages": messages},
        headers={"x-veekshana-key": "wrong"},
    )
    assert denied.status_code == 401, denied.status_code

    time.sleep(0.5)  # streamed spans are written when the relay generator closes

    traces = _get("/api/v1/traces?limit=10")
    assert len(traces) == 4, f"expected 4 traces, got {len(traces)}"
    spans = []
    for t in traces:
        spans.extend(_get(f"/api/v1/traces/{t['trace_id']}")["spans"])
    spans.sort(key=lambda s: s["start_time"])
    a_plain, a_stream, o_plain, o_stream = spans

    for s in spans:
        assert s["span_type"] == "llm"
        assert s["cost_usd"] and s["cost_usd"] > 0, s
        assert s["duration_ms"] is not None

    assert a_plain["name"] == "gateway.anthropic.messages"
    assert a_plain["model"] == "claude-sonnet-5-5"
    assert (a_plain["input_tokens"], a_plain["output_tokens"]) == (25, 12)
    assert a_plain["output"]["content"] == "Hello from mock Claude."
    assert a_plain["output"]["streamed"] is False

    assert a_stream["model"] == "claude-sonnet-5-5"
    assert (a_stream["input_tokens"], a_stream["output_tokens"]) == (25, 12)
    assert a_stream["output"]["content"] == "Hello from mock Claude."
    assert a_stream["output"]["streamed"] is True

    assert o_plain["name"] == "gateway.openai.completions"
    assert o_plain["model"] == "gpt-4o"
    assert (o_plain["input_tokens"], o_plain["output_tokens"]) == (9, 12)
    assert o_plain["output"]["content"] == "Hello from mock GPT."

    assert o_stream["model"] == "gpt-4o"
    assert (o_stream["input_tokens"], o_stream["output_tokens"]) == (9, 12)
    assert o_stream["output"]["streamed"] is True

    print("gateway mode: 4 proxied calls recorded with usage + cost; bad key rejected (401)")


if __name__ == "__main__":
    main()
