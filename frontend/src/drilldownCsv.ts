import type { DrillCell } from './api';

export const dimensionLabels:Record<string,string> = {channel:'渠道',region:'区域',category:'品类',segment:'客群'};

function text(value:string) {
  const safe=/^[\s\uFEFF]*[=+@\-\t\r]/u.test(value)?`'${value}`:value;
  return `"${safe.replace(/"/g,'""')}"`;
}

function number(value:string) {
  if(!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value))
    throw new Error('分组数值格式无效，无法导出');
  return value;
}

export function drilldownCsv(rows:DrillCell[],expanded:Set<string>,order:(items:DrillCell[])=>DrillCell[]) {
  const lines=[['层级','维度','分组','基期','现期','变化'].map(text).join(',')];
  const line=(level:string,row:DrillCell)=>[text(level),text(dimensionLabels[row.dimension]??row.dimension),text(row.value),
    number(row.baseline),number(row.current),number(row.delta)].join(',');
  for(const row of rows) {
    lines.push(line('一级',row));
    if(expanded.has(row.value))for(const child of order(row.children??[]))lines.push(line('二级',child));
  }
  return '\uFEFF'+lines.join('\r\n');
}
