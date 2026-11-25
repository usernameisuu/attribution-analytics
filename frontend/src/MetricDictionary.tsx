import { useEffect, useState } from 'react';
import { api, type MetricCatalog, type MetricExpression } from './api';

const labels:Record<string,string>={sales_amount:'营收',material_cost:'原材料成本',logistics_cost:'物流成本',
  commission_cost:'佣金',other_cost:'其他成本',tax_cost:'税费',visits:'访问次数',orders:'订单数',
  conversion_factor:'订单转化因子',basket:'客单价',gmv_from_factors:'GMV',
  sample_net_profit:'样例净利润',sample_net_margin:'样例净利润率'};
const symbols={add:'+',sub:'−',mul:'×',div:'÷'};
function expression(node:MetricExpression):string {
  if('ref' in node)return labels[node.ref]??node.ref;
  if('const' in node)return node.const;
  return `（${expression(node.args[0])} ${symbols[node.op]} ${expression(node.args[1])}）`;
}
function unit(value:Record<string,number>):string {
  const names:Record<string,string>={cny:'元',visit:'次访问',order:'单'};
  const parts=Object.entries(value).map(([key,power])=>`${names[key]??key}${power===1?'':`^${power}`}`);
  return parts.length?parts.join(' · '):'无量纲';
}

export function MetricDictionary({scenario,version}:{scenario:string;version?:string}) {
  const [open,setOpen]=useState(false),[catalog,setCatalog]=useState<MetricCatalog|null>(null),[error,setError]=useState('');
  useEffect(()=>{
    if(!open)return;
    let alive=true;setCatalog(null);setError('');
    api<MetricCatalog>(`/metrics/${encodeURIComponent(scenario)}`).then(value=>{if(alive)setCatalog(value)})
      .catch(e=>{if(alive)setError((e as Error).message)});
    return()=>{alive=false};
  },[scenario,open]);
  return <details className="composer" onToggle={event=>setOpen(event.currentTarget.open)}><summary>查看内置指标口径</summary>
    {error&&<p role="alert" className="error">{error}</p>}
    {!error&&!catalog&&<p>正在读取指标口径…</p>}
    {catalog&&<><p>当前内置口径版本：{catalog.version}。此处为只读样例定义，尚未提供配置和版本管理。</p>
      {version!==catalog.version&&<p>当前会话记录的口径版本：{version??'未记录'}；以下是当前内置定义，请勿视为该历史快照的已验证口径。</p>}
      <p>{catalog.scenario_metric.description}</p>{catalog.scenario_metric.limitations.map(item=><p key={item}>{item}</p>)}
      <div className="table-wrap"><table><thead><tr><th>指标</th><th>公式或来源</th><th>单位</th></tr></thead><tbody>
        {Object.entries(catalog.definitions).map(([key,definition])=><tr key={key}><td>{labels[key]??key}<br/><small>{key}</small></td>
          <td>{definition.expression?expression(definition.expression):'数据集的聚合字段'}</td><td>{unit(definition.unit)}</td></tr>)}
      </tbody></table></div>
      <p>公式中的比率基于期内总量计算；分母为零时不适用。此字典展示样例口径，不代表财务政策已确认。</p>
    </>}
  </details>;
}
