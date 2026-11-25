import { useEffect, useRef } from 'react';
import { echarts } from './charts';
import type { Breakdown } from './api';
import { formatNumber } from './formatNumber';

export function Waterfall({ breakdown: b }: { breakdown: Breakdown }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.init(element.current);
    let running = Number(b.baseline);
    const items: { name: string; raw:string; value: [number, number, number]; itemStyle: { color: string } }[] = [];
    items.push({name:'基期', raw:b.baseline, value:[0,0,running], itemStyle:{color:'#283d56'}});
    b.factors.forEach((f, i) => {
      const next = running + Number(f.contribution);
      items.push({name:f.label, raw:f.contribution, value:[i+1, running, next], itemStyle:{color:Number(f.contribution)>=0?'#0b857a':'#cb5867'}});
      running = next;
    });
    items.push({name:'现期', raw:b.current, value:[items.length,0,Number(b.current)], itemStyle:{color:'#283d56'}});
    chart.setOption({
      animation: false, grid: {left:65,right:16,top:20,bottom:60},
      tooltip: { trigger: 'item', formatter: (p: unknown) => {
        const point = p as {name:string; data:{raw:string}};
        return `${point.name}: ${formatNumber(point.data.raw)} ${b.unit}`;
      }},
      xAxis: {type:'category', data:items.map(i=>i.name), axisLabel:{interval:0,rotate:25,fontSize:12}},
      yAxis: {type:'value', axisLabel:{formatter:(n:number)=>Math.abs(n)>=10000?`${(n/10000).toFixed(0)}万`:String(n)}},
      series: [{type:'custom', encode:{x:0,y:[1,2]}, data:items,
        renderItem: (_params: unknown, a: {value:(i:number)=>number; coord:(v:number[])=>number[]; size:(v:number[])=>number[]; style:()=>object}) => {
          const start=a.coord([a.value(0),a.value(1)]), end=a.coord([a.value(0),a.value(2)]);
          const width=a.size([1,0])[0]*0.55;
          return {type:'rect',shape:{x:start[0]-width/2,y:Math.min(start[1],end[1]),width,height:Math.max(1,Math.abs(start[1]-end[1]))},style:a.style()};
        }
      }]
    });
    const resize = new ResizeObserver(() => chart.resize());
    resize.observe(element.current);
    return () => { resize.disconnect(); chart.dispose(); };
  }, [b]);
  return <><div ref={element} className="chart" role="img" aria-label="因子贡献瀑布图，具体数值见下方数据表"/><small>图形使用浮点近似；未舍入数值见报告。</small></>;
}
