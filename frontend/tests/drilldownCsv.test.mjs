import test from 'node:test';
import assert from 'node:assert/strict';
import { drilldownCsv } from '../src/drilldownCsv.ts';

const child={dimension:'region',value:'华南',baseline:'20',current:'10',delta:'-10',contribution_rate:null};
const row={dimension:'channel',value:' =HYPERLINK("https://invalid")',baseline:'100',current:'80',delta:'-20',contribution_rate:null,children:[child]};
const identity=rows=>rows;

test('escapes formulas and quotes while preserving numeric values',()=>{
  const csv=drilldownCsv([row],new Set(),identity);
  assert.ok(csv.startsWith('\uFEFF'));
  assert.ok(csv.includes('"\' =HYPERLINK(""https://invalid"")"'));
  assert.ok(csv.includes(',100,80,-20'));
  assert.ok(!csv.includes('华南'));
});

test('exports only expanded child rows and handles legacy rows',()=>{
  const csv=drilldownCsv([row,{...child,children:undefined}],new Set([row.value]),identity);
  assert.equal(csv.split('\r\n').length,4);
  assert.ok(csv.includes('"二级","区域","华南",20,10,-10'));
});

test('rejects malformed numeric fields before they can become spreadsheet formulas',()=>{
  assert.throws(()=>drilldownCsv([{...row,baseline:'=1+1'}],new Set(),identity),/数值格式无效/);
});
