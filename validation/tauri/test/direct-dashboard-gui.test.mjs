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
  nodes['remote-page'].hidden = true;
  nodes['fixture-workbench'].hidden = true;
  nodes['remote-port'].value = '22';
  nodes['pair-device'].value = 'Fixture';

  globalThis.document = {
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
  const calls = [];

  const invoke = async (name, args = {}) => {
    calls.push({ name, args });
    if (['host_init', 'host_new', 'remote_cancel', 'remote_select', 'remote_ack'].includes(name)) return;
    if (name === 'remote_input_mode') return inputMode(args);
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
      this.textarea = new Element();
      this.focusedAs = [];
      this.parser = { registerOscHandler() {} };
    }
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
