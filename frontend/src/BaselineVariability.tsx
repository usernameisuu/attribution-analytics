import { useEffect, useState } from 'react';
import { api, type Analysis } from './api';

interface Row { key:string; label:string; n:number; missing_days:number; mean:string|null; stddev:string|null; relative_percent:string|null }
interface Variability { analysis_revision:string; window:string[]; days:number; missing_dates:number; notice:string; metric:Row; factors:Row[] }
const format=(value:string|null)=>{
  if(value===null)return '不适用';
  const number=Number(value);
  return number!==0&&Math.abs(number)<0.000001?number.toExponential(3):number.toLocaleString('zh-CN',{maximumFractionDigits:6});
};

export function BaselineVariability({analysis}:{analysis:Analysis}) {
  const [open,setOpen]=useState(false),[data,setData]=useState<Variability|null>(null),[error,setError]=useState('');
  useEffect(()=>{
    if(!open||!analysis.scope||!analysis.id||!analysis.analysis_revision)return;
    let live=true;setData(null);setError('');
    api<Variability>(`/sessions/${analysis.id}/baseline-variability`).then(result=>{
      if(!live)return;
      if(result.analysis_revision!==analysis.analysis_revision){setError('分析已更新，请刷新后查看波动。');return}
      setData(result);
    }).catch(e=>{if(live)setError(e.message)});
    return()=>{live=false};
  },[open,analysis.id,analysis.analysis_revision]);
  return <details onToggle={event=>setOpen(event.currentTarget.open)}><summary>查看基期每日历史波动</summary>
    {!analysis.scope&&<p>固定汇总样例没有逐日数据，无法计算。</p>}
    {error&&<p className="error" role="alert">{error}</p>}
    {data&&<><p>基期 {data.window.join(' 至 ')}；实际观察 {data.days} 天，缺少日期 {data.missing_dates} 天。{data.notice}</p>
      <p>样本少于 2 天时标准差不适用；均值为零时相对波动不适用。转换因子的零分母日期不计入对应样本。</p>
      <div className="table-wrap"><table><thead><tr><th>指标或因子</th><th>有效天数</th><th>缺失天数</th><th>每日均值</th><th>样本标准差</th><th>相对波动（%）</th></tr></thead><tbody>{[data.metric,...data.factors].map(row=><tr key={row.key}><td>{row.label}</td><td>{row.n}</td><td>{row.missing_days}</td><td>{format(row.mean)}</td><td>{format(row.stddev)}</td><td>{format(row.relative_percent)}</td></tr>)}</tbody></table></div></>}
  </details>;
}
