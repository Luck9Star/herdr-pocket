import test from 'node:test';
import assert from 'node:assert/strict';
import { matchedReceipt } from '../src/input-receipt.js';

test('receipt must identify the selected stable target and exact bytes', () => {
  const target={paneId:'p',terminalId:'t'};
  const receipt={requestId:'a'.repeat(32),paneId:'p',terminalId:'t',acceptedBytes:9};
  assert.deepEqual(matchedReceipt({...receipt, ignored:'private'},target,9),receipt);
  for (const invalid of [{...receipt,requestId:'x'}, {...receipt,paneId:'other'},
    {...receipt,terminalId:'other'}, {...receipt,acceptedBytes:8}]) {
    assert.equal(matchedReceipt(invalid,target,9),null);
  }
});
