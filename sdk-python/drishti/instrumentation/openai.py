"""Auto-instrumentation for the OpenAI Python SDK (v1+).

Covers chat.completions.create and the newer responses.create, sync and async.
Because most providers (Groq, Together, Ollama, OpenRouter, DeepSeek, Mistral,
Gemini's compat endpoint, ...) are OpenAI-API-compatible and used through this
SDK with a custom base_url, this one wrapper observes all of them.
"""

from __future__ import annotations

import logging

from ..cost import compute_cost
from ..decorators import _finish_span, _start_span

logger = logging.getLogger("drishti")

_patched = False


def _summarize_chat_request(kwargs: dict) -> dict:
    return {
        "model": kwargs.get("model"),
        "messages": kwargs.get("messages"),
        "max_tokens": kwargs.get("max_tokens") or kwargs.get("max_completion_tokens"),
        "tools": [
            t.get("function", {}).get("name")
            for t in kwargs.get("tools", [])
            if isinstance(t, dict)
        ] or None,
    }


def _record_chat_response(span, response) -> dict:
    model = getattr(response, "model", None)
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
    output_tokens = getattr(usage, "completion_tokens", None) if usage else None
    span.model = model
    span.input_tokens = input_tokens
    span.output_tokens = output_tokens
    span.cost_usd = compute_cost(model, input_tokens, output_tokens)
    try:
        choices = [c.message.model_dump(exclude_none=True) for c in response.choices]
    except Exception:
        choices = str(getattr(response, "choices", response))
    return {"choices": choices}


def _record_responses_response(span, response) -> dict:
    model = getattr(response, "model", None)
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None) if usage else None
    output_tokens = getattr(usage, "output_tokens", None) if usage else None
    span.model = model
    span.input_tokens = input_tokens
    span.output_tokens = output_tokens
    span.cost_usd = compute_cost(model, input_tokens, output_tokens)
    return {"output_text": getattr(response, "output_text", None)}


def _wrap(original, name: str, summarize, record):
    def patched(self, *args, **kwargs):
        span, token = _start_span(name=name, span_type="llm", input_value=summarize(kwargs))
        try:
            response = original(self, *args, **kwargs)
        except BaseException as exc:
            _finish_span(span, token, error=f"{type(exc).__name__}: {exc}")
            raise
        output = record(span, response)
        _finish_span(span, token, output=output)
        return response

    return patched


def _wrap_async(original, name: str, summarize, record):
    async def patched(self, *args, **kwargs):
        span, token = _start_span(name=name, span_type="llm", input_value=summarize(kwargs))
        try:
            response = await original(self, *args, **kwargs)
        except BaseException as exc:
            _finish_span(span, token, error=f"{type(exc).__name__}: {exc}")
            raise
        output = record(span, response)
        _finish_span(span, token, output=output)
        return response

    return patched


def instrument_openai() -> bool:
    """Patch the installed openai SDK. Returns True if patched."""
    global _patched
    if _patched:
        return True
    try:
        from openai.resources.chat.completions import AsyncCompletions, Completions
    except ImportError:
        return False

    Completions.create = _wrap(
        Completions.create, "openai.chat.completions.create",
        _summarize_chat_request, _record_chat_response,
    )
    AsyncCompletions.create = _wrap_async(
        AsyncCompletions.create, "openai.chat.completions.create",
        _summarize_chat_request, _record_chat_response,
    )

    try:  # Responses API exists on newer SDK versions only
        from openai.resources.responses import AsyncResponses, Responses

        Responses.create = _wrap(
            Responses.create, "openai.responses.create",
            lambda kw: {"model": kw.get("model"), "input": kw.get("input")},
            _record_responses_response,
        )
        AsyncResponses.create = _wrap_async(
            AsyncResponses.create, "openai.responses.create",
            lambda kw: {"model": kw.get("model"), "input": kw.get("input")},
            _record_responses_response,
        )
    except ImportError:
        pass

    _patched = True
    logger.info("drishti: openai SDK instrumented")
    return True
