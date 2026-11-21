export interface User { username: string; role: string; domains: string[]; csrf: string }
export interface Factor { key: string; label: string; baseline: string; current: string; contribution: string; contribution_rate: string | null }
export interface Breakdown { method: string; unit: string; baseline: string; current: string; delta: string; change_rate: string | null; residual: string; factors: Factor[] }
export interface Analysis { id?: string; scenario_id: string; title: string; metric: string; data_kind: string; dataset_version: string; algorithm_version: string; breakdown: Breakdown; margin_breakdown?: Breakdown; evidence_status: string; limitations: string[] }
export interface History { id: string; title: string; scenario: string; created_at: string }
export interface Simulation { prediction: string; improvement: string; kind: string; assumptions: string; interval: null }
let csrf = '';
export function setCsrf(value: string) { csrf = value; }
export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (response.status === 204) return undefined as T;
  const result = await response.json();
  if (!response.ok) throw new Error(result.message || '请求失败，请稍后重试');
  return result as T;
}
