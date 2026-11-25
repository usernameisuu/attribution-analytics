export interface User { username: string; role: string; domains: string[]; csrf: string }
export interface Factor { key: string; label: string; baseline: string; current: string; contribution: string; contribution_rate: string | null }
export interface Breakdown { method: string; unit: string; baseline: string; current: string; delta: string; change_rate: string | null; residual: string; factors: Factor[] }
export interface Scope { baseline: [string,string]; current: [string,string]; filters: Record<string,string>; group_by: string }
export interface DrillCell { dimension: string; value: string; baseline: string; current: string; delta: string; contribution_rate: string|null; children?:DrillCell[] }
export interface TrendPoint { date:string; period:'baseline'|'current'; value:string; spend:string; visits:string }
export interface DescriptiveEvidence { kind:'descriptive_comparison'; dimension:string; metric:string; unit:string; delta_unit:string; groups:{value:string;baseline:string|null;current:string|null;delta:string|null}[]; total_groups:number; truncated:boolean; note:string }
export interface Hypothesis { id:string; question:string; required_data:string[]; status:'pending'; status_label:string; source:'rule'; factor_key:string; factor_label:string; factor_contribution:string; contribution_unit:string; evidence:DescriptiveEvidence[]; limitations:string[] }
export interface ActionItem { action:string; factor_key:string; factor_label:string; factor_contribution:string; owner_role:string; estimated_days:number|null; estimated_benefit:string|null; benefit_basis:string; source:'analyst' }
export interface StatisticalCheck { method:string; metric:string; factor_key?:string|null; unit:string; delta_unit?:string; sample_unit:string; current_n:number; baseline_n:number; current_mean:number|null; baseline_mean:number|null; mean_difference:number|null; current_mean_decimal?:string|null; baseline_mean_decimal?:string|null; mean_difference_decimal?:string|null; confidence_level:number; status:'computed'|'not_applicable'; reason:string|null; statistic:number|null; degrees_of_freedom:number|null; p_value:number|null; p_value_underflow?:boolean; interval:{low:number;high:number}|null; limitations:string[]; calculated_at?:string; method_version?:string; scipy_version?:string; dataset_version?:string; data_digest?:string; scope?:Scope }
export interface Analysis { id?: string; scenario_id: string; title: string; metric: string; data_kind: string; dataset_version: string; algorithm_version: string; metric_definition_version?:string; analysis_revision?:string; report_revision?:string; action_revision?:string; simulation_revision?:string; statistics_revision?:string; note_revision?:string; report_note?:{text:string;author:string;updated_at:string}|null; drilldown_revision?:string|null; breakdown: Breakdown; margin_breakdown?: Breakdown; evidence_status: string; limitations: string[]; scope?: Scope; parameters?: Record<string,string>; drilldown?: DrillCell[]; trends?:TrendPoint[]; hypotheses?:Hypothesis[]; simulation_scenarios?:SimulationScenario[]; action_items?:ActionItem[]; statistical_checks?:StatisticalCheck[] }
export type MetricExpression = {ref:string}|{const:string}|{op:'add'|'sub'|'mul'|'div';args:[MetricExpression,MetricExpression]};
export interface MetricCatalog { version:string; scenario:string; scenario_metric:{metric:string;margin_metric?:string;name:string; description:string; limitations:string[]}; definitions:Record<string,{unit:Record<string,number>;expression:MetricExpression|null}> }
export interface Dataset { id: string; scenario: string; name: string; digest: string; row_count: number; start: string; end: string; dimensions: Record<string,string[]> }
export interface Comparison { metric:string; unit:string; threshold:string; threshold_unit:string; method:string; baseline:string|null; current:string|null; delta:string|null; change:string|null; status:'normal'|'anomaly'|'not_applicable'; reason:string|null; dataset_version:string; data_digest:string; scope:Scope }
export interface Run { id: string; session_id: string; question: string; mode: string; status: string; stage: string; sequence: number; attempts: number; error: string|null; created_at: string; has_previous_drafts?:boolean }
export interface History { id: string; title: string; scenario: string; created_at: string }
export interface SimulationScenario { name:string; changes:Record<string,string>; parameters:Record<string,string>; prediction:string; improvement:string; kind:string; assumptions:string; interval:null; margin?:{prediction:string|null;improvement:string|null;reason:string|null} }
let csrf = '';
export class ApiError extends Error { status:number; constructor(message:string,status:number) { super(message);this.status=status; } }
export function setCsrf(value: string) { csrf = value; }
export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (response.status === 204) return undefined as T;
  if (!response.ok) {
    let message = '请求失败，请检查输入或稍后重试';
    try {
      const result: unknown = await response.json();
      if (result && typeof result === 'object' && 'message' in result && typeof result.message === 'string') message = result.message;
    } catch {
      // Servers and proxies can return plain text or HTML for errors.
    }
    throw new ApiError(message, response.status);
  }
  return await response.json() as T;
}
