import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

class Element {
  constructor(id = '') {
    this.id = id;
    this.tagName = 'div';
    this.children = [];
    this.attrs = {};
    this.dataset = {};
    this.value = '';
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.events = {};
    this.textContent = '';
  }
  append(...nodes) { this.children.push(...nodes); }
  prepend(...nodes) { this.children.unshift(...nodes); }
  remove() { this.removed=true; }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(name, fn) { (this.events[name] ??= []).push(fn); }
  dispatch(name, event = {}) {
    for (const fn of this.events[name] || []) {
      fn({ target: this, preventDefault() {}, ...event });
    }
  }
  click() { this.onclick?.({ target: this, preventDefault() {} }); }
  checkValidity() { return true; }
  focus() {
    if (document.activeElement === this) return;
    document.activeElement?.blur();
    document.activeElement = this;
    this.dispatch('focus');
  }
  blur() {
    if (document.activeElement !== this) return;
    document.activeElement = null;
    this.dispatch('blur');
  }
  contains(node) { return node === this || this.all().includes(node); }
  all() { return this.children.flatMap(child => [child, ...(child.all?.() || [])]); }
  querySelector() { return null; }
  querySelectorAll(selector) {
    if (selector === 'input[type=password]') return [];
    if (selector === 'button[data-remote-key]') {
      return this.all().filter(node => node.tagName === 'button' && node.dataset.remoteKey);
    }
    if (selector === 'button') return this.all().filter(node => node.tagName === 'button');
    return [];
  }
}

const flush = () => new Promise(resolve => setImmediate(resolve));
let moduleNonce = 0;

// Exercise the real entry module while replacing only external browser/native imports.
async function importedRemote() {
  const url = new URL('../src/remote.js', import.meta.url);
  let code = await readFile(url, 'utf8');
  code = code
    .replace("import { Terminal } from '@xterm/xterm';", 'const {Terminal}=globalThis.__directGuiDeps;')
    .replace("import { invoke, Channel } from '@tauri-apps/api/core';", 'const {invoke,Channel}=globalThis.__directGuiDeps;')
    .replace(/from '(\.\/[^']+)'/g, (_match, path) => `from '${new URL(path, url).href}'`);
  const source = Buffer.from(code + `\n// fixture ${++moduleNonce}`).toString('base64');
  return import(`data:text/javascript;base64,${source}`);
}

