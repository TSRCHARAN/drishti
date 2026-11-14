# Veekshana — The Complete Guide

*What it is, how to use it, how it works inside, and how ready it is to deploy.*

---

## 1. What is Veekshana?

Veekshana (వీక్షణ / वीक्षण, "observation" in Telugu and Sanskrit) is an **open-source observability platform for AI agents**. You instrument your agent once; Veekshana then answers three questions the whole time it runs:

1. **What is my agent doing?** Every run becomes a *trace*: a tree of spans covering the agent function, each LLM call, and each tool call, with inputs, outputs, timing, and errors.
2. **What does it cost?** Tokens and dollars per call, per model, per trace, computed from a maintained rate card.
3. **Is it actually working?** An LLM judge scores every trace on *task completion*, and humans can annotate runs 👍/👎 — so regressions show up as numbers, not vibes.

It is Apache-2.0 licensed, self-hosted in one command, and compatible with the OpenTelemetry ecosystem.

## 2. What we built (component map)

```
your agent code
  │  @veekshana.observe()          ──┐
  │  Anthropic SDK (auto-patched)  │  sdk-python/  (pip install veekshana)
  │  OpenAI SDK   (auto-patched)   │  batching exporter, never blocks your app
  └────────────── spans ──────────┘
                    │ HTTP (batch JSON)                 ┌ any OTel SDK / OpenLLMetry /
                    ▼                                   │ Phoenix / Langfuse-v3 spans
            POST /api/v1/ingest        POST /v1/traces ◄┘ (OTLP protobuf or JSON)
                    │                         │
                    ▼                         ▼
              ┌───────────────────────────────────┐
              │  server/  FastAPI + SQLAlchemy    │
              │  SQLite (default) / Postgres      │
              │  spans + scores tables            │
              │  veekshana-eval (LLM-as-judge CLI)  │
              └───────────────┬───────────────────┘
                              │ REST (x-api-key)
                              ▼
              ┌───────────────────────────────────┐
              │  web/  Next.js UI                 │
              │  dashboard · traces · waterfall   │
              │  score chips · 👍/👎 annotation    │
              └───────────────────────────────────┘
```

| Piece | What it does |
|---|---|
| `sdk-python/` | `@observe` decorator and `span()` context manager build the trace tree via `contextvars`; a daemon-thread exporter batches spans and ships them without ever blocking or crashing the host app. Auto-instrumentation patches `anthropic` and `openai` SDKs at `init()` — zero code changes. |
| `server/` | FastAPI app. Ingests spans (native batch JSON or OTLP), stores them (SQLite by default, Postgres via `VEEKSHANA_DATABASE_URL`), serves query endpoints, and hosts the evals CLI. |
| `web/` | Next.js UI: dashboard (stat tiles, evals summary, cost-by-model), traces list, and the span waterfall with click-to-inspect input/output. Light/dark themed. |
| `docker/` + `docker-compose.yml` | One-command self-host. |
| `examples/` | `toy_agent.py` (Veekshana SDK, mock LLM — works with no API keys) and `otel_agent.py` (plain OpenTelemetry SDK — proves OTLP compatibility). |

## 3. How to use it

### 3.1 Run the stack

```bash
git clone https://github.com/TSRCHARAN/veekshana && cd veekshana
docker compose up
```

- API: `http://localhost:8787` (health: `/health`)
- UI: `http://localhost:3000`
- Default API key: `dev-key` → change with `VEEKSHANA_API_KEY=... docker compose up --build`

Without Docker: `pip install -e sdk-python -e server`, run `veekshana-server`, and `npm install && npm run dev` inside `web/`.

### 3.2 Instrument your agent

```bash
pip install -e sdk-python        # (PyPI package planned post-launch)
```

```python
import veekshana

veekshana.init(host="http://localhost:8787", api_key="dev-key")

@veekshana.observe()                      # the agent: outermost call = one trace
def my_agent(question: str) -> str:
    plan = client.messages.create(...)  # Anthropic/OpenAI calls auto-captured
    data = fetch_data(question)         # tools: decorate with span_type="tool"
    return answer

@veekshana.observe(span_type="tool")
def fetch_data(q: str) -> dict: ...
```

