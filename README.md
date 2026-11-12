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

### 3. See your traces

```bash
curl http://localhost:8787/api/v1/traces -H "x-api-key: dev-key"
```

(Web UI coming in Phase 2.)

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
- [ ] OpenAI auto-instrumentation
- [ ] Web UI: trace waterfall, sessions, cost dashboard
- [ ] Evals v1: LLM-as-judge on sampled traces, manual annotation
- [ ] TypeScript SDK
- [ ] OpenTelemetry export compatibility

## License

[Apache 2.0](LICENSE)
