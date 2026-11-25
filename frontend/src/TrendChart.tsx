import { useEffect, useMemo, useRef } from 'react';
import { echarts } from './charts';
import type { TrendPoint } from './api';
import { formatNumber } from './formatNumber';

export function TrendChart({ points, metric }: {points?:TrendPoint[]; metric:string}) {
  const element = useRef<HTMLDivElement>(null);
  const sorted = useMemo(() => [...(points ?? [])].sort((a,b)=>a.date.localeCompare(b.date)), [points]);
  useEffect(()=>{
    if (!element.current || !sorted.length) return;
    const chart = echarts.init(element.current);
    chart.setOption({
      animation:false,
      color:['#647b99','#087f75'],
      legend:{data:['基期','现期']},
      grid:{left:72,right:22,top:42,bottom:55},
      tooltip:{trigger:'axis'},
      xAxis:{type:'category',data:sorted.map(point=>point.date),axisLabel:{rotate:30}},
      yAxis:{type:'value',name:'元',axisLabel:{formatter:(value:number)=>Math.abs(value)>=10000?`${(value/10000).toFixed(1)}万`:String(value)}},
      series:([
        {period:'baseline',name:'基期'},
        {period:'current',name:'现期'},
      ] as const).map(({period,name})=>({
        name,type:'line',showSymbol:true,connectNulls:false,
        data:sorted.map(point=>point.period===period?Number(point.value):null),
      })),
    });
    const observer = new ResizeObserver(()=>chart.resize());
    observer.observe(element.current);
    return ()=>{observer.disconnect();chart.dispose()};
  },[sorted]);
  if (!sorted.length) return null;
  return <section className="trend-section">
    <h3>每日{metric}趋势</h3>
    <p>按实际日期展示当前筛选范围内的每日金额；基期和现期分别标记。</p>
    <div ref={element} className="chart" role="img" aria-label={`每日${metric}趋势，明细可在下方表格查看`}/>
    <details><summary>查看每日数值</summary><div className="table-wrap"><table><thead><tr><th>日期</th><th>比较期</th><th>{metric}（元）</th></tr></thead><tbody>{sorted.map(point=><tr key={`${point.period}-${point.date}`}><td>{point.date}</td><td>{point.period==='baseline'?'基期':'现期'}</td><td>{formatNumber(point.value)}</td></tr>)}</tbody></table></div></details>
  </section>;
}