async function setup({ inputMode = () => 1 } = {}) {
  const previous = {
    document: globalThis.document,
    window: globalThis.window,
    confirm: globalThis.confirm,
    fixture: globalThis.__directGuiDeps,
  };
  const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
  const nodes = Object.fromEntries(
    [...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], new Element(match[1])]),
  );
  nodes['remote-rejected-drafts'].hidden = true;
  nodes['remote-page'].hidden = true;
  nodes['fixture-workbench'].hidden = true;
  nodes['remote-port'].value = '22';
  nodes['pair-device'].value = 'Fixture';

  globalThis.document = {
    body: new Element('body'),
    hidden: false,
    activeElement: null,
    getElementById: id => nodes[id] ?? null,
    createElement: tag => {
      const node = new Element();
      node.tagName = tag;
      return node;
    },
    addEventListener() {},
  };
  globalThis.window = { addEventListener() {}, confirm: () => true };
  globalThis.confirm = () => true;

  const target = {
    host: 'fixture.invalid', port: 22, username: 'u',
    expectedHostKey: 'ssh-ed25519 FIXTURE',
    socketPath: '/tmp/herdr/sessions/work/herdr.sock',
    herdrPath: '/usr/bin/herdr', session: 'work',
  };
  let records = [];
  let channel = null;
  let resolveObserve;
  let rejectObserve;
  let readOverride = null;
  let sendResult = null;
  const calls = [];

  const invoke = async (name, args = {}) => {
    calls.push({ name, args });
    if (['host_init', 'host_new', 'remote_cancel', 'remote_select', 'remote_ack'].includes(name)) return;
    if (name === 'remote_input_mode') return inputMode(args);
    if (name === 'remote_input_send' && sendResult) return sendResult;
    if (name === 'remote_input_send') return {
      status: 'accepted', receipt: { requestId: 'a'.repeat(32), paneId: 'w1:p1', terminalId: 'term_a001', acceptedBytes: args.bytes.length },
    };
    if (name === 'host_list' || name === 'network_list') {
      const value = name === 'host_list'
        ? structuredClone(records)
        : { revision: 'r1', profiles: [], bindings: [], preferences: { terminalFontSize: 14 } };
      return readOverride ? readOverride(name, value) : value;
    }
    if (name === 'host_save') {
      if (!records.length) {
        records = [{
          id: 'a'.repeat(32), name: 'Fixture', enabled: true, retired: false,
          target, deviceFingerprint: null, hostFingerprint: 'host-key', networkProfileId: null,
        }];
      }
      return structuredClone(records[0]);
    }
    if (name === 'pair_create') {
      records[0].deviceFingerprint = 'device-fingerprint';
      records[0].pairingStatus = 'awaiting-host';
      return { stored: true, state: 'awaiting-host', request: 'request', fingerprint: 'device-fingerprint' };
    }
    if (name === 'pair_accept') {
      records[0].pairingStatus = 'authorized';
      return { state: 'authorized-unverified', fingerprint: 'device-fingerprint' };
    }
    if (name === 'remote_observe') {
      channel = args.onEvent;
      return new Promise((resolve, reject) => { resolveObserve = resolve; rejectObserve = reject; });
    }
    throw Error(name);
  };
  class Channel { constructor() { channel = this; } }
  let terminal;
  class Terminal {
    constructor(options) {
      terminal = this;
      this.options = options;
      this.unicode = {};
      this.textarea = new Element();
      this.focusedAs = [];
      this.modes = { bracketedPasteMode: false };
      this.parser = { registerOscHandler() {} };
    }
    loadAddon() {}
    open() {}
    dispose() {}
    focus() {
      this.focusedAs.push([this.options.disableStdin, this.textarea.attrs.inputmode]);
      this.textarea.focus();
    }
    onData(handler) { this.data = handler; }
    write(_bytes, ack) { ack(); }
  }
  globalThis.__directGuiDeps = { Terminal, invoke, Channel };
  const { initRemote } = await importedRemote();
  initRemote({ native: true, theme: { terminal: {} }, onFixture() {}, onLeaveFixture() {} });
  await flush();
  await flush();

  return {
    nodes, calls, target, get terminal() { return terminal; },
    setRead: fn => { readOverride = fn; },
    setSendResult: result => { sendResult = result; },
    updateHost: update => { Object.assign(records[0], update); },
    emit: event => channel.onmessage(event),
    finish: () => resolveObserve?.(),
    fail: () => rejectObserve?.(Error('fixture failure')),
    restore() {
      globalThis.document = previous.document;
      globalThis.window = previous.window;
      globalThis.confirm = previous.confirm;
      globalThis.__directGuiDeps = previous.fixture;
    },
  };
}

async function pairAndConnect(h) {
  const n = h.nodes;
  n['host-open-remote'].click();
  await flush();
  const fields = {
    'remote-host': h.target.host, 'remote-port': '22', 'remote-user': 'u',
    'remote-pin': h.target.expectedHostKey, 'remote-socket': h.target.socketPath,
    'remote-herdr': h.target.herdrPath, 'remote-session': 'work', 'host-save-name': 'Fixture',
  };
  for (const [key, value] of Object.entries(fields)) n[key].value = value;
  n['pair-mode'].checked = true;
  n['pair-target-review'].checked = true;
  n['pair-create'].click();
  await flush(); await flush(); await flush();
  n['pair-response'].value = JSON.stringify({
    account: 'u', host_key: 'host-key', fingerprint: 'device-fingerprint',
    status: 'authorized', request_id: 'request', issued_at: 1, expires_at: 2,
    authorization_added: true,
  });
  n['pair-preview'].click();
  n['pair-source-review'].checked = true;
  n['pair-accept'].click();
  await flush(); await flush(); await flush();
  n['remote-review'].checked = true;
  n['remote-form'].dispatch('input', { target: n['remote-review'] });
  n['remote-form'].dispatch('submit');
  await flush();
}

function publishDashboard(h, panes) {
  h.emit({ kind: 'stage', generation: 9, stage: 'authenticated' });
  h.emit({ kind: 'dashboard', generation: 9, panes });
}
function blockedPane() {
  return [{ paneId: 'w1:p1', terminalId: 'term_a001', agentStatus: 'blocked' }];
}

async function openInput(h) {
  await pairAndConnect(h);
  publishDashboard(h, blockedPane());
  h.nodes['remote-panes'].children[0].click();
  h.emit({ kind: 'frame', generation: 9, frame: { seq: 1, full: true, bytes: [65] } });
  h.emit({ kind: 'input_ready', generation: 9, unknown: false, recovery_status: 'ready' });
}

