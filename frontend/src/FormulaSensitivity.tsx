import { useEffect, useState } from 'react';
import { api, type Analysis } from './api';

interface Sensitivity {
  analysis_revision:string; metric:string; notice:string;
  rows:{key:string;label:string;current:string;per_unit:string;elasticity:string|null;reason:string|null}[];
}
const format=(value:string)=>{const n=Number(value);return n!==0&&Math.abs(n)<0.000001?n.toExponential(3):n.toLocaleString('zh-CN',{maximumFractionDigits:6})};

export function FormulaSensitivity({analysis}:{analysis:Analysis}) {
  const [data,setData]=useState<Sensitivity|null>(null),[error,setError]=useState('');
  useEffect(()=>{
    let live=true;setData(null);setError('');
    if(!analysis.id||!analysis.analysis_revision)return;
    api<Sensitivity>(`/sessions/${analysis.id}/formula-sensitivity`).then(result=>{
      if(!live)return;
      if(result.analysis_revision!==analysis.analysis_revision){setError('分析已更新，请刷新后查看敏感性。');return}
      setData(result);
    }).catch(e=>{if(live)setError(e.message)});
    return()=>{live=false};
  },[analysis.id,analysis.analysis_revision]);
  return <details><summary>查看当前公式的局部敏感性</summary>
    {error&&<p className="error" role="alert">{error}</p>}
    {data&&<><p>{data.notice}</p><p>因子增加 1 个原始单位时，目标指标的局部变化量；相对弹性是因子变化 1% 时指标相对变化的理论百分比。订单转化因子的 1 个单位是 100 个百分点。</p>
      <div className="table-wrap"><table><thead><tr><th>因子</th><th>每增加 1 单位，{data.metric}变化（元）</th><th>公式相对弹性</th></tr></thead><tbody>{data.rows.map(row=><tr key={row.key}><td>{row.label}</td><td>{format(row.per_unit)}</td><td>{row.elasticity===null?`不适用（${row.reason}）`:format(row.elasticity)}</td></tr>)}</tbody></table></div></>}
  </details>;
}
