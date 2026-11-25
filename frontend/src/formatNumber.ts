/** Display rounded numbers without presenting a small nonzero value as exact zero. */
export function formatNumber(value:string|number|null, digits=2):string {
  if(value===null)return '不适用';
  if(typeof value==='string' && !value.trim())return '不适用';
  const number=Number(value);
  if(!Number.isFinite(number))return '不适用';
  if(number===0 && typeof value==='string' && /^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim())
     && /[1-9]/.test(value.trim().split(/[eE]/)[0]))return value.trim();
  if(number!==0&&Math.abs(number)<0.5*10**(-digits))return number.toExponential(3);
  return number.toLocaleString('zh-CN',{maximumFractionDigits:digits});
}
