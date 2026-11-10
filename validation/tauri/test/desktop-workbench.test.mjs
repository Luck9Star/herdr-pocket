import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { HostDashboardSummary } from '../src/host-dashboard-summary.js';
import { initDesktopWorkbench } from '../src/desktop-workbench.js';

const flush = () => new Promise(resolve => setImmediate(resolve));

class Element {
  constructor(id = '') {
    this.id = id; this.tagName = 'div'; this.children = [];
    this.dataset = {}; this.attrs = {}; this.value = '';
    this.hidden = false; this.disabled = false; this.type = ''; this.title = '';
    this.textContent = '';
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(name, fn) { (this.events ??= {})[name] ??= []; this.events[name].push(fn); }
  dispatch(name, event = {}) { for (const fn of this.events?.[name] || []) fn({ target: this, preventDefault() {}, ...event }); }
  click() { this.onclick?.({ target: this, preventDefault() {} }); }
  focus() { if (globalThis.document.activeElement === this) return; globalThis.document.activeElement?.blur?.(); globalThis.document.activeElement = this; this.dispatch('focus'); }
  blur() { if (globalThis.document.activeElement !== this) return; globalThis.document.activeElement = null; this.dispatch('blur'); }
  contains(node) { return node === this || this.children.some(child => child.contains?.(node) || child === node); }
  all() { return this.children.flatMap(child => [child, ...(child.all?.() || [])]); }
  querySelector() { return null; }
  querySelectorAll(selector) {
    if (selector === 'input[type=password]') return [];
    if (selector === 'button[data-remote-key]') return this.all().filter(node => node.tagName === 'button' && node.dataset.remoteKey);
    if (selector === 'button') return this.all().filter(node => node.tagName === 'button');
    return [];
  }
}

const workbenchIds = ['workbench-host-list', 'workbench-host-error', 'workbench-host-retry', 'workbench-pending-list', 'workbench-host-count', 'workbench-pending-count'];
function unitHarness() {
  const nodes = Object.fromEntries(workbenchIds.map(id => [id, new Element(id)]));
  const previous = globalThis.document;
  globalThis.document = { activeElement: null, getElementById: id => nodes[id] ?? null, createElement: tag => { const node = new Element(); node.tagName = tag; return node; } };
  return { nodes, restore: () => { globalThis.document = previous; } };
}

const summaryHost = over => ({
  id: 'host-a', name: '工作站', enabled: true, retired: false, keyDeletionPending: false,
  pairingStatus: null, deviceFingerprint: 'device-fp', networkProfileId: null, networkRevision: null,
  target: { host: 'fixture.invalid', port: 22, username: 'u', session: 'work', expectedHostKey: 'k', socketPath: '/s', herdrPath: '/h' },
  provider: 'tailscale', ...over,
});
const summaryBoard = { panes: [{ agentStatus: 'blocked', paneId: 'w1:p1', terminalId: 'term_a001', label: '构建' }], capturedAt: 2000, phase: 'fresh' };

test('desktop skeleton is declared in index.html and falls back below 900px in style.css', async () => {
  const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
  const css = await readFile(new URL('../src/style.css', import.meta.url), 'utf8');
  for (const id of ['workbench-sidebar', 'workbench-host-list', 'workbench-host-error', 'workbench-host-retry', 'workbench-pending-list', 'workbench-host-count', 'workbench-pending-count', 'workbench-main']) {
    assert.ok(html.includes(`id="${id}"`), `index.html 缺少 #${id}`);
  }
  const remotePage = html.indexOf('<main id="remote-page"');
  const sidebar = html.indexOf('id="workbench-sidebar"');
  const hostTabs = html.indexOf('id="host-tabs"');
  const main = html.indexOf('id="workbench-main"');
  const fixture = html.indexOf('<main id="fixture-workbench"');
  assert.ok(remotePage < sidebar && sidebar < main && main < hostTabs, '侧栏与主区包裹层必须在 #remote-page 内、host-tabs 之前打开');
  assert.ok(html.indexOf('</div></main>', main) > main && fixture > main, '#workbench-main 必须在 remote-page 闭合前收口');
  // ≤899px：侧栏隐藏、主区透明化，移动端单列 DOM 与既有形态一致；≥900px：镜像 .app-grid 两栏。
  assert.ok(css.includes('#workbench-sidebar{display:none}'), '窄窗必须无条件隐藏侧栏');
  assert.ok(css.includes('#workbench-main{display:contents}'), '窄窗主区必须 display:contents 透明化');
  const desktop = css.slice(css.indexOf('@media(min-width:900px)'));
  assert.ok(desktop.includes('#remote-page{max-width:1680px;padding:0;min-height:calc(100vh - 89px);display:grid;grid-template-columns:224px minmax(0,1fr)'));
  assert.ok(desktop.includes('#workbench-main{display:block'));
  assert.ok(desktop.includes('.workbench-main .terminal-host{width:auto;max-width:100%}'), '宽屏必须放开 .terminal-host 的 680px 固定宽');
  assert.ok(desktop.includes('.workbench-main .term-scroll{height:min(560px,60dvh)}'), '宽屏必须抬高 .term-scroll 高度上限');
  assert.ok(css.includes('@media(min-width:900px) and (max-width:1199px){\n  #remote-page{grid-template-columns:190px minmax(0,1fr)}'), '900–1199px 需镜像 .app-grid 的窄列模式');
});

test('sidebar renders compact host cards with active/disabled state and open callback', () => {
  const h = unitHarness();
  try {
    const opened = [];
    const workbench = initDesktopWorkbench({
      hosts: () => [summaryHost(), summaryHost({ id: 'host-b', name: '备份机', enabled: false })],
      activeHostId: () => 'host-a',
      provider: host => host.provider === 'tailscale' ? 'Tailscale' : '',
      hostStatus: () => '尚未在本次运行中连接',
      store: new HostDashboardSummary(),
      isBusy: () => false,
      onOpenHost: id => opened.push(id),
      onOpenBlocked: () => {}, onRetry: () => {},
    });
    workbench.render();
    const cards = h.nodes['workbench-host-list'].children;
    assert.equal(cards.length, 2);
    assert.equal(cards[0].children[0].children[0].textContent, '工作站');
    assert.equal(cards[0].attrs['aria-pressed'], 'true');
    assert.equal(cards[1].attrs['aria-pressed'], 'false');
    assert.equal(cards[1].disabled, true);
    assert.equal(h.nodes['workbench-host-count'].textContent, '2');
    cards[0].click(); assert.deepEqual(opened, ['host-a']);
    cards[1].click(); assert.deepEqual(opened, ['host-a'], '已停用主机不可点击');
  } finally { h.restore(); }
});

test('pending list mirrors task snapshots and forwards blocked-target reopening', () => {
  const h = unitHarness();
  try {
    const store = new HostDashboardSummary();
    const host = summaryHost();
    store.begin(host, 'source-1'); store.publish(host, 'source-1', summaryBoard);
    const reopened = [];
    const workbench = initDesktopWorkbench({
      hosts: () => [host], activeHostId: () => null,
      provider: () => '', hostStatus: () => '', store,
      isBusy: () => false, onOpenHost: () => {},
      onOpenBlocked: (hostId, target) => reopened.push([hostId, target.paneId]),
      onRetry: () => {},
    });
    workbench.render();
    const line = h.nodes['workbench-pending-list'].children[0];
    assert.equal(line.dataset.workbenchSummary, 'host-a');
    assert.match(line.textContent, /工作站 · 受阻 1/);
    assert.equal(h.nodes['workbench-pending-count'].textContent, '1');
    const target = h.nodes['workbench-pending-list'].all().find(node => node.dataset.blockedTarget);
    assert.ok(target, '待处理列表必须复用受阻目标入口');
    target.click();
    assert.deepEqual(reopened, [['host-a', 'w1:p1']]);
    store.suspendAll();
    workbench.render();
    assert.match(h.nodes['workbench-pending-list'].children[0].textContent, /已陈旧/);
  } finally { h.restore(); }
});

test('unreachable hosts show reason and retry instead of an empty list', () => {
  const h = unitHarness();
  try {
    const retried = [];
    const workbench = initDesktopWorkbench({
      hosts: () => [], activeHostId: () => null, provider: () => '', hostStatus: () => '',
      store: new HostDashboardSummary(), isBusy: () => false,
      onOpenHost: () => {}, onOpenBlocked: () => {}, onRetry: () => retried.push(true),
    });
    workbench.setUnavailable('本机主机资料不可达（host_storage_unavailable）；仍可在工作区手动连接。');
    assert.equal(h.nodes['workbench-host-error'].hidden, false);
    assert.match(h.nodes['workbench-host-error'].textContent, /host_storage_unavailable/);
    assert.equal(h.nodes['workbench-host-retry'].hidden, false);
    assert.equal(h.nodes['workbench-host-list'].children.length, 0);
    assert.match(h.nodes['workbench-pending-list'].children[0].textContent, /暂停同步/);
    h.nodes['workbench-host-retry'].click();
    assert.deepEqual(retried, [true]);
    workbench.setUnavailable('浏览器预览不读取本机主机资料', { retry: false });
    assert.equal(h.nodes['workbench-host-retry'].hidden, true, '预览模式重试无意义，必须隐藏');
    workbench.clearUnavailable();
    assert.equal(h.nodes['workbench-host-error'].hidden, true);
    assert.equal(h.nodes['workbench-host-retry'].hidden, true);
    assert.match(h.nodes['workbench-pending-list'].children[0].textContent, /暂无任务快照/);
  } finally { h.restore(); }
});

test('integration: a board filter with zero matches never marks the sidebar unreachable', async () => {
  const s = await integrationSetup();
  try {
    // 看板输入一个命中 0 台的过滤词：看板卡片全部隐藏（filterHostCards 只隐藏看板卡片，不改 hostRecords）。
    s.nodes['host-query'].value = '不存在的主机';
    s.nodes['host-query'].dispatch('input');
    const boardCards = s.nodes['host-list'].children;
    assert.ok(boardCards.length > 0, '集成桩必须先渲染出看板卡片');
    assert.ok(boardCards.every(card => card.hidden === true), '过滤词命中 0 台：看板卡片应全部隐藏');
    assert.match(s.nodes['host-filter-status'].textContent, /没有匹配的主机/);
    assert.equal(s.nodes['host-filter-reset'].hidden, false, '0 结果时看板提供重置入口');
    // 契约：侧栏与看板同源但不参与过滤——仍显示全部已存主机，且不得被当作「资料不可达」。
    assert.equal(s.nodes['workbench-host-list'].children.length, 2, '侧栏仍显示全部已存主机');
    assert.equal(s.nodes['workbench-host-error'].hidden, true, '看板过滤为空不等于侧栏不可达');
    assert.equal(s.nodes['workbench-host-retry'].hidden, true);
    assert.equal(s.nodes['workbench-host-count'].textContent, '2');
  } finally { s.restore(); }
});

test('sidebar re-render defers while a card holds focus and catches up after focusout', async () => {
  const h = unitHarness();
  try {
    const store = new HostDashboardSummary();
    const workbench = initDesktopWorkbench({
      hosts: () => [summaryHost()], activeHostId: () => null, provider: () => '', hostStatus: () => '',
      store, isBusy: () => false, onOpenHost: () => {}, onOpenBlocked: () => {}, onRetry: () => {},
    });
    workbench.render();
    const first = h.nodes['workbench-host-list'].children[0];
    first.focus();
    workbench.render();
    assert.equal(h.nodes['workbench-host-list'].children[0], first, '焦点所在卡片不得被重绘打断');
    first.blur(); h.nodes['workbench-host-list'].dispatch('focusout');
    await flush();
    assert.notEqual(h.nodes['workbench-host-list'].children[0], first, '焦点离开后必须补上最新清单');
  } finally { h.restore(); }
});

// ---- 集成：真实 remote.js 装配（与 direct-dashboard-gui.test.mjs 同一替换策略） ----
let moduleNonce = 0;
async function importedRemote() {
  const url = new URL('../src/remote.js', import.meta.url);
  let code = await readFile(url, 'utf8');
  code = code
    .replace("import {createUnicodeTerminal} from './terminal-unicode.js';", 'const createUnicodeTerminal=(Terminal,options)=>new Terminal(options);')
    .replace("import { Terminal } from '@xterm/xterm';", 'const {Terminal}=globalThis.__workbenchDeps;')
    .replace("import { invoke, Channel } from '@tauri-apps/api/core';", 'const {invoke,Channel}=globalThis.__workbenchDeps;')
    .replace(/from '(\.\/[^']+)'/g, (_match, path) => `from '${new URL(path, url).href}'`);
  const source = Buffer.from(code + `\n// fixture ${++moduleNonce}`).toString('base64');
  return import(`data:text/javascript;base64,${source}`);
}

