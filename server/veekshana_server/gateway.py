"""Gateway (proxy) mode: zero-code logging.

Point a provider SDK's base_url at Veekshana instead of the vendor, and every
call is recorded as a trace while being forwarded untouched:

    Anthropic(base_url="http://<veekshana>/gateway/anthropic",
              default_headers={"x-veekshana-key": "<key>"})
    OpenAI(base_url="http://<veekshana>/gateway/openai/v1",
           default_headers={"x-veekshana-key": "<key>"})

The vendor credential (Authorization / x-api-key) passes through unchanged;
`x-veekshana-key` authenticates to Veekshana and picks the project. Streaming
responses are relayed byte-for-byte while usage is parsed from the SSE text.

Upstreams default to the real vendors; override with
VEEKSHANA_GATEWAY_ANTHROPIC_URL / VEEKSHANA_GATEWAY_OPENAI_URL.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from .db import SessionLocal, SpanRow

try:
    from veekshana.cost import compute_cost
except ImportError:  # pragma: no cover
    def compute_cost(model, input_tokens, output_tokens):  # type: ignore
        return None

logger = logging.getLogger("veekshana.gateway")

router = APIRouter()

UPSTREAMS = {
    "anthropic": os.environ.get("VEEKSHANA_GATEWAY_ANTHROPIC_URL", "https://api.anthropic.com"),
    "openai": os.environ.get("VEEKSHANA_GATEWAY_OPENAI_URL", "https://api.openai.com"),
}
LLM_PATHS = ("v1/messages", "v1/chat/completions", "v1/responses")
SKIP_HEADERS = {"host", "content-length", "x-veekshana-key", "connection", "accept-encoding"}
SSE_BUFFER_CAP = 2_000_000  # parse usage from at most ~2MB of streamed text

_client: Optional[httpx.AsyncClient] = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0))
    return _client


def _summarize_request(body: bytes) -> Optional[dict]:
    try:
        obj = json.loads(body)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    return {
        "model": obj.get("model"),
        "messages": obj.get("messages") or obj.get("input"),
        "system": obj.get("system"),
        "stream": obj.get("stream"),
    }


def _parse_json_payload(provider: str, path: str, text: str):
    """-> (model, input_tokens, output_tokens, text, stop_reason)"""
    try:
        obj = json.loads(text)
    except ValueError:
        return None, None, None, None, None
    if not isinstance(obj, dict):
        return None, None, None, None, None
    model = obj.get("model")
    usage = obj.get("usage") or {}
    if provider == "anthropic":
        content = "".join(
            block.get("text", "")
            for block in obj.get("content") or []
            if isinstance(block, dict) and block.get("type") == "text"
        )
        return model, usage.get("input_tokens"), usage.get("output_tokens"), content, obj.get("stop_reason")
    if "chat/completions" in path:
        choices = obj.get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        stop = choices[0].get("finish_reason") if choices else None
        return model, usage.get("prompt_tokens"), usage.get("completion_tokens"), message.get("content"), stop
    # Responses API and friends
    input_t = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_t = usage.get("output_tokens", usage.get("completion_tokens"))
    return model, input_t, output_t, obj.get("output_text"), obj.get("status")


def _parse_sse_payload(provider: str, text: str):
    """-> (model, input_tokens, output_tokens, text, stop_reason)"""
    model = input_t = output_t = stop = None
    parts: list[str] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            obj = json.loads(data)
        except ValueError:
            continue
        etype = obj.get("type")
        if provider == "anthropic":
            if etype == "message_start":
                message = obj.get("message") or {}
                model = message.get("model") or model
                usage = message.get("usage") or {}
                input_t = usage.get("input_tokens", input_t)
            elif etype == "content_block_delta":
                delta = (obj.get("delta") or {}).get("text")
                if delta:
                    parts.append(delta)
            elif etype == "message_delta":
                usage = obj.get("usage") or {}
                if usage.get("output_tokens") is not None:
                    output_t = usage["output_tokens"]
                stop = (obj.get("delta") or {}).get("stop_reason") or stop
        elif etype and etype.startswith("response."):  # OpenAI Responses stream
            if etype == "response.output_text.delta":
                if obj.get("delta"):
                    parts.append(obj["delta"])
            elif etype in ("response.completed", "response.incomplete", "response.failed"):
                resp = obj.get("response") or {}
                model = resp.get("model") or model
                usage = resp.get("usage") or {}
                input_t = usage.get("input_tokens", input_t)
                output_t = usage.get("output_tokens", output_t)
                stop = etype.split(".", 1)[1]
        else:  # OpenAI chat completion chunk
            model = obj.get("model") or model
            usage = obj.get("usage")
            if usage:
                input_t = usage.get("prompt_tokens", input_t)
                output_t = usage.get("completion_tokens", output_t)
            for choice in obj.get("choices") or []:
                delta = (choice.get("delta") or {}).get("content")
                if delta:
                    parts.append(delta)
                if choice.get("finish_reason"):
                    stop = choice["finish_reason"]
    return model, input_t, output_t, "".join(parts), stop


def _write_span(
    *, project: str, provider: str, path: str, session_id: Optional[str],
    start_ms: float, input_value, status_code: Optional[int],
    content_type: str = "", payload_text: str = "", error: Optional[str] = None,
) -> None:
    try:
        if error is not None:
            model = input_t = output_t = text = stop = None
        elif "text/event-stream" in content_type:
            model, input_t, output_t, text, stop = _parse_sse_payload(provider, payload_text)
        else:
            model, input_t, output_t, text, stop = _parse_json_payload(provider, path, payload_text)
            if status_code and status_code >= 400 and error is None:
                error = f"upstream returned {status_code}: {payload_text[:300]}"
        output_value = None
        if error is None:
            output_value = {
                "content": text,
                "stop_reason": stop,
                "streamed": "text/event-stream" in content_type,
            }
        db = SessionLocal()
        try:
            db.add(SpanRow(
                span_id=uuid.uuid4().hex,
                trace_id=uuid.uuid4().hex,
                project_id=project,
                parent_span_id=None,
                name=f"gateway.{provider}.{path.rsplit('/', 1)[-1]}",
                span_type="llm" if path in LLM_PATHS else "span",
                session_id=session_id,
                start_time=start_ms,
                end_time=time.time() * 1000.0,
                input=input_value,
                output=output_value,
                error=error,
                model=model,
                input_tokens=input_t,
                output_tokens=output_t,
                cost_usd=compute_cost(model, input_t, output_t),
            ))
            db.commit()
        finally:
            db.close()
    except Exception:  # recording must never break the proxied call
        logger.warning("gateway: failed to record span", exc_info=True)


@router.post("/gateway/{provider}/{path:path}")
async def gateway(provider: str, path: str, request: Request):
    from .main import API_KEYS  # late import to avoid a circular import

    upstream_base = UPSTREAMS.get(provider)
    if upstream_base is None:
        raise HTTPException(status_code=404, detail=f"unknown gateway provider '{provider}'")
    project = API_KEYS.get(request.headers.get("x-veekshana-key") or "")
    if project is None:
        raise HTTPException(status_code=401, detail="missing or invalid x-veekshana-key header")

    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in SKIP_HEADERS}
    session_id = request.headers.get("x-veekshana-session")
    start_ms = time.time() * 1000.0
    input_value = _summarize_request(body)

    http = _http()
    upstream_request = http.build_request(
        "POST", f"{upstream_base.rstrip('/')}/{path}", content=body, headers=headers
    )
    try:
        upstream = await http.send(upstream_request, stream=True)
    except Exception as exc:
        _write_span(
            project=project, provider=provider, path=path, session_id=session_id,
            start_ms=start_ms, input_value=input_value, status_code=None,
            error=f"upstream unreachable: {exc}",
        )
        raise HTTPException(status_code=502, detail=f"upstream unreachable: {exc}")

    content_type = upstream.headers.get("content-type", "")

    if "text/event-stream" in content_type:
        async def relay():
            buffer = bytearray()
            try:
                async for chunk in upstream.aiter_bytes():
                    if len(buffer) < SSE_BUFFER_CAP:
                        buffer.extend(chunk)
                    yield chunk
            finally:
                await upstream.aclose()
                _write_span(
                    project=project, provider=provider, path=path, session_id=session_id,
                    start_ms=start_ms, input_value=input_value,
                    status_code=upstream.status_code, content_type=content_type,
                    payload_text=bytes(buffer).decode("utf-8", "replace"),
                )

        return StreamingResponse(
            relay(), status_code=upstream.status_code, media_type="text/event-stream"
        )

    raw = await upstream.aread()
    await upstream.aclose()
    _write_span(
        project=project, provider=provider, path=path, session_id=session_id,
        start_ms=start_ms, input_value=input_value,
        status_code=upstream.status_code, content_type=content_type,
        payload_text=raw.decode("utf-8", "replace"),
    )
    return Response(
        content=raw,
        status_code=upstream.status_code,
        media_type=content_type.split(";")[0] or "application/json",
    )
