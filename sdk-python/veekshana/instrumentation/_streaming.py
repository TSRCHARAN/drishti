"""Shared machinery for capturing streamed LLM calls.

A wrapped stream is a transparent passthrough: every event is handed to the
consumer unchanged, while a provider-specific accumulator collects model,
token usage, and text deltas. The span finishes when the stream is exhausted,
closed, or raises — with whatever was accumulated by then.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..cost import compute_cost
from ..decorators import _finish_span

logger = logging.getLogger("veekshana")


class StreamState:
    """Base accumulator. Providers subclass and implement feed(event)."""

    def __init__(self) -> None:
        self.model: Optional[str] = None
        self.input_tokens: Optional[int] = None
        self.output_tokens: Optional[int] = None
        self.stop_reason: Optional[str] = None
        self.parts: list[str] = []

    def feed(self, event: Any) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def output(self) -> dict:
        return {
            "content": "".join(self.parts),
            "stop_reason": self.stop_reason,
            "streamed": True,
        }


def finish_stream_span(span, token, state: StreamState, error: Optional[str] = None) -> None:
    span.model = state.model
    span.input_tokens = state.input_tokens
    span.output_tokens = state.output_tokens
    span.cost_usd = compute_cost(state.model, state.input_tokens, state.output_tokens)
    try:
        _finish_span(span, token, output=state.output(), error=error)
    except Exception:  # never break the host app over telemetry
        logger.debug("veekshana: failed to finish streamed span", exc_info=True)


class WrappedStream:
    """Sync passthrough wrapper around a provider stream object."""

    def __init__(self, inner, span, token, state: StreamState) -> None:
        self._vk_inner = inner
        self._vk_span = span
        self._vk_token = token
        self._vk_state = state
        self._vk_done = False

    def _vk_finish(self, error: Optional[str] = None) -> None:
        if self._vk_done:
            return
        self._vk_done = True
        finish_stream_span(self._vk_span, self._vk_token, self._vk_state, error)

    def __iter__(self):
        return self

    def __next__(self):
        try:
            event = self._vk_inner.__next__()
        except StopIteration:
            self._vk_finish()
            raise
        except BaseException as exc:
            self._vk_finish(error=f"{type(exc).__name__}: {exc}")
            raise
        try:
            self._vk_state.feed(event)
        except Exception:
            pass
        return event

    def __enter__(self):
        enter = getattr(self._vk_inner, "__enter__", None)
        if enter is not None:
            enter()
        return self

    def __exit__(self, exc_type, exc, tb):
        exit_ = getattr(self._vk_inner, "__exit__", None)
        result = exit_(exc_type, exc, tb) if exit_ is not None else False
        self._vk_finish(error=f"{exc_type.__name__}: {exc}" if exc_type else None)
        return result

    def close(self):
        close = getattr(self._vk_inner, "close", None)
        if close is not None:
            close()
        self._vk_finish()

    def __getattr__(self, name):
        return getattr(self._vk_inner, name)


class WrappedAsyncStream:
    """Async passthrough wrapper around a provider stream object."""

    def __init__(self, inner, span, token, state: StreamState) -> None:
        self._vk_inner = inner
        self._vk_span = span
        self._vk_token = token
        self._vk_state = state
        self._vk_done = False

    def _vk_finish(self, error: Optional[str] = None) -> None:
        if self._vk_done:
            return
        self._vk_done = True
        finish_stream_span(self._vk_span, self._vk_token, self._vk_state, error)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            event = await self._vk_inner.__anext__()
        except StopAsyncIteration:
            self._vk_finish()
            raise
        except BaseException as exc:
            self._vk_finish(error=f"{type(exc).__name__}: {exc}")
            raise
        try:
            self._vk_state.feed(event)
        except Exception:
            pass
        return event

    async def __aenter__(self):
        enter = getattr(self._vk_inner, "__aenter__", None)
        if enter is not None:
            await enter()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        exit_ = getattr(self._vk_inner, "__aexit__", None)
        result = (await exit_(exc_type, exc, tb)) if exit_ is not None else False
        self._vk_finish(error=f"{exc_type.__name__}: {exc}" if exc_type else None)
        return result

    async def aclose(self):
        close = getattr(self._vk_inner, "aclose", None) or getattr(self._vk_inner, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
        self._vk_finish()

    def __getattr__(self, name):
        return getattr(self._vk_inner, name)
