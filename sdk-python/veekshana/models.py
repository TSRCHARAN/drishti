"""Core data model: a Span is one unit of work inside a trace."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

MAX_PAYLOAD_CHARS = 20_000  # truncate huge prompts/outputs so ingestion stays cheap


def new_id() -> str:
    return uuid.uuid4().hex


def now_ms() -> float:
    return time.time() * 1000.0


def safe_serialize(value: Any, max_chars: int = MAX_PAYLOAD_CHARS) -> Any:
    """Make any value JSON-safe; truncate if enormous."""
    if value is None:
        return None
    try:
        text = json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = json.dumps(str(value), ensure_ascii=False)
    if len(text) > max_chars:
        return {"_truncated": True, "preview": text[:max_chars]}
    return json.loads(text)


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str = field(default_factory=new_id)
    parent_span_id: Optional[str] = None
    span_type: str = "span"  # "span" | "llm" | "tool"
    session_id: Optional[str] = None
    start_time: float = field(default_factory=now_ms)  # epoch ms
    end_time: Optional[float] = None
    input: Any = None
    output: Any = None
    error: Optional[str] = None
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    metadata: dict = field(default_factory=dict)

    def end(self) -> None:
        if self.end_time is None:
            self.end_time = now_ms()

    def to_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "span_type": self.span_type,
            "session_id": self.session_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "input": safe_serialize(self.input),
            "output": safe_serialize(self.output),
            "error": self.error,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "metadata": safe_serialize(self.metadata) or {},
        }