async function integrationSetup({ failHostList = false } = {}) {
  const previous = { document: globalThis.document, window: globalThis.window, confirm: globalThis.confirm, deps: globalThis.__workbenchDeps };
  const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
  const nodes = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], new Element(match[1])]));
  nodes['remote-page'].hidden = true;
  nodes['fixture-workbench'].hidden = true;
  nodes['remote-rejected-drafts'].hidden = true;
  nodes['remote-port'].value = '22';
  nodes['remote-canvas'].value = '80x24';
  nodes['pair-device'].value = 'Fixture';
  const viewport = new Element('remote-viewport');
  Object.assign(viewport, { clientWidth: 320, scrollWidth: 800, clientHeight: 200, scrollHeight: 400, scrollLeft: 0, scrollTop: 0 });
  nodes['remote-terminal'].parentElement = viewport;
  globalThis.document = {
    body: new Element('body'), hidden: false, hasFocus: () => true, activeElement: null,
    getElementById: id => nodes[id] ?? null,
    createElement: tag => { const node = new Element(); node.tagName = tag; return node; },
    addEventListener() {},
  };
  globalThis.window = { addEventListener() {}, confirm: () => true };
  globalThis.confirm = () => true;

  let failing = failHostList;
  const calls = [];
  const records = [
    summaryHost({ id: 'a'.repeat(32), name: '工作站' }),
    summaryHost({ id: 'b'.repeat(32), name: '备份机', enabled: false, deviceFingerprint: null, pairingStatus: null }),
  ];
  const invoke = async name => {
    calls.push(name);
    if (['host_init', 'host_new', 'remote_cancel', 'remote_select', 'remote_ack'].includes(name)) return;
    if (name === 'host_list') { if (failing) throw Error('host_storage_unavailable'); return structuredClone(records); }
    if (name === 'network_list') return { revision: 'r1', profiles: [], bindings: [], preferences: { terminalFontSize: 14 } };
    if (name === 'remote_input_mode') return 1;
    if (name === 'host_select') return structuredClone(records.find(host => host.id === name) ?? records[0]);
    throw Error(name);
  };
  class Channel {}
  class Terminal {
    constructor(options) { this.options = options; this.element = { querySelector: () => ({ getBoundingClientRect: () => ({ width: 800 }) }) }; this.unicode = {}; this.textarea = new Element(); this.parser = { registerOscHandler() {} }; }
    resize() {} reset() {} loadAddon() {} open() {} dispose() {} focus() {} onData() {} write(_bytes, ack) { ack(); }
  }
  globalThis.__workbenchDeps = { Terminal, invoke, Channel };
  const { initRemote } = await importedRemote();
  initRemote({ native: true, theme: { terminal: {} }, onFixture() {}, onLeaveFixture() {} });
  await flush(); await flush();
  return {
    nodes, calls,
    healHostList: () => { failing = false; },
    restore: () => { globalThis.document = previous.document; globalThis.window = previous.window; globalThis.confirm = previous.confirm; globalThis.__workbenchDeps = previous.deps; },
  };
}

