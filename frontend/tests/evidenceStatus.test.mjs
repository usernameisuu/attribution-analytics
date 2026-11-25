import test from 'node:test';
import assert from 'node:assert/strict';
import { evidenceStatus } from '../src/evidenceStatus.ts';

test('evidence status distinguishes an executed check from hypothesis validation',()=>{
  assert.equal(evidenceStatus('待执行', []), '待执行');
  assert.match(evidenceStatus('待执行', [{status:'computed'}]), /已执行每日均值检验；候选业务假设仍待验证/);
  assert.match(evidenceStatus('待执行', [{status:'not_applicable'}]), /检验未能计算/);
  assert.match(evidenceStatus('待执行', [{status:'computed'}, {status:'not_applicable'}]), /部分检验未能计算/);
});
