import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { api, type Analysis } from './api';
import { ReportBody } from './ReportBody';

interface Preview { revision:string; markdown:string; events_checked_at:string }

export function ReportPreview({analysis}:{analysis:Analysis}) {
  const [open,setOpen]=useState(false),[preview,setPreview]=useState<Preview|null>(null);
  const [loading,setLoading]=useState(false),[error,setError]=useState(''),[refresh,setRefresh]=useState(0);
  const id=analysis.id, revision=analysis.report_revision;
  useEffect(()=>{
    setPreview(null);setError('');
    if(!open||!id||!revision){setLoading(false);return}
    let current=true;setLoading(true);
    api<Preview>(`/sessions/${id}/report-preview?revision=${encodeURIComponent(revision)}`)
      .then(value=>{if(current&&value.revision===revision)setPreview(value)})
      .catch(e=>{if(current)setError((e as Error).message)})
      .finally(()=>{if(current)setLoading(false)});
    return()=>{current=false};
  },[open,id,revision,refresh]);
  return <details className="composer" onToggle={event=>setOpen(event.currentTarget.open)}><summary>预览报告草稿</summary>
    <p>预览显示已保存的报告草稿。事件在预览时重新匹配；报告仍是草稿，不代表已发布或验证。</p>
    {!revision&&<p>报告内容已变化，请重新打开会话后预览。</p>}
    <button type="button" disabled={loading||!revision} onClick={()=>setRefresh(value=>value+1)}>重新匹配并刷新预览</button>
    {loading&&<p>正在生成预览…</p>}{error&&<p role="alert" className="error">{error}</p>}
    {preview&&!loading&&preview.revision===revision&&<><p>事件匹配时间：{new Date(preview.events_checked_at).toLocaleString('zh-CN')}</p>
      <button type="button" onClick={()=>window.print()}>打印报告</button>
      <ReportBody className="report-preview" markdown={preview.markdown}/>
      {createPortal(<ReportBody className="report-print" markdown={preview.markdown}/>, document.body)}</>}
  </details>;
}
