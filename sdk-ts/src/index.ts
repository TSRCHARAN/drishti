/**
 * Veekshana TypeScript/Node SDK (v0).
 *
 * - observe(fn) wraps a function as a span; nested observed calls become
 *   children; the outermost call starts a trace.
 * - instrumentOpenAI(client) / instrumentAnthropic(client) patch a client
 *   INSTANCE so every chat/messages call (streamed or not) becomes an llm span
 *   with model, tokens, cost, and latency.
 * - A batching background queue ships spans to the Veekshana server and never
 *   blocks or crashes the host app.
 */

import { AsyncLocalStorage } from "node:async_hooks";
import { randomBytes } from "node:crypto";

// ---------- span model ----------

export interface Span {
  span_id: string;
  trace_id: string;
  parent_span_id: string | null;
  name: string;
  span_type: string;
  session_id: string | null;
  start_time: number;
  end_time: number | null;
  input: unknown;
  output: unknown;
  error: string | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  metadata: Record<string, unknown>;
}

const MAX_VALUE_CHARS = 20_000;
const QUEUE_MAX = 10_000;
const FLUSH_INTERVAL_MS = 2_000;

// ---------- pricing (USD per 1M tokens, same table as the Python SDK) ----------

const PRICING: Record<string, [number, number]> = {
  "claude-fable-5-2": [8.0, 40.0],
  "claude-fable-5-1": [10.0, 50.0],
  "claude-fable-5": [10.0, 50.0],
  "claude-opus-5-5": [4.0, 20.0],
  "claude-opus-5": [5.0, 25.0],
  "claude-opus-4-8": [5.0, 25.0],
  "claude-opus-4-7": [5.0, 25.0],
  "claude-opus-4-6": [5.0, 25.0],
  "claude-sonnet-5-5": [2.0, 10.0],
  "claude-sonnet-5": [2.0, 10.0],
  "claude-sonnet-4-6": [3.0, 15.0],
  "claude-sonnet-4-5": [3.0, 15.0],
  "claude-haiku-5-5": [0.1, 0.5],
  "claude-haiku-4-5": [1.0, 5.0],
  "claude-opus-4-1": [15.0, 75.0],
  "gpt-5": [10.0, 30.0],
  "gpt-5-mini": [2.0, 8.0],
  "gpt-4o": [2.5, 10.0],
  "gpt-4o-mini": [0.15, 0.6],
};

const PRICING_KEYS = Object.keys(PRICING).sort((a, b) => b.length - a.length);

export function computeCost(
  model: string | null | undefined,
  inputTokens: number | null | undefined,
  outputTokens: number | null | undefined,
): number | null {
  if (!model) return null;
  const key = PRICING[model] ? model : PRICING_KEYS.find((k) => model.includes(k));
  if (!key) return null;
  const [inRate, outRate] = PRICING[key];
  const cost = ((inputTokens ?? 0) * inRate + (outputTokens ?? 0) * outRate) / 1_000_000;
  return Math.round(cost * 1e8) / 1e8;
}

// ---------- config + exporter ----------

const config = {
  host: process.env.VEEKSHANA_HOST ?? "http://localhost:8787",
  apiKey: process.env.VEEKSHANA_API_KEY ?? "dev-key",
};

let queue: Span[] = [];
let timer: NodeJS.Timeout | null = null;
let sessionId: string | null = null;

export function init(opts: { host?: string; apiKey?: string } = {}): void {
  if (opts.host) config.host = opts.host;
  if (opts.apiKey) config.apiKey = opts.apiKey;
  if (!timer) {
    timer = setInterval(() => void flush(), FLUSH_INTERVAL_MS);
    timer.unref?.();
    process.once("beforeExit", () => void flush());
  }
}

export function setSession(id: string | null): void {
  sessionId = id;
}

export async function flush(): Promise<void> {
  if (queue.length === 0) return;
  const batch = queue;
  queue = [];
  try {
    await fetch(config.host.replace(/\/+$/, "") + "/api/v1/ingest", {
      method: "POST",
      headers: { "content-type": "application/json", "x-api-key": config.apiKey },
      body: JSON.stringify({ spans: batch }),
    });
  } catch {
    /* telemetry must never break the host app */
  }
}

