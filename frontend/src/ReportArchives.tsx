import { useEffect, useState } from 'react';
import { api, type Analysis } from './api';

interface Archive { id:string; title:string; created_at:string; digest:string; status:'archived_draft'; published:boolean }

export function ReportArchives({analysis,editable}:{analysis:Analysis;editable:boolean}) {
  const [open,setOpen]=useState(false), [reports,setReports]=useState<Archive[]>([]);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[version,setVersion]=useState(0);
  const id=analysis.id;
  useEffect(()=>{
    if(!open||!id)return;
    let live=true;setError('');
    api<Archive[]>(`/sessions/${id}/reports`).then(value=>{if(live)setReports(value)}).catch(e=>{if(live)setError(e.message)});
    return()=>{live=false};
  },[id,open,version]);
  async function archive() {
    if(!id||!analysis.report_revision)return;
    setBusy(true);setError('');
    try {await api(`/sessions/${id}/reports`,'POST',{revision:analysis.report_revision});setVersion(value=>value+1)}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function publication(report:Archive) {
    setBusy(true);setError('');
    try {await api(`/reports/${report.id}/publication`,report.published?'DELETE':'PUT');setVersion(value=>value+1);window.dispatchEvent(new Event('report-publications-changed'))}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  return <details className="composer" onToggle={event=>setOpen(event.currentTarget.open)}><summary>报告归档</summary>
    <p>归档保存不可变快照；发布后拥有该业务线权限的用户可查看和导出，撤回阻止后续访问。</p>
    {editable&&<button type="button" disabled={busy||!analysis.report_revision} onClick={archive}>{busy?'保存中…':'归档当前草稿'}</button>}
    {editable&&!analysis.report_revision&&<p>会话内容已变化，请重新打开会话后归档。</p>}
    {error&&<p className="error" role="alert">{error}</p>}
    {!error&&reports.length===0&&<p>暂无归档草稿。</p>}
    {reports.map(report=><article key={report.id}><strong>{report.title}</strong><p>归档时间：{new Date(report.created_at).toLocaleString('zh-CN')} · 摘要 {report.digest.slice(0,16)}… · {report.published?'已发布':'未发布'}</p>{editable&&<button disabled={busy} onClick={()=>publication(report)}>{report.published?'撤回发布':'发布到业务线'}</button>}<div className="report-exports"><a href={`/api/v1/reports/${report.id}/export/md`}>Markdown</a><a href={`/api/v1/reports/${report.id}/export/pdf`}>PDF</a><a href={`/api/v1/reports/${report.id}/export/xlsx`}>Excel</a></div></article>)}
  </details>;
}
