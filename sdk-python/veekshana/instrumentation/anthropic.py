"""Auto-instrumentation for the Anthropic Python SDK.

Patches Messages.create (sync + async) so every LLM call becomes an "llm" span
with model, prompt, response, token usage, cost, and latency — no code changes.
"""

from __future__ import annotations

import logging

from .. import context
from ..cost import compute_cost
from ..decorators import _finish_span, _start_span

logger = logging.getLogger("veekshana")

_patched = False


def _summarize_request(kwargs: dict) -> dict:
    return {
        "model": kwargs.get("model"),
        "system": kwargs.get("system"),
        "messages": kwargs.get("messages"),
        "max_tokens": kwargs.get("max_tokens"),
        "tools": [t.get("name") for t in kwargs.get("tools", []) if isinstance(t, dict)] or None,
    }


def _record_response(span, response) -> dict:
    model = getattr(response, "model", None)
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None) if usage else None
    output_tokens = getattr(usage, "output_tokens", None) if usage else None
    span.model = model
    span.input_tokens = input_tokens
    span.output_tokens = output_tokens
    span.cost_usd = compute_cost(model, input_tokens, output_tokens)
    try:
        content = [block.model_dump() for block in response.content]
    except Exception:
        content = str(getattr(response, "content", response))
    return {"content": content, "stop_reason": getattr(response, "stop_reason", None)}


def instrument_anthropic() -> bool:
    """Patch the installed anthropic SDK. Returns True if patched."""
    global _patched
    if _patched:
        return True
    try:
        from anthropic.resources.messages import AsyncMessages, Messages
    except ImportError:
        return False

    original_create = Messages.create
    original_async_create = AsyncMessages.create

    def patched_create(self, *args, **kwargs):
        span, token = _start_span(
            name=f"anthropic.messages.create",
            span_type="llm",
            input_value=_summarize_request(kwargs),
        )
        try:
            response = original_create(self, *args, **kwargs)
        except BaseException as exc:
            _finish_span(span, token, error=f"{type(exc).__name__}: {exc}")
            raise
        output = _record_response(span, response)
        _finish_span(span, token, output=output)
        return response

    async def patched_async_create(self, *args, **kwargs):
        span, token = _start_span(
            name=f"anthropic.messages.create",
            span_type="llm",
            input_value=_summarize_request(kwargs),
        )
        try:
            response = await original_async_create(self, *args, **kwargs)
        except BaseException as exc:
            _finish_span(span, token, error=f"{type(exc).__name__}: {exc}")
            raise
        output = _record_response(span, response)
        _finish_span(span, token, output=output)
        return response

    Messages.create = patched_create
    AsyncMessages.create = patched_async_create
    _patched = True
    logger.info("veekshana: anthropic SDK instrumented")
    return True
