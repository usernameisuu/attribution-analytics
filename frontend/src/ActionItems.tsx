import { useState } from 'react';
import { api, type Analysis } from './api';

interface Draft { action:string; factor_key:string; owner_role:string; estimated_days:string; estimated_benefit:string; benefit_basis:string }

export function ActionItems({analysis,editable,onResult}:{analysis:Analysis;editable:boolean;onResult:(value:Analysis)=>void}) {
  const factors=analysis.breakdown.factors;
  const [items,setItems]=useState<Draft[]>(()=>analysis.action_items?.map(item=>({action:item.action, factor_key:item.factor_key,
    owner_role:item.owner_role, estimated_days:item.estimated_days===null?'':String(item.estimated_days),
    estimated_benefit:item.estimated_benefit??'', benefit_basis:item.benefit_basis}))??[]);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  function update(index:number,change:Partial<Draft>) {setItems(previous=>previous.map((item,i)=>i===index?{...item,...change}:item))}
  async function submit() {
    if(!analysis.id||!analysis.analysis_revision||!analysis.action_revision)return;
    setBusy(true);setError('');
    try {
      const payload=items.map(item=>({...item,estimated_days:item.estimated_days?Number(item.estimated_days):null,
        estimated_benefit:item.estimated_benefit.trim()||null}));
      const result=await api<Analysis>(`/sessions/${analysis.id}/action-items`,'PUT',{revision:analysis.analysis_revision,draft_revision:analysis.action_revision,items:payload});
      onResult(result);
    } catch(e) {setError((e as Error).message)} finally {setBusy(false)}
  }
  return <section className="hypotheses"><h3>行动清单</h3><p>由分析师填写并关联数学驱动因子。责任、周期或收益依据不足时可以留空；录入不代表行动已获批准。</p>
    {editable&&<form onSubmit={event=>{event.preventDefault();submit()}}>{items.map((item,index)=><fieldset key={index} className="scenario-draft" disabled={busy}><legend>行动 {index+1}</legend>
      <label>具体动作<textarea maxLength={500} required value={item.action} onChange={event=>update(index,{action:event.target.value})}/></label>
      <label>关联因子<select value={item.factor_key} onChange={event=>update(index,{factor_key:event.target.value})}>{factors.map(factor=><option key={factor.key} value={factor.key}>{factor.label}（贡献 {factor.contribution} {analysis.breakdown.unit}）</option>)}</select></label>
      <label>责任岗位（可暂不填写）<input maxLength={100} value={item.owner_role} onChange={event=>update(index,{owner_role:event.target.value})}/></label>
      <label>预计周期（天，可暂不填写）<input type="number" min="1" max="3650" step="1" value={item.estimated_days} onChange={event=>update(index,{estimated_days:event.target.value})}/></label>
      <label>预计收益（元，可暂不填写）<input type="number" step="any" value={item.estimated_benefit} onChange={event=>update(index,{estimated_benefit:event.target.value})}/></label>
      <label>收益估算依据{item.estimated_benefit?'（填写收益时必填）':'（可暂不填写）'}<textarea maxLength={500} required={!!item.estimated_benefit} value={item.benefit_basis} onChange={event=>update(index,{benefit_basis:event.target.value})}/></label>
      <button type="button" onClick={()=>setItems(previous=>previous.filter((_,i)=>i!==index))}>移除</button>
    </fieldset>)}<div className="form-row"><button type="button" disabled={busy||items.length>=10} onClick={()=>setItems(previous=>[...previous,{action:'',factor_key:factors[0]?.key??'',owner_role:'',estimated_days:'',estimated_benefit:'',benefit_basis:''}])}>添加行动</button><button className="primary" disabled={busy||!analysis.analysis_revision||!analysis.action_revision}>{busy?'保存中…':'保存行动清单'}</button></div></form>}
    {error&&<p className="error" role="alert">{error}</p>}
    {!!analysis.action_items?.length&&<div><h4>已保存的草稿</h4>{analysis.action_items.map((item,index)=><article key={index}><strong>{item.action}</strong><p>关联因子：{item.factor_label}；数学贡献 {item.factor_contribution} {analysis.breakdown.unit}。责任：{item.owner_role||'待补充'}；周期：{item.estimated_days===null?'待补充':`${item.estimated_days} 天`}。</p><p>预计收益：{item.estimated_benefit===null?'暂无依据':`${item.estimated_benefit} 元（分析师估计）`}；依据：{item.benefit_basis||'待补充'}。</p></article>)}</div>}
  </section>;
}
