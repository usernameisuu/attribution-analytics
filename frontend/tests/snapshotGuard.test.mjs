import test from 'node:test';
import assert from 'node:assert/strict';
import { canApplySnapshot } from '../src/snapshotGuard.ts';

test('only applies a response to the unchanged session and revision',()=>{
  const current={id:'s1',report_revision:'old'};
  assert.equal(canApplySnapshot(current,{id:'s1',report_revision:'new'},'old'),true);
  assert.equal(canApplySnapshot({...current,report_revision:'edited'},{id:'s1'},'old'),false);
  assert.equal(canApplySnapshot(current,{id:'s2'},'old'),false);
  assert.equal(canApplySnapshot({...current,report_revision:undefined},{id:'s1'},undefined),false);
});
