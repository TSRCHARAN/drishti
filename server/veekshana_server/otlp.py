"""OTLP/HTTP trace ingest: OpenTelemetry spans → Veekshana spans.

Accepts both OTLP encodings on POST /v1/traces:
  - application/x-protobuf  (the OTel SDK default for http exporters)
  - application/json        (OTLP/JSON)

Maps GenAI semantic conventions (and the OpenLLMetry/Traceloop dialect) onto
Veekshana's span model, so existing instrumentation points here with only an
endpoint + header change:

    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:8787/v1/traces
    OTEL_EXPORTER_OTLP_TRACES_HEADERS=x-api-key=dev-key
"""

from __future__ import annotations

import json
from typing import Any, Optional

try:  # reuse the SDK's pricing table when it is installed alongside the server
    from veekshana.cost import compute_cost
except ImportError:  # pragma: no cover
    def compute_cost(model, input_tokens, output_tokens):  # type: ignore
        return None

_MAX_FIELD = 20_000

# Attribute aliases, newest conventions first.
_MODEL_KEYS = ["gen_ai.response.model", "gen_ai.request.model", "llm.response.model", "llm.request.model"]
_INPUT_TOKEN_KEYS = ["gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens", "llm.usage.prompt_tokens"]
_OUTPUT_TOKEN_KEYS = ["gen_ai.usage.output_tokens", "gen_ai.usage.completion_tokens", "llm.usage.completion_tokens"]
_SESSION_KEYS = ["gen_ai.conversation.id", "session.id", "langfuse.session.id", "traceloop.association.properties.session_id"]


def _any_value(v: dict) -> Any:
    """Decode an OTLP JSON AnyValue."""
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        return int(v["intValue"])  # proto3 JSON renders int64 as string
    if "doubleValue" in v:
        return v["doubleValue"]
    if "boolValue" in v:
        return v["boolValue"]
    if "arrayValue" in v:
        return [_any_value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return {kv["key"]: _any_value(kv.get("value", {})) for kv in v["kvlistValue"].get("values", [])}
    if "bytesValue" in v:
        return v["bytesValue"]
    return None


def _pb_any_value(v) -> Any:
    """Decode a protobuf AnyValue."""
    kind = v.WhichOneof("value")
    if kind is None:
        return None
    if kind == "array_value":
        return [_pb_any_value(x) for x in v.array_value.values]
    if kind == "kvlist_value":
        return {kv.key: _pb_any_value(kv.value) for kv in v.kvlist_value.values}
    if kind == "bytes_value":
        return v.bytes_value.hex()
    return getattr(v, kind)


def _first(attrs: dict, keys: list[str]) -> Any:
    for k in keys:
        if k in attrs:
            return attrs[k]
    return None


def _collect_prefixed(attrs: dict, prefixes: list[str]) -> Optional[Any]:
    """Collect e.g. gen_ai.prompt / gen_ai.prompt.0.content style attributes."""
    for prefix in prefixes:
        if prefix in attrs:
            value = attrs[prefix]
            if isinstance(value, str) and len(value) > _MAX_FIELD:
                return value[:_MAX_FIELD]
            return value
        nested = {k[len(prefix) + 1:]: v for k, v in attrs.items() if k.startswith(prefix + ".")}
        if nested:
            return nested
    return None


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def map_otel_span(
    trace_id: str,
    span_id: str,
    parent_span_id: Optional[str],
    name: str,
    start_ns: int,
    end_ns: int,
    attrs: dict,
    status_code: Any,
    status_message: str,
) -> dict:
    """Map one decoded OTel span to a Veekshana span dict (matches SpanIn)."""
    model = _first(attrs, _MODEL_KEYS)
    input_tokens = _to_int(_first(attrs, _INPUT_TOKEN_KEYS))
    output_tokens = _to_int(_first(attrs, _OUTPUT_TOKEN_KEYS))

    if model or "gen_ai.system" in attrs or "gen_ai.operation.name" in attrs:
        span_type = "llm"
    elif "gen_ai.tool.name" in attrs or attrs.get("traceloop.span.kind") == "tool":
        span_type = "tool"
    else:
        span_type = "span"

    input_value = _collect_prefixed(attrs, ["gen_ai.prompt", "gen_ai.input.messages", "traceloop.entity.input"])
    output_value = _collect_prefixed(attrs, ["gen_ai.completion", "gen_ai.output.messages", "traceloop.entity.output"])

    is_error = status_code in (2, "STATUS_CODE_ERROR", "2")
    metadata = {
        k: (v if not (isinstance(v, str) and len(v) > 2000) else v[:2000])
        for k, v in attrs.items()
        if len(json.dumps({k: v}, default=str)) < 4000
    }
    metadata["otel"] = True

    return {
        "span_id": span_id,
        "trace_id": trace_id,
        "parent_span_id": parent_span_id or None,
        "name": name or "span",
        "span_type": span_type,
        "session_id": _first(attrs, _SESSION_KEYS),
        "start_time": start_ns / 1_000_000,
        "end_time": end_ns / 1_000_000 if end_ns else None,
        "input": input_value,
        "output": output_value,
        "error": (status_message or "error") if is_error else None,
        "model": str(model) if model else None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": compute_cost(str(model) if model else None, input_tokens, output_tokens),
        "metadata": metadata,
    }


def parse_otlp_json(body: bytes) -> list[dict]:
    """Parse an OTLP/JSON ExportTraceServiceRequest into Veekshana span dicts."""
    payload = json.loads(body)
    out: list[dict] = []
    for rs in payload.get("resourceSpans", []):
        for ss in rs.get("scopeSpans", []) + rs.get("instrumentationLibrarySpans", []):
            for span in ss.get("spans", []):
                attrs = {a["key"]: _any_value(a.get("value", {})) for a in span.get("attributes", [])}
                status = span.get("status", {}) or {}
                out.append(
                    map_otel_span(
                        trace_id=span.get("traceId", ""),
                        span_id=span.get("spanId", ""),
                        parent_span_id=span.get("parentSpanId") or None,
                        name=span.get("name", "span"),
                        start_ns=int(span.get("startTimeUnixNano", 0)),
                        end_ns=int(span.get("endTimeUnixNano", 0)),
                        attrs=attrs,
                        status_code=status.get("code"),
                        status_message=status.get("message", ""),
                    )
                )
    return out


def parse_otlp_protobuf(body: bytes) -> list[dict]:
    """Parse an OTLP protobuf ExportTraceServiceRequest into Veekshana span dicts."""
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    req = ExportTraceServiceRequest()
    req.ParseFromString(body)
    out: list[dict] = []
    for rs in req.resource_spans:
        for ss in rs.scope_spans:
            for span in ss.spans:
                attrs = {a.key: _pb_any_value(a.value) for a in span.attributes}
                out.append(
                    map_otel_span(
                        trace_id=span.trace_id.hex(),
                        span_id=span.span_id.hex(),
                        parent_span_id=span.parent_span_id.hex() if span.parent_span_id else None,
                        name=span.name,
                        start_ns=span.start_time_unix_nano,
                        end_ns=span.end_time_unix_nano,
                        attrs=attrs,
                        status_code=int(span.status.code) if span.HasField("status") else None,
                        status_message=span.status.message if span.HasField("status") else "",
                    )
                )
    return out
