import test from 'node:test';
import assert from 'node:assert/strict';
import { reportBlocks } from '../src/reportBlocks.ts';

test('renders headings, escaped table values and literal HTML as text',()=>{
  const blocks=reportBlocks('# 标题\n\n| 分组 | 值 |\n| --- | ---: |\n| A\\|B | &lt;script&gt; |\n\n- 待验证');
  assert.deepEqual(blocks[0],{kind:'heading',level:1,text:'标题'});
  assert.deepEqual(blocks[1],{kind:'table',header:['分组','值'],rows:[['A|B','<script>']]});
  assert.deepEqual(blocks[2],{kind:'bullet',text:'待验证'});
});

test('escaped formatting remains literal and backslashes preserve table boundaries',()=>{
  const blocks=reportBlocks('\\# 非标题\n\\- 非列表\n| A\\\\ | B\\|C |\n| --- | --- |\n| x | y |');
  assert.deepEqual(blocks[0],{kind:'paragraph',text:'# 非标题'});
  assert.deepEqual(blocks[1],{kind:'paragraph',text:'- 非列表'});
  assert.deepEqual(blocks[2],{kind:'table',header:['A\\','B|C'],rows:[['x','y']]});
});
