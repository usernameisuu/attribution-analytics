import type { StatisticalCheck } from './api';

export function evidenceStatus(original:string, checks?:Pick<StatisticalCheck,'status'>[]):string {
  if (!checks?.length) return original;
  const computed=checks.some(check=>check.status==='computed');
  const unavailable=checks.some(check=>check.status!=='computed');
  if (computed&&unavailable) return '数学分解已完成，已执行每日均值检验；部分检验未能计算，候选业务假设仍待验证。';
  if (computed) return '数学分解已完成，已执行每日均值检验；候选业务假设仍待验证。';
  return '数学分解已完成；每日均值检验未能计算，候选业务假设仍待验证。';
}
