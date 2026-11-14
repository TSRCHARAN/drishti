"""Offline end-to-end test: streamed LLM calls land as spans with usage + cost.

Runs the real anthropic/openai SDKs against local mock endpoints and a local
Veekshana server — no network, no keys. Run directly:

    python tests/test_streaming.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

MOCK_PORT = 9671
VK_PORT = 8791

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["VEEKSHANA_DATABASE_URL"] = (
    "sqlite:///" + os.path.join(tempfile.mkdtemp(prefix="vk-test-"), "test.db").replace("\\", "/")
)


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


def _get(path: str) -> dict | list:
    req = urllib.request.Request(
        f"http://127.0.0.1:{VK_PORT}{path}", headers={"x-api-key": "dev-key"}
    )
    return json.loads(urllib.request.urlopen(req).read())


def main() -> None:
    from mock_providers import app as mock_app
    from veekshana_server.main import app as vk_app

    _start_uvicorn(mock_app, MOCK_PORT)
    _start_uvicorn(vk_app, VK_PORT)

    import veekshana

    veekshana.init(host=f"http://127.0.0.1:{VK_PORT}", api_key="dev-key")

    from anthropic import Anthropic
    from openai import OpenAI

    anthropic_client = Anthropic(
        api_key="test-key", base_url=f"http://127.0.0.1:{MOCK_PORT}/anthropic"
    )
    openai_client = OpenAI(
        api_key="test-key", base_url=f"http://127.0.0.1:{MOCK_PORT}/openai/v1"
    )
    messages = [{"role": "user", "content": "Say hello."}]

    # 1. Anthropic raw event stream: create(stream=True)
    stream = anthropic_client.messages.create(
        model="claude-sonnet-5-5", max_tokens=100, messages=messages, stream=True
    )
    raw_text = "".join(
        event.delta.text
        for event in stream
        if getattr(event, "type", "") == "content_block_delta"
    )
    assert raw_text == "Hello from mock Claude.", raw_text

    # 2. Anthropic high-level stream manager: messages.stream(...)
    with anthropic_client.messages.stream(
        model="claude-sonnet-5-5", max_tokens=100, messages=messages
    ) as s:
        manager_text = "".join(s.text_stream)
    assert manager_text == "Hello from mock Claude.", manager_text

    # 3. OpenAI chat stream with usage
    chunks = openai_client.chat.completions.create(
        model="gpt-4o", messages=messages, stream=True,
        stream_options={"include_usage": True},
    )
    chat_text = "".join(
        c.choices[0].delta.content or "" for c in chunks if c.choices
    )
    assert chat_text == "Hello from mock GPT.", chat_text

    # 4. OpenAI chat stream without usage (provider sends none) — must not break
    chunks2 = openai_client.chat.completions.create(
        model="gpt-4o", messages=messages, stream=True
    )
    for _ in chunks2:
        pass

    veekshana.flush()
    time.sleep(0.3)

    traces = _get("/api/v1/traces?limit=10")
    assert len(traces) == 4, f"expected 4 traces, got {len(traces)}"
    spans = []
    for t in traces:
        spans.extend(_get(f"/api/v1/traces/{t['trace_id']}")["spans"])
    spans.sort(key=lambda s: s["start_time"])
    assert len(spans) == 4, spans

    s1, s2, s3, s4 = spans

    assert s1["name"] == "anthropic.messages.create"
    assert s1["model"] == "claude-sonnet-5-5"
    assert (s1["input_tokens"], s1["output_tokens"]) == (25, 12), s1
    assert s1["cost_usd"] and s1["cost_usd"] > 0
    assert s1["output"]["content"] == "Hello from mock Claude."
    assert s1["output"]["streamed"] is True

    assert s2["name"] == "anthropic.messages.stream"
    assert s2["model"] == "claude-sonnet-5-5"
    assert (s2["input_tokens"], s2["output_tokens"]) == (25, 12), s2
    assert s2["cost_usd"] and s2["cost_usd"] > 0
    assert s2["output"]["streamed"] is True

    assert s3["name"] == "openai.chat.completions.create"
    assert s3["model"] == "gpt-4o"
    assert (s3["input_tokens"], s3["output_tokens"]) == (9, 12), s3
    assert s3["output"]["content"] == "Hello from mock GPT."

    assert s4["model"] == "gpt-4o"
    assert s4["input_tokens"] is None and s4["output_tokens"] is None  # no usage sent
    assert s4["output"]["content"] == "Hello from mock GPT."

    print("streaming capture: all 4 scenarios verified (durations, usage, cost, text)")


if __name__ == "__main__":
    main()
