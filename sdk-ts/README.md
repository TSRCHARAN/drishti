# veekshana (TypeScript/Node SDK)

**TypeScript SDK for [Veekshana](https://github.com/TSRCHARAN/veekshana)** — open-source observability for AI agents: traces, costs, and evals.

> వీక్షణ (*Veekshana*) — "observation" in Telugu and Sanskrit.

```bash
npm install veekshana
```

```ts
import OpenAI from "openai";
import * as veekshana from "veekshana";

veekshana.init({ host: "http://localhost:8787", apiKey: "dev-key" });

const openai = veekshana.instrumentOpenAI(new OpenAI());
// every chat.completions call — streamed or not — is now an llm span
// (model, tokens, cost, latency). instrumentAnthropic(client) likewise.

const myAgent = veekshana.observe(async function myAgent(question: string) {
  const res = await openai.chat.completions.create({
    model: "gpt-4o",
    messages: [{ role: "user", content: question }],
  });
  return res.choices[0].message.content;
});

await myAgent("hello");
await veekshana.flush(); // before exit in short scripts
```

- `observe(fn, { name?, spanType? })` — wraps any function (sync or async) as a span; nested observed calls become children; the outermost call starts a trace.
- `instrumentOpenAI(client)` / `instrumentAnthropic(client)` — patch a client *instance*; covers Groq, Together, Ollama, OpenRouter and other OpenAI-compatible providers via `baseURL`.
- `setSession(id)`, `updateCurrentSpan({...})`, `flush()`, `computeCost(model, in, out)`.
- Zero runtime dependencies (Node ≥ 18, global `fetch`); the background queue batches every 2s and never blocks or crashes your app.

Run the full stack (API + UI) with one command — see the [main repository](https://github.com/TSRCHARAN/veekshana) and the [Complete Guide](https://github.com/TSRCHARAN/veekshana/blob/main/docs/GUIDE.md).

Apache 2.0.
