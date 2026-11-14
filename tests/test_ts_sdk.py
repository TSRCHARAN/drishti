"""Harness for the TypeScript SDK smoke test: builds nothing (expects
sdk-ts/dist to exist), starts a local Veekshana server, runs tests/ts_smoke.mjs
with node, and asserts the resulting trace. Run directly:

    python tests/test_ts_sdk.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

VK_PORT = 8793

os.environ["VEEKSHANA_DATABASE_URL"] = (
    "sqlite:///" + os.path.join(tempfile.mkdtemp(prefix="vk-tstest-"), "test.db").replace("\\", "/")
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
    from veekshana_server.main import app as vk_app

    _start_uvicorn(vk_app, VK_PORT)

    env = dict(os.environ, VK_HOST=f"http://127.0.0.1:{VK_PORT}")
    result = subprocess.run(
        ["node", os.path.join(REPO, "tests", "ts_smoke.mjs")],
        env=env, capture_output=True, text=True, shell=(os.name == "nt"),
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise SystemExit("node smoke script failed")

    traces = _get("/api/v1/traces?limit=5")
    assert len(traces) == 1, f"expected 1 trace, got {len(traces)}"
    trace = _get(f"/api/v1/traces/{traces[0]['trace_id']}")
    spans = sorted(trace["spans"], key=lambda s: s["start_time"])
    assert len(spans) == 3, spans

    root = next(s for s in spans if s["parent_span_id"] is None)
    assert root["name"] == "myAgent"
    assert root["session_id"] == "ts-smoke-session"
    children = [s for s in spans if s["parent_span_id"] == root["span_id"]]
    assert len(children) == 2, children

    plain, streamed = sorted(children, key=lambda s: s["start_time"])
    for s in (plain, streamed):
        assert s["name"] == "openai.chat.completions.create"
        assert s["span_type"] == "llm"
        assert s["model"] == "gpt-4o"
        assert (s["input_tokens"], s["output_tokens"]) == (5, 7), s
        assert s["cost_usd"] and s["cost_usd"] > 0
    assert plain["output"]["content"] == "Hi there"
    assert streamed["output"]["content"] == "Hi streamed"
    assert streamed["output"]["streamed"] is True

    print("ts sdk: trace tree, llm children, streamed usage + cost all verified")


if __name__ == "__main__":
    main()
