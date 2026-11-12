"""API schemas."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SpanIn(BaseModel):
    span_id: str = Field(max_length=64)
    trace_id: str = Field(max_length=64)
    parent_span_id: Optional[str] = None
    name: str
    span_type: str = "span"
    session_id: Optional[str] = None
    start_time: float
    end_time: Optional[float] = None
    input: Any = None
    output: Any = None
    error: Optional[str] = None
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    metadata: Optional[dict] = None


class IngestRequest(BaseModel):
    spans: list[SpanIn] = Field(max_length=1000)


class TraceSummary(BaseModel):
    trace_id: str
    name: str                     # root span name
    session_id: Optional[str]
    start_time: float
    duration_ms: Optional[float]
    span_count: int
    llm_call_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    has_error: bool
