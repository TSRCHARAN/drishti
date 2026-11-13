"use client";

import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, fmtCost, fmtInt, fmtMs, fmtTime, Score, Span, TraceDetail } from "@/lib/api";

function ScoreChip({ score }: { score: Score }) {
  const color = score.value >= 0.7 ? "var(--series-llm)" : score.value < 0.5 ? "var(--error)" : "var(--series-tool)";
  return (
    <span className="badge" title={score.comment ?? ""}>
      <span className="swatch" style={{ background: color }} />
      {score.name} {score.value.toFixed(2)} · {score.source === "human" ? "human" : score.model ?? "judge"}
    </span>
  );
}

interface Row {
  span: Span;
  depth: number;
}

/** Depth-first ordering of the span tree (children sorted by start time). */
function buildRows(spans: Span[]): Row[] {
  const byParent = new Map<string | null, Span[]>();
  const ids = new Set(spans.map((s) => s.span_id));
  for (const s of spans) {
    // Treat spans whose parent we never received as roots, so nothing is lost.
    const parent = s.parent_span_id && ids.has(s.parent_span_id) ? s.parent_span_id : null;
    if (!byParent.has(parent)) byParent.set(parent, []);
    byParent.get(parent)!.push(s);
  }
  for (const group of byParent.values()) group.sort((a, b) => a.start_time - b.start_time);

  const rows: Row[] = [];
  const visit = (parent: string | null, depth: number) => {
    for (const s of byParent.get(parent) ?? []) {
      rows.push({ span: s, depth });
      visit(s.span_id, depth + 1);
    }
  };
  visit(null, 0);
  return rows;
}

export default function TracePage() {
  const { traceId } = useParams<{ traceId: string }>();
  const [trace, setTrace] = useState<TraceDetail | null>(null);
  const [scores, setScores] = useState<Score[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [note, setNote] = useState("");

  useEffect(() => {
    api.trace(traceId).then(setTrace).catch((e) => setError(String(e)));
    api.traceScores(traceId).then(setScores).catch(() => {});
  }, [traceId]);

  const annotate = (value: number) => {
    api
      .postScore({ trace_id: traceId, name: "human_review", value, source: "human", comment: note || undefined })
      .then(() => api.traceScores(traceId).then(setScores))
      .catch((e) => setError(String(e)));
    setNote("");
  };

  const rows = useMemo(() => (trace ? buildRows(trace.spans) : []), [trace]);

  if (error) return <div className="empty">Could not load trace: {error}</div>;
  if (!trace) return <div className="empty">Loading…</div>;

  const t0 = Math.min(...trace.spans.map((s) => s.start_time));
  const t1 = Math.max(...trace.spans.map((s) => s.end_time ?? s.start_time));
  const total = Math.max(t1 - t0, 1);
  const root = rows[0]?.span;
  const selected = trace.spans.find((s) => s.span_id === selectedId) ?? null;
  const totalCost = trace.spans.reduce((acc, s) => acc + (s.cost_usd ?? 0), 0);

  return (
    <>
      <div className="page-title">
        {root?.name ?? "Trace"}{" "}
        <span className="faint mono" style={{ fontSize: 12 }}>{trace.trace_id}</span>
      </div>
      <div className="muted" style={{ marginBottom: 4 }}>
        {root && fmtTime(root.start_time)} · {fmtMs(total)} · {trace.spans.length} spans ·{" "}
        {fmtCost(totalCost)}
        {root?.session_id && <> · session <code>{root.session_id}</code></>}
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
        {scores.map((s) => <ScoreChip key={s.score_id} score={s} />)}
        <input
          className="btn"
          style={{ width: 200 }}
          placeholder="annotation note (optional)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <button className="btn" title="Mark this run as good" onClick={() => annotate(1)}>👍 good</button>
        <button className="btn" title="Mark this run as bad" onClick={() => annotate(0)}>👎 bad</button>
      </div>

      <div className="card wf">
        <div className="wf-legend">
          <span className="badge"><span className="swatch llm" /> LLM</span>
          <span className="badge"><span className="swatch tool" /> Tool</span>
          <span className="badge"><span className="swatch span" /> Span</span>
        </div>

        {rows.map(({ span, depth }) => {
          const left = ((span.start_time - t0) / total) * 100;
          const width = span.end_time
            ? Math.max(((span.end_time - span.start_time) / total) * 100, 0.5)
            : 0.5;
          return (
            <div
              key={span.span_id}
              className={`wf-row${selectedId === span.span_id ? " selected" : ""}`}
              onClick={() => setSelectedId(span.span_id)}
            >
              <div className="wf-name">
                <span className="wf-indent" style={{ width: depth * 16 }} />
                <span className={`swatch ${span.error ? "" : span.span_type}`}
                  style={span.error ? { background: "var(--error)" } : undefined} />
                <span className="nm" title={span.name}>{span.name}</span>
              </div>
              <div className="wf-track">
                <div
                  className={`wf-bar ${span.error ? "error" : span.span_type}`}
                  style={{ left: `${left}%`, width: `${width}%` }}
                />
              </div>
              <div className="wf-dur">
                {fmtMs(span.duration_ms)}
                {span.cost_usd != null && <span className="faint"> · {fmtCost(span.cost_usd)}</span>}
              </div>
            </div>
          );
        })}
      </div>

      {selected && (
        <div className="card">
          <h2>
            {selected.name}{" "}
            <span className="badge" style={{ marginLeft: 6 }}>
              <span className={`swatch ${selected.span_type}`} /> {selected.span_type}
            </span>
            {selected.error && <span className="badge error" style={{ marginLeft: 6 }}>⚠ error</span>}
          </h2>

          <div className="kv">
            <div className="k">Duration</div><div>{fmtMs(selected.duration_ms)}</div>
            {selected.model && (<><div className="k">Model</div><div className="mono">{selected.model}</div></>)}
            {selected.input_tokens != null && (
              <><div className="k">Tokens</div>
                <div>{fmtInt(selected.input_tokens)} in · {fmtInt(selected.output_tokens)} out</div></>
            )}
            {selected.cost_usd != null && (<><div className="k">Cost</div><div>{fmtCost(selected.cost_usd)}</div></>)}
            {selected.error && (<><div className="k">Error</div><div style={{ color: "var(--error)" }}>{selected.error}</div></>)}
          </div>

          <div className="detail-grid" style={{ marginTop: 14 }}>
            <div>
              <div className="muted">Input</div>
              <pre className="json">{JSON.stringify(selected.input, null, 2) ?? "null"}</pre>
            </div>
            <div>
              <div className="muted">Output</div>
              <pre className="json">{JSON.stringify(selected.output, null, 2) ?? "null"}</pre>
            </div>
          </div>
        </div>
      )}
      {!selected && <div className="faint" style={{ marginTop: 12 }}>Click a span to inspect its input/output.</div>}
    </>
  );
}
