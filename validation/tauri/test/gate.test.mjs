import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { ViewGate, readBoundClipboard, WaitRegistry } from '../src/gate.js';
const ready = (id = 'a', cap = 65536) => { const gate = new ViewGate(id, cap); gate.focus(true); const t = gate.reconnect(); gate.consumed(gate.receive('full', 'full', t)); gate.mode = 'direct'; return gate; };
test('no input until a new full frame has actually been consumed', () => {
  const g = new ViewGate('a'); g.focus(true); const t = g.reconnect(); g.mode = 'direct';
  assert.equal(g.input('x', t).accepted, false);
  assert.equal(g.receive('delta', 'x', t), null);
  const full = g.receive('full', 'screen', t);
  assert.equal(g.input('x', t).accepted, false);
  assert.equal(g.consumed(full), true);
  assert.equal(g.input('x', t).accepted, true);
});
test('late data and callbacks cannot cross generations', () => {
  const g = ready(); const old = g.token(); const receipt = g.receive('delta', 'abc', old);
  g.reconnect(); assert.equal(g.receive('full', 'late', old), null); assert.equal(g.consumed(receipt), false); assert.equal(g.pendingBytes, 0);
});
test('focus change rejects a delayed IME commit even after returning to same target', () => {
  const g = ready(); const old = g.token(); g.focus(false); g.focus(true);
  assert.equal(g.input('中文', old).accepted, false); assert.equal(g.input('中文', g.token()).accepted, true);
});
test('target identity is part of input binding', () => { const a = ready('a'), b = ready('b'); assert.equal(b.input('x', a.token()).accepted, false); });
test('hidden view requires full and explicit mode restoration', () => {
  const g = ready(); g.hide(); assert.equal(g.input('x', g.token()).accepted, false);
  const t = g.reconnect(); assert.equal(g.receive('delta', 'x', t), null);
  g.consumed(g.receive('full', 'screen', t)); assert.equal(g.input('x', t).accepted, false);
});
test('overflow invalidates entire observe stream, never drops delta and continues', () => {
  const g = ready('a', 8); const old = g.token(); assert.ok(g.receive('delta', '12345678', old)); assert.equal(g.receive('delta', 'x', old), null);
  assert.equal(g.ready, false); assert.equal(g.pendingBytes, 0); assert.equal(g.input('x', old).accepted, false);
});
test('credit acknowledgment is exactly once', () => { const g = ready(); const r = g.receive('delta', '中文', g.token()); assert.equal(g.pendingBytes, 6); assert.equal(g.consumed(r), true); assert.equal(g.consumed(r), false); assert.equal(g.pendingBytes, 0); });
test('unknown send has no replay queue and requires new full + explicit input', () => {
  const g = ready(); assert.equal(g.input('run\r', g.token()).accepted, true); g.unknownSend(); assert.equal(g.input('run\r', g.token()).accepted, false);
  const t = g.reconnect(); g.consumed(g.receive('full', 'new', t)); assert.equal(g.mode, 'observe'); assert.equal(g.unknown, true); assert.equal('inputQueue' in g, false); g.setMode('direct'); assert.equal(g.input('run\r', g.token()).accepted, false); assert.equal(g.acknowledgeUnknown(g.token()), true); assert.equal(g.input('x',g.token()).accepted,true);
});
test('draft sends exactly the preview bytes without adding Enter', () => { const g = ready(); g.mode = 'draft'; assert.deepEqual([...g.input('中文', g.token(), { draft:true }).bytes], [...new TextEncoder().encode('中文')]); });
test('input budget is UTF8 bytes, not UTF16 code units', () => { const g = ready(); assert.equal(g.input('中'.repeat(1366), g.token()).accepted, false); });
test('shared file and font hashes match locked fixture', async () => {
 const root = new URL('../../shared/', import.meta.url);
 for (const line of (await readFile(new URL('SHA256SUMS', root), 'utf8')).trim().split('\n')) {
   const [expected, path] = line.split('  '); assert.equal(createHash('sha256').update(await readFile(new URL(path, root))).digest('hex'), expected, path);
 }
 const fixture = JSON.parse(await readFile(new URL('fixture.json', root), 'utf8'));
 assert.equal((await readFile(new URL(fixture.load.chunkFile, root))).byteLength, fixture.load.chunkBytes);
 for (const input of fixture.inputCases) assert.equal(Buffer.from(input.text).toString('hex'), input.expectedUtf8Hex);
});

test('mode round trip invalidates delayed composition',()=>{const g=ready(),old=g.token();g.setMode('draft');g.setMode('direct');assert.equal(g.input('中文',old).accepted,false);});
test('clipboard result is rejected after a focus or mode change during read',async()=>{const g=ready();let finish;const result=readBoundClipboard(g,()=>new Promise(resolve=>finish=resolve));g.focus(false);g.focus(true);finish('must not move');assert.equal(await result,null);});
test('native wait settles when cancellation occurs before channel delivery',async()=>{const waits=new WaitRegistry();const w=waits.create(1000);waits.cancel();assert.equal(await w.promise,false);assert.equal(waits.pending.size,0);});
test('native wait has a bounded deadline even if WebView never responds',async()=>{const waits=new WaitRegistry();const w=waits.create(5);assert.equal(await w.promise,false);assert.equal(waits.pending.size,0);});
