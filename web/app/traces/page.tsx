"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, fmtCost, fmtInt, fmtMs, fmtTime, TraceSummary } from "@/lib/api";

export default function TracesPage() {
  const router = useRouter();
  const [traces, setTraces] = useState<TraceSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.traces().then(setTraces).catch((e) => setError(String(e)));
  }, []);

  if (error) return <div className="empty">Could not load traces: {error}</div>;
  if (!traces) return <div className="empty">Loading…</div>;

  return (
    <>
      <div className="page-title">Traces</div>
      <div className="card" style={{ padding: 8, overflowX: "auto" }}>
        {traces.length === 0 && (
          <div className="empty">
            No traces yet. Instrument your agent with <code>@drishti.observe()</code> and run it.
          </div>
        )}
        {traces.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Session</th>
                <th>Started</th>
                <th className="num">Duration</th>
                <th className="num">Spans</th>
                <th className="num">LLM calls</th>
                <th className="num">Tokens</th>
                <th className="num">Cost</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {traces.map((t) => (
                <tr
                  key={t.trace_id}
                  className="row-link"
                  onClick={() => router.push(`/traces/${t.trace_id}`)}
                >
                  <td>{t.name}</td>
                  <td className="mono faint">{t.session_id ?? "–"}</td>
                  <td className="muted">{fmtTime(t.start_time)}</td>
                  <td className="num">{fmtMs(t.duration_ms)}</td>
                  <td className="num">{t.span_count}</td>
                  <td className="num">{t.llm_call_count}</td>
                  <td className="num">{fmtInt(t.total_input_tokens + t.total_output_tokens)}</td>
                  <td className="num">{fmtCost(t.total_cost_usd)}</td>
                  <td>
                    {t.has_error
                      ? <span className="badge error">⚠ error</span>
                      : <span className="badge">ok</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
