import { useEffect, useState } from 'react';
import { api } from './api';

interface Draft {id:string;name:string;scenario:string;digest:string;author_id:string;created_at:string;status:'draft';definitions?:unknown}
interface Template {base_version:string;definitions:unknown}
interface Preview {draft_id:string;digest:string;target:string;value:string;unit:Record<string,number>;notice:string}
interface SyntheticComparison {target:string;unit:Record<string,number>;data_digest:string;dataset_version:string;
  builtin_metric_version:string;builtin_algorithm_version:string;notice:string;
  scope:{baseline:[string,string];current:[string,string]};periods:{period:string;draft:string;builtin:string;difference:string}[]}
interface ComparisonRecord {id:string;created_at:string;actor_id:string|null;target:string|null;status:'available'|'unavailable'|'corrupt';result:SyntheticComparison|null}

function ComparisonResult({value}:{value:SyntheticComparison}) {
  return <div><p>{value.notice}</p><p>数据 {value.dataset_version} · 摘要 {value.data_digest}；内置口径 {value.builtin_metric_version}，算法 {value.builtin_algorithm_version}。</p>
    <p>基期 {value.scope.baseline.join(' 至 ')}；现期 {value.scope.current.join(' 至 ')}；单位 {JSON.stringify(value.unit)}。</p>
    <div className="table-wrap"><table><thead><tr><th>比较期</th><th>草稿公式</th><th>内置计算</th><th>草稿减内置</th></tr></thead><tbody>{value.periods.map(item=><tr key={item.period}><td>{item.period==='baseline'?'基期':'现期'}</td><td>{item.draft}</td><td>{item.builtin}</td><td>{item.difference}</td></tr>)}</tbody></table></div>
  </div>;
}

