import { useState } from 'react';
import { api, type Analysis } from './api';

export function ReportNote({analysis, editable, onResult}:{analysis:Analysis; editable:boolean; onResult:(result:Analysis, revision:string)=>void}) {
  const [text,setText]=useState(analysis.report_note?.text??'');
  const [busy,setBusy]=useState(false), [error,setError]=useState('');
  async function save() {
    const revision=analysis.report_revision;
    if(!analysis.id||!revision)return;
    setBusy(true);setError('');
    try {
      const result=await api<Analysis>(`/sessions/${analysis.id}/report-note`,'PUT',{revision,text});
      onResult(result,revision);
    } catch(e) {setError((e as Error).message)} finally {setBusy(false)}
  }
  return <section className="hypotheses"><h3>分析师说明</h3>
    <p>说明将随当前草稿导出和归档；内容由分析师填写，不代表已发布或验证。</p>
    {analysis.report_note&&<p>已保存：{analysis.report_note.author} · {new Date(analysis.report_note.updated_at).toLocaleString('zh-CN')}</p>}
    {editable?<form onSubmit={event=>{event.preventDefault();void save()}}>
      <label>报告说明<textarea maxLength={2000} value={text} onChange={event=>setText(event.target.value)} /></label>
      <button disabled={busy||!analysis.report_revision}>{busy?'保存中…':'保存说明'}</button>
      {!analysis.report_revision&&<p>报告内容已变化，请重新打开会话后保存。</p>}
    </form>:<p>{analysis.report_note?.text||'暂无说明。'}</p>}
    {error&&<p className="error" role="alert">{error}</p>}
  </section>;
}
