import { useEffect, useState } from "react";
import { api, type RunRow, type TrajIndexRow } from "../api/client";

export default function Trajectory() {
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [runId, setRunId] = useState<string>("");
  const [index, setIndex] = useState<TrajIndexRow[]>([]);
  const [sel, setSel] = useState<TrajIndexRow | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { api.runs().then((r) => { setRuns(r); if (r[0]) setRunId(r[0].run_id); }).catch((e) => setErr(String(e))); }, []);
  useEffect(() => {
    if (!runId) return;
    setSel(null); setDetail(null);
    api.trajIndex(runId).then((ix) => { setIndex(ix); if (ix[0]) setSel(ix[0]); }).catch((e) => setErr(String(e)));
  }, [runId]);
  useEffect(() => {
    if (!runId || !sel) return;
    api.trajDetail(runId, sel.split, sel.task_id, sel.trial).then(setDetail).catch((e) => setErr(String(e)));
  }, [runId, sel]);

  return (
    <div>
      <h2>Trajectory replay</h2>
      <p className="page-sub">Inspect a single past interaction turn-by-turn, with the trial verdict and a ground-truth-vs-taken actions diff.</p>
      {err && <div className="panel error">{err}</div>}
      <div className="controls">
        <span className="muted">Run:</span>
        <select value={runId} onChange={(e) => setRunId(e.target.value)} style={{ maxWidth: 460 }}>
          {runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.run_id}</option>)}
        </select>
        <span className="muted">Task/trial:</span>
        <select
          value={sel ? `${sel.split}|${sel.task_id}|${sel.trial}` : ""}
          onChange={(e) => {
            const [split, task_id, trial] = e.target.value.split("|");
            setSel(index.find((i) => i.split === split && i.task_id === task_id && i.trial === Number(trial)) || null);
          }}
          style={{ maxWidth: 360 }}
        >
          {index.map((i) => (
            <option key={`${i.split}|${i.task_id}|${i.trial}`} value={`${i.split}|${i.task_id}|${i.trial}`}>
              {i.passed ? "✓" : "✗"} {i.split}/{i.task_id} · trial {i.trial}
            </option>
          ))}
        </select>
      </div>

      {detail && (
        <>
          <div className="panel">
            <h3>
              Verdict — {detail.split}/{detail.task_id} · trial {detail.trial}{" "}
              <span className={"pill " + (detail.passed ? "good" : "bad")}>{detail.passed ? "PASS" : "FAIL"}</span>
            </h3>
            {detail.instruction && <p className="muted" style={{ marginTop: 0 }}>“{detail.instruction}”</p>}
            <div>
              {Object.entries(detail.verdict).map(([k, v]) => (
                <span key={k} className={"pill " + pill(v)} style={{ marginRight: 6 }}>{k}: {label(v)}</span>
              ))}
            </div>
            {hasErrors(detail.verdict_diagnostics) && (
              <pre className="code" style={{ marginTop: 10 }}>{JSON.stringify(detail.verdict_diagnostics, null, 2)}</pre>
            )}
          </div>

          <div className="panel">
            <h3>Ground-truth actions vs taken</h3>
            <div className="diff">
              <div className="col">
                <h4>Expected (ground truth)</h4>
                {detail.ground_truth_actions.map((a: any, i: number) => (
                  <div className="action" key={i}><b>{a.name}</b> {a.kwargs ? <code>{JSON.stringify(a.kwargs)}</code> : null}</div>
                ))}
              </div>
              <div className="col">
                <h4>Taken (agent)</h4>
                {detail.taken_actions.map((a: any, i: number) => (
                  <div className="action" key={i}><b>{a.name}</b> {a.arguments ? <code>{String(a.arguments).slice(0, 200)}</code> : null}</div>
                ))}
              </div>
            </div>
          </div>

          <div className="panel chat">
            <h3>Trajectory</h3>
            {detail.trajectory.map((m: any, i: number) => (
              <div key={i} className={"msg " + (m.role || "")}>
                <div className="role">{m.role}{m.name ? ` · ${m.name}` : ""}</div>
                {m.content ? <pre>{m.content}</pre> : null}
                {m.tool_calls && m.tool_calls.length > 0 && (
                  <pre>{m.tool_calls.map((tc: any) => `→ ${tc.function?.name}(${tc.function?.arguments ?? ""})`).join("\n")}</pre>
                )}
                {m.turn_metrics && (
                  <div className="turn-meta">
                    {m.turn_metrics.prompt_tokens ?? 0}p / {m.turn_metrics.completion_tokens ?? 0}c / {m.turn_metrics.thinking_tokens ?? 0}t tok
                    {m.evaluator_metrics?.a2a_turn_time_ms ? ` · ${Math.round(m.evaluator_metrics.a2a_turn_time_ms)}ms` : ""}
                    {m.turn_metrics.cost ? ` · $${m.turn_metrics.cost}` : ""}
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function pill(v: any) { return v == null ? "na" : v >= 1 ? "good" : "bad"; }
function label(v: any) { return v == null ? "n/a" : v >= 1 ? "pass" : "fail"; }
function hasErrors(d: any) {
  return d && Object.values(d).some((v) => Array.isArray(v) ? v.length > 0 : v != null);
}
