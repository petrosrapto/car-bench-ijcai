import type { CI } from "../api/client";

// A horizontal bar with a bootstrap-CI whisker overlaid. Values are fractions
// in [0, 1] rendered as percentages.
export function CIBar({ label, ci }: { label: string; ci: CI }) {
  const mean = ci.mean ?? 0;
  const lo = ci.lo ?? mean;
  const hi = ci.hi ?? mean;
  return (
    <div className="bar-row">
      <div className="bar-label" title={label}>{label}</div>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${mean * 100}%` }} />
        <div
          className="bar-ci"
          style={{ left: `${lo * 100}%`, width: `${Math.max(0, (hi - lo) * 100)}%` }}
        />
      </div>
      <div className="bar-val">
        {ci.mean == null ? "—" : (mean * 100).toFixed(1) + "%"}
        <span className="muted" style={{ fontSize: 10 }}> (n={ci.n})</span>
      </div>
    </div>
  );
}

export function SplitPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="overall">Overall</option>
      <option value="base">Base</option>
      <option value="hallucination">Hallucination</option>
      <option value="disambiguation">Disambiguation</option>
    </select>
  );
}
