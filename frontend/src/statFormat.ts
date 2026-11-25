export function formatStatistic(value:number|null):string {
  if(value===null)return '不适用';
  if(value!==0&&Math.abs(value)<0.00005)return value.toExponential(3);
  return value.toLocaleString('zh-CN',{maximumFractionDigits:4});
}