test('paired form requests an editable keyboard in the click and only sends compositions begun after permission', async () => {
  let allow;
  const h = await setup({ inputMode: () => new Promise(resolve => { allow = resolve; }) });
  try {
    await openInput(h);
    h.nodes['remote-input-direct'].click();
    assert.deepEqual(h.terminal.focusedAs, [[false, 'text']]);
    for (const event of ['keydown', 'keypress', 'beforeinput', 'input', 'paste']) {
      let prevented = false, stopped = false;
      h.terminal.textarea.dispatch(event, {
        preventDefault() { prevented = true; },
        stopImmediatePropagation() { stopped = true; },
      });
      assert.ok(prevented && stopped, event);
    }
    h.terminal.data('x');
    h.terminal.textarea.dispatch('compositionstart');
    await flush();
    allow(2);
    await flush();
    h.terminal.textarea.dispatch('compositionend');
    h.terminal.data('旧');
    assert.equal(h.calls.filter(c => c.name === 'remote_input_send').length, 0);
    h.terminal.textarea.dispatch('compositionstart');
    h.terminal.textarea.dispatch('compositionend');
    h.terminal.data('中');
    assert.deepEqual(h.calls.filter(c => c.name === 'remote_input_send').map(c => c.args.bytes), [[228, 184, 173]]);
  } finally { h.finish(); await flush(); h.restore(); }
});

for (const outcome of ['blur', 'reject', 'cancel']) {
  test(`paired form locks the keyboard when a direct request ends in ${outcome}`, async () => {
    let allow, deny;
    const h = await setup({ inputMode: args => args.mode === 'direct' ? new Promise((r, j) => { allow = r; deny = j; }) : 3 });
    try {
      await openInput(h);
      h.nodes['remote-input-direct'].click();
      await flush();
      if (outcome === 'blur') h.terminal.textarea.blur();
      if (outcome === 'cancel') h.nodes['remote-cancel'].click();
      if (outcome === 'reject') deny(Error('fixture'));
      else allow(2);
      await flush();
      assert.equal(h.terminal.options.disableStdin, true);
      assert.equal(h.terminal.textarea.attrs.inputmode, 'none');
      h.terminal.data('x');
      assert.equal(h.calls.filter(c => c.name === 'remote_input_send').length, 0);
    } finally { h.finish(); await flush(); h.restore(); }
  });
}
function summary(nodes, live = true) {
  return live
    ? nodes['host-task-board'].children.find(node => node.attrs['data-live-host-summary'])
    : nodes['host-list'].children[0].children.find(node => node.attrs['data-host-task-summary']);
}

test('normal new pairing form publishes one-shot host summary and marks it stale on pane selection and home return', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await pairAndConnect(h);
    assert.equal(h.calls.filter(call => call.name === 'remote_observe').length, 1);
    publishDashboard(h, blockedPane());
    assert.match(summary(n).textContent, /本次快照（持续更新不可用）.*会话 work.*受阻 1.*同步/);
    const pane = n['remote-panes'].children.find(node => node.textContent.startsWith('w1:p1'));
    assert.ok(pane);
    pane.click();
    await flush();
    assert.match(summary(n).textContent, /上次快照/);
    n['host-return-home'].click();
    await flush(); await flush();
    assert.match(summary(n, false).textContent, /上次快照.*受阻 1/);
    assert.equal(h.calls.filter(call => call.name === 'remote_observe').length, 1);
  } finally { h.finish(); await flush(); h.restore(); }
});

test('cancel and late dashboard cannot restore current summary', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await pairAndConnect(h);
    publishDashboard(h, blockedPane());
    n['remote-cancel'].click();
    assert.match(summary(n).textContent, /上次快照/);
    h.emit({ kind: 'dashboard', generation: 9, panes: [] });
    assert.match(summary(n).textContent, /上次快照.*受阻 1/);
  } finally { h.finish(); await flush(); h.restore(); }
});

test('failed direct connection preserves prior snapshot as stale without auto retry', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await pairAndConnect(h);
    publishDashboard(h, blockedPane());
    h.fail();
    await flush(); await flush();
    assert.match(summary(n).textContent, /上次快照.*受阻 1/);
    assert.equal(h.calls.filter(call => call.name === 'remote_observe').length, 1);
  } finally { h.finish(); await flush(); h.restore(); }
});

test('temporary manual form cannot claim a saved paired host summary', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await pairAndConnect(h);
    publishDashboard(h, []);
    n['remote-cancel'].click();
    h.finish();
    await flush(); await flush();
    n['pair-mode'].checked = false;
    n['remote-private-key'].value = 'fixture-only';
    n['remote-review'].checked = true;
    n['remote-form'].dispatch('input', { target: n['remote-review'] });
    n['remote-form'].dispatch('submit');
    await flush();
    h.emit({ kind: 'stage', generation: 10, stage: 'authenticated' });
    h.emit({ kind: 'dashboard', generation: 10, panes: blockedPane() });
    assert.match(summary(n).textContent, /上次快照.*受阻 0/);
  } finally { h.finish(); await flush(); h.restore(); }
});

