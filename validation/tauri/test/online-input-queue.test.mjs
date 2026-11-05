import test from 'node:test';
import assert from 'node:assert/strict';
import { OnlineInputQueue } from '../src/online-input-queue.js';
const token={generation:1,epoch:2,revision:3};
test('FIFO preserves exact bytes and is scoped to a single focus lease',()=>{
  const q=new OnlineInputQueue(3,8);const a=new Uint8Array([65]);
  assert.equal(q.push(token,a),true);a[0]=90;assert.equal(q.push(token,new Uint8Array([3,13])),true);
  assert.deepEqual([...q.take(token).bytes],[65]);assert.deepEqual([...q.take(token).bytes],[3,13]);
  assert.equal(q.push(token,new Uint8Array([66])),true);assert.equal(q.take({...token,revision:4}),null);assert.equal(q.items.length,0);
});
test('overflow is bounded and cleanup reports unsent items',()=>{
  const q=new OnlineInputQueue(2,3);assert.ok(q.push(token,new Uint8Array([1,2])));assert.ok(q.push(token,new Uint8Array([3])));
  assert.equal(q.push(token,new Uint8Array([4])),false);assert.deepEqual(q.clear(),{count:2,bytes:3});assert.equal(q.take(token),null);
});
