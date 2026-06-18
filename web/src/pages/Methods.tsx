import { useEffect, useState } from "react";
import { api, type HeadlineRow } from "../api/client";
import { CIBar, SplitPicker } from "../components/CIBar";

export default function Methods() {
  const [split, setSplit] = useState("overall");
  const [headline, setHeadline] = useState<HeadlineRow[]>([]);
  const [subscores, setSubscores] = useState<Record<string, number>>({});
  const [policies, setPolicies] = useState<{ policy_id: string; source: string; n: number }[]>([]);
  const [tools, setTools] = useState<{ detail: string; source: string; n: number }[]>([]);
  const [econ, setEcon] = useState<Record<string, number>>({});
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setErr(null);
    Promise.all([
      api.headline(split),
      api.subscores(split),
      api.policies(split),
      api.tools(split),
      api.economics(split),
    ])
      .then(([h, s, p, t, e]) => {
        setHeadline(h);
        setSubscores(s);
        setPolicies(p);
        setTools(t);
        setEcon(e);
      })
      .catch((e) => setErr(String(e)));
  }, [split]);

  const subscoreRows = Object.entries(subscores).filter(([k]) => k.startsWith("r_"));

  return (
    <div>
      <h2>Methods</h2>
      <p className="page-sub">Per-method headline Pass^3 (bootstrap 95% CI) and failure breakdowns. Latest run per variant.</p>
      <div className="controls">
        <span className="muted">Split:</span>
        <SplitPicker value={split} onChange={setSplit} />
      </div>
      {err && <div className="panel error">{err} — is the store built? Run <code>cbtrack refresh</code>.</div>}

      <div className="panel">
        <h3>Pass^3 (consistency) — higher is better</h3>
        {headline.length === 0 && <div className="muted">No runs yet.</div>}
        {headline.map((h) => (
          <CIBar key={h.variant_ref ?? h.run_id} label={h.variant_ref ?? h.run_id} ci={h.pass_power_3} />
        ))}
      </div>

      <div className="panel">
        <h3>Pass@3 (capability) vs Pass^3 — the consistency gap</h3>
        {headline.map((h) => (
          <CIBar key={"at-" + (h.variant_ref ?? h.run_id)} label={h.variant_ref ?? h.run_id} ci={h.pass_at_3} />
        ))}
      </div>

      <div className="grid2">
        <div className="panel">
          <h3>Subscore failures (among failed trials)</h3>
          <table>
            <thead><tr><th>Subscore</th><th className="num">Failures</th></tr></thead>
            <tbody>
              {subscoreRows.map(([k, v]) => (
                <tr key={k}><td><code>{k}</code></td><td className="num">{v ?? 0}</td></tr>
              ))}
              <tr><td className="muted">failed trials total</td><td className="num">{subscores.failed_trials ?? 0}</td></tr>
            </tbody>
          </table>
        </div>

        <div className="panel">
          <h3>Economics (per task-trial mean)</h3>
          <table>
            <tbody>
              <tr><td>Cost (USD)</td><td className="num">{fmt(econ.mean_cost, 4)}</td></tr>
              <tr><td>Input tokens</td><td className="num">{fmt(econ.mean_input_tokens, 0)}</td></tr>
              <tr><td>Output tokens</td><td className="num">{fmt(econ.mean_output_tokens, 0)}</td></tr>
              <tr><td>Total tokens</td><td className="num">{fmt(econ.mean_total_tokens, 0)}</td></tr>
              <tr><td>A2A task time (s)</td><td className="num">{fmt(econ.mean_a2a_task_time_s, 2)}</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid2">
        <div className="panel">
          <h3>Policy violations (AUT / LLM)</h3>
          <table>
            <thead><tr><th>Policy</th><th>Source</th><th className="num">Count</th></tr></thead>
            <tbody>
              {policies.length === 0 && <tr><td colSpan={3} className="muted">none</td></tr>}
              {policies.map((p, i) => (
                <tr key={i}><td><code>{p.policy_id}</code></td><td>{p.source}</td><td className="num">{p.n}</td></tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <h3>Tool errors</h3>
          <table>
            <thead><tr><th>Detail</th><th>Kind</th><th className="num">Count</th></tr></thead>
            <tbody>
              {tools.length === 0 && <tr><td colSpan={3} className="muted">none</td></tr>}
              {tools.map((t, i) => (
                <tr key={i}><td>{t.detail}</td><td>{t.source}</td><td className="num">{t.n}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function fmt(x: number | null | undefined, d: number) {
  return x == null ? "—" : Number(x).toFixed(d);
}
