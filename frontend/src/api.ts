export interface User { username: string; role: string; domains: string[]; csrf: string }
export interface Factor { key: string; label: string; baseline: string; current: string; contribution: string; contribution_rate: string | null }
export interface Breakdown { method: string; unit: string; baseline: string; current: string; delta: string; change_rate: string | null; residual: string; factors: Factor[] }
export interface Scope { baseline: [string,string]; current: [string,string]; filters: Record<string,string>; group_by: string }
export interface DrillCell { dimension: string; value: string; baseline: string; current: string; delta: string; contribution_rate: string|null }
export interface Analysis { id?: string; scenario_id: string; title: string; metric: string; data_kind: string; dataset_version: string; algorithm_version: string; breakdown: Breakdown; margin_breakdown?: Breakdown; evidence_status: string; limitations: string[]; scope?: Scope; parameters?: Record<string,string>; drilldown?: DrillCell[] }
export interface Dataset { id: string; scenario: string; name: string; digest: string; row_count: number; start: string; end: string; dimensions: Record<string,string[]> }
export interface Run { id: string; session_id: string; question: string; mode: string; status: string; stage: string; sequence: number; attempts: number; error: string|null; created_at: string }
export interface History { id: string; title: string; scenario: string; created_at: string }
export interface Simulation { prediction: string; improvement: string; kind: string; assumptions: string; interval: null }
let csrf = '';
export class ApiError extends Error { status:number; constructor(message:string,status:number) { super(message);this.status=status; } }
export function setCsrf(value: string) { csrf = value; }
export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (response.status === 204) return undefined as T;
  const result = await response.json();
  if (!response.ok) throw new ApiError(typeof result.message==='string'?result.message:'请求失败，请检查输入或稍后重试',response.status);
  return result as T;
}
