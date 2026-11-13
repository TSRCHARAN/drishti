# veekshana

**Python SDK for [Veekshana](https://github.com/TSRCHARAN/veekshana)** — open-source observability for AI agents: traces, costs, and evals.

> వీక్షణ (*Veekshana*) — "observation" in Telugu and Sanskrit.

```bash
pip install veekshana
```

```python
import veekshana

veekshana.init(host="http://localhost:8787", api_key="dev-key")

@veekshana.observe()                 # outermost call = one trace
def my_agent(question: str) -> str:
    ...  # Anthropic / OpenAI calls inside are captured automatically

@veekshana.observe(span_type="tool")
def fetch_data(q: str) -> dict: ...
```

- **Auto-instrumentation**: patches the Anthropic and OpenAI SDKs at `init()` — model, tokens, cost, and latency per call, zero code changes. Covers Groq, Together, Ollama, OpenRouter, DeepSeek, Mistral and other OpenAI-compatible providers used via `base_url`.
- **Never hurts your app**: spans ship through a bounded, batching background exporter; a down server means warnings, not exceptions.
- **Extras**: `veekshana.set_session(...)`, `veekshana.span(...)` context manager, `veekshana.update_current_span(...)`, `veekshana.flush()`.

Run the full stack (API + UI) with one command — see the [main repository](https://github.com/TSRCHARAN/veekshana) and the [Complete Guide](https://github.com/TSRCHARAN/veekshana/blob/main/docs/GUIDE.md).

Apache 2.0.
