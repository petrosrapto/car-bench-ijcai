import { useEffect, useState } from "react";
import { api } from "../api/client";

export default function Submission() {
  const [variants, setVariants] = useState<any[]>([]);
  const [subs, setSubs] = useState<any[]>([]);
  const [variantRef, setVariantRef] = useState("");
  const [preview, setPreview] = useState<Record<string, string> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const refresh = () => api.submissions().then(setSubs).catch((e) => setErr(String(e)));
  useEffect(() => {
    api.variants().then((vs) => { setVariants(vs); if (vs[0]) setVariantRef(vs[0].variant_ref); }).catch((e) => setErr(String(e)));
    refresh();
  }, []);

  async function generate() {
    setErr(null); setMsg(null);
    try {
      const r = await api.generateSubmission(variantRef);
      setMsg(`Generated ${r.submission_id}`);
      await refresh();
      setPreview(await api.submission(r.submission_id));
    } catch (e) { setErr(String(e)); }
  }

  return (
    <div>
      <h2>Submission</h2>
      <p className="page-sub">Generate the digest-pinned <code>scenario.toml</code> + reproducibility bundle + validation table from a promoted checkpoint.</p>
      {err && <div className="panel error">{err}</div>}
      {msg && <div className="panel"><span className="pill good">{msg}</span></div>}

      <div className="controls">
        <span className="muted">Checkpoint:</span>
        <select value={variantRef} onChange={(e) => setVariantRef(e.target.value)} style={{ minWidth: 360 }}>
          {variants.map((v) => <option key={v.variant_ref} value={v.variant_ref}>{v.variant_ref} ({v.lifecycle})</option>)}
        </select>
        <button onClick={generate}>Generate submission bundle</button>
      </div>

      <div className="panel">
        <h3>Existing submissions</h3>
        <table>
          <thead><tr><th>Submission</th><th>Variant</th><th>Image</th></tr></thead>
          <tbody>
            {subs.length === 0 && <tr><td colSpan={3} className="muted">none yet</td></tr>}
            {subs.map((s) => (
              <tr key={s.submission_id}>
                <td><a onClick={() => api.submission(s.submission_id).then(setPreview)} style={{ cursor: "pointer" }}>{s.submission_id}</a></td>
                <td><code>{s.variant_ref}</code></td>
                <td><code>{s.image}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {preview && (
        <>
          {["scenario.toml", "reproducibility.md", "validation_table.md"].map((f) => preview[f] && (
            <div className="panel" key={f}>
              <h3>{f}</h3>
              <pre className="code">{preview[f]}</pre>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
