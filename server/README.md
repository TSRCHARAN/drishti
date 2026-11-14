# veekshana-server

**Ingestion + query API for [Veekshana](https://github.com/TSRCHARAN/veekshana)** — open-source observability for AI agents: traces, costs, and evals.

```bash
pip install veekshana-server
veekshana-server          # API on :8787, SQLite database veekshana.db
```

- **Ingest**: native span batches at `POST /api/v1/ingest`, plus standard **OTLP/HTTP** at `POST /v1/traces` (protobuf and JSON, GenAI semantic conventions) — point any OpenTelemetry exporter at it.
- **Query**: traces, span trees, cost/token stats, eval scores — all under `x-api-key` auth, with per-project key scoping via `VEEKSHANA_API_KEYS`.
- **Evals**: `veekshana-eval` scores traces with an LLM judge on *your own key*, any provider — `ANTHROPIC_API_KEY`, or `OPENAI_API_KEY` (+ `OPENAI_BASE_URL` for Groq/Together/Ollama/OpenRouter) — against your own plain-English criteria (`--criteria`), or with a keyless deterministic mock judge (`--mock`). Install with `pip install veekshana-server[evals]`.
- **Storage**: SQLite by default, Postgres via `VEEKSHANA_DATABASE_URL` (`pip install veekshana-server[postgres]`).

The web UI and one-command Docker stack live in the [main repository](https://github.com/TSRCHARAN/veekshana); internals are documented in the [Complete Guide](https://github.com/TSRCHARAN/veekshana/blob/main/docs/GUIDE.md).

Apache 2.0.
