import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { ReportBody } from './ReportBody';
import { ReportComments } from './ReportComments';

interface Published {id:string; title:string; scenario:string; digest:string; published_at:string}
export function PublishedReports() {
  const [reports,setReports]=useState<Published[]>([]), [error,setError]=useState('');
  const [selected,setSelected]=useState<{id:string;markdown:string}|null>(null);
  const request=useRef(0);
  const [open,setOpen]=useState(false), [version,setVersion]=useState(0);
  useEffect(()=>{const refresh=()=>{request.current++;setSelected(null);setVersion(v=>v+1)};
    window.addEventListener('report-publications-changed',refresh);
    return()=>window.removeEventListener('report-publications-changed',refresh)},[]);
  useEffect(()=>{if(!open)return;let live=true;setError('');
    api<Published[]>('/published-reports').then(value=>{if(live)setReports(value)}).catch(e=>{if(live)setError(e.message)});
    return()=>{live=false};},[open,version]);
  async function view(id:string) {const seq=++request.current;setSelected(null);setError('');try {const result=await api<{id:string;markdown:string}>(`/published-reports/${id}`);if(seq===request.current)setSelected(result)}catch(e){if(seq===request.current)setError((e as Error).message)}}
  return <details className="composer" onToggle={e=>setOpen(e.currentTarget.open)}><summary>已发布报告</summary>
    <p>仅显示当前业务线有权访问的冻结报告。发布是共享，不代表结论已验证；撤回阻止后续访问，不能收回已下载的文件。</p>
    <button onClick={()=>{request.current++;setSelected(null);setVersion(v=>v+1)}}>刷新列表</button>
    {error&&<p className="error" role="alert">{error}</p>}
    {reports.map(report=><article key={report.id}><strong>{report.title}</strong><p>{report.scenario} · {new Date(report.published_at).toLocaleString('zh-CN')} · 摘要 {report.digest.slice(0,16)}…</p><button onClick={()=>view(report.id)}>查看报告</button><div className="report-exports"><a href={`/api/v1/published-reports/${report.id}/export/md`}>Markdown</a><a href={`/api/v1/published-reports/${report.id}/export/pdf`}>PDF</a><a href={`/api/v1/published-reports/${report.id}/export/xlsx`}>Excel</a></div></article>)}
    {selected&&<><ReportBody markdown={selected.markdown} className="report-body"/><ReportComments key={selected.id} reportId={selected.id}/></>}
  </details>;
}
