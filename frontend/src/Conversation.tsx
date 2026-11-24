import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type Analysis, type Run } from './api';

const pending = (run:Run) => ['queued','running'].includes(run.status);
const names:Record<string,string>={queued:'等待 worker',running:'执行中',succeeded:'数学分析完成',cancelled:'已取消',failed:'执行失败',needs_input:'需要明确问题'};

export function Conversation({analysis,onResult}:{analysis:Analysis;onResult:(result:Analysis)=>void}) {
  const [runs,setRuns]=useState<Run[]>([]), [question,setQuestion]=useState(''), [mode,setMode]=useState('rules');
  const [error,setError]=useState(''), [busy,setBusy]=useState(false), [progress,setProgress]=useState('');
  const [loading,setLoading]=useState(true);
  const pendingKey=useRef<{text:string;mode:string;key:string}|null>(null);
  const resultHandler=useRef(onResult);resultHandler.current=onResult;
  const active=runs.find(pending), sessionId=analysis.id!;
  useEffect(()=>{
    let live=true;
    if(!analysis.scope){setLoading(false);return}
    api<Run[]>(`/sessions/${sessionId}/runs`).then(async r=>{
      if(!live)return;
      setRuns(r);
      const snapshot=await api<Analysis>(`/sessions/${sessionId}`);
      if(live)resultHandler.current(snapshot);
    }).catch(e=>{if(live)setError(e.message)}).finally(()=>{if(live)setLoading(false)});
    return()=>{live=false};
  },[sessionId]);
  useEffect(()=>{
    if(!active)return;
    let live=true;
    const events=new EventSource(`/api/v1/runs/${active.id}/events`);
    events.addEventListener('progress',e=>{try{const data=JSON.parse((e as MessageEvent).data);setProgress(data.message||data.stage)}catch{setError('任务事件格式无效')}});
    events.addEventListener('access-revoked',()=>{events.close();setError('登录状态或业务权限已变更，请刷新页面');setRuns([])});
    events.addEventListener('done',()=>{
      events.close();
      Promise.all([api<Run[]>(`/sessions/${sessionId}/runs`),api<Analysis>(`/sessions/${sessionId}`)])
        .then(([r,a])=>{if(live){setRuns(r);resultHandler.current(a);setProgress('')}})
        .catch(e=>{if(live)setError(e.message)});
    });
    events.onerror=()=>{
      if(!live)return;
      setProgress('连接中断，正在恢复任务事件…');
      api<Run>(`/runs/${active.id}`).catch(e=>{
        if(live&&e instanceof ApiError&&[401,403,404].includes(e.status)){
          events.close();setError('登录状态或业务权限已变更，请刷新页面');setRuns([]);
        }
      });
    };
    return()=>{live=false;events.close()};
  },[active?.id,sessionId]);

  async function submit(text=question) {
    if(!text.trim()||busy||active||loading)return;
    setBusy(true);setError('');
    const request=pendingKey.current?.text===text&&pendingKey.current.mode===mode?pendingKey.current:{text,mode,key:crypto.randomUUID()};
    pendingKey.current=request;
    try {
      const run=await api<Run>(`/sessions/${sessionId}/runs`,'POST',{question:text,mode,request_key:request.key});
      setRuns(previous=>[run,...previous.filter(r=>r.id!==run.id)]);pendingKey.current=null;setQuestion('');
      if(!pending(run))resultHandler.current(await api<Analysis>(`/sessions/${sessionId}`));
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  if(!analysis.scope)return <div className="composer"><p>固定汇总样例只支持公式拆解。请在「数据源」导入或生成日聚合版本，开始多轮追问。</p></div>;
  return <div className="composer"><h3>多轮探查</h3>
    <p className="muted">基期 {analysis.scope.baseline.join(' 至 ')}<br/>现期 {analysis.scope.current.join(' 至 ')}<br/>筛选：{Object.entries(analysis.scope.filters).map(([k,v])=>`${k}=${v}`).join('，')||'全部'} · 分组：{analysis.scope.group_by}</p>
    <div className="conversation-log" aria-live="polite">{[...runs].reverse().map(run=><article key={run.id}><strong>{run.question}</strong><p>{names[run.status]||run.status} · {run.mode==='rules'?'规则解析':'DeepSeek'} · 第 {run.attempts} 次执行</p>{run.error&&<p className="error">{run.error}</p>}{['failed','needs_input','cancelled'].includes(run.status)&&<button disabled={!!active||busy} onClick={()=>{setQuestion(run.question);setMode(run.mode)}}>编辑后重新提交</button>}</article>)}</div>
    {active&&<div role="status"><p>{progress||names[active.status]}</p><button disabled={busy} onClick={async()=>{setBusy(true);try{const run=await api<Run>(`/runs/${active.id}/cancel`,'POST');setRuns(previous=>previous.map(r=>r.id===run.id?run:r));setProgress('');resultHandler.current(await api<Analysis>(`/sessions/${sessionId}`))}catch(e){setError((e as Error).message)}finally{setBusy(false)}}}>取消任务</button></div>}
    {loading&&<p role="status">正在恢复任务记录…</p>}
    <form onSubmit={e=>{e.preventDefault();submit()}}><label htmlFor="question">继续追问<textarea id="question" maxLength={2000} value={question} onChange={e=>setQuestion(e.target.value)} disabled={!!active||busy||loading} placeholder="例如：只看华东，按渠道；返回全国，按品类"/></label>
      <div className="form-row"><label>解析方式<select value={mode} onChange={e=>setMode(e.target.value)} disabled={!!active||busy||loading}><option value="rules">规则模式 · 不调用模型</option><option value="deepseek">DeepSeek · 使用 API 预算</option></select></label><button className="primary" disabled={!question.trim()||!!active||busy||loading}>提交追问</button><button type="button" disabled={!!active||busy||loading} onClick={()=>submit('返回上一级')}>返回上一级</button></div>
      <small>DeepSeek 需远程配置密钥及价格。规则模式支持维度值筛选、按维度分组、清除筛选和返回上一级。统计检验尚未接入。</small>
    </form>{error&&<p className="error" role="alert">{error}</p>}
  </div>;
}
