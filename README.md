# Drishti 🔭

**Open-source observability for AI agents.** Traces, costs, and evals for LLM applications — self-hosted, in under 2 minutes.

> दृष्टि (*Drishti*) — Sanskrit for "sight". See what your agents are actually doing.

> ⚠️ **Early development.** Drishti is a working codename; APIs will change. Star the repo to follow along.

## Why Drishti?

You shipped an AI agent. Now you need to know:

- **What is it doing?** Full traces of every agent run — LLM calls, tool calls, inputs, outputs — as a waterfall you can click into.
- **What does it cost?** Token usage and spend per model, per feature, per session. Latency p50/p95.
- **Is it actually working?** LLM-as-judge evals on sampled traces. Flag bad runs, catch regressions when you change prompts or models.

## Quickstart

### 1. Run the server

```bash
cd server
pip install -e .
drishti-server
```

The server starts at `http://localhost:8787` with a local SQLite database. (Postgres: set `DRISHTI_DATABASE_URL`.)

### 2. Instrument your agent

```bash
pip install -e sdk-python
```

```python
import drishti

drishti.init(host="http://localhost:8787", api_key="dev-key")

@drishti.observe()
def my_agent(question: str) -> str:
    # your agent logic — LLM calls inside are captured automatically
    ...
```

Anthropic and OpenAI clients are auto-instrumented: every `messages.create` / `chat.completions.create` call is captured with model, tokens, cost, and latency — zero code changes.

**Already instrumented with OpenTelemetry** (OpenLLMetry, Phoenix, Langfuse v3, or your own GenAI spans)? Skip the SDK entirely — point your exporter at Drishti:

```bash
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:8787/v1/traces
export OTEL_EXPORTER_OTLP_TRACES_HEADERS=x-api-key=dev-key
```

Drishti accepts OTLP/HTTP (protobuf and JSON) and maps GenAI semantic conventions — model, token usage, prompts/completions, tool calls, sessions, errors — automatically. See [examples/otel_agent.py](examples/otel_agent.py).

### 3. See your traces

```bash
cd web
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000): dashboard with cost/token stats, traces list, and a click-through trace waterfall with per-span latency, cost, and input/output inspection.

Prefer raw JSON? `curl http://localhost:8787/api/v1/traces -H "x-api-key: dev-key"`

## Repository layout

```
sdk-python/   Python SDK — @observe decorator, auto-instrumentation, batched exporter
server/       FastAPI ingestion + query API (SQLite / Postgres)
web/          Next.js trace viewer + cost dashboard (Phase 2)
docker/       docker-compose for one-command self-hosting
docs/         Quickstart and SDK reference
examples/     Instrumented demo agents
```

## Roadmap

- [x] Python SDK: `@observe`, trace context, batched ingestion
- [x] Anthropic auto-instrumentation + cost tracking
- [x] FastAPI ingestion + query API
- [x] Web UI: trace waterfall, traces list, cost dashboard
- [x] Evals v1: LLM-as-judge on sampled traces, manual annotation
- [x] OTLP ingest (OpenTelemetry GenAI semantic conventions, protobuf + JSON)
- [ ] OpenAI auto-instrumentation
- [ ] TypeScript SDK
- [ ] Gateway/proxy mode (zero-code logging)

## License

[Apache 2.0](LICENSE)
