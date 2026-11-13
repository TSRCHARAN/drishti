"use client";

import { useEffect, useState } from "react";
import { api, fmtCost, fmtInt, Stats } from "@/lib/api";

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.stats().then(setStats).catch((e) => setError(String(e)));
  };
  useEffect(load, []);

  if (error) {
    return (
      <div className="empty">
        Could not reach the Drishti server.
        <div className="faint" style={{ marginTop: 6 }}>{error} — is it running on port 8787?</div>
      </div>
    );
  }
  if (!stats) return <div className="empty">Loading…</div>;

  const maxCost = Math.max(...stats.by_model.map((m) => m.cost_usd), 0);

  return (
    <>
      <div className="page-title">Dashboard</div>

      <div className="tiles">
        <div className="tile">
          <div className="label">Traces</div>
          <div className="value">{fmtInt(stats.traces)}</div>
        </div>
        <div className="tile">
          <div className="label">Spans</div>
          <div className="value">{fmtInt(stats.spans)}</div>
        </div>
        <div className="tile">
          <div className="label">Tokens</div>
          <div className="value">{fmtInt(stats.input_tokens + stats.output_tokens)}</div>
          <div className="sub">{fmtInt(stats.input_tokens)} in · {fmtInt(stats.output_tokens)} out</div>
        </div>
        <div className="tile">
          <div className="label">Total cost</div>
          <div className="value">{stats.cost_usd === 0 ? "$0" : `$${stats.cost_usd.toFixed(4)}`}</div>
        </div>
      </div>

      <div className="card">
        <h2>Cost by model</h2>
        {stats.by_model.length === 0 && <div className="empty">No LLM calls recorded yet.</div>}
        {stats.by_model
          .slice()
          .sort((a, b) => b.cost_usd - a.cost_usd)
          .map((m) => (
            <div className="bar-row" key={m.model}>
              <div className="name mono" title={m.model}>{m.model}</div>
              <div className="bar-track">
                <div
                  className="bar-fill"
                  style={{ width: `${maxCost > 0 ? (m.cost_usd / maxCost) * 100 : 0}%` }}
                />
              </div>
              <div className="val">{fmtCost(m.cost_usd)}</div>
            </div>
          ))}
      </div>

      <div className="card">
        <h2>Model usage</h2>
        <table>
          <thead>
            <tr>
              <th>Model</th>
              <th className="num">Calls</th>
              <th className="num">Input tokens</th>
              <th className="num">Output tokens</th>
              <th className="num">Cost</th>
            </tr>
          </thead>
          <tbody>
            {stats.by_model.map((m) => (
              <tr key={m.model}>
                <td className="mono">{m.model}</td>
                <td className="num">{fmtInt(m.calls)}</td>
                <td className="num">{fmtInt(m.input_tokens)}</td>
                <td className="num">{fmtInt(m.output_tokens)}</td>
                <td className="num">{fmtCost(m.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 16 }}>
        <button className="btn" onClick={load}>Refresh</button>
      </div>
    </>
  );
}
