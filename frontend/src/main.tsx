import { StrictMode, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, setCsrf, type User, type Analysis, type History, type Simulation, type Scope } from './api';
import { Waterfall } from './Waterfall';
import { DataSources } from './DataSources';
import { Conversation } from './Conversation';
import { Drilldown } from './Drilldown';
import { BudgetSummary } from './BudgetSummary';
import { BusinessEvents } from './BusinessEvents';
import './style.css';

const money = (value: string) => Number(value).toLocaleString('zh-CN',{maximumFractionDigits:2});

function App() {
  const [user,setUser]=useState<User|null>(null), [initializing,setInitializing]=useState(true);
  const [error,setError]=useState(''), [busy,setBusy]=useState(false);
  const [dashboard,setDashboard]=useState<Analysis[]>([]), [history,setHistory]=useState<History[]>([]);
  const [active,setActive]=useState<Analysis|null>(null), [simulation,setSimulation]=useState<Simulation|null>(null);
  const [adjustment,setAdjustment]=useState(0), [showMargin,setShowMargin]=useState(false);
  const generation=useRef(0);
  useEffect(()=>{api<User>('/me').then(u=>{setCsrf(u.csrf);setUser(u)}).catch(()=>{}).finally(()=>setInitializing(false))},[]);
  useEffect(()=>{if(user) {Promise.all([api<Analysis[]>('/dashboard'),api<History[]>('/sessions')]).then(([d,h])=>{setDashboard(d);setHistory(h)}).catch(e=>setError(e.message))}},[user]);

  async function enter(scenarioOrId: string, create: boolean, datasetId?:string, scope?:Scope) {
    const seq=++generation.current;
    setBusy(true);setError('');setSimulation(null);setShowMargin(false);setAdjustment(0);
    try {
      const result=await api<Analysis>(create?'/sessions':`/sessions/${scenarioOrId}`,create?'POST':'GET',create?{scenario:scenarioOrId,dataset_id:datasetId,scope}:undefined);
      if(seq!==generation.current)return;
      setActive(result);
      setHistory(await api<History[]>('/sessions'));
    } catch(e) {setError((e as Error).message)} finally {if(seq===generation.current)setBusy(false)}
  }

  async function runSimulation() {
    if(!active?.id)return;
    const seq=generation.current;
    const changes=active.scenario_id==='ecommerce'?{conversion:String(Number(active.parameters?.conversion??'0.03')+adjustment/100)}:{material:String(Number(active.parameters?.material??'540000')*(1-adjustment/100))};
    setBusy(true);setError('');
    try {const result=await api<Simulation>(`/sessions/${active.id}/simulate`,'POST',{changes});if(seq===generation.current)setSimulation(result)}
    catch(e){setError((e as Error).message)} finally {if(seq===generation.current)setBusy(false)}
  }

  if(initializing)return <main className="login"><p>正在恢复登录状态…</p></main>;
  if(!user)return <main className="login"><form onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');const data=new FormData(e.currentTarget);try{const u=await api<User>('/auth/login','POST',Object.fromEntries(data));setCsrf(u.csrf);setUser(u)}catch(err){setError((err as Error).message)}finally{setBusy(false)}}}>
    <div className="brand">经营洞察 <span>ATTRIBUTION</span></div><h1>让变化有据可循</h1><p>进入经营归因分析工作台</p>
    <label>用户名<input name="username" required autoComplete="username"/></label><label>密码<input name="password" type="password" required autoComplete="current-password"/></label>
    {error&&<p role="alert" className="error">{error}</p>}<button className="primary" disabled={busy}>{busy?'正在登录…':'登录工作台'}</button><small>账号由部署管理员创建，没有默认公开密码。</small>
  </form></main>;

  const breakdown=showMargin&&active?.margin_breakdown?active.margin_breakdown:active?.breakdown;
  return <div className="shell">
    <header><div className="brand">经营洞察 <span>ATTRIBUTION</span></div><span className="phase">确定性分析 · 开发阶段</span><div className="account">{user.username}<button onClick={async()=>{try{await api('/auth/logout','POST');generation.current++;setCsrf('');setUser(null);setActive(null);setDashboard([]);setHistory([])}catch(e){setError((e as Error).message)}}}>退出</button></div></header>
    <section className="overview"><div><span className="eyebrow">经营监测 / 分析工作台</span><h1>从指标变化，追溯经营驱动</h1><p>查看数学贡献，保存分析快照，评估条件性改善空间。</p></div><div className="overview-meta">固定模拟数据<br/><strong>PRD 基准案例 v1</strong></div></section>
    {error&&<div className="error banner" role="alert">{error}<button onClick={()=>setError('')}>关闭</button></div>}
    <section className="metric-cards">{dashboard.map(item=><button key={item.scenario_id} disabled={busy||user.role!=='analyst'} onClick={()=>enter(item.scenario_id,true)} className={'metric-card '+(active?.scenario_id===item.scenario_id?'selected':'')}><span>{item.title}</span><strong>¥ {money(item.breakdown.current)}</strong><div><em>较基期 {Number(item.breakdown.change_rate)*100}%</em><span>发起分析</span></div></button>)}</section>
    {user.role==='analyst'&&<DataSources domains={user.domains} onAnalyze={(dataset,scope)=>enter(dataset.scenario,true,dataset.id,scope)}/>}
    {user.role==='admin'&&<BudgetSummary/>}
    <main className="workspace">
      <aside className="panel sessions"><div className="panel-title"><h2>分析会话</h2><span>{history.length}</span></div><p className="muted">已保存的计算快照</p>{history.length===0?<p className="empty-small">选择上方指标，创建首个分析。</p>:history.map(h=><button key={h.id} className={'session '+(active?.id===h.id?'active':'')} onClick={()=>enter(h.id,false)} disabled={busy}><strong>{h.title}</strong><small>{new Date(h.created_at).toLocaleString('zh-CN')}</small></button>)}</aside>
      <section className="panel exploration"><div className="panel-title"><h2>分析与证据</h2><span className="pill">计算结果</span></div>
      {!active?<div className="empty"><div className="empty-icon">∑</div><h3>开始一次有依据的分析</h3><p>选择一个指标，计算引起变化的因素及其贡献。</p></div>:<><div className="question">分析「{active.title}」的核心驱动因素</div><article className="answer"><span className="eyebrow">指标拆解</span><h3>{active.metric}变化 {money(active.breakdown.delta)} 元</h3><p>本次使用 <strong>{active.breakdown.method.toUpperCase()}</strong> 分解，基于{active.data_kind}的两期数据实际计算。</p><div className="steps"><div><b>1</b><span>数据范围<strong>{active.dataset_version}</strong></span></div><div><b>2</b><span>计算方法<strong>{active.algorithm_version}</strong></span></div><div><b>3</b><span>贡献守恒<strong>残差 {Number(active.breakdown.residual).toExponential(2)}</strong></span></div></div></article><article className="notice"><strong>证据边界</strong><p>{active.evidence_status}</p>{active.limitations.map(l=><p key={l}>{l}</p>)}</article><a className="export" href={`/api/v1/sessions/${active.id}/report.md`}>导出数学分解草稿 · Markdown</a></>}
      {active&&user.role==='analyst'&&<Conversation key={active.id} analysis={active} onResult={result=>{setActive(previous=>previous?.id===result.id?result:previous);setSimulation(null)}}/>}
      {active&&<BusinessEvents key={active.id} analysis={active} canCreate={user.role==='analyst'}/>}</section>
      <section className="panel findings"><div className="panel-title"><h2>归因看板</h2>{active?.margin_breakdown&&<button onClick={()=>setShowMargin(!showMargin)}>{showMargin?'查看利润额':'查看利润率'}</button>}</div>
      {breakdown&&active?<><div className="summary"><div><span>基期</span><strong>{money(breakdown.baseline)}</strong></div><div><span>现期</span><strong>{money(breakdown.current)}</strong></div><div><span>变化 · {breakdown.unit}</span><strong className="negative">{money(breakdown.delta)}</strong></div></div><Waterfall breakdown={breakdown}/>{!showMargin&&<Drilldown rows={active.drilldown}/>}<div className="table-wrap"><table><thead><tr><th>驱动因子</th><th>贡献量</th><th>贡献率</th></tr></thead><tbody>{breakdown.factors.map(f=><tr key={f.key}><td>{f.label}</td><td className={Number(f.contribution)>=0?'positive':'negative'}>{money(f.contribution)}</td><td>{f.contribution_rate===null?'不适用':`${(Number(f.contribution_rate)*100).toFixed(1)}%`}</td></tr>)}</tbody></table></div><section className="simulator"><h3>What-If 情景模拟</h3><p>{active.scenario_id==='ecommerce'?'转化率提升（百分点）':'原材料成本下降（%）'}</p><div className="slider-row"><input aria-label="模拟调整值" type="range" min="0" max={active.scenario_id==='ecommerce'?2:20} step={active.scenario_id==='ecommerce'?0.1:1} value={adjustment} onChange={e=>{setAdjustment(Number(e.target.value));setSimulation(null)}}/><output>{adjustment}</output></div><button className="primary" disabled={busy||user.role!=='analyst'} onClick={runSimulation}>{busy?'处理中…':'计算模拟结果'}</button>{simulation&&<div className="simulation-result"><span>预计改善 · 条件性点估计</span><strong>¥ {money(simulation.improvement)}</strong><p>模拟结果：{money(simulation.prediction)} 元</p><small>{simulation.assumptions}</small></div>}</section></>:<div className="empty"><p>分析结果将在这里呈现。</p></div>}</section>
    </main><footer>数据与计算可追溯 · 当前版本尚未完成统计、沙箱及在线模型验收</footer>
  </div>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>);
