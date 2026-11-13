# Contributing to Veekshana

Thanks for your interest! Veekshana is early and moving fast — that makes contributions both easier (lots of greenfield) and riskier (APIs still change). **Open an issue before starting anything bigger than a small fix** so we can save you wasted work.

## Dev setup

```bash
git clone https://github.com/TSRCHARAN/veekshana && cd veekshana

# Server + SDK (editable)
pip install -e server -e sdk-python
veekshana-server                       # API on :8787, SQLite file veekshana.db

# Web UI
cd web && npm install && npm run dev # UI on :3000

# Seed demo data (no API keys needed)
python examples/toy_agent.py
veekshana-eval --mock
```

Or run everything with `docker compose up`.

## Layout

| Path | What lives there |
|---|---|
| `sdk-python/` | `@observe`, context propagation, batching exporter, Anthropic/OpenAI auto-instrumentation |
| `server/` | FastAPI ingest + query API, OTLP decoding, `veekshana-eval` CLI, SQLAlchemy models |
| `web/` | Next.js UI — plain CSS design tokens in `app/globals.css`, **no Tailwind** |
| `examples/` | Runnable demo agents (keyless) |
| `docs/` | [The Complete Guide](docs/GUIDE.md) — read this first; it explains the internals |

## Ground rules

- **Never block or crash the host app.** The SDK must degrade silently: server down → warning, queue full → drop. Any SDK change is judged against this first.
- **Compatible at the bottom, opinionated at the top.** Ingestion follows OpenTelemetry/GenAI semantic conventions; don't invent wire formats. Product opinions (evals, cost, UI) live above the wire.
- **Unknown model → cost `None`**, never a guessed number. Pricing table updates (with a source link) are very welcome PRs.
- Python: type-hinted, no new runtime deps without discussion. Web: plain CSS tokens, no CSS frameworks.
- Keep PRs focused — one change per PR.

## Good first contributions

- Pricing table entries for more providers/models (`sdk-python/veekshana/cost.py`)
- OTLP attribute aliases from other instrumentation libraries (`server/veekshana_server/otlp.py`)
- Streaming call capture (Anthropic/OpenAI `.stream()`) — tracked on the roadmap
- Test coverage — the project predates its test suite; pytest scaffolding is welcome

## License

By contributing, you agree your contributions are licensed under [Apache 2.0](LICENSE).
