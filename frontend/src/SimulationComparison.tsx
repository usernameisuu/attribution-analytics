import { useEffect, useState } from 'react';
import { api, type Analysis, type SimulationScenario } from './api';
import { FormulaSensitivity } from './FormulaSensitivity';
import { BaselineVariability } from './BaselineVariability';
import { formatNumber } from './formatNumber';

interface Draft { name:string; changes:Record<string,string> }
const money=(value:string)=>formatNumber(value);

export function SimulationComparison({analysis,editable,onResult}:{analysis:Analysis;editable:boolean;onResult:(value:Analysis)=>void}) {
  const factors=analysis.breakdown.factors;
  const initial=(index:number):Draft=>({name:`情景 ${index}`,changes:factors[0]?{[factors[0].key]:factors[0].current}:{}});
  const [drafts,setDrafts]=useState<Draft[]>(()=>analysis.simulation_scenarios?.length
    ? analysis.simulation_scenarios.map(item=>({name:item.name,changes:{...item.changes}})) : [initial(1)]);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const [preview,setPreview]=useState<SimulationScenario[]|null>(null),[previewError,setPreviewError]=useState(''),[previewPending,setPreviewPending]=useState(false);
  useEffect(()=>{
    if(!editable||!analysis.id||!analysis.analysis_revision)return;
    let live=true;
    setPreview(null);setPreviewError('');
    if(drafts.some(item=>!item.name.trim()||Object.values(item.changes).some(value=>!value.trim()))) {
      setPreviewPending(false);return;
    }
    setPreviewPending(true);
    const timer=setTimeout(()=>{
      api<SimulationScenario[]>(`/sessions/${analysis.id}/simulation-preview`,'POST',{revision:analysis.analysis_revision,scenarios:drafts})
        .then(result=>{if(live)setPreview(result)}).catch(e=>{if(live)setPreviewError((e as Error).message)})
        .finally(()=>{if(live)setPreviewPending(false)});
    },400);
    return()=>{live=false;clearTimeout(timer)};
  },[analysis.id,analysis.analysis_revision,drafts,editable]);
  function update(index:number,change:Partial<Draft>) {setDrafts(previous=>previous.map((item,i)=>i===index?{...item,...change}:item))}
  async function submit() {
    if(!analysis.id||!analysis.analysis_revision||!analysis.simulation_revision)return;
    setBusy(true);setError('');
    try {
      const scenarios=drafts.map(item=>({name:item.name,changes:item.changes}));
      const result=await api<Analysis>(`/sessions/${analysis.id}/simulation-comparison`,'POST',{revision:analysis.analysis_revision,draft_revision:analysis.simulation_revision,scenarios});
      onResult(result);
    } catch(e) {setError((e as Error).message)} finally {setBusy(false)}
  }
  return <section className="simulator"><h3>What-If 多情景模拟</h3>
    <p>可同时调整多个因子，未选因子保持当前值。模拟指标为{analysis.metric}（元）；结果为条件性点估计，未包含执行成本，也未估计因子联动；收益区间暂无依据。</p>
    <FormulaSensitivity analysis={analysis}/>
    <BaselineVariability analysis={analysis}/>
    {editable&&<><form onSubmit={event=>{event.preventDefault();submit()}}>{drafts.map((draft,index)=><fieldset key={index} className="scenario-draft" disabled={busy}><legend>情景 {index+1}</legend>
      <label>名称<input maxLength={80} required value={draft.name} onChange={event=>update(index,{name:event.target.value})}/></label>
      {factors.map(factor=>{const selected=Object.hasOwn(draft.changes,factor.key);return <div key={factor.key} className="scenario-factor">
        <label><input type="checkbox" checked={selected} disabled={selected&&Object.keys(draft.changes).length===1} onChange={event=>{
          const changes={...draft.changes};if(event.target.checked)changes[factor.key]=factor.current;else delete changes[factor.key];update(index,{changes});
        }}/>{factor.label}（当前 {factor.current}）</label>
        {selected&&<label>{factor.label}模拟值<input type="number" min="0" step="any" required value={draft.changes[factor.key]} onChange={event=>update(index,{changes:{...draft.changes,[factor.key]:event.target.value}})}/></label>}
      </div>})}
      {drafts.length>1&&<button type="button" onClick={()=>setDrafts(previous=>previous.filter((_,i)=>i!==index))}>移除</button>}
    </fieldset>)}<div className="form-row"><button type="button" disabled={busy||drafts.length>=5} onClick={()=>setDrafts(previous=>[...previous,initial(previous.length+1)])}>添加情景</button><button className="primary" disabled={busy||!analysis.analysis_revision||!analysis.simulation_revision}>{busy?'计算中…':'计算并保存对比'}</button></div></form>{error&&<p className="error" role="alert">{error}</p>}
      <div aria-live="polite"><strong>未保存预览</strong>{previewPending&&<p>计算中…</p>}{previewError&&<p className="error">{previewError}</p>}{preview?.map((item,index)=><p key={index}>{item.name}：{analysis.metric} {money(item.prediction)} 元，较现期 {money(item.improvement)} 元{analysis.scenario_id==='consumer'&&item.margin?.prediction!=null?`；净利润率 ${money(item.margin.prediction)}%`:''}{item.margin?.reason?`；${item.margin.reason}`:''}</p>)}</div>
    </>}
    {analysis.simulation_scenarios?.length ? <div className="table-wrap"><table><thead><tr><th>情景</th><th>模拟{analysis.metric}（元）</th><th>{analysis.metric}较现期变化（元）</th>{analysis.scenario_id==='consumer'&&<><th>模拟净利润率（%）</th><th>较现期变化（百分点）</th></>}</tr></thead><tbody>{analysis.simulation_scenarios.map((item,index)=><tr key={`${index}-${item.name}`}><td>{item.name}</td><td>{money(item.prediction)}</td><td>{money(item.improvement)}</td>{analysis.scenario_id==='consumer'&&<><td>{item.margin?.prediction!=null?money(item.margin.prediction):'不适用'}</td><td>{item.margin?.improvement!=null?money(item.margin.improvement):'不适用'}</td></>}</tr>)}</tbody></table><p>收益区间：暂无依据。模拟值与假设随当前会话快照保存。</p>{analysis.simulation_scenarios.map((item,index)=><p key={`${index}-${item.name}`}><strong>{item.name}：</strong>{Object.entries(item.changes).map(([key,value])=>`${factors.find(factor=>factor.key===key)?.label??key} = ${value}`).join('；')}。{item.assumptions}{analysis.scenario_id==='consumer'&&(!item.margin?' 旧情景未记录利润率，请重新计算。':item.margin.reason?` ${item.margin.reason}`:'')}</p>)}</div>:null}
  </section>;
}
