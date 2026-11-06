import test from 'node:test';
import assert from 'node:assert/strict';
import { settleNetworkOperation } from '../src/network-ui.js';

test('unknown write invalidates affected host and waits for refresh before catalog reload', async () => {
  const calls=[]; let release;
  const refreshing=new Promise(resolve=>{release=resolve;});
  const pending=settleNetworkOperation(async()=>{calls.push('write');throw Error('sync_result_unknown');},['host-a'],async ids=>{calls.push(['invalidate',ids]);await refreshing;calls.push('hosts-refreshed');},async message=>{calls.push(['catalog-reload',message]);});
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls,['write',['invalidate',['host-a']]]);
  release();assert.equal(await pending,false);
  assert.equal(calls[2],'hosts-refreshed');assert.equal(calls[3][0],'catalog-reload');
  assert.match(calls[3][1],/结果未确认/);assert.doesNotMatch(calls[3][1],/重试|未更改/);
});

test('successful write also invalidates before catalog reload', async () => {
  const calls=[];
  assert.equal(await settleNetworkOperation(async()=>{calls.push('write');},[],async()=>{calls.push('refresh');},async()=>{calls.push('catalog');}),true);
  assert.deepEqual(calls,['write','refresh','catalog']);
});
