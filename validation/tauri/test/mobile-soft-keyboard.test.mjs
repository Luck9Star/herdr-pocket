import assert from 'node:assert/strict';
import test from 'node:test';
import {createMobileKeyboard} from '../src/mobile-soft-keyboard.js';

function environment(platform = 'android') {
  const editor = {isConnected: true}, doc = {activeElement: editor, hasFocus: () => true};
  const native = [], web = [], timers = new Map();
  let now = 0, id = 0, random = 0;
  const view = {
    document: doc,
    navigator: {virtualKeyboard: {show: () => web.push('show'), hide: () => web.push('hide')}},
    performance: {now: () => now},
    crypto: {getRandomValues: bytes => bytes.fill(++random)},
    setTimeout(fn) { timers.set(++id, fn); return id; },
    clearTimeout(key) { timers.delete(key); },
  };
  const request = createMobileKeyboard({
    view, shell: {current: () => platform},
    callNative(command, args) { assert.equal(command, 'mobile_terminal_keyboard'); native.push(args); return Promise.resolve(); },
  });
  const check = args => view.__herdrPocketKeyboardGesture?.(args.ticket, args.action) === true;
  return {view, doc, editor, native, web, request, check, timers, advance: delta => { now += delta; }};
}

test('an already focused editor requests Android IME again; only its newest gesture can be consumed once', () => {
  const h = environment();
  h.request('show', h.editor, () => true);
  h.request('show', h.editor, () => true);
  const [old, latest] = h.native;
  assert.match(latest.ticket, /^[a-f0-9]{32}$/);
  assert.notEqual(old.ticket, latest.ticket);
  assert.equal(h.check(old), false);
  assert.equal(h.check({...latest, action:'hide'}), false);
  assert.equal(h.check(latest), true);
  assert.equal(h.check(latest), false);
  assert.deepEqual(h.web, []);
});

test('expired, detached, background, changed focus and revoked target all drop an Android show', () => {
  for (const change of ['expired','detached','hidden','unfocused','other','readonly','revoked','timer']) {
    const h = environment();
    let current = true;
    h.request('show', h.editor, () => current);
    if (change === 'expired') h.advance(2001);
    if (change === 'detached') h.editor.isConnected = false;
    if (change === 'hidden') h.doc.hidden = true;
    if (change === 'unfocused') h.doc.hasFocus = () => false;
    if (change === 'other') h.doc.activeElement = {};
    if (change === 'readonly') h.editor.readOnly = true;
    if (change === 'revoked') current = false;
    if (change === 'timer') for (const expire of h.timers.values()) expire();
    assert.equal(h.check(h.native[0]), false, change);
  }
});

test('hide may follow local blur, but cannot dismiss another active editor or target', () => {
  for (const state of ['body','same','new-editor','other-target']) {
    const h = environment();
    let current = true;
    h.request('hide', h.editor, () => current);
    if (state === 'body') h.doc.activeElement = {};
    if (state === 'new-editor') h.doc.activeElement = {matches: () => true};
    if (state === 'other-target') current = false;
    assert.equal(h.check(h.native[0]), state === 'body' || state === 'same', state);
  }
});

test('Web APIs run in the tap stack and do not change document focus or input permission', () => {
  const h = environment('webview');
  h.request('show', h.editor, () => false);
  h.request('show', h.editor, () => true);
  h.request('hide', h.editor, () => true);
  assert.deepEqual(h.web, ['show','hide']);
  assert.deepEqual(h.native, []);
  assert.equal(h.doc.activeElement, h.editor);
  h.view.navigator.virtualKeyboard = undefined;
  h.request('show', h.editor, () => true);
  assert.equal(h.doc.activeElement, h.editor);
});
