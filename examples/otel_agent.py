"""Agent instrumented with plain OpenTelemetry (no Drishti SDK), exporting
straight to Drishti's OTLP endpoint — proves any OTel GenAI instrumentation
(OpenLLMetry, Phoenix, Langfuse v3, ...) can point at Drishti unchanged.

Setup:
    pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
    python otel_agent.py
"""

from __future__ import annotations

import random
import time

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

provider = TracerProvider(resource=Resource.create({"service.name": "otel-demo-agent"}))
provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(
            endpoint="http://localhost:8787/v1/traces",
            headers={"x-api-key": "dev-key"},
        )
    )
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("otel-demo")


def llm_call(prompt: str) -> str:
    """A mock LLM call carrying GenAI semantic-convention attributes."""
    with tracer.start_as_current_span("chat claude-haiku-5-5") as span:
        time.sleep(random.uniform(0.05, 0.2))
        input_tokens = len(prompt.split()) * 2
        output_tokens = random.randint(30, 200)
        span.set_attribute("gen_ai.system", "anthropic")
        span.set_attribute("gen_ai.request.model", "claude-haiku-5-5")
        span.set_attribute("gen_ai.response.model", "claude-haiku-5-5")
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
        span.set_attribute("gen_ai.prompt", prompt[:500])
        answer = f"[otel mock answer to: {prompt[:40]}...]"
        span.set_attribute("gen_ai.completion", answer)
        return answer


def lookup_weather(city: str) -> str:
    with tracer.start_as_current_span("lookup_weather") as span:
        span.set_attribute("gen_ai.tool.name", "lookup_weather")
        time.sleep(random.uniform(0.02, 0.08))
        if random.random() < 0.2:
            span.set_status(Status(StatusCode.ERROR, f"weather API timeout for {city}"))
            raise RuntimeError(f"weather API timeout for {city}")
        return f"{city}: 31°C, humid"


def run_agent(city: str) -> str:
    with tracer.start_as_current_span("travel_agent") as span:
        span.set_attribute("session.id", "otel-session-042")
        plan = llm_call(f"Plan a day trip in {city}")
        try:
            weather = lookup_weather(city)
        except RuntimeError:
            return llm_call(f"Weather API failed. Suggest indoor plans for {city}.")
        return llm_call(f"Finalize the itinerary. Weather: {weather}. Plan: {plan}")


if __name__ == "__main__":
    for city in ["Hyderabad", "Bengaluru", "Mumbai"]:
        print(f"→ otel agent: {city}")
        try:
            print(f"  {run_agent(city)[:70]}")
        except Exception as exc:
            print(f"  failed: {exc}")
    provider.shutdown()  # flush
    print("\nDone. OTel traces shipped to Drishti → /v1/traces")
