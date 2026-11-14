"""Auto-instrumentation for the Anthropic Python SDK.

Patches Messages.create and Messages.stream (sync + async) so every LLM call —
streamed or not — becomes an "llm" span with model, prompt, response, token
usage, cost, and latency. No code changes.
"""

from __future__ import annotations

import logging

from .. import context
from ..cost import compute_cost
from ..decorators import _finish_span, _start_span
from ._streaming import StreamState, WrappedAsyncStream, WrappedStream, finish_stream_span

logger = logging.getLogger("veekshana")

_patched = False


class _AnthropicStreamState(StreamState):
    """Accumulates Anthropic SSE events (message_start/content_block_delta/message_delta)."""

    def feed(self, event) -> None:
        etype = getattr(event, "type", None)
        if etype == "message_start":
            message = getattr(event, "message", None)
            self.model = getattr(message, "model", None) or self.model
            usage = getattr(message, "usage", None)
            if usage is not None:
                self.input_tokens = getattr(usage, "input_tokens", None)
                self.output_tokens = getattr(usage, "output_tokens", None) or self.output_tokens
        elif etype == "content_block_delta":
            text = getattr(getattr(event, "delta", None), "text", None)
            if text:
                self.parts.append(text)
        elif etype == "message_delta":
            usage = getattr(event, "usage", None)
            out = getattr(usage, "output_tokens", None) if usage is not None else None
            if out is not None:
                self.output_tokens = out
            stop = getattr(getattr(event, "delta", None), "stop_reason", None)
            if stop:
                self.stop_reason = stop


class _StreamManagerWrapper:
    """Wraps MessageStreamManager (client.messages.stream(...) used as a context
    manager). On exit, the SDK's accumulated final message gives exact usage."""

    def __init__(self, manager, span, token) -> None:
        self._manager = manager
        self._span = span
        self._token = token

    def __enter__(self):
        self._stream = self._manager.__enter__()
        return self._stream

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                try:
                    final = self._stream.get_final_message()
                    output = _record_response(self._span, final)
                    output["streamed"] = True
                    _finish_span(self._span, self._token, output=output)
                except Exception as inner:
                    _finish_span(
                        self._span, self._token,
                        output={"streamed": True, "note": f"final message unavailable: {inner}"},
                    )
            else:
                _finish_span(self._span, self._token, error=f"{exc_type.__name__}: {exc}")
        except Exception:
            logger.debug("veekshana: failed to finish stream span", exc_info=True)
        return self._manager.__exit__(exc_type, exc, tb)


class _AsyncStreamManagerWrapper:
    def __init__(self, manager, span, token) -> None:
        self._manager = manager
        self._span = span
        self._token = token

    async def __aenter__(self):
        self._stream = await self._manager.__aenter__()
        return self._stream

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                try:
                    final = await self._stream.get_final_message()
                    output = _record_response(self._span, final)
                    output["streamed"] = True
                    _finish_span(self._span, self._token, output=output)
                except Exception as inner:
                    _finish_span(
                        self._span, self._token,
                        output={"streamed": True, "note": f"final message unavailable: {inner}"},
                    )
            else:
                _finish_span(self._span, self._token, error=f"{exc_type.__name__}: {exc}")
        except Exception:
            logger.debug("veekshana: failed to finish stream span", exc_info=True)
        return await self._manager.__aexit__(exc_type, exc, tb)


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
    original_stream = getattr(Messages, "stream", None)
    original_async_stream = getattr(AsyncMessages, "stream", None)

    def patched_create(self, *args, **kwargs):
        span, token = _start_span(
            name="anthropic.messages.create",
            span_type="llm",
            input_value=_summarize_request(kwargs),
        )
        try:
            response = original_create(self, *args, **kwargs)
        except BaseException as exc:
            _finish_span(span, token, error=f"{type(exc).__name__}: {exc}")
            raise
        if kwargs.get("stream"):
            return WrappedStream(response, span, token, _AnthropicStreamState())
        output = _record_response(span, response)
        _finish_span(span, token, output=output)
        return response

    async def patched_async_create(self, *args, **kwargs):
        span, token = _start_span(
            name="anthropic.messages.create",
            span_type="llm",
            input_value=_summarize_request(kwargs),
        )
        try:
            response = await original_async_create(self, *args, **kwargs)
        except BaseException as exc:
            _finish_span(span, token, error=f"{type(exc).__name__}: {exc}")
            raise
        if kwargs.get("stream"):
            return WrappedAsyncStream(response, span, token, _AnthropicStreamState())
        output = _record_response(span, response)
        _finish_span(span, token, output=output)
        return response

    def patched_stream(self, *args, **kwargs):
        span, token = _start_span(
            name="anthropic.messages.stream",
            span_type="llm",
            input_value=_summarize_request(kwargs),
        )
        try:
            manager = original_stream(self, *args, **kwargs)
        except BaseException as exc:
            _finish_span(span, token, error=f"{type(exc).__name__}: {exc}")
            raise
        return _StreamManagerWrapper(manager, span, token)

    def patched_async_stream(self, *args, **kwargs):
        span, token = _start_span(
            name="anthropic.messages.stream",
            span_type="llm",
            input_value=_summarize_request(kwargs),
        )
        try:
            manager = original_async_stream(self, *args, **kwargs)
        except BaseException as exc:
            _finish_span(span, token, error=f"{type(exc).__name__}: {exc}")
            raise
        return _AsyncStreamManagerWrapper(manager, span, token)

    Messages.create = patched_create
    AsyncMessages.create = patched_async_create
    if original_stream is not None:
        Messages.stream = patched_stream
    if original_async_stream is not None:
        AsyncMessages.stream = patched_async_stream
    _patched = True
    logger.info("veekshana: anthropic SDK instrumented")
    return True
