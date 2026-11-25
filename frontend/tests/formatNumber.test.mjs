import test from 'node:test';
import assert from 'node:assert/strict';
import { formatNumber } from '../src/formatNumber.ts';

test('keeps small nonzero values visible rather than rounding to zero',()=>{
  assert.equal(formatNumber('0'), '0');
  assert.equal(formatNumber('-0.00001'), '-1.000e-5');
  assert.equal(formatNumber('1e-400'), '1e-400');
  assert.equal(formatNumber('0e-400'), '0');
  assert.equal(formatNumber('1234.567'), '1,234.57');
  assert.equal(formatNumber(null), '不适用');
});
