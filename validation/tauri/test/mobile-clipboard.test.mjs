import test from 'node:test';
import assert from 'node:assert/strict';
import {createPasteClipboard, clipboardPasteMessage} from '../src/mobile-clipboard.js';

test('Android discovers the platform without reading and uses only the native reader after a tap', async () => {
  const calls = [];
  const reader = createPasteClipboard({
    focused: () => true,
    callNative: async cmd => {
      calls.push(cmd);
      return cmd === 'config_document_platform' ? 'android' : '中\n';
    },
    webClipboard: () => assert.fail('unexpected web fallback'),
  });
  await reader.initialize(true);
  assert.deepEqual(calls, ['config_document_platform']);
  assert.equal(await reader.read(), '中\n');
  assert.deepEqual(calls, ['config_document_platform', 'mobile_clipboard_read_text']);
});

test('web reader runs on the gesture stack and checks the real UTF-8 limit', async () => {
  let reads = 0, value = '😀'.repeat(1024);
  const reader = createPasteClipboard({
    focused: () => true,
    callNative: () => assert.fail('unexpected native fallback'),
    webClipboard: () => ({readText: async () => { reads++; return value; }}),
  });
  reader.initialize(false);
  const first = reader.read();
  assert.equal(reads, 1);
  assert.equal(await first, value);
  value += 'a';
  await assert.rejects(reader.read(), /clipboard_too_large/);
  value = 'x'.repeat(100000);
  await assert.rejects(reader.read(), /clipboard_too_large/);
  value = '';
  await assert.rejects(reader.read(), /clipboard_empty/);
});

test('a changed focus discards a pending read and suppresses a subsequent read', async () => {
  let focused = true, reads = 0, resolve;
  const reader = createPasteClipboard({
    focused: () => focused,
    webClipboard: () => ({readText: () => {
      reads++;
      return new Promise(done => { resolve = done; });
    }}),
  });
  const pending = reader.read();
  focused = false;
  resolve('synthetic text');
  await assert.rejects(pending, /clipboard_unfocused/);
  await assert.rejects(reader.read(), /clipboard_unfocused/);
  assert.equal(reads, 1);
});

test('unknown platform and native errors never cause a second clipboard read', async () => {
  let platform = 'invalid', failure = 'clipboard_unsupported';
  const calls = [];
  const reader = createPasteClipboard({
    focused: () => true,
    webClipboard: () => assert.fail('unexpected web read'),
    callNative: async cmd => {
      calls.push(cmd);
      if (cmd === 'config_document_platform') return platform;
      throw failure;
    },
  });
  await reader.initialize(true);
  await assert.rejects(reader.read(), /clipboard_unavailable/);
  assert.ok(calls.every(cmd => cmd === 'config_document_platform'));
  platform = 'android';
  await reader.initialize(true);
  await assert.rejects(reader.read(), /clipboard_unsupported/);
  failure = 'synthetic private diagnostic';
  await assert.rejects(reader.read(), /^Error: clipboard_unavailable$/);
  assert.doesNotMatch(clipboardPasteMessage(failure), /synthetic/);
  const denied = Object.assign(new Error('synthetic private diagnostic'), {name:'NotAllowedError'});
  assert.match(clipboardPasteMessage(denied), /未允许/);
});
