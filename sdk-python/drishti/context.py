"""Trace context propagation via contextvars (works across async + threads started with copy_context)."""

from __future__ import annotations

import contextvars
from typing import Optional

from .models import Span

# Stack of active spans in the current execution context.
_span_stack: contextvars.ContextVar[tuple] = contextvars.ContextVar("drishti_span_stack", default=())
_session_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("drishti_session_id", default=None)


def current_span() -> Optional[Span]:
    stack = _span_stack.get()
    return stack[-1] if stack else None


def current_trace_id() -> Optional[str]:
    span = current_span()
    return span.trace_id if span else None


def push_span(span: Span) -> contextvars.Token:
    return _span_stack.set(_span_stack.get() + (span,))


def pop_span(token: contextvars.Token) -> None:
    _span_stack.reset(token)


def set_session(session_id: Optional[str]) -> None:
    """Group subsequent traces under one session (e.g. one user conversation)."""
    _session_id.set(session_id)


def get_session() -> Optional[str]:
    return _session_id.get()
