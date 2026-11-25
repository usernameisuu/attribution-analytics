import { useState } from 'react';
import { api, type Analysis } from './api';
import { formatStatistic as format } from './statFormat';
const decimalOrNumber=(value:number|null, decimal?:string|null)=>value===null&&decimal?decimal:format(value);

export function StatisticalCheck({analysis,editable,onResult}:{analysis:Analysis;editable:boolean;onResult:(result:Analysis)=>void}) {
  const [level,setLevel]=useState('0.95'),[factor,setFactor]=useState(''),[group,setGroup]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const evidence=analysis.hypotheses?.find(item=>item.factor_key===factor)?.evidence[0];
  const dimensions:Record<string,string>={channel:'渠道',region:'区域',category:'品类',segment:'客群'};
  async function run() {
    if(!analysis.id||!analysis.analysis_revision||!analysis.statistics_revision)return;
    setBusy(true);setError('');
    try {
      const result=await api<Analysis>(`/sessions/${analysis.id}/daily-statistical-check`,'POST',{
        revision:analysis.analysis_revision,draft_revision:analysis.statistics_revision,confidence_level:Number(level),factor_key:factor||null,group_value:group||null});
      onResult(result);
    } catch(e) {setError((e as Error).message)} finally {setBusy(false)}
  }
  return <section className="hypotheses"><h3>每日均值检验</h3>
    <p>比较当前范围的每日均值，也可比较所选分组与其余分组的每日差距。每日数据可能相关，独立性未验证；结果不能证明因果或直接验证候选问题。每个指标与分组组合保留最近一次检验。</p>
    {editable&&analysis.scope&&<div className="form-row"><label>检验指标<select value={factor} disabled={busy} onChange={event=>{setFactor(event.target.value);setGroup('')}}><option value="">整体指标</option>{analysis.hypotheses?.map(item=><option key={item.factor_key} value={item.factor_key}>{item.factor_label}的相关每日指标</option>)}</select></label>{factor&&evidence&&<label>分组对比（{dimensions[evidence.dimension]??evidence.dimension}）<select value={group} disabled={busy} onChange={event=>setGroup(event.target.value)}><option value="">不做分组对比</option>{evidence.groups.map(item=><option key={item.value} value={item.value}>{item.value} 与其他分组</option>)}</select></label>}<label>置信水平<select value={level} disabled={busy} onChange={event=>setLevel(event.target.value)}><option value="0.90">90%</option><option value="0.95">95%</option><option value="0.99">99%</option></select></label><button type="button" disabled={busy||!analysis.statistics_revision} onClick={run}>{busy?'计算中…':'执行内置检验'}</button></div>}
    {factor&&evidence?.truncated&&<p>分组列表只包含描述性比较中展示的前 {evidence.groups.length} 项。</p>}
    {!analysis.scope&&<p>固定汇总样例没有每日数据，无法执行此检验。</p>}
    {error&&<p className="error" role="alert">{error}</p>}
    {analysis.statistical_checks?.map((check,index)=><div key={index}><p>{check.metric} · {check.sample_unit}；基期 {check.baseline_n} 个可计算日值，现期 {check.current_n} 个可计算日值。</p>
      <p>数据版本：{check.dataset_version??'旧记录未保存'}；方法版本：{check.method_version??'旧记录未保存'}；检验时间：{check.calculated_at?new Date(check.calculated_at).toLocaleString('zh-CN'):'旧记录未保存'}。</p>
      <p>基期均值 {decimalOrNumber(check.baseline_mean,check.baseline_mean_decimal)} {check.unit}；现期均值 {decimalOrNumber(check.current_mean,check.current_mean_decimal)} {check.unit}；现期减基期 {decimalOrNumber(check.mean_difference,check.mean_difference_decimal)} {check.delta_unit??check.unit}。</p>
      {check.status==='computed'?<p>t = {format(check.statistic)}，自由度 = {format(check.degrees_of_freedom)}，p {check.p_value_underflow?'小于浮点可表示范围':`= ${check.p_value?.toPrecision(6)}`}；{check.confidence_level*100}% 置信区间 [{format(check.interval?.low??null)}, {format(check.interval?.high??null)}] {check.delta_unit??check.unit}。</p>:<p>无法计算：{check.reason}</p>}
      {check.limitations.map(limit=><p key={limit}>{limit}</p>)}
    </div>)}
  </section>;
}
