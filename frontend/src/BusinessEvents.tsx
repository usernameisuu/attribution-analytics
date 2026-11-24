import { useEffect, useState } from 'react';
import { api, type Analysis } from './api';

interface EventItem { id:string; title:string; start:string; end:string; source:string; scope:Record<string,string[]>; evidence_status:string }
interface EventResult { events:EventItem[]; notice:string }

export function BusinessEvents({ analysis, canCreate }:{ analysis:Analysis; canCreate:boolean }) {
  const [result,setResult]=useState<EventResult|null>(null), [error,setError]=useState(''), [busy,setBusy]=useState(false);
  const [version,setVersion]=useState(0);
  const [editing,setEditing]=useState<EventItem|null>(null);
  const sessionId=analysis.id!, filters=JSON.stringify(analysis.scope?.filters ?? {});
  const current=analysis.scope?.current.join(':') ?? '';
  useEffect(()=>{
    if(!analysis.scope)return;
    let live=true; setResult(null);setError('');
    api<EventResult>(`/sessions/${sessionId}/business-events`).then(data=>{if(live)setResult(data)}).catch(e=>{if(live)setError(e.message)});
    return()=>{live=false};
  },[sessionId,filters,current,version]);
  if(!analysis.scope)return null;
  async function save(e:React.FormEvent<HTMLFormElement>, target:EventItem|null) {
    e.preventDefault();setBusy(true);setError('');
    const form=e.currentTarget, data=new FormData(form);
    const region=String(data.get('region')||'').trim(), channel=String(data.get('channel')||'').trim();
    const scope:Record<string,string[]>={...(target?.scope??{})};if(!target&&region)scope.region=[region];if(!target&&channel)scope.channel=[channel];
    try {
      await api(target?`/business-events/${target.id}`:'/business-events',target?'PUT':'POST',{scenario:analysis.scenario_id,title:String(data.get('title')||''),
        start:String(data.get('start')||''),end:String(data.get('end')||''),source:String(data.get('source')||''),scope});
      form.reset();setEditing(null);setVersion(value=>value+1);
    } catch(err) {setError((err as Error).message)} finally {setBusy(false)}
  }
  return <section className="composer"><h3>关联业务事件</h3>
    <p className="muted">匹配现期窗口前后 3 日的个人事件，事件关联不代表因果。</p>
    {result&&<><p>{result.notice}</p>{result.events.length===0?<p>当前范围暂无匹配事件。</p>:
      result.events.map(item=><article key={item.id}><strong>{item.title}</strong><p>{item.start} 至 {item.end} · {item.source}</p><small>{item.evidence_status}</small>
        {canCreate&&<div><button type="button" onClick={()=>setEditing(item)}>编辑</button><button type="button" disabled={busy} onClick={async()=>{
          if(!window.confirm(`确定删除事件「${item.title}」？`))return;
          setBusy(true);setError('');try{await api(`/business-events/${item.id}`,'DELETE');if(editing?.id===item.id)setEditing(null);setVersion(value=>value+1)}catch(err){setError((err as Error).message)}finally{setBusy(false)}
        }}>删除</button></div>}</article>)}</>}
    {canCreate&&<details><summary>添加业务事件</summary><form onSubmit={e=>save(e,null)}>
      <label>事件名称<input name="title" maxLength={160} required /></label>
      <label>开始日期<input name="start" type="date" required /></label><label>结束日期<input name="end" type="date" required /></label>
      <label>来源<input name="source" maxLength={200} required placeholder="例如：活动日历" /></label>
      <label>区域（可选）<input name="region" maxLength={60} placeholder="留空表示全部区域" /></label>
      <label>渠道（可选）<input name="channel" maxLength={60} placeholder="留空表示全部渠道" /></label>
      <button className="primary" disabled={busy}>{busy?'保存中…':'保存事件'}</button>
    </form></details>}
    {editing&&<form key={editing.id} onSubmit={e=>save(e,editing)}><h4>编辑事件</h4>
      <label>事件名称<input name="title" maxLength={160} required defaultValue={editing.title}/></label>
      <label>开始日期<input name="start" type="date" required defaultValue={editing.start}/></label>
      <label>结束日期<input name="end" type="date" required defaultValue={editing.end}/></label>
      <label>来源<input name="source" maxLength={200} required defaultValue={editing.source}/></label>
      <small>原有适用范围保持不变。</small><button className="primary" disabled={busy}>保存修改</button>
      <button type="button" onClick={()=>setEditing(null)}>取消</button></form>}
    {error&&<p className="error" role="alert">{error}</p>}
  </section>;
}