function safeValue(value: unknown): unknown {
  if (value == null) return value;
  try {
    const text = JSON.stringify(value);
    if (text && text.length > MAX_VALUE_CHARS) {
      return text.slice(0, MAX_VALUE_CHARS) + "…[truncated]";
    }
    return value;
  } catch {
    return String(value).slice(0, MAX_VALUE_CHARS);
  }
}

// ---------- context + span lifecycle ----------

const storage = new AsyncLocalStorage<Span[]>();

function newId(): string {
  return randomBytes(16).toString("hex");
}

export function currentSpan(): Span | undefined {
  const stack = storage.getStore();
  return stack?.[stack.length - 1];
}

function startSpan(name: string, spanType: string, input: unknown): Span {
  const parent = currentSpan();
  return {
    span_id: newId(),
    trace_id: parent?.trace_id ?? newId(),
    parent_span_id: parent?.span_id ?? null,
    name,
    span_type: spanType,
    session_id: sessionId,
    start_time: Date.now(),
    end_time: null,
    input: safeValue(input),
    output: null,
    error: null,
    model: null,
    input_tokens: null,
    output_tokens: null,
    cost_usd: null,
    metadata: {},
  };
}

function finishSpan(span: Span, output: unknown, error: string | null): void {
  span.end_time = Date.now();
  span.output = safeValue(output);
  span.error = error;
  if (queue.length < QUEUE_MAX) queue.push(span);
}

export function updateCurrentSpan(fields: Record<string, unknown>): void {
  const span = currentSpan();
  if (!span) return;
  for (const [key, value] of Object.entries(fields)) {
    if (key in span) (span as unknown as Record<string, unknown>)[key] = value;
    else span.metadata[key] = value;
  }
}

// ---------- observe ----------

export interface ObserveOptions {
  name?: string;
  spanType?: string;
  captureInput?: boolean;
  captureOutput?: boolean;
}

export function observe<T extends (...args: never[]) => unknown>(fn: T, opts: ObserveOptions = {}): T {
  const name = opts.name ?? fn.name ?? "anonymous";
  const wrapped = function (this: unknown, ...args: unknown[]): unknown {
    const span = startSpan(name, opts.spanType ?? "span", opts.captureInput === false ? null : args);
    const stack = [...(storage.getStore() ?? []), span];
    return storage.run(stack, () => {
      try {
        const result = fn.apply(this, args as never[]);
        if (result instanceof Promise) {
          return result.then(
            (value) => {
              finishSpan(span, opts.captureOutput === false ? null : value, null);
              return value;
            },
            (err) => {
              finishSpan(span, null, String(err));
              throw err;
            },
          );
        }
        finishSpan(span, opts.captureOutput === false ? null : result, null);
        return result;
      } catch (err) {
        finishSpan(span, null, String(err));
        throw err;
      }
    });
  };
  return wrapped as unknown as T;
}

// ---------- streaming accumulation ----------

interface StreamStateData {
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  stop_reason: string | null;
  parts: string[];
}

function newStreamState(): StreamStateData {
  return { model: null, input_tokens: null, output_tokens: null, stop_reason: null, parts: [] };
}

/* eslint-disable @typescript-eslint/no-explicit-any */

function feedChatChunk(state: StreamStateData, chunk: any): void {
  if (chunk?.model) state.model = chunk.model;
  const usage = chunk?.usage;
  if (usage) {
    state.input_tokens = usage.prompt_tokens ?? state.input_tokens;
    state.output_tokens = usage.completion_tokens ?? state.output_tokens;
  }
  for (const choice of chunk?.choices ?? []) {
    const text = choice?.delta?.content;
    if (text) state.parts.push(text);
    if (choice?.finish_reason) state.stop_reason = choice.finish_reason;
  }
}

function feedAnthropicEvent(state: StreamStateData, event: any): void {
  switch (event?.type) {
    case "message_start": {
      const message = event.message;
      if (message?.model) state.model = message.model;
      const usage = message?.usage;
      if (usage) {
        state.input_tokens = usage.input_tokens ?? state.input_tokens;
        state.output_tokens = usage.output_tokens ?? state.output_tokens;
      }
      break;
    }
    case "content_block_delta": {
      const text = event.delta?.text;
      if (text) state.parts.push(text);
      break;
    }
    case "message_delta": {
      const out = event.usage?.output_tokens;
      if (out != null) state.output_tokens = out;
      if (event.delta?.stop_reason) state.stop_reason = event.delta.stop_reason;
      break;
    }
  }
}