test('dashboard before native authentication never claims a saved host summary', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await pairAndConnect(h);
    h.emit({ kind: 'dashboard', generation: 9, panes: blockedPane() });
    assert.match(summary(n).textContent, /任务状态未知/);
  } finally { h.finish(); await flush(); h.restore(); }
});

test('return home directly after snapshot preserves it only as stale', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await pairAndConnect(h);
    publishDashboard(h, []);
    n['host-return-home'].click();
    await flush(); await flush();
    assert.match(summary(n, false).textContent, /上次快照.*受阻 0/);
  } finally { h.finish(); await flush(); h.restore(); }
});

test('older catalog response cannot overwrite newer host identity or name', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await pairAndConnect(h);
    publishDashboard(h, blockedPane());
    let networkReads = 0, hostReads = 0, release;
    const wait = new Promise(resolve => { release = resolve; });
    h.setRead(async (name, value) => {
      if (name === 'host_list') {
        hostReads++;
        if (hostReads === 2) {
          value[0].name = 'New identity';
          value[0].deviceFingerprint = 'replacement-device';
        }
        return value;
      }
      if (++networkReads === 1) await wait;
      return value;
    });
    n['host-return-home'].click();
    await flush();
    n['host-return-home'].click();
    await flush(); await flush();
    assert.equal(n['host-list'].children[0].children[0].textContent, 'New identity');
    assert.match(summary(n, false).textContent, /任务状态未知/);
    release();
    await flush(); await flush();
    assert.equal(n['host-list'].children[0].children[0].textContent, 'New identity');
    assert.match(summary(n, false).textContent, /任务状态未知/);
  } finally { h.finish(); await flush(); h.restore(); }
});

test('catalog failure restores historical summary only as stale and ignores late old dashboard', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await pairAndConnect(h);
    publishDashboard(h, blockedPane());
    h.setRead(async (name, value) => {
      if (name === 'network_list') throw Error('unavailable');
      return value;
    });
    n['host-return-home'].click();
    await flush(); await flush();
    assert.equal(n['host-list'].children.length, 0);
    h.setRead(null);
    n['host-return-home'].click();
    await flush(); await flush();
    assert.match(summary(n, false).textContent, /上次快照.*受阻 1/);
    h.emit({ kind: 'dashboard', generation: 9, panes: [] });
    assert.match(summary(n, false).textContent, /上次快照.*受阻 1/);
  } finally { h.finish(); await flush(); h.restore(); }
});

function dispatchPaste(element, text) {
  let prevented = false, stopped = false;
  element.dispatch('paste', {
    preventDefault() { prevented = true; },
    stopImmediatePropagation() { stopped = true; },
    clipboardData: { getData: () => text },
  });
  assert.equal(prevented, true);
  assert.equal(stopped, true);
}

async function readyDirectPaste(h) {
  await openInput(h);
  const draft = h.nodes['remote-input-draft'];
  draft.value = '原草稿';
  draft.dispatch('input');
  h.nodes['remote-input-direct'].click();
  await flush(); await flush();
}

for (const [choice, expected] of [
  ['append', '原草稿新\n行'],
  ['replace', '新\n行'],
  ['cancel', '原草稿'],
]) {
  test(`paired direct paste ${choice} reviews before changing local draft`, async () => {
    const h = await setup(), n = h.nodes;
    try {
      await readyDirectPaste(h);
      dispatchPaste(h.terminal.textarea, '新\n行');
      await flush(); await flush();
      assert.equal(n['remote-paste-review'].hidden, false);
      assert.equal(n['remote-input-draft'].value, '原草稿');
      assert.match(n['remote-paste-preview'].textContent, /⏎/);
      n[`remote-paste-${choice}`].click();
      assert.equal(n['remote-input-draft'].value, expected);
      assert.equal(n['remote-paste-review'].hidden, true);
      assert.equal(h.calls.filter(call => call.name === 'remote_input_send').length, 0);
    } finally { h.finish(); await flush(); h.restore(); }
  });
}

test('draft textarea paste is intercepted and previewed without overwriting current draft', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await openInput(h);
    const draft = n['remote-input-draft'];
    draft.value = '原草稿'; draft.dispatch('input');
    n['remote-input-draft-mode'].click();
    await flush(); await flush();
    dispatchPaste(draft, '新');
    await flush(); await flush();
    assert.equal(n['remote-paste-review'].hidden, false);
    assert.equal(draft.value, '原草稿');
    n['remote-paste-append'].click();
    assert.equal(draft.value, '原草稿新');
    assert.equal(h.calls.filter(call => call.name === 'remote_input_send').length, 0);
  } finally { h.finish(); await flush(); h.restore(); }
});

