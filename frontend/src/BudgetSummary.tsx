import { useEffect, useState } from 'react';
import { api } from './api';

interface Budget { limit:string; spent:string; reserved:string; available:string }
export function BudgetSummary() {
  const [budget,setBudget]=useState<Budget|null>(null), [error,setError]=useState('');
  async function refresh(){try{setBudget(await api<Budget>('/admin/budget'));setError('')}catch(e){setError((e as Error).message)}}
  useEffect(()=>{refresh()},[]);
  return <section className="panel data-sources"><h2>DeepSeek 开发验收预算</h2>{budget&&<p>累计上限 ¥{budget.limit} · 已结算估算 ¥{budget.spent} · 预留 ¥{budget.reserved} · 可用 ¥{budget.available}</p>}<p className="muted">预留包含用量未知的请求，需与供应商账单核对；当前页面不能提高 25 元累计上限。</p><button onClick={refresh}>刷新账本</button>{error&&<p className="error" role="alert">{error}</p>}</section>;
}
