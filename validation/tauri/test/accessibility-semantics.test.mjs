import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {blockedTargetList} from '../src/blocked-target-list.js';
import {HostDashboardSummary} from '../src/host-dashboard-summary.js';

// docs/08-ui-design-plan.md:94 —— 状态不只靠颜色；按钮有可读名称，禁用给原因，焦点可见，触控空间可用。
// 本文件断言 Tauri 壳动态渲染 DOM 的上述语义；焦点与 44px 触控由 style.css 全局规则覆盖，不在此重复。

class StubElement {
  constructor() { this.children = []; this.dataset = {}; this.attrs = {}; }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute(key, value) { this.attrs[key] = value; }
}

test('blocked target list keeps readable names and textual state without color-only cues', () => {
  const old = globalThis.document;
  globalThis.document = { createElement: () => new StubElement() };
  try {
    const host = {id:'h', enabled:true, target:{session:'original'}, deviceFingerprint:'device'};
    const store = new HostDashboardSummary(), source = {};
    const render = () => blockedTargetList({store, host, onOpen() {}});
    const unknown = render();
    assert.equal(unknown.attrs['aria-label'], '受阻窗格清单');
    assert.match(unknown.children[0].textContent, /\S/);
    store.begin(host, source);
    store.publish(host, source, {panes:[{paneId:'w1:p1', terminalId:'term_a001', agentStatus:'blocked'}], capturedAt:1000, phase:'fresh'});
    const fresh = render();
    const freshButton = fresh.children[1];
    assert.match(freshButton.textContent, /观察受阻目标/);
    assert.match(freshButton.textContent, /w1:p1/);
    assert.match(freshButton.textContent, /term_a001/);
    store.invalidateHost(host.id);
    const staleButton = render().children[1];
    assert.match(staleButton.textContent, /重新核查此目标/, '受阻清单的新鲜/陈旧状态必须以文字区分，不能只靠颜色');
  } finally { globalThis.document = old; }
});