Useful extras:

```python
veekshana.set_session("user-123-chat-42")   # group traces into a session
with veekshana.span("retrieval", input=q) as s:   # manual span
    s.output = docs
veekshana.update_current_span(model="...", input_tokens=..., output_tokens=...)
veekshana.flush()                            # before exit in short scripts
```

### 3.3 Already on OpenTelemetry? Skip the SDK

Any OTel-based GenAI instrumentation (OpenLLMetry/Traceloop, Arize Phoenix, Langfuse v3, hand-rolled spans) can export straight to Veekshana:

```bash
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:8787/v1/traces
export OTEL_EXPORTER_OTLP_TRACES_HEADERS=x-api-key=dev-key
```

Veekshana accepts OTLP/HTTP in protobuf and JSON and maps the GenAI semantic conventions (model, token usage, prompt/completion, tool name, session, error status) onto its span model.

### 3.4 Read the UI

- **Dashboard** — traces/spans/tokens/total-cost tiles, evals summary (average score, low-score count), cost-by-model bars, model usage table.
- **Traces** — one row per agent run: duration, spans, LLM calls, tokens, cost, ok/error badge. Click through.
- **Trace page** — the waterfall: spans on a timeline, indented by nesting, colored by type (blue LLM, orange tool, gray span, red error). Click a span for duration, model, tokens, cost, and full input/output JSON. Score chips sit above; 👍/👎 buttons post human annotations.

### 3.5 Evals

```bash
docker compose exec server veekshana-eval          # real judge; runs on your own key
docker compose exec server veekshana-eval --mock   # deterministic mock, no key
```

The judge reads each unscored trace (task, final output, steps, errors) and writes a `task_completion` score (0–1) with one-line reasoning. Human annotations from the UI land in the same scores table as `human_review`.

**The judge works with any provider, on your own key.** Provider is inferred from the environment, or set explicitly:

| Env | Effect |
|---|---|
| `ANTHROPIC_API_KEY` | Claude judge — default model `claude-opus-5-5` (`claude-haiku-5-5` is the budget option) |
| `OPENAI_API_KEY` | OpenAI-compatible judge — default model `gpt-4o` |
| `OPENAI_API_KEY` + `OPENAI_BASE_URL` | Judge on Groq, Together, Ollama, OpenRouter, DeepSeek, Mistral, … |
| `VEEKSHANA_EVAL_PROVIDER` | Force `anthropic`, `openai`, or `mock` |
| `VEEKSHANA_EVAL_MODEL` | Override the judge model for either provider |
| *(nothing)* or `--mock` | Deterministic mock judge — zero keys, pipeline still works |

**Describe what your agent is supposed to do**, and the judge scores against *your* definition of correct, not a generic one:

```bash
veekshana-eval --criteria "The agent drafts polite payment reminders in formal English, never threatens the customer, and always includes the exact overdue amount."
# or: VEEKSHANA_EVAL_CRITERIA="..." veekshana-eval
```

