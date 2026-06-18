import { useEffect, useState } from "react";
import { api } from "../api/client";

export default function Trends() {
  const [variants, setVariants] = useState<any[]>([]);
  const [variantId, setVariantId] = useState("");
  const [rows, setRows] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.variants().then((vs) => {
      setVariants(vs);
      const ids = Array.from(new Set(vs.map((v) => v.variant_id)));
      if (ids[0]) setVariantId(ids[0]);
    }).catch((e) => setErr(String(e)));
  }, []);
  useEffect(() => { if (variantId) api.trends(variantId).then(setRows).catch((e) => setErr(String(e))); }, [variantId]);

  const ids = Array.from(new Set(variants.map((v) => v.variant_id)));
  const max = Math.max(0.0001, ...rows.map((r) => r.pass_power_3 ?? 0));

  return (
    <div>
      <h2>Trends</h2>
      <p className="page-sub">Pass^3 across a method's run history — watch it improve as you iterate.</p>
      {err && <div className="panel error">{err}</div>}
      <div className="controls">
        <span className="muted">Method:</span>
        <select value={variantId} onChange={(e) => setVariantId(e.target.value)} style={{ minWidth: 320 }}>
          {ids.map((id) => <option key={id} value={id}>{id}</option>)}
        </select>
      </div>

      <div className="panel">
        <h3>Pass^3 over time</h3>
        {rows.length === 0 && <div className="muted">No runs.</div>}
        {rows.map((r) => (
          <div className="bar-row" key={r.run_id}>
            <div className="bar-label" title={r.run_id}>{(r.completed_at || r.run_id).slice(0, 19)} · {r.task_split}</div>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${((r.pass_power_3 ?? 0) / max) * 100}%` }} />
            </div>
            <div className="bar-val">{r.pass_power_3 == null ? "—" : (r.pass_power_3 * 100).toFixed(1) + "%"}</div>
          </div>
        ))}
      </div>

      <div className="panel">
        <h3>Run history</h3>
        <table>
          <thead><tr><th>Run</th><th>Split</th><th className="num">Pass^3</th><th className="num">Pass@3</th><th className="num">Gap</th><th className="num">Cost</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.run_id}>
                <td><code>{r.run_id}</code></td>
                <td>{r.task_split}</td>
                <td className="num">{pct(r.pass_power_3)}</td>
                <td className="num">{pct(r.pass_at_3)}</td>
                <td className="num">{r.consistency_gap_pass3 == null ? "—" : (r.consistency_gap_pass3 * 100).toFixed(1) + "%"}</td>
                <td className="num">{r.mean_cost == null ? "—" : Number(r.mean_cost).toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function pct(x: number | null) { return x == null ? "—" : (x * 100).toFixed(1) + "%"; }