test('paste preview makes control and bidi characters visible and enforces merged UTF-8 limit', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await readyDirectPaste(h);
    dispatchPaste(h.terminal.textarea, '\u001b\u202e中');
    await flush(); await flush();
    assert.match(n['remote-paste-preview'].textContent, /\\u\{1b\}/);
    assert.match(n['remote-paste-preview'].textContent, /\\u\{202e\}/);
    n['remote-paste-cancel'].click();
    n['remote-input-draft'].value = 'A'.repeat(4095);
    n['remote-input-draft'].dispatch('input');
    n['remote-input-draft-mode'].click();
    await flush(); await flush();
    dispatchPaste(n['remote-input-draft'], '中');
    await flush(); await flush();
    assert.equal(n['remote-paste-append'].disabled, true);
    assert.equal(document.activeElement, n['remote-paste-replace']);
    assert.match(n['remote-paste-target'].textContent, /w1:p1.*term_a001/);
    assert.equal(n['remote-input-draft'].value, 'A'.repeat(4095));
    assert.match(n['remote-paste-status'].textContent, /4096/);
    n['remote-paste-replace'].click();
    assert.equal(n['remote-input-draft'].value, '中');
    assert.equal(h.calls.filter(call => call.name === 'remote_input_send').length, 0);
  } finally { h.finish(); await flush(); h.restore(); }
});

test('composition in progress blocks direct and draft paste reviews', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await readyDirectPaste(h);
    h.terminal.textarea.dispatch('compositionstart');
    dispatchPaste(h.terminal.textarea, '新');
    await flush();
    assert.equal(n['remote-paste-review'].hidden, true);
    assert.equal(n['remote-input-draft'].value, '原草稿');
    h.terminal.textarea.dispatch('compositionend');
    n['remote-input-draft-mode'].click();
    await flush(); await flush();
    n['remote-input-draft'].dispatch('compositionstart');
    dispatchPaste(n['remote-input-draft'], '新');
    await flush();
    assert.equal(n['remote-paste-review'].hidden, true);
    assert.equal(n['remote-input-draft'].value, '原草稿');
    n['remote-input-draft'].dispatch('compositionend');
  } finally { h.finish(); await flush(); h.restore(); }
});

test('stopping while observe reset is pending prevents a late paste review', async () => {
  let release;
  const h = await setup({ inputMode: args => args.mode === 'observe'
    ? new Promise(resolve => { release = resolve; }) : 2 });
  const n = h.nodes;
  try {
    await readyDirectPaste(h);
    dispatchPaste(h.terminal.textarea, '新');
    await flush();
    n['remote-cancel'].click();
    release(3);
    await flush(); await flush();
    assert.equal(n['remote-paste-review'].hidden, true);
    assert.equal(n['remote-input-draft'].value, '原草稿');
    n['remote-paste-replace'].click();
    assert.equal(n['remote-input-draft'].value, '原草稿');
    assert.equal(h.calls.filter(call => call.name === 'remote_input_send').length, 0);
  } finally { h.finish(); await flush(); h.restore(); }
});

test('focus leaving paste review revokes its buttons without touching the draft', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await readyDirectPaste(h);
    dispatchPaste(h.terminal.textarea, '新');
    await flush(); await flush();
    n['remote-paste-review'].dispatch('focusout', { relatedTarget: new Element('outside') });
    assert.equal(n['remote-paste-review'].hidden, true);
    n['remote-paste-replace'].click();
    assert.equal(n['remote-input-draft'].value, '原草稿');
  } finally { h.finish(); await flush(); h.restore(); }
});

test('draft edits and restoration during a pending review invalidate its original version', async () => {
  let release;
  const h = await setup({ inputMode: args => args.mode === 'observe'
    ? new Promise(resolve => { release = resolve; }) : 2 });
  const n = h.nodes;
  try {
    await readyDirectPaste(h);
    dispatchPaste(h.terminal.textarea, '新');
    await flush();
    n['remote-input-draft'].value = '改动';
    n['remote-input-draft'].dispatch('input');
    n['remote-input-draft'].value = '原草稿';
    n['remote-input-draft'].dispatch('input');
    release(3);
    await flush(); await flush();
    assert.equal(n['remote-paste-review'].hidden, true);
    n['remote-paste-replace'].click();
    assert.equal(n['remote-input-draft'].value, '原草稿');
    assert.equal(h.calls.filter(call => call.name === 'remote_input_send').length, 0);
  } finally { h.finish(); await flush(); h.restore(); }
});

