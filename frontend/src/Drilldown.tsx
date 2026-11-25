import { useMemo, useState } from 'react';
import { api, type DrillCell, type Scope } from './api';
import { dimensionLabels as dimensions, drilldownCsv } from './drilldownCsv';
import { formatNumber } from './formatNumber';

type SortKey = 'value'|'baseline'|'current'|'delta';
const money=(value:string)=>formatNumber(value);

export function Drilldown({rows,sessionId,datasetVersion,scope,revision}:{rows?:DrillCell[];sessionId?:string;datasetVersion:string;scope?:Scope;revision?:string|null}) {
  const [sortKey,setSortKey]=useState<SortKey>('value');
  const [ascending,setAscending]=useState(true);
  const [expanded,setExpanded]=useState<Set<string>>(()=>new Set());
  const [exporting,setExporting]=useState(false), [error,setError]=useState('');
  const order=(items:DrillCell[])=>[...items].sort((a,b)=>{
    const result=sortKey==='value'?a.value.localeCompare(b.value,'zh-CN'):Number(a[sortKey])-Number(b[sortKey]);
    return (ascending?1:-1)*result || a.value.localeCompare(b.value,'zh-CN');
  });
  const ordered=useMemo(()=>order(rows??[]),[rows,sortKey,ascending]);
  if(!ordered.length)return null;
  const headers:[SortKey,string][]=[['value','分组'],['baseline','基期'],['current','现期'],['delta','变化']];
  function sort(key:SortKey) {
    if(key===sortKey)setAscending(!ascending);
    else {setSortKey(key);setAscending(true)}
  }
  function toggle(value:string) {
    setExpanded(previous=>{const next=new Set(previous);if(next.has(value))next.delete(value);else next.add(value);return next});
  }
  async function exportTable() {
    if(!sessionId||!scope||!revision)return;
    setExporting(true);setError('');
    try {
      const csv=drilldownCsv(ordered,expanded,order);
      await api<void>(`/sessions/${sessionId}/drilldown-export`,'POST',{dataset_version:datasetVersion,scope,revision});
      const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
      const link=document.createElement('a');link.href=url;link.download='分析分组.csv';link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    } catch(e) {setError((e as Error).message)} finally {setExporting(false)}
  }
  return <div className="table-wrap scope-table"><div className="drilldown-heading"><h3>当前分组贡献</h3><button type="button" onClick={exportTable} disabled={!sessionId||!scope||!revision||exporting}>{exporting?'正在导出…':'导出当前表格 CSV'}</button></div>
    <table><thead><tr>{headers.map(([key,label])=><th key={key} aria-sort={sortKey===key?(ascending?'ascending':'descending'):'none'}><button type="button" onClick={()=>sort(key)}>{label}{sortKey===key?(ascending?' ↑':' ↓'):''}</button></th>)}</tr></thead>
      <tbody>{ordered.flatMap(row=>{
        const children=order(row.children??[]), isOpen=expanded.has(row.value);
        const parent=<tr key={`parent:${row.value}`}><td>{children.length>0&&<button type="button" aria-expanded={isOpen} aria-label={`${isOpen?'折叠':'展开'}${row.value}`} onClick={()=>toggle(row.value)}>{isOpen?'−':'+'}</button>} {row.value}</td><td>{money(row.baseline)}</td><td>{money(row.current)}</td><td className={Number(row.delta)>=0?'positive':'negative'}>{money(row.delta)}</td></tr>;
        return [parent,...(isOpen?children.map(child=><tr key={`child:${row.value}:${child.value}`} className="drilldown-child"><td>{dimensions[child.dimension]??child.dimension}：{child.value}</td><td>{money(child.baseline)}</td><td>{money(child.current)}</td><td className={Number(child.delta)>=0?'positive':'negative'}>{money(child.delta)}</td></tr>):[])];
      })}</tbody>
    </table><small>展开后查看第二层维度；下级合计对应所属上级，不应将两层重复相加。导出包含当前展开的行。</small>{error&&<p className="error" role="alert">{error}</p>}
  </div>;
}
