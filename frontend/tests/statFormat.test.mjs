import test from 'node:test';
import assert from 'node:assert/strict';
import { formatStatistic } from '../src/statFormat.ts';

test('small nonzero statistics are not displayed as exact zero',()=>{
  assert.equal(formatStatistic(0), '0');
  assert.equal(formatStatistic(0.00000001), '1.000e-8');
  assert.equal(formatStatistic(-0.00000001), '-1.000e-8');
  assert.equal(formatStatistic(null), '不适用');
});