test('applying a paste changes only the local draft until separate draft permission and send confirmation', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await readyDirectPaste(h);
    dispatchPaste(h.terminal.textarea, '新');
    await flush(); await flush();
    n['remote-paste-append'].click();
    assert.equal(n['remote-input-draft'].value, '原草稿新');
    assert.equal(h.calls.filter(call => call.name === 'remote_input_send').length, 0);
    n['remote-input-preview'].click();
    assert.equal(n['remote-input-preview-area'].hidden, true);
    n['remote-input-draft-mode'].click();
    await flush(); await flush();
    n['remote-input-preview'].click();
    assert.equal(n['remote-input-preview-area'].hidden, false);
    n['remote-input-confirm'].click();
    await flush();
    assert.equal(h.calls.filter(call => call.name === 'remote_input_send').length, 1);
  } finally { h.finish(); await flush(); h.restore(); }
});

test('returning home revokes an open paste review without changing the saved draft', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await readyDirectPaste(h);
    dispatchPaste(h.terminal.textarea, '新');
    await flush(); await flush();
    assert.equal(n['remote-paste-review'].hidden, false);
    n['host-return-home'].click();
    await flush();
    assert.equal(n['remote-paste-review'].hidden, true);
    n['remote-paste-replace'].click();
    assert.equal(n['remote-input-draft'].value, '原草稿');
    assert.equal(h.calls.filter(call => call.name === 'remote_input_send').length, 0);
  } finally { h.finish(); await flush(); h.restore(); }
});

async function reconnectTo(h, pane) {
  h.finish();
  await flush();
  h.nodes['remote-review'].checked = true;
  h.nodes['remote-form'].dispatch('input', { target: h.nodes['remote-review'] });
  h.nodes['remote-form'].dispatch('submit');
  await flush();
  publishDashboard(h, [pane]);
  h.nodes['remote-panes'].children[0].click();
  h.emit({ kind: 'frame', generation: 9, frame: { seq: 1, full: true, bytes: [65] } });
  h.emit({ kind: 'input_ready', generation: 9, unknown: false, recovery_status: 'ready' });
}

test('direct drafts follow the reviewed device and exact pane and terminal across reconnects', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await openInput(h);
    n['remote-input-draft'].value = '第一终端草稿';
    n['remote-input-draft'].dispatch('input');
    const first = blockedPane()[0];
    const otherPane = { paneId: 'w1:p2', terminalId: 'term_a002', agentStatus: 'idle' };
    const otherTerminal = { ...first, terminalId: 'term_a003' };
    await reconnectTo(h, otherPane);
    assert.equal(n['remote-input-draft'].value, '');
    n['remote-input-draft'].value = '第二终端草稿';
    await reconnectTo(h, otherTerminal);
    assert.equal(n['remote-input-draft'].value, '');
    await reconnectTo(h, first);
    assert.equal(n['remote-input-draft'].value, '第一终端草稿');
    h.updateHost({ deviceFingerprint: 'different-device' });
    n['host-save'].click();
    await flush(); await flush();
    await reconnectTo(h, first);
    assert.equal(n['remote-input-draft'].value, '');
  } finally { h.finish(); await flush(); h.restore(); }
});

test('an unknown draft send never returns to the sendable editor', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await openInput(h);
    n['remote-input-draft'].value = '不重放';
    n['remote-input-draft'].dispatch('input');
    n['remote-input-draft-mode'].click();
    await flush(); await flush();
    h.setSendResult({ status: 'unknown' });
    n['remote-input-preview'].click();
    n['remote-input-confirm'].click();
    await flush();
    assert.equal(n['remote-input-draft'].value, '');
    await reconnectTo(h, blockedPane()[0]);
    assert.equal(n['remote-input-draft'].value, '');
    assert.equal(h.calls.filter(call => call.name === 'remote_input_send').length, 1);
  } finally { h.finish(); await flush(); h.restore(); }
});

async function submitDraft(h, value) {
  const n=h.nodes;
  n['remote-input-draft'].value=value;
  n['remote-input-draft'].dispatch('input');
  n['remote-input-draft-mode'].click();
  await flush(); await flush();
  n['remote-input-preview'].click();
  n['remote-input-confirm'].click();
}

test('definite rejection restores untouched original draft', async () => {
  const h=await setup(), n=h.nodes;
  try {
    await openInput(h);
    h.setSendResult({status:'rejected'});
    await submitDraft(h,'被拒原文');
    await flush();
    assert.equal(n['remote-input-draft'].value,'被拒原文');
    assert.equal(n['remote-rejected-drafts'].hidden,true);
  } finally {h.finish();await flush();h.restore();}
});

