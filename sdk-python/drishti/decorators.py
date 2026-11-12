"""The @observe decorator and manual span API."""

from __future__ import annotations

import functools
import inspect
from contextlib import contextmanager
from typing import Any, Callable, Optional

from . import context
from .exporter import get_exporter
from .models import Span, new_id


def _start_span(name: str, span_type: str, input_value: Any) -> tuple[Span, Any]:
    parent = context.current_span()
    span = Span(
        name=name,
        trace_id=parent.trace_id if parent else new_id(),
        parent_span_id=parent.span_id if parent else None,
        span_type=span_type,
        session_id=context.get_session(),
        input=input_value,
    )
    token = context.push_span(span)
    return span, token


def _finish_span(span: Span, token: Any, output: Any = None, error: Optional[str] = None) -> None:
    span.output = output
    span.error = error
    span.end()
    context.pop_span(token)
    exporter = get_exporter()
    if exporter is not None:
        exporter.submit(span)


def _capture_args(func: Callable, args: tuple, kwargs: dict) -> Any:
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
        bound.apply_defaults()
        captured = dict(bound.arguments)
        captured.pop("self", None)
        captured.pop("cls", None)
        return captured
    except Exception:
        return {"args": list(args), "kwargs": kwargs}


def observe(
    name: Optional[str] = None,
    span_type: str = "span",
    capture_input: bool = True,
    capture_output: bool = True,
) -> Callable:
    """Decorator: record this function as a span. Nested observed calls become child spans;
    the outermost call starts a new trace."""

    def decorator(func: Callable) -> Callable:
        span_name = name or func.__qualname__

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                input_value = _capture_args(func, args, kwargs) if capture_input else None
                span, token = _start_span(span_name, span_type, input_value)
                try:
                    result = await func(*args, **kwargs)
                except BaseException as exc:
                    _finish_span(span, token, error=f"{type(exc).__name__}: {exc}")
                    raise
                _finish_span(span, token, output=result if capture_output else None)
                return result

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            input_value = _capture_args(func, args, kwargs) if capture_input else None
            span, token = _start_span(span_name, span_type, input_value)
            try:
                result = func(*args, **kwargs)
            except BaseException as exc:
                _finish_span(span, token, error=f"{type(exc).__name__}: {exc}")
                raise
            _finish_span(span, token, output=result if capture_output else None)
            return result

        return wrapper

    return decorator


@contextmanager
def span(name: str, span_type: str = "span", input: Any = None):
    """Manual span context manager:

        with drishti.span("retrieve-docs", input=query) as s:
            s.output = docs
    """
    sp, token = _start_span(name, span_type, input)
    try:
        yield sp
    except BaseException as exc:
        _finish_span(sp, token, output=sp.output, error=f"{type(exc).__name__}: {exc}")
        raise
    _finish_span(sp, token, output=sp.output)


def update_current_span(**fields: Any) -> None:
    """Attach data to the active span, e.g. model/usage/cost from inside an observed function:

        drishti.update_current_span(model="claude-sonnet-5-5", input_tokens=812, output_tokens=102)
    """
    sp = context.current_span()
    if sp is None:
        return
    for key, value in fields.items():
        if hasattr(sp, key):
            setattr(sp, key, value)
        else:
            sp.metadata[key] = value
