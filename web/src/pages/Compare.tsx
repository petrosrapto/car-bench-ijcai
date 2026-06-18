import { useEffect, useState } from "react";
import { api } from "../api/client";
import { CIBar, SplitPicker } from "../components/CIBar";

export default function Compare() {
  const [variants, setVariants] = useState<any[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [split, setSplit] = useState("overall");
  const [data, setData] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { api.variants().then(setVariants).catch((e) => setErr(String(e))); }, []);
  useEffect(() => {
    if (selected.length < 1) { setData([]); return; }
    api.compare(selected, split).then(setData).catch((e) => setErr(String(e)));
  }, [selected, split]);

  const allTasks = Array.from(new Set(data.flatMap((d) => Object.keys(d.tasks)))).sort();

  return (
    <div>
      <h2>Compare methods</h2>
      <p className="page-sub">Side-by-side Pass^3 and per-task win/loss for the latest run of each selected variant.</p>
      {err && <div className="panel error">{err}</div>}
      <div className="controls">
        <span className="muted">Split:</span>
        <SplitPicker value={split} onChange={setSplit} />
        <span className="muted">Variants:</span>
        <select multiple value={selected} onChange={(e) => setSelected(Array.from(e.target.selectedOptions, (o) => o.value))}
          style={{ minWidth: 320, minHeight: 90 }}>
          {variants.map((v) => <option key={v.variant_ref} value={v.variant_ref}>{v.variant_ref}</option>)}
        </select>
      </div>

      {data.length > 0 && (
        <div className="panel">
          <h3>Headline Pass^3</h3>
          {data.map((d) => <CIBar key={d.variant_ref} label={d.variant_ref} ci={d.pass_power_3} />)}
        </div>
      )}

      {data.length >= 1 && allTasks.length > 0 && (
        <div className="panel">
          <h3>Per-task Pass^3 (✓ pass / ✗ fail)</h3>
          <table>
            <thead>
              <tr><th>Task</th>{data.map((d) => <th key={d.variant_ref} className="num">{shortRef(d.variant_ref)}</th>)}</tr>
            </thead>
            <tbody>
              {allTasks.map((t) => (
                <tr key={t}>
                  <td><code>{t}</code></td>
                  {data.map((d) => {
                    const v = d.tasks[t];
                    return <td key={d.variant_ref} className="num">
                      <span className={"pill " + (v == null ? "na" : v ? "good" : "bad")}>{v == null ? "—" : v ? "✓" : "✗"}</span>
                    </td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function shortRef(r: string) { return r.length > 22 ? r.slice(0, 20) + "…" : r; }