test('recovery-required rejection keeps a read-only copy and never overwrites edits', async () => {
  const h=await setup(), n=h.nodes;
  try {
    await openInput(h);
    let resolve;
    h.setSendResult(new Promise(r=>{resolve=r;}));
    await submitDraft(h,'待找回原文');
    n['remote-input-draft'].value='新编辑';
    n['remote-input-draft'].dispatch('input');
    resolve({status:'rejected',recoveryRequired:true});
    await flush();
    assert.equal(n['remote-input-draft'].value,'新编辑');
    const label=n['remote-rejected-drafts'].children[0];
    assert.match(label.textContent,/w1:p1.*term_a001/);
    assert.equal(label.children[0].value,'待找回原文');
    assert.equal(label.children[0].readOnly,true);
  } finally {h.finish();await flush();h.restore();}
});

test('late definite rejection belongs to the original target, never the new draft', async () => {
  const h=await setup(), n=h.nodes;
  try {
    await openInput(h);
    let resolve;
    h.setSendResult(new Promise(r=>{resolve=r;}));
    await submitDraft(h,'旧目标原文');
    await reconnectTo(h,{paneId:'w1:p2',terminalId:'term_a002',agentStatus:'idle'});
    n['remote-input-draft'].value='新目标草稿';
    n['remote-input-draft'].dispatch('input');
    resolve({status:'rejected'});
    await flush();
    assert.equal(n['remote-input-draft'].value,'新目标草稿');
    const label=n['remote-rejected-drafts'].children[0];
    assert.match(label.textContent,/w1:p1.*term_a001/);
    assert.equal(label.children[0].value,'旧目标原文');
  } finally {h.finish();await flush();h.restore();}
});

test('accepted text does not reappear as sendable or read-only rejected text', async () => {
  const h=await setup(), n=h.nodes;
  try {
    await openInput(h);
    await submitDraft(h,'已接收文本');
    await flush();
    assert.equal(n['remote-input-draft'].value,'');
    assert.equal(n['remote-rejected-drafts'].hidden,true);
    await reconnectTo(h,blockedPane()[0]);
    assert.equal(n['remote-input-draft'].value,'');
  } finally {h.finish();await flush();h.restore();}
});


test('proven input_stale error restores untouched draft', async () => {
  const h=await setup(), n=h.nodes;
  try {
    await openInput(h);
    let reject;
    h.setSendResult(new Promise((_resolve,r)=>{reject=r;}));
    await submitDraft(h,'未发送原文');
    reject('input_stale');
    await flush();
    assert.equal(n['remote-input-draft'].value,'未发送原文');
    assert.equal(n['remote-rejected-drafts'].hidden,true);
  } finally {h.finish();await flush();h.restore();}
});


test('full recovery area refuses sending until an explicit removal, retaining every exact text', async () => {
  const h=await setup(), n=h.nodes;
  try {
    await openInput(h);
    for(let i=0;i<32;i++) {
      let resolve;
      h.setSendResult(new Promise(r=>{resolve=r;}));
      await submitDraft(h,`未发送 ${i}`);
      n['remote-input-draft'].value=`新草稿 ${i}`;
      n['remote-input-draft'].dispatch('input');
      resolve({status:'rejected'});
      await flush();
    }
    assert.equal(n['remote-rejected-drafts'].children.length,64);
    const oldRemove=n['remote-rejected-drafts'].children[1];
    assert.equal(n['remote-rejected-drafts'].children[0].children[0].value,'未发送 0');
    const before=h.calls.filter(call=>call.name==='remote_input_send').length;
    await submitDraft(h,'等待容量');
    assert.equal(h.calls.filter(call=>call.name==='remote_input_send').length,before);
    assert.equal(n['remote-input-draft'].value,'等待容量');
    assert.match(n['remote-input-status'].textContent,/已满/);
    oldRemove.click();
    assert.equal(n['remote-rejected-drafts'].children.length,62);
    oldRemove.click();
    assert.equal(n['remote-rejected-drafts'].children.length,62);
    let resolve;
    h.setSendResult(new Promise(r=>{resolve=r;}));
    await submitDraft(h,'容量已释放');
    assert.equal(h.calls.filter(call=>call.name==='remote_input_send').length,before+1);
    n['remote-input-draft'].value='继续编辑';
    n['remote-input-draft'].dispatch('input');
    resolve({status:'rejected'});
    await flush();
    assert.equal(n['remote-rejected-drafts'].children.length,64);
    assert.equal(n['remote-rejected-drafts'].children[62].children[0].value,'容量已释放');
  } finally {h.finish();await flush();h.restore();}
});


