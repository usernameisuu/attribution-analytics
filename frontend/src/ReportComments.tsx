import { useEffect, useState } from 'react';
import { api } from './api';

interface Comment {id:string;body:string;author:string;editable:boolean;revision:number;created_at:string;updated_at:string}
export function ReportComments({reportId}:{reportId:string}) {
  const [items,setItems]=useState<Comment[]>([]), [text,setText]=useState(''), [editing,setEditing]=useState<Comment|null>(null);
  const [busy,setBusy]=useState(false), [error,setError]=useState(''), [version,setVersion]=useState(0);
  useEffect(()=>{let live=true;api<Comment[]>(`/published-reports/${reportId}/comments`)
    .then(data=>{if(live)setItems(data)}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[reportId,version]);
  async function save() {
    setBusy(true);setError('');
    try {
      await api(`/published-reports/${reportId}/comments${editing?`/${editing.id}`:''}`,editing?'PUT':'POST',editing?{body:text,revision:editing.revision}:{body:text});
      setText('');setEditing(null);setVersion(v=>v+1);
    } catch(e){setError((e as Error).message)} finally {setBusy(false)}
  }
  return <section className="hypotheses"><h3>协作批注</h3><p>批注与报告快照分开保存，不包含在导出中；显示最近 100 条。</p>
    <button type="button" onClick={()=>{setError('');setVersion(v=>v+1)}}>刷新批注</button>
    {items.map(item=><article key={item.id}><strong>{item.author}</strong><p>{new Date(item.updated_at).toLocaleString('zh-CN')} · 修订 {item.revision}</p><p style={{whiteSpace:'pre-wrap'}}>{item.body}</p>{item.editable&&<button type="button" onClick={()=>{setEditing(item);setText(item.body);setError('')}}>编辑自己的批注</button>}</article>)}
    <form onSubmit={e=>{e.preventDefault();void save()}}><label>{editing?'编辑批注':'添加批注'}<textarea value={text} maxLength={2000} required onChange={e=>setText(e.target.value)}/></label><button disabled={busy||!text.trim()}>{busy?'保存中…':'保存批注'}</button>{editing&&<button type="button" onClick={()=>{setEditing(null);setText('')}}>取消编辑</button>}</form>
    {error&&<p role="alert" className="error">{error}</p>}
  </section>;
}
