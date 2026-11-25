import { useEffect, useRef, useState } from 'react';
import { api, type Analysis } from './api';

interface EventItem { id:string; title:string; start:string; end:string; source:string; scope:Record<string,string[]>; revision:string; evidence_status?:string; match_basis?:string }
interface EventResult { events:EventItem[]; notice:string }
interface EventList { events:EventItem[]; truncated:boolean; next_cursor:{start:string;id:string}|null }
const scopeDimensions = [['region','区域'],['channel','渠道'],['category','品类'],['segment','客群']] as const;
const scopeLabels:Record<string,string> = Object.fromEntries(scopeDimensions);

function ScopeFields({item}:{item?:EventItem}) {
  return <fieldset><legend>适用范围</legend><small>每行填写一个值；留空表示该维度全部适用。值须与数据中的维度名称一致。</small>
    {scopeDimensions.map(([key,label])=><label key={key}>{label}<textarea name={`scope_${key}`} rows={2} defaultValue={(item?.scope[key]??[]).join('\n')}/></label>)}
  </fieldset>;
}

export function BusinessEvents({ analysis, canCreate }:{ analysis:Analysis; canCreate:boolean }) {
  const [result,setResult]=useState<EventResult|null>(null), [error,setError]=useState(''), [busy,setBusy]=useState(false);
  const [version,setVersion]=useState(0);
  const [editing,setEditing]=useState<EventItem|null>(null);
  const [catalog,setCatalog]=useState<EventList|null>(null), [range,setRange]=useState({start:'',end:''});
  const [catalogOpen,setCatalogOpen]=useState(false);
  const [catalogLoading,setCatalogLoading]=useState(false);
  const catalogGeneration=useRef(0);
  const sessionId=analysis.id!, filters=JSON.stringify(analysis.scope?.filters ?? {});
  const current=analysis.scope?.current.join(':') ?? '';
  useEffect(()=>{
    if(!analysis.scope)return;
    let live=true; setResult(null);setError('');
    api<EventResult>(`/sessions/${sessionId}/business-events`).then(data=>{if(live)setResult(data)}).catch(e=>{if(live)setError(e.message)});
    return()=>{live=false};
  },[sessionId,filters,current,version]);
  useEffect(()=>{
    if(!catalogOpen)return;
    const generation=++catalogGeneration.current;
    const params=new URLSearchParams({scenario:analysis.scenario_id});
    if(range.start)params.set('start',range.start);
    if(range.end)params.set('end',range.end);
    setCatalog(null);setCatalogLoading(true);
    api<EventList>(`/business-events?${params}`).then(data=>{if(generation===catalogGeneration.current)setCatalog(data)}).catch(e=>{if(generation===catalogGeneration.current)setError(e.message)}).finally(()=>{if(generation===catalogGeneration.current)setCatalogLoading(false)});
    return()=>{catalogGeneration.current++};
  },[catalogOpen,analysis.scenario_id,range,version]);
  if(!analysis.scope)return null;
  async function save(e:React.FormEvent<HTMLFormElement>, target:EventItem|null) {
    e.preventDefault();setBusy(true);setError('');
    const form=e.currentTarget, data=new FormData(form);
    const scope:Record<string,string[]>={};
    for(const [key] of scopeDimensions) {
      const raw=String(data.get(`scope_${key}`)||'');
      const original=target?.scope[key];
      const values=original&&raw===original.join('\n')?original:raw.split(/\r?\n/).map(value=>value.trim()).filter(Boolean);
      if(values.length)scope[key]=values;
    }
    try {
      await api(target?`/business-events/${target.id}`:'/business-events',target?'PUT':'POST',{scenario:analysis.scenario_id,title:String(data.get('title')||''),
        start:String(data.get('start')||''),end:String(data.get('end')||''),source:String(data.get('source')||''),scope,
        ...(target?{revision:target.revision}:{})});
      form.reset();setEditing(null);setVersion(value=>value+1);
    } catch(err) {setError((err as Error).message)} finally {setBusy(false)}
  }
  async function remove(item:EventItem) {
    if(!window.confirm(`确定删除事件「${item.title}」？`))return;
    setBusy(true);setError('');try{await api(`/business-events/${item.id}?revision=${encodeURIComponent(item.revision)}`,'DELETE');if(editing?.id===item.id)setEditing(null);setVersion(value=>value+1)}catch(err){setError((err as Error).message)}finally{setBusy(false)}
  }
  function controls(item:EventItem) {
    return canCreate&&<div><button type="button" disabled={busy} onClick={()=>setEditing(item)}>编辑</button><button type="button" disabled={busy} onClick={()=>remove(item)}>删除</button></div>;
  }
  async function loadMore() {
    if(!catalog?.next_cursor||catalogLoading)return;
    const generation=catalogGeneration.current, cursor=catalog.next_cursor;
    const params=new URLSearchParams({scenario:analysis.scenario_id,after_start:cursor.start,after_id:cursor.id});
    if(range.start)params.set('start',range.start);
    if(range.end)params.set('end',range.end);
    setCatalogLoading(true);setError('');
    try {
      const page=await api<EventList>(`/business-events?${params}`);
      if(generation===catalogGeneration.current)setCatalog(previous=>{
        if(!previous)return previous;
        const seen=new Set(previous.events.map(item=>item.id));
        return {...page,events:[...previous.events,...page.events.filter(item=>!seen.has(item.id))]};
      });
    } catch(e) {if(generation===catalogGeneration.current)setError((e as Error).message)} finally {if(generation===catalogGeneration.current)setCatalogLoading(false)}
  }
  return <section className="composer"><h3>关联业务事件</h3>
    <p className="muted">匹配现期窗口前后 3 日的个人事件，事件关联不代表因果。</p>
    {result&&<><p>{result.notice}</p>{result.events.length===0?<p>当前范围暂无匹配事件。</p>:
      result.events.map(item=><article key={item.id}><strong>{item.title}</strong><p>{item.start} 至 {item.end} · {item.source}</p><small>{item.match_basis}</small><p><small>{item.evidence_status}</small></p>
        {controls(item)}</article>)}</>}
    <details onToggle={e=>setCatalogOpen(e.currentTarget.open)}><summary>查看本业务线的个人事件</summary>
      <form onSubmit={e=>{e.preventDefault();const data=new FormData(e.currentTarget);setError('');setCatalog(null);setRange({start:String(data.get('start')||''),end:String(data.get('end')||'')})}}>
        <label>筛选开始日期<input name="start" type="date"/></label><label>筛选结束日期<input name="end" type="date"/></label>
        <button type="submit">筛选重叠事件</button>
      </form>
      {catalogLoading&&!catalog&&<p role="status">正在加载事件…</p>}
      {catalog&&<><p>按事件开始日期倒序，仅显示本业务线的个人事件。列表变化时可重新筛选以刷新。</p>{catalog.events.length===0?<p>没有符合条件的事件。</p>:catalog.events.map(item=><article key={item.id}><strong>{item.title}</strong><p>{item.start} 至 {item.end} · {item.source}</p><small>范围：{Object.entries(item.scope).map(([key,values])=>`${scopeLabels[key]??key}：${values.join('、')}`).join('；')||'全部'}</small>{controls(item)}</article>)}{catalog.next_cursor&&<button type="button" disabled={catalogLoading} onClick={loadMore}>{catalogLoading?'加载中…':'加载更多'}</button>}</>}
    </details>
    {canCreate&&<details><summary>添加业务事件</summary><form onSubmit={e=>save(e,null)}>
      <label>事件名称<input name="title" maxLength={160} required /></label>
      <label>开始日期<input name="start" type="date" required /></label><label>结束日期<input name="end" type="date" required /></label>
      <label>来源<input name="source" maxLength={200} required placeholder="例如：活动日历" /></label>
      <ScopeFields/>
      <button className="primary" disabled={busy}>{busy?'保存中…':'保存事件'}</button>
    </form></details>}
    {editing&&<form key={editing.id} onSubmit={e=>save(e,editing)}><h4>编辑事件</h4>
      <label>事件名称<input name="title" maxLength={160} required defaultValue={editing.title}/></label>
      <label>开始日期<input name="start" type="date" required defaultValue={editing.start}/></label>
      <label>结束日期<input name="end" type="date" required defaultValue={editing.end}/></label>
      <label>来源<input name="source" maxLength={200} required defaultValue={editing.source}/></label>
      <ScopeFields item={editing}/><button className="primary" disabled={busy}>保存修改</button>
      <button type="button" onClick={()=>setEditing(null)}>取消</button></form>}
    {error&&<p className="error" role="alert">{error}</p>}
  </section>;
}