class Element {
  constructor(id = '') {
    this.id = id;
    this.isConnected = true;
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
  remove() { this.removed = true; }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(name, fn) { (this.events[name] ??= []).push(fn); }
  dispatch(name, event = {}) {
    for (const fn of this.events[name] || []) fn({ target: this, preventDefault() {}, ...event });
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
    if (selector === 'button[data-remote-key]') return this.all().filter(node => node.tagName === 'button' && node.dataset.remoteKey);
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
    .replace("import {createUnicodeTerminal} from './terminal-unicode.js';", 'const createUnicodeTerminal=(Terminal,options)=>new Terminal(options);')
    .replace("import { Terminal } from '@xterm/xterm';", 'const {Terminal}=globalThis.__a11yDeps;')
    .replace("import { invoke, Channel } from '@tauri-apps/api/core';", 'const {invoke,Channel}=globalThis.__a11yDeps;')
    .replace(/from '(\.\/[^']+)'/g, (_match, path) => `from '${new URL(path, url).href}'`);
  const source = Buffer.from(code + `\n// fixture ${++moduleNonce}`).toString('base64');
  return import(`data:text/javascript;base64,${source}`);
}

const profilesFixture = JSON.parse(await readFile(new URL('../../shared/connection-profile-v1.json', import.meta.url), 'utf8'));
function pairingCameraFixture(now = Math.floor(Date.now() / 1000)) {
  const request = {version: 2, type: 'pairing-public-key-request', request_id: 'c'.repeat(32), account: 'u', host_key: 'host-key', device: 'Fixture', public_key: JSON.parse(profilesFixture.valid[0].raw).expectedHostKey, issued_at: now, expires_at: now + 300};
  const response = {version: 2, type: 'pairing-binding-response', request_id: request.request_id, account: request.account, host_key: request.host_key, fingerprint: 'device-fingerprint', issued_at: now, expires_at: now + 200, status: 'authorized', authorization_added: true};
  return {request: JSON.stringify(request), response: JSON.stringify(response), expires: request.expires_at};
}

async function setup({ hosts = [] } = {}) {
  const previous = { document: globalThis.document, window: globalThis.window, fixture: globalThis.__a11yDeps };
  const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
  const nodes = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], new Element(match[1])]));
  nodes['remote-rejected-drafts'].hidden = true;
  nodes['remote-page'].hidden = true;
  nodes['fixture-workbench'].hidden = true;
  nodes['remote-port'].value = '22';
  nodes['remote-canvas'].value = '80x24';
  nodes['pair-device'].value = 'Fixture';
  const viewport = new Element('remote-viewport');
  Object.assign(viewport, {clientWidth: 320, scrollWidth: 800, clientHeight: 200, scrollHeight: 400, scrollLeft: 0, scrollTop: 0});
  nodes['remote-terminal'].parentElement = viewport;

  const documentEvents = {}, windowEvents = {};
  globalThis.document = {
    body: new Element('body'), hidden: false, hasFocus: () => true, activeElement: null,
    getElementById: id => nodes[id] ?? null,
    createElement: tag => { const node = new Element(); node.tagName = tag; return node; },
    addEventListener(name, fn) { (documentEvents[name] ??= []).push(fn); },
  };
  globalThis.window = { addEventListener(name, fn) { (windowEvents[name] ??= []).push(fn); } };

  const target = {host: 'fixture.invalid', port: 22, username: 'u', expectedHostKey: 'ssh-ed25519 FIXTURE', socketPath: '/tmp/herdr/sessions/work/herdr.sock', herdrPath: '/usr/bin/herdr', session: 'work'};
  const baseHost = id => ({id, name: 'Host', enabled: true, retired: false, requiresNetworkBinding: false, provider: 'direct', deviceFingerprint: 'device-fingerprint', pairingStatus: null, hostFingerprint: 'host-key', networkProfileId: null, target: structuredClone(target)});
  let records = hosts.map(([id, update]) => Object.assign(baseHost(id), update));
  const fixture = pairingCameraFixture();
  let channel = null, resolveObserve;
  const calls = [];
  const invoke = async (name, args = {}) => {
    calls.push({name, args});
    if (['host_init', 'host_new', 'remote_cancel', 'remote_select', 'remote_ack'].includes(name)) return;
    if (name === 'pair_scan_response') return '';
    if (name === 'remote_input_mode') return 1;
    if (name === 'remote_input_send') return {status: 'accepted', receipt: {requestId: 'a'.repeat(32), paneId: 'w1:p1', terminalId: 'term_a001', acceptedBytes: args.bytes.length}};
    if (name === 'host_list') return structuredClone(records);
    if (name === 'network_list') return {revision: 'r1', profiles: [], bindings: [], preferences: {terminalFontSize: 14}};
    if (name === 'host_select') return structuredClone(records.find(h => h.id === args.id));
    if (name === 'host_restore') return {state: records.find(x => x.id === args.id)?.pairingStatus === 'revoked' ? 'revoked' : 'authorized-unverified', fingerprint: 'device-fingerprint', request: fixture.request};
    if (name === 'host_save') {
      if (!records.length) records = [Object.assign(baseHost('a'.repeat(32)), {name: args.name || 'Fixture', target: args.config})];
      return structuredClone(records[0]);
    }
    if (name === 'pair_create') {
      records[0].deviceFingerprint = 'device-fingerprint';
      records[0].pairingStatus = 'awaiting-host';
      return {stored: true, state: 'awaiting-host', request: fixture.request, fingerprint: 'device-fingerprint'};
    }
    if (name === 'pair_accept') {
      const revoked = JSON.parse(args.response).status === 'revoked';
      records[0].pairingStatus = revoked ? 'revoked' : 'authorized';
      return {state: revoked ? 'revoked' : 'authorized-unverified', fingerprint: 'device-fingerprint', stored: true};
    }
    if (name === 'remote_observe') { channel = args.onEvent; return new Promise(resolve => { resolveObserve = resolve; }); }
    throw Error(name);
  };
  class Channel { constructor() { channel = this; } }
  class Terminal {
    constructor(options) {
      this.options = options;
      this.cols = options.cols; this.rows = options.rows;
      this.unicode = {};
      this.textarea = new Element();
      this.modes = {bracketedPasteMode: false};
      this.parser = {registerOscHandler() {}};
    }
    resize() {} reset() {} open() {} dispose() {}
    focus() { this.textarea.focus(); }
    onData() {}
    write(_bytes, ack) { ack(); }
  }
  globalThis.__a11yDeps = {Terminal, invoke, Channel};
  const {initRemote} = await importedRemote();
  initRemote({native: true, theme: {terminal: {}}, onFixture() {}, onLeaveFixture() {}});
  await flush(); await flush();
  return {
    nodes, calls,
    emit: event => channel.onmessage(event),
    finish: () => resolveObserve?.(),
    restore() {
      globalThis.document = previous.document;
      globalThis.window = previous.window;
      globalThis.__a11yDeps = previous.fixture;
    },
  };
}

const hostCard = (list, id) => list.children.find(card => card.dataset.hostId === id);
const describedText = (node, root) => {
  const id = node.attrs['aria-describedby'];
  assert.ok(id, `expected aria-describedby on ${node.textContent || node.id}`);
  const found = root.all().find(element => element.id === id) || root[id];
  assert.ok(found, `aria-describedby target "${id}" not found`);
  return found.textContent;
};

