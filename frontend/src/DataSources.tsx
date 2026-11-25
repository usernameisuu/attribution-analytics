import { useEffect, useRef, useState } from 'react';
import { api, type Comparison, type Dataset, type MetricCatalog, type Scope } from './api';
import { formatNumber } from './formatNumber';

const dayBefore = (day: string, days: number) => {
  const value = new Date(`${day}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate()-days);
  return value.toISOString().slice(0,10);
};

export function DataSources({domains,onAnalyze}:{domains:string[];onAnalyze:(dataset:Dataset,scope:Scope)=>Promise<void>}) {
  const [datasets,setDatasets]=useState<Dataset[]>([]), [scenario,setScenario]=useState(domains[0]||'ecommerce');
  const [selected,setSelected]=useState(''), [name,setName]=useState(''), [file,setFile]=useState<File|null>(null);
  const [busy,setBusy]=useState(false), [error,setError]=useState('');
  const [dates,setDates]=useState<string[]>(['','','','']);
  const [threshold,setThreshold]=useState(''), [comparison,setComparison]=useState<Comparison|null>(null);
  const [catalog,setCatalog]=useState<MetricCatalog|null>(null), [catalogError,setCatalogError]=useState('');
  const comparisonVersion=useRef(0);
  const dataset=datasets.find(d=>d.id===selected);
  useEffect(()=>{let alive=true;api<Dataset[]>('/datasets').then(d=>{if(alive)setDatasets(d)}).catch(e=>{if(alive)setError(e.message)});return()=>{alive=false}},[]);
  useEffect(()=>{
    let alive=true;setCatalog(null);setCatalogError('');
    if(dataset)api<MetricCatalog>(`/metrics/${dataset.scenario}`).then(value=>{if(alive)setCatalog(value)}).catch(e=>{if(alive)setCatalogError(e.message)});
    return()=>{alive=false};
  },[dataset?.scenario]);
  function choose(record:Dataset) {
    comparisonVersion.current++;setComparison(null);setThreshold('');
    setSelected(record.id);
    setDates([dayBefore(record.end,59),dayBefore(record.end,30),dayBefore(record.end,29),record.end]);
  }
  async function compareData() {
    if(!dataset)return;
    if(!threshold.trim()||dates.some(day=>!day)){setError('请填写比较期和大于零的阈值');return}
    const version=++comparisonVersion.current;
    setBusy(true);setError('');setComparison(null);
    try {
      const result=await api<Comparison>(`/datasets/${dataset.id}/compare`,'POST',{
        scope:{baseline:[dates[0],dates[1]],current:[dates[2],dates[3]],filters:{},group_by:'channel'},threshold
      });
      if(version===comparisonVersion.current)setComparison(result);
    } catch(e) {if(version===comparisonVersion.current)setError((e as Error).message)}
    finally {setBusy(false)}
  }
  async function importData(demo:boolean) {
    setBusy(true);setError('');
    try {
      if(!demo&&(!file||!name.trim()))throw new Error('请选择 CSV/JSON 文件并填写名称');
      if(file&&file.size>10_000_000&&!demo)throw new Error('文件不能超过 10 MB');
      if(!demo&&!/\.(csv|json)$/i.test(file!.name))throw new Error('仅支持 CSV 或 JSON 文件');
      const record=await api<Dataset>(demo?'/datasets/demo':'/datasets','POST',demo?{scenario}:{scenario,name,format:file!.name.toLowerCase().endsWith('.csv')?'csv':'json',content:await file!.text()});
      setDatasets(await api<Dataset[]>('/datasets'));choose(record);
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  return <details className="panel data-sources"><summary>数据源 · 导入与分析</summary>
    <p className="muted">导入个人版本化日聚合数据，或生成 90 天合成样例。每个日期须覆盖相同业务组合，缺失业务需显式填零。</p>
    <div className="form-row"><label>业务线<select value={scenario} onChange={e=>setScenario(e.target.value)}>{domains.map(d=><option key={d} value={d}>{d==='ecommerce'?'电商 GMV':'快消品利润'}</option>)}</select></label>
      <label>版本名称<input maxLength={120} value={name} onChange={e=>setName(e.target.value)} placeholder="例如：9—10 月经营数据"/></label>
      <label>数据文件<input type="file" accept=".csv,.json" onChange={e=>setFile(e.target.files?.[0]||null)}/></label>
      <button disabled={busy} onClick={()=>importData(false)}>校验并导入</button><button disabled={busy} onClick={()=>importData(true)}>生成合成样例</button></div>
    <details><summary>查看数据格式</summary><p>CSV 表头（JSON 使用同名字段的对象数组）：</p><code>date,channel,region,category,segment,visitors,orders,revenue,material,logistics,commission,other,tax,spend</code><p>日期 YYYY-MM-DD；计数为非负整数；金额使用元。visitors 表示访问次数，不表示去重访客。最多 20,000 行 / 10 MB。</p></details>
    <form onSubmit={async e=>{e.preventDefault();if(!dataset)return;setBusy(true);setError('');try{await onAnalyze(dataset,{baseline:[dates[0],dates[1]],current:[dates[2],dates[3]],filters:{},group_by:'channel'})}catch(err){setError((err as Error).message)}finally{setBusy(false)}}}>
      <label>已保存版本<select value={selected} onChange={e=>{const d=datasets.find(r=>r.id===e.target.value);if(d)choose(d);else {comparisonVersion.current++;setComparison(null);setSelected('')}}}><option value="">请选择版本</option>{datasets.map(d=><option key={d.id} value={d.id}>{d.name} · {d.scenario==='ecommerce'?'电商':'快消'} · {d.row_count} 行</option>)}</select></label>
      {dataset&&<><p className="muted">覆盖 {dataset.start} 至 {dataset.end} · SHA-256 {dataset.digest.slice(0,16)}…</p>{catalog&&<details><summary>查看样例指标口径 · {catalog.version}</summary><p>{catalog.scenario_metric.name}：{catalog.scenario_metric.description}</p>{catalog.scenario_metric.limitations.map(item=><p key={item}>{item}</p>)}<small>当前为内置口径，尚不支持在线编辑。</small></details>}{catalogError&&<p className="error">指标口径加载失败：{catalogError}</p>}<div className="form-row">{['基期开始','基期结束','现期开始','现期结束'].map((label,i)=><label key={label}>{label}<input type="date" required min={dataset.start} max={dataset.end} value={dates[i]} onChange={e=>{comparisonVersion.current++;setComparison(null);setDates(previous=>previous.map((d,j)=>j===i?e.target.value:d))}}/></label>)}<button className="primary" disabled={busy}>创建数据分析</button></div><small>比较期必须等长、不重叠且数据完整；默认最近两个 30 天。</small>
        <div className="form-row"><label>异动阈值（{dataset.scenario==='ecommerce'?'相对变化 %':'利润率变化百分点'}）<input type="number" min="0.0001" max="10000" step="any" value={threshold} onChange={e=>{comparisonVersion.current++;setComparison(null);setThreshold(e.target.value)}} placeholder="由分析师填写"/></label><button type="button" disabled={busy} onClick={compareData}>比较并标记</button></div>
        <small>本次临时阈值由分析师指定，按变化绝对值比较；此处不是自动定时监控。</small>
        {comparison&&<div className="notice" role="status"><strong>{comparison.status==='anomaly'?'达到异动阈值':comparison.status==='normal'?'未达到异动阈值':'无法判定'}</strong><p>{comparison.metric} · 基期 {comparison.baseline??'不适用'} {comparison.unit} · 现期 {comparison.current??'不适用'} {comparison.unit}</p><p>{comparison.change===null?comparison.reason:`变化 ${formatNumber(comparison.change)} ${comparison.threshold_unit}；阈值 ${comparison.threshold} ${comparison.threshold_unit}`}</p><small>{comparison.method}。阈值标记不代表统计显著性或因果结论。</small></div>}
      </>}
    </form>{error&&<p className="error" role="alert">{error}</p>}
  </details>;
}
