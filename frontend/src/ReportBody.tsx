import { reportBlocks } from './reportBlocks';

export function ReportBody({markdown, className}:{markdown:string;className:string}) {
  return <article className={className}>{reportBlocks(markdown).map((block,index)=>{
    if(block.kind==='heading') {
      if(block.level===1)return <h2 key={index}>{block.text}</h2>;
      if(block.level===2)return <h3 key={index}>{block.text}</h3>;
      return <h4 key={index}>{block.text}</h4>;
    }
    if(block.kind==='table')return <div className="report-table" key={index}><table><thead><tr>{block.header.map((cell,i)=><th key={i}>{cell}</th>)}</tr></thead>
      <tbody>{block.rows.map((row,i)=><tr key={i}>{row.map((cell,j)=><td key={j}>{cell}</td>)}</tr>)}</tbody></table></div>;
    if(block.kind==='bullet')return <p className="report-bullet" key={index}>• {block.text}</p>;
    return <p key={index}>{block.text}</p>;
  })}</article>;
}