function wrapStream(inner: any, span: Span, feed: (s: StreamStateData, e: any) => void): any {
  const state = newStreamState();
  let done = false;
  const finish = (error: string | null) => {
    if (done) return;
    done = true;
    span.model = state.model;
    span.input_tokens = state.input_tokens;
    span.output_tokens = state.output_tokens;
    span.cost_usd = computeCost(state.model, state.input_tokens, state.output_tokens);
    finishSpan(
      span,
      error ? null : { content: state.parts.join(""), stop_reason: state.stop_reason, streamed: true },
      error,
    );
  };
  async function* generate() {
    try {
      for await (const event of inner) {
        try {
          feed(state, event);
        } catch {
          /* accumulator errors never reach the consumer */
        }
        yield event;
      }
      finish(null);
    } catch (err) {
      finish(String(err));
      throw err;
    }
  }
  const iterator = generate();
  return new Proxy(inner, {
    get(target, prop, receiver) {
      if (prop === Symbol.asyncIterator) return () => iterator;
      return Reflect.get(target, prop, receiver);
    },
  });
}

// ---------- client instrumentation (per instance) ----------

/** Patch an OpenAI client instance; returns the same client. Streamed and
 *  plain chat.completions calls become llm spans. Works for every
 *  OpenAI-compatible provider used via baseURL (Groq, Ollama, OpenRouter, …). */
export function instrumentOpenAI<T>(client: T): T {
  const completions = (client as any)?.chat?.completions;
  if (!completions?.create || completions.__veekshana) return client;
  const original = completions.create.bind(completions);
  completions.create = (body: any, ...rest: any[]) => {
    const span = startSpan("openai.chat.completions.create", "llm", {
      model: body?.model,
      messages: body?.messages,
    });
    let result: any;
    try {
      result = original(body, ...rest);
    } catch (err) {
      finishSpan(span, null, String(err));
      throw err;
    }
    return Promise.resolve(result).then(
      (response: any) => {
        if (body?.stream) return wrapStream(response, span, feedChatChunk);
        span.model = response?.model ?? null;
        span.input_tokens = response?.usage?.prompt_tokens ?? null;
        span.output_tokens = response?.usage?.completion_tokens ?? null;
        span.cost_usd = computeCost(span.model, span.input_tokens, span.output_tokens);
        finishSpan(
          span,
          {
            content: response?.choices?.[0]?.message?.content ?? null,
            stop_reason: response?.choices?.[0]?.finish_reason ?? null,
          },
          null,
        );
        return response;
      },
      (err: any) => {
        finishSpan(span, null, String(err));
        throw err;
      },
    );
  };
  completions.__veekshana = true;
  return client;
}

/** Patch an Anthropic client instance; returns the same client. Streamed
 *  (stream: true) and plain messages.create calls become llm spans. */
export function instrumentAnthropic<T>(client: T): T {
  const messages = (client as any)?.messages;
  if (!messages?.create || messages.__veekshana) return client;
  const original = messages.create.bind(messages);
  messages.create = (body: any, ...rest: any[]) => {
    const span = startSpan("anthropic.messages.create", "llm", {
      model: body?.model,
      system: body?.system,
      messages: body?.messages,
    });
    let result: any;
    try {
      result = original(body, ...rest);
    } catch (err) {
      finishSpan(span, null, String(err));
      throw err;
    }
    return Promise.resolve(result).then(
      (response: any) => {
        if (body?.stream) return wrapStream(response, span, feedAnthropicEvent);
        span.model = response?.model ?? null;
        span.input_tokens = response?.usage?.input_tokens ?? null;
        span.output_tokens = response?.usage?.output_tokens ?? null;
        span.cost_usd = computeCost(span.model, span.input_tokens, span.output_tokens);
        const content = Array.isArray(response?.content)
          ? response.content
              .filter((b: any) => b?.type === "text")
              .map((b: any) => b.text)
              .join("")
          : null;
        finishSpan(span, { content, stop_reason: response?.stop_reason ?? null }, null);
        return response;
      },
      (err: any) => {
        finishSpan(span, null, String(err));
        throw err;
      },
    );
  };
  messages.__veekshana = true;
  return client;
}