Keys: **you** bring the LLM for judging, from whichever provider you already use — Veekshana itself needs no AI vendor account. (Note: this key powers the *judge*; the `x-api-key`/`dev-key` used by the SDK and UI is Veekshana's own auth secret, unrelated to AI vendors.)

### 3.5b Projects (multi-team groundwork)

Every span and score belongs to a **project**. With no configuration, everything lands in the `default` project. To split teams or apps on one server, issue one API key per project:

```bash
VEEKSHANA_API_KEYS="agent-team-key:collections,bot-team-key:support" veekshana-server
```

Each key sees only its own project's traces, stats, and scores — reads and writes are fully isolated, and databases created by older versions are migrated automatically. (This is the open-source groundwork the hosted multi-tenant cloud builds on.)

### 3.6 API reference (all under `x-api-key`)

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/ingest` | Native span batch ingest (what the SDK calls) |
| `POST /v1/traces` | OTLP/HTTP ingest (protobuf or JSON) |
| `GET /api/v1/traces?limit=&session_id=` | Trace summaries, newest first |
| `GET /api/v1/traces/{id}` | Full span tree for one trace |
| `GET /api/v1/stats` | Totals + per-model usage and cost |
| `POST /api/v1/scores` | Write a score/annotation |
| `GET /api/v1/traces/{id}/scores` | Scores for one trace |
| `GET /api/v1/scores/summary` | Eval averages by score name |

## 4. How it works inside

**Trace building.** `@observe` wraps a function call in a `Span`. A `contextvars` stack tracks the active span, so nested observed calls (and the patched SDK calls inside them) attach as children automatically — the outermost call mints the `trace_id`. This propagates correctly through `async` code.

**Never hurt the host app.** Spans go into a bounded in-process queue; a daemon thread flushes batches of 50 every 2 s over HTTP. Queue full → spans drop with a warning. Server down → warnings, not exceptions. `atexit` flushes on clean exit.

**Auto-instrumentation.** `veekshana.init()` monkey-patches `Messages.create` (Anthropic) and `chat.completions.create` / `responses.create` (OpenAI), sync and async. Each call becomes an `llm` span carrying model, token usage, and computed cost. Because Groq, Together, Ollama, OpenRouter, DeepSeek, Mistral and others are used through the OpenAI SDK with a custom `base_url`, the one OpenAI wrapper covers them all.

**Cost.** A pricing table (USD per 1M tokens, Anthropic rate card of 2026-11 + common OpenAI ids) with longest-match lookup, so dated ids like `claude-sonnet-5-5-20260101` and prefixed ids like `us.anthropic.claude-...` still resolve. Unknown model → cost `None`, never a wrong number.

**Storage.** One wide `spans` table (SQLAlchemy), JSON columns for input/output/metadata, indexed by `trace_id` and time. Trace summaries are computed at query time — fine into the tens of thousands of spans on SQLite; the Postgres/ClickHouse path exists for scale.

**OTLP ingest.** `/v1/traces` decodes the OTLP wire format (both encodings), flattens attributes, and maps GenAI semantic conventions — including older alias names (`prompt_tokens` vs `input_tokens`) and the Traceloop dialect — onto the same spans table. Span type inference: GenAI model/system attrs → `llm`; tool attrs → `tool`; else `span`.

**Evals.** `veekshana-eval` selects traces with no `task_completion` score, renders each as a compact digest (task, output, step list with errors), asks the judge for strict JSON `{score, reasoning}`, and writes to the `scores` table. No credentials → a deterministic mock judge keeps the pipeline testable.

## 5. Deployment readiness — honest status

**Ready today** (self-host, demos, design partners, internal teams):
- One-command Docker stack, verified end-to-end (build → up → ingest → evals → UI)
- SQLite persisted on a volume; Postgres path wired (`VEEKSHANA_DATABASE_URL` + compose block)
- API-key auth on every endpoint; CORS configurable
- Idempotent ingest (duplicate spans ignored), bounded queues, defensive SDK

**Not yet** (needed before a public multi-tenant SaaS):
- **Auth is a single shared key** — no users, orgs, or per-project keys
- **No streaming capture** — `.stream()` calls on both SDKs pass through untraced
- **UI embeds the API key** (`NEXT_PUBLIC_*`) — fine self-hosted, needs a proxy for hosted cloud
- **No TLS** — put a reverse proxy (Caddy/nginx) in front for anything non-local
- **No automated test suite / CI yet** — verification has been end-to-end manual
- **No retention/sampling controls** — every span is kept forever
- Third-party host pricing (Groq/Together/...) not in the cost table — tokens tracked, cost `None`

**Bottom line:** deploy it today for yourself, your team, or a design partner on a VPS behind a reverse proxy. Don't open it to the public internet as a shared service until auth and TLS are in place.

## 6. Roadmap

Streaming capture → PyPI/npm publish + CI → gateway/proxy mode (zero-code) → TypeScript SDK → multi-user auth → hosted cloud (the open-core business layer) → agent-behavior analytics (tool-failure rates, retry loops, cost per completed task).

---

*Built by a 2-person team as the observability layer for AI agents — dogfooded on our own agents.*
