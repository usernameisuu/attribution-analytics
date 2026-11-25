import type { Hypothesis, StatisticalCheck } from './api';

const dimensions:Record<string,string>={channel:'渠道',region:'区域',category:'品类',segment:'客群'};
import { formatNumber } from './formatNumber';
const display=(value:string|null)=>formatNumber(value);

export function Hypotheses({items,checks}:{items?:Hypothesis[];checks?:StatisticalCheck[]}) {
  if(!items?.length)return null;
  return <section className="hypotheses"><h3>待验证问题</h3>
    <p>规则候选问题附有当前范围内的描述性比较；这些问题尚未通过统计检验验证。</p>
    {items.map(item=><details key={item.id}>
      <summary>{item.question} <span>{item.status_label}</span></summary>
      <p>对应因子：{item.factor_label}；数学贡献 {formatNumber(item.factor_contribution)} {item.contribution_unit}。</p>
      <p>可能需要的数据：{item.required_data.join('；')}。</p>
      {item.evidence.map((evidence,index)=><div key={index}>
        <p>{dimensions[evidence.dimension]??evidence.dimension}比较：{evidence.metric}（{evidence.unit}）</p>
        <div className="table-wrap"><table><thead><tr><th>分组</th><th>基期</th><th>现期</th><th>变化（{evidence.delta_unit}）</th></tr></thead><tbody>{evidence.groups.map(group=><tr key={group.value}><td>{group.value}</td><td>{display(group.baseline)}</td><td>{display(group.current)}</td><td>{display(group.delta)}</td></tr>)}</tbody></table></div>
        <p>{evidence.note}{evidence.truncated&&` 已展示变化幅度最大的 ${evidence.groups.length} 项，共 ${evidence.total_groups} 项。`}</p>
      </div>)}
      {item.factor_key&&checks?.some(check=>check.factor_key===item.factor_key)&&<div><p>相关逐日检验（按因子关联，不能直接验证该问题）：</p>
        {checks.filter(check=>check.factor_key===item.factor_key).map((check,index)=><p key={index}>{check.metric}：{check.status==='computed'?'已计算，详见每日均值检验':`无法计算：${check.reason??'原因未记录'}`}。</p>)}
      </div>}
      {item.limitations.map(limit=><p key={limit}>{limit}</p>)}
    </details>)}
  </section>;
}
