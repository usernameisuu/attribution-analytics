import type { DrillCell } from './api';

export function Drilldown({rows}:{rows?:DrillCell[]}) {
  if(!rows?.length)return null;
  const money=(v:string)=>Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
  return <div className="table-wrap scope-table"><h3>当前分组贡献</h3><table><thead><tr><th>分组</th><th>基期</th><th>现期</th><th>变化</th></tr></thead><tbody>{rows.map(r=><tr key={r.value}><td>{r.value}</td><td>{money(r.baseline)}</td><td>{money(r.current)}</td><td className={Number(r.delta)>=0?'positive':'negative'}>{money(r.delta)}</td></tr>)}</tbody></table><small>同一分组维度内的变化可相加；不同维度之间不能重复累计。</small></div>;
}