test('host cards give every action a readable name and attach disabled reasons for screen readers', async () => {
  const alpha = 'a'.repeat(32), beta = 'b'.repeat(32), gamma = 'c'.repeat(32);
  const h = await setup({hosts: [
    [alpha, {name: 'Alpha'}],
    [beta, {name: 'Beta', enabled: false}],
    [gamma, {name: 'Gamma', pairingStatus: 'revoked'}],
  ]});
  try {
    const list = h.nodes['host-list'];
    assert.equal(list.children.length, 3);
    const actionsOf = card => card.children.find(node => node.className === 'saved-host-actions');
    for (const card of list.children) {
      for (const button of actionsOf(card).children) {
        assert.match(button.textContent, /\S/, 'docs/08:94 按钮有可读名称——主机卡动作按钮必须带可读名称');
      }
      const rename = card.children.find(node => node.tagName === 'input');
      assert.match(rename.attrs['aria-label'], /重命名/);
    }
    const betaCard = hostCard(list, beta), gammaCard = hostCard(list, gamma);
    const buttonByLabel = (card, label) => actionsOf(card).children.find(b => b.textContent === label || b.textContent.startsWith(label));
    const open = buttonByLabel(betaCard, '打开');
    assert.equal(open.disabled, true);
    assert.match(describedText(open, betaCard), /已停用/, 'docs/08:94 禁用给原因——读屏须能读到“打开”被禁用的原因');
    const openTab = buttonByLabel(gammaCard, '新终端标签');
    assert.equal(openTab.disabled, true);
    assert.match(describedText(openTab, gammaCard), /撤销/);
    const remove = buttonByLabel(gammaCard, '移除');
    assert.equal(remove.attrs['aria-describedby'], `host-card-detail-${gamma}`);
    for (const tab of h.nodes['host-tabs'].children) {
      assert.match(tab.textContent, /\S/);
      assert.ok(['true', 'false'].includes(tab.attrs['aria-pressed']), '主机标签的选中状态须有非颜色语义标识');
    }
  } finally { h.restore(); }
});

test('paste review buttons point their disabled reason text to screen readers', async () => {
  const h = await setup();
  try {
    assert.ok(h.nodes['remote-paste-status'], 'remote-paste-status 节点必须存在');
    assert.equal(h.nodes['remote-paste-append'].attrs['aria-describedby'], 'remote-paste-status');
    assert.equal(h.nodes['remote-paste-replace'].attrs['aria-describedby'], 'remote-paste-status');
  } finally { h.restore(); }
});

async function pairAndConnect(h) {
  const n = h.nodes;
  n['host-open-remote'].click();
  await flush();
  const fields = {
    'remote-host': 'fixture.invalid', 'remote-port': '22', 'remote-user': 'u',
    'remote-pin': 'ssh-ed25519 FIXTURE', 'remote-socket': '/tmp/herdr/sessions/work/herdr.sock',
    'remote-herdr': '/usr/bin/herdr', 'remote-session': 'work', 'host-save-name': 'Fixture',
  };
  for (const [key, value] of Object.entries(fields)) n[key].value = value;
  n['pair-mode'].checked = true;
  n['pair-target-review'].checked = true;
  n['pair-create'].click();
  await flush(); await flush(); await flush();
  const request = JSON.parse(n['pair-request'].value);
  n['pair-response'].value = pairingCameraFixture().response;
  n['pair-preview'].click();
  n['pair-source-review'].checked = true;
  n['pair-accept'].click();
  await flush(); await flush(); await flush();
  n['remote-review'].checked = true;
  n['remote-form'].dispatch('input', {target: n['remote-review']});
  n['remote-form'].dispatch('submit');
  await flush();
}

test('pane board buttons read their phase reason and carry textual pane status', async () => {
  const h = await setup();
  try {
    await pairAndConnect(h);
    const panes = h.nodes['remote-panes'];
    const gen = h.calls.find(call => call.name === 'remote_observe').args.clientGeneration;
    const paneButton = () => panes.children.find(node => node.tagName === 'button' && node.textContent.startsWith('w1:p1'));
    const newTabButton = () => panes.children.find(node => node.tagName === 'button' && node.textContent.startsWith('在新标签打开'));
    h.emit({kind: 'observation', generation: gen, snapshot: {epoch: 1, phase: 'starting'}});
    h.emit({kind: 'dashboard_watch', generation: gen, update: {epoch: 1, revision: 1, phase: 'fresh', reason: 'fixture', panes: [{paneId: 'w1:p1', terminalId: 'term_a001', agentStatus: 'blocked'}]}});
    const fresh = panes.children[0];
    assert.equal(fresh.attrs['role'], 'status');
    assert.equal(fresh.id, 'remote-dashboard-phase-note');
    assert.match(fresh.textContent, /看板已同步/);
    assert.match(paneButton().children[0].textContent, /受阻/, 'pane 状态须以文字出现（受阻/空闲/工作中），不能只靠颜色');
    assert.match(paneButton().textContent, /w1:p1/);
    assert.equal(paneButton().disabled, true, 'selection_ready 之前 pane 按钮禁用');
    assert.match(describedText(paneButton(), panes), /看板/, 'docs/08:94 禁用给原因——pane 按钮禁用时须能读到看板阶段原因');
    assert.ok(newTabButton().attrs['aria-describedby']);
    h.emit({kind: 'selection_ready', generation: gen, epoch: 1});
    assert.equal(paneButton().disabled, false);
    h.emit({kind: 'observation', generation: gen, snapshot: {epoch: 1, phase: 'paused'}});
    assert.equal(paneButton().disabled, true);
    assert.match(describedText(paneButton(), panes), /陈旧/, '暂停后禁用原因须指向陈旧状态文字');
  } finally { h.restore(); }
});