test('read-only records distinguish same pane across reviewed hosts', async () => {
  const h=await setup(), n=h.nodes;
  try {
    await openInput(h);
    for(const host of ['fixture.invalid','other.invalid']) {
      if(host==='other.invalid') {
        n['remote-host'].value=host;
        await reconnectTo(h,blockedPane()[0]);
      }
      let resolve;
      h.setSendResult(new Promise(r=>{resolve=r;}));
      await submitDraft(h,`内容 ${host}`);
      n['remote-input-draft'].value='新文字';
      n['remote-input-draft'].dispatch('input');
      resolve({status:'rejected'});
      await flush();
    }
    const labels=n['remote-rejected-drafts'].children.filter(node=>node.tagName==='label');
    assert.equal(labels.length,2);
    assert.match(labels[0].textContent,/fixture\.invalid.*会话 work.*w1:p1.*term_a001/);
    assert.match(labels[1].textContent,/手动连接第 .*other\.invalid.*会话 work.*w1:p1.*term_a001/);
    assert.equal(labels[0].children[0].value,'内容 fixture.invalid');
    assert.equal(labels[1].children[0].value,'内容 other.invalid');
  } finally {h.finish();await flush();h.restore();}
});

test('late old send cannot block or unlock the new connection send owner', async () => {
  const h=await setup(), n=h.nodes;
  try {
    await openInput(h);
    let resolveA, resolveB;
    h.setSendResult(new Promise(resolve=>{resolveA=resolve;}));
    await submitDraft(h,'旧目标文本');
    assert.equal(h.calls.filter(call=>call.name==='remote_input_send').length,1);

    await reconnectTo(h,{paneId:'w1:p2',terminalId:'term_a002',agentStatus:'idle'});
    h.setSendResult(new Promise(resolve=>{resolveB=resolve;}));
    await submitDraft(h,'新目标文本');
    assert.equal(h.calls.filter(call=>call.name==='remote_input_send').length,2);

    resolveA({status:'rejected'});
    await flush();
    const oldRecord=n['remote-rejected-drafts'].children[0];
    assert.match(oldRecord.textContent,/w1:p1.*term_a001/);
    assert.equal(oldRecord.children[0].value,'旧目标文本');

    n['remote-input-draft'].value='不可并发提交';
    n['remote-input-draft'].dispatch('input');
    n['remote-input-preview'].click();
    n['remote-input-confirm'].click();
    assert.equal(h.calls.filter(call=>call.name==='remote_input_send').length,2);
    assert.equal(n['remote-input-draft'].value,'不可并发提交');
    resolveB({status:'accepted',receipt:{requestId:'b'.repeat(32),paneId:'w1:p2',terminalId:'term_a002',acceptedBytes:new TextEncoder().encode('新目标文本').length}});
    await flush();
    assert.equal(n['remote-input-draft'].value,'不可并发提交');
    assert.equal(n['remote-rejected-drafts'].children.length,2);
  } finally {h.finish();await flush();h.restore();}
});


test('paired entry revokes direct input during selection and does not restore it on close', async () => {
  const h=await setup(),oldStyle=globalThis.getComputedStyle;
  try {
    document.querySelectorAll=()=>[];document.documentElement={clientWidth:100,clientHeight:100};document.elementsFromPoint=()=>[h.terminal.element];globalThis.getComputedStyle=()=>({});
    await openInput(h);h.terminal.element={contains:()=>true,querySelector:()=>({parentElement:null,getBoundingClientRect:()=>({left:0,top:0,width:10,height:10})})};h.terminal.cols=1;h.terminal.rows=1;h.terminal.buffer={active:{viewportY:0,getLine:()=>({length:1,isWrapped:false,getCell:()=>({getChars:()=> 'A',getWidth:()=>1}),translateToString:()=> 'A'})}};
    h.nodes['remote-input-direct'].click();await flush();
    const select=h.nodes['remote-result'].all().find(n=>n.textContent==='选择终端文本');assert.ok(select);
    let prevented=false;select.onpointerdown({preventDefault(){prevented=true;}});assert.equal(prevented,true);select.click();
    const panel=document.body.children.at(-1);assert.equal(panel.attrs['aria-label'],'选择终端文本');assert.equal(h.terminal.options.disableStdin,true);
    h.nodes['remote-input-direct'].click();h.terminal.textarea.focus();h.terminal.data('x');await flush();
    assert.equal(h.calls.filter(c=>c.name==='remote_input_send').length,0);
    assert.equal(h.calls.filter(c=>c.name==='remote_input_mode' && c.args.mode==='direct').length,1);
    panel.children[2].focus();panel.children.at(-1).children.at(-1).click();assert.equal(panel.removed,true);assert.notEqual(document.activeElement,h.terminal.textarea);
    h.terminal.data('x');await flush();assert.equal(h.calls.filter(c=>c.name==='remote_input_send').length,0);
  } finally {globalThis.getComputedStyle=oldStyle;h.restore();}
});
