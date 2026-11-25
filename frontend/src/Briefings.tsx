import {useEffect,useState} from 'react';
import {api} from './api';

type Subscription={scenario:string;frequency:'daily'|'weekly';active:boolean;next_due:string};
type Issue={id:string;period_start:string;period_end:string;truncated:boolean;unavailable_count:number;reports:{id:string;title:string;digest:string}[]};
export function Briefings({domains}:{domains:string[]}) {
  const [scenario,setScenario]=useState(domains[0]??''),[frequency,setFrequency]=useState<'daily'|'weekly'>('weekly');
  const [subs,setSubs]=useState<Subscription[]>([]),[issues,setIssues]=useState<Issue[]>([]),[error,setError]=useState('');
  const [open,setOpen]=useState(false),[version,setVersion]=useState(0),[busy,setBusy]=useState(false);
  useEffect(()=>{if(!open||!scenario)return;let live=true;setError('');
    Promise.all([api<Subscription[]>('/brief-subscriptions'),api<Issue[]>(`/brief-issues/${scenario}`)])
      .then(([a,b])=>{if(live){setSubs(a);setIssues(b)}}).catch(e=>{if(live){setIssues([]);setError(e.message)}});
    return()=>{live=false}},[open,scenario,version]);
  const sub=subs.find(item=>item.scenario===scenario);
  useEffect(()=>{if(sub?.active)setFrequency(sub.frequency)},[scenario,sub?.active,sub?.frequency]);
  async function change(cancel:boolean) {setBusy(true);setError('');try {
    await api(`/brief-subscriptions/${scenario}`,cancel?'DELETE':'PUT',cancel?undefined:{frequency});setVersion(v=>v+1);
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  if(!domains.length)return null;
  return <details className="composer" onToggle={e=>setOpen(e.currentTarget.open)}><summary>周期简报订阅</summary>
    <p>站内简报按 UTC 间隔汇总新增的已发布报告，不会重新计算指标。worker 停机期间的内容在恢复后合并为一期；撤回报告不会继续展示。</p>
    <label>业务线<select value={scenario} onChange={e=>{setScenario(e.target.value);setIssues([])}}>{domains.map(d=><option key={d} value={d}>{d}</option>)}</select></label>
    <label>频率<select value={frequency} onChange={e=>setFrequency(e.target.value as 'daily'|'weekly')}><option value="daily">每日</option><option value="weekly">每周</option></select></label>
    <button disabled={busy} onClick={()=>change(false)}>保存订阅</button>{sub?.active&&<button disabled={busy} onClick={()=>change(true)}>取消订阅</button>}
    <button onClick={()=>setVersion(v=>v+1)}>刷新简报</button>
    {sub?.active&&<p>当前{sub.frequency==='daily'?'每日':'每周'}，下次不早于 {new Date(sub.next_due).toLocaleString('zh-CN')}；worker 运行时生成。</p>}
    {error&&<p className="error" role="alert">{error}</p>}
    {issues.map(issue=><article key={issue.id}><strong>{new Date(issue.period_start).toLocaleString('zh-CN')} 至 {new Date(issue.period_end).toLocaleString('zh-CN')}</strong><p>{issue.reports.length===0?'此期没有当前可查看的报告。':`当前可查看 ${issue.reports.length} 份报告。`}{issue.unavailable_count>0&&` ${issue.unavailable_count} 份已撤回或不再可用。`}{issue.truncated&&' 此期超过 100 份，仅收录最近 100 份。'}</p>{issue.reports.map(report=><p key={report.id}>{report.title} · 摘要 {report.digest.slice(0,16)}… <a href={`/api/v1/published-reports/${report.id}/export/md`}>下载 Markdown</a></p>)}</article>)}
  </details>;
}