test('integration: reachable hosts render sidebar cards; unreachable shows reason, retry restores', async () => {
  const good = await integrationSetup();
  try {
    const cards = good.nodes['workbench-host-list'].children;
    assert.equal(cards.length, 2);
    assert.equal(cards[0].children[0].children[0].textContent, '工作站');
    assert.equal(good.nodes['workbench-host-error'].hidden, true);
    assert.equal(good.nodes['workbench-host-retry'].hidden, true);
    assert.match(good.nodes['workbench-pending-list'].children[0].textContent, /暂无任务快照/);
  } finally { good.restore(); }

  const bad = await integrationSetup({ failHostList: true });
  try {
    assert.equal(bad.nodes['workbench-host-list'].children.length, 0, '读取失败时不再渲染主机卡片');
    assert.equal(bad.nodes['workbench-host-error'].hidden, false, '不可达必须显示原因，不允许空白侧栏');
    assert.match(bad.nodes['workbench-host-error'].textContent, /host_storage_unavailable/);
    assert.equal(bad.nodes['workbench-host-retry'].hidden, false);
    const before = bad.calls.filter(name => name === 'host_list').length;
    bad.healHostList();
    bad.nodes['workbench-host-retry'].click();
    await flush(); await flush();
    assert.equal(bad.calls.filter(name => name === 'host_list').length, before + 1, '重试必须重新发起 host_list');
    assert.equal(bad.nodes['workbench-host-error'].hidden, true);
    assert.equal(bad.nodes['workbench-host-list'].children.length, 2, '重试成功后侧栏恢复主机清单');
  } finally { bad.restore(); }
});