export function MetricDrafts() {
  const [scenario,setScenario]=useState('ecommerce'),[name,setName]=useState(''),[content,setContent]=useState('');
  const [drafts,setDrafts]=useState<Draft[]>([]),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [selected,setSelected]=useState<Draft|null>(null),[target,setTarget]=useState('gmv_from_factors');
  const [inputs,setInputs]=useState('{"visits":"100000","orders":"5000","sales_amount":"1000000"}');
  const [preview,setPreview]=useState<Preview|null>(null);
  const [compareTarget,setCompareTarget]=useState('gmv_from_factors'),[comparison,setComparison]=useState<SyntheticComparison|null>(null);
  const [history,setHistory]=useState<{draftId:string;items:ComparisonRecord[]}|null>(null),[historyError,setHistoryError]=useState(''),[historyVersion,setHistoryVersion]=useState(0);
  const [busy,setBusy]=useState(false),[refresh,setRefresh]=useState(0);
  useEffect(()=>{
    let live=true;setDrafts([]);setError('');
    api<Draft[]>(`/admin/metric-drafts?scenario=${scenario}`).then(value=>{if(live)setDrafts(value)})
      .catch(e=>{if(live)setError((e as Error).message)});
    return()=>{live=false};
  },[scenario,refresh]);
  useEffect(()=>{
    const id=selected?.id;if(!id){setHistory(null);return}
    let live=true;setHistory(null);setHistoryError('');
    api<ComparisonRecord[]>(`/admin/metric-drafts/${id}/comparisons`).then(items=>{if(live)setHistory({draftId:id,items})})
      .catch(e=>{if(live)setHistoryError((e as Error).message)});
    return()=>{live=false};
  },[selected?.id,historyVersion]);
  async function loadTemplate() {
    setBusy(true);setError('');setNotice('');
    try {const result=await api<Template>(`/admin/metric-drafts/template/${scenario}`);
      setContent(JSON.stringify(result.definitions,null,2));setSelected(null);setPreview(null);setComparison(null);setNotice(`已载入 ${result.base_version} 模板，请保存后试算。`);
    } catch(e) {setError((e as Error).message)} finally {setBusy(false)}
  }
  async function loadDraft(draft:Draft) {
    setBusy(true);setError('');setNotice('');
    try {const result=await api<Draft>(`/admin/metric-drafts/${draft.id}`);
      setName(result.name);setContent(JSON.stringify(result.definitions,null,2));setSelected(result);setPreview(null);setComparison(null);setNotice('已载入历史草稿；保存会创建新版本。');
    } catch(e) {setError((e as Error).message)} finally {setBusy(false)}
  }
  async function save() {
    setBusy(true);setError('');setNotice('');
    try {
      let definitions:unknown;
      try {definitions=JSON.parse(content)} catch {throw new Error('指标定义必须是有效 JSON。')}
      const result=await api<Draft>('/admin/metric-drafts','POST',{scenario,name,definitions});
      setSelected(result);setPreview(null);setComparison(null);setNotice(`已保存草稿 ${result.name}；摘要 ${result.digest.slice(0,16)}…。`);setRefresh(value=>value+1);
    } catch(e) {setError((e as Error).message)} finally {setBusy(false)}
  }
  async function runPreview() {
    if(!selected)return;
    setBusy(true);setError('');setNotice('');setPreview(null);
    try {
      let values:unknown;
      try {values=JSON.parse(inputs)} catch {throw new Error('试算输入必须是有效 JSON。')}
      if(!values||typeof values!=='object'||Array.isArray(values)||Object.values(values).some(value=>typeof value!=='string'))
        throw new Error('试算输入须为指标标识到十进制字符串的对象。');
      const result=await api<Preview>(`/admin/metric-drafts/${selected.id}/preview`,'POST',{target,inputs:values});
      setPreview(result);
    } catch(e) {setError((e as Error).message)} finally {setBusy(false)}
  }
  async function runComparison() {
    if(!selected)return;
    setBusy(true);setError('');setNotice('');setComparison(null);
    try {setComparison(await api<SyntheticComparison>(`/admin/metric-drafts/${selected.id}/compare-synthetic`,'POST',{target:compareTarget}));setHistoryVersion(value=>value+1)}
    catch(e) {setError((e as Error).message)} finally {setBusy(false)}
  }
  return <section className="panel data-sources metric-drafts"><h2>指标定义草稿</h2>
    <p>管理员可编辑并保存经过依赖、循环和单位校验的定义版本。草稿不会启用，也不会改变现有分析计算。</p>
    <div className="form-row"><label>业务线<select value={scenario} disabled={busy} onChange={event=>{const value=event.target.value;setScenario(value);setSelected(null);setPreview(null);setComparison(null);setTarget(value==='ecommerce'?'gmv_from_factors':'sample_net_profit');setCompareTarget(value==='ecommerce'?'gmv_from_factors':'sample_net_profit')}}><option value="ecommerce">电商 GMV</option><option value="consumer">快消品利润</option></select></label>
      <label>版本名称<input maxLength={120} value={name} disabled={busy} onChange={event=>setName(event.target.value)}/></label>
      <button type="button" disabled={busy} onClick={loadTemplate}>载入内置模板</button></div>
    <p className="muted">载入模板或历史草稿会替换当前编辑内容；切换业务线后请检查所用定义。</p>
    <label>指标定义 JSON<textarea value={content} disabled={busy} onChange={event=>setContent(event.target.value)} spellCheck={false}/></label>
    <button type="button" disabled={busy||!name.trim()||!content.trim()} onClick={save}>{busy?'处理中…':'校验并保存新草稿'}</button>
    {error&&<p className="error" role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
    {selected&&<details><summary>试算已保存版本</summary><p>试算使用已保存的「{selected.name}」，不包含编辑区中未保存的修改；输入由管理员手动提供。</p>
      <label>目标指标标识<input value={target} disabled={busy} maxLength={64} onChange={event=>{setTarget(event.target.value);setPreview(null)}}/></label>
      <label>原子指标输入 JSON<textarea value={inputs} disabled={busy} onChange={event=>{setInputs(event.target.value);setPreview(null)}} spellCheck={false}/></label>
      <button type="button" disabled={busy||!target.trim()} onClick={runPreview}>试算保存的版本</button>
      {preview&&<div role="status"><p>{preview.target} = {preview.value}；单位：{JSON.stringify(preview.unit)}。</p><p>{preview.notice}</p></div>}
    </details>}
    {selected&&<details><summary>比较合成数据与内置口径</summary><p>使用可复现的合成数据比较已保存草稿「{selected.name}」与当前内置计算；编辑区中未保存的修改不参与比较。</p>
      <label>比较指标<select value={compareTarget} disabled={busy} onChange={event=>{setCompareTarget(event.target.value);setComparison(null)}}>
        {scenario==='ecommerce'?<option value="gmv_from_factors">GMV</option>:<><option value="sample_net_profit">样例净利润</option><option value="sample_net_margin">样例净利润率</option></>}
      </select></label><button type="button" disabled={busy} onClick={runComparison}>{busy?'计算中…':'运行合成数据比较'}</button>
      {comparison&&<div role="status"><ComparisonResult value={comparison}/></div>}
      <details><summary>历史比较记录（最近 50 条）</summary>
        <p>记录保留当时的合成数据摘要和结果；摘要一致只用于发现内容变化，不代表公式已通过审批。</p>
        {historyError&&<p className="error" role="alert">{historyError}</p>}
        {!historyError&&history?.draftId===selected.id&&history.items.length===0&&<p>暂无比较记录。</p>}
        {history?.draftId===selected.id&&history.items.map(record=><details key={record.id}><summary>{record.target??'旧记录'} · {new Date(record.created_at).toLocaleString('zh-CN')} · {record.status==='available'?'摘要一致':record.status==='corrupt'?'摘要校验失败':'旧记录未保存结果'}</summary>
          {record.status==='available'&&record.result&&<ComparisonResult value={record.result}/>}
          {record.status==='corrupt'&&<p>记录内容与摘要不一致，不能展示该结果。</p>}
          {record.status==='unavailable'&&<p>该旧记录只保存了审计信息，没有保存比较结果。</p>}
        </details>)}
      </details>
    </details>}
    <h3>已保存草稿</h3>{drafts.length===0&&<p>当前业务线暂无草稿。</p>}
    {drafts.map(draft=><p key={draft.id}>{draft.name} · {draft.digest.slice(0,16)}… · {new Date(draft.created_at).toLocaleString('zh-CN')} <button type="button" disabled={busy} onClick={()=>loadDraft(draft)}>载入草稿</button></p>)}
  </section>;
}
