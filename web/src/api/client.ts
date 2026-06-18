// Tiny typed fetch wrapper. All endpoints are same-origin (/api/*), proxied to
// the FastAPI backend by Vite in dev and served alongside it in production.

export interface CI {
  mean: number | null;
  lo: number | null;
  hi: number | null;
  n: number;
}

export interface RunRow {
  run_id: string;
  variant_ref: string | null;
  variant_id: string | null;
  status: string;
  task_split: string | null;
  completed_at: string | null;
  pass_power_3: number | null;
  pass_at_3: number | null;
  tags: string[];
}

export interface HeadlineRow {
  variant_ref: string | null;
  variant_id: string | null;
  run_id: string;
  split: string;
  pass_power_3: CI;
  pass_at_3: CI;
}

export interface TrajIndexRow {
  split: string;
  task_id: string;
  trial: number;
  task_type: string | null;
  reward: number | null;
  passed: boolean;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(path, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  health: () => get<{ ok: boolean; store_built: boolean }>("/api/health"),
  runs: () => get<RunRow[]>("/api/runs"),
  run: (id: string) => get<any>(`/api/runs/${id}`),
  variants: () => get<any[]>("/api/variants"),
  headline: (split = "overall", variant_ref?: string) =>
    get<HeadlineRow[]>(
      `/api/stats/headline?split=${split}` + (variant_ref ? `&variant_ref=${encodeURIComponent(variant_ref)}` : "")
    ),
  subscores: (split = "overall", variant_ref?: string) =>
    get<Record<string, number>>(
      `/api/stats/subscores?split=${split}` + (variant_ref ? `&variant_ref=${encodeURIComponent(variant_ref)}` : "")
    ),
  policies: (split = "overall", variant_ref?: string) =>
    get<{ policy_id: string; source: string; n: number }[]>(
      `/api/stats/policies?split=${split}` + (variant_ref ? `&variant_ref=${encodeURIComponent(variant_ref)}` : "")
    ),
  tools: (split = "overall", variant_ref?: string) =>
    get<{ detail: string; source: string; n: number }[]>(
      `/api/stats/tools?split=${split}` + (variant_ref ? `&variant_ref=${encodeURIComponent(variant_ref)}` : "")
    ),
  economics: (split = "overall", variant_ref?: string) =>
    get<Record<string, number>>(
      `/api/stats/economics?split=${split}` + (variant_ref ? `&variant_ref=${encodeURIComponent(variant_ref)}` : "")
    ),
  compare: (refs: string[], split = "overall") =>
    get<any[]>(`/api/compare?variant_refs=${encodeURIComponent(refs.join(","))}&split=${split}`),
  trends: (variant_id: string) => get<any[]>(`/api/trends?variant_id=${encodeURIComponent(variant_id)}`),
  trajIndex: (runId: string) => get<TrajIndexRow[]>(`/api/trajectory/${runId}/index`),
  trajDetail: (runId: string, split: string, taskId: string, trial: number) =>
    get<any>(`/api/trajectory/${runId}/${split}/${taskId}/${trial}`),
  submissions: () => get<any[]>("/api/submissions"),
  submission: (id: string) => get<Record<string, string>>(`/api/submissions/${id}`),
  generateSubmission: (variantRef: string) =>
    post<{ submission_id: string }>(`/api/submissions/generate/${encodeURIComponent(variantRef)}`),
};
