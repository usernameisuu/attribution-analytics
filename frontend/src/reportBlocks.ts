/** Parse only the plain headings, tables and lists emitted by our report service.
 * All output is text: HTML and links are never interpreted or executed.
 */
export type ReportBlock =
  | {kind:'heading'; level:number; text:string}
  | {kind:'paragraph'|'bullet'; text:string}
  | {kind:'table'; header:string[]; rows:string[][]};

function text(value:string):string {
  const unescaped=value.replace(/\\([\\|\[\]()*_`#+-])/g,'$1');
  return unescaped.replace(/&(amp|lt|gt);/g,(_,entity:string)=>({amp:'&',lt:'<',gt:'>'})[entity]!);
}

function cells(line:string):string[] {
  const source=line.trim().replace(/^\|/,'').replace(/\|\s*$/,'');
  const result:string[]=[];
  let part='', slashes=0;
  for (const char of source) {
    if(char==='|' && slashes%2===0) {result.push(text(part.trim()));part='';}
    else part+=char;
    slashes=char==='\\'?slashes+1:0;
  }
  result.push(text(part.trim()));
  return result;
}

export function reportBlocks(markdown:string):ReportBlock[] {
  const lines=markdown.split(/\r?\n/), blocks:ReportBlock[]=[];
  for(let i=0;i<lines.length;i++) {
    const line=lines[i].trim();
    if(!line)continue;
    const heading=/^(#{1,3})\s+(.*)$/.exec(line);
    if(heading){blocks.push({kind:'heading',level:heading[1].length,text:text(heading[2])});continue;}
    const separator=lines[i+1]?.trim();
    if(line.startsWith('|') && separator && /^\|(?:\s*:?-{3,}:?\s*\|)+$/.test(separator)) {
      const header=cells(line), rows:string[][]=[];i++;
      while(i+1<lines.length && lines[i+1].trim().startsWith('|')) rows.push(cells(lines[++i]));
      blocks.push({kind:'table',header,rows});continue;
    }
    if(line.startsWith('- ')){blocks.push({kind:'bullet',text:text(line.slice(2))});continue;}
    blocks.push({kind:'paragraph',text:text(line)});
  }
  return blocks;
}
