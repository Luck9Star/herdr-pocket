import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {createPublicRequestClipboard} from '../src/public-request-clipboard.js';

const connectionProfiles=JSON.parse(await readFile(new URL('../../shared/connection-profile-v1.json',import.meta.url),'utf8'));

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
  append(...nodes) { for (const node of nodes) node.parentElement=this; this.children.push(...nodes); }
  prepend(...nodes) { for (const node of nodes) node.parentElement=this; this.children.unshift(...nodes); }
  remove() { this.removed=true; }
  showModal() { this.previousFocus=document.activeElement; this.open=true; this.modal=true; }
  close() { this.open=false; this.previousFocus?.focus(); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  setAttribute(key, value) { this.attrs[key] = value; }
  getAttribute(key) { return this.attrs[key] ?? null; }
  addEventListener(name, fn) { (this.events[name] ??= []).push(fn); }
  dispatch(name, event = {}) {
    for (const fn of this.events[name] || []) {
      fn({ target: this, preventDefault() {}, ...event });
    }
  }
  click() { if(this.tagName==='summary' && this.parentElement?.tagName==='details') this.parentElement.open=!this.parentElement.open; this.onclick?.({ target: this, preventDefault() {} }); }
  checkValidity() { return true; }
  select(){this.selected=true;}
  setSelectionRange(start,end){this.selection=[start,end];}
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
function expandedActions(actions) { const details=actions.children.find(node=>node.className==='host-manage'); if(details && !details.open) details.children.find(node=>node.tagName==='summary').click(); return actions.all(); }
let moduleNonce = 0;

// Exercise the real entry module while replacing only external browser/native imports.
async function importedRemote() {
  const url = new URL('../src/remote.js', import.meta.url);
  let code = await readFile(url, 'utf8');
  code = code
    .replace("import {createUnicodeTerminal} from './terminal-unicode.js';", 'const createUnicodeTerminal=(Terminal,options)=>new Terminal(options);')
    .replace("import { Terminal } from '@xterm/xterm';", 'const {Terminal}=globalThis.__directGuiDeps;')
    .replace("import { invoke, Channel } from '@tauri-apps/api/core';", 'const {invoke,Channel}=globalThis.__directGuiDeps;')
    .replace('  let networkProviders=new Map();', "  let networkProviders=new Map();globalThis.__remoteCatalogState=()=>({revisions:[...networkRevisions],providers:[...networkProviders],font:terminalFontSize});")
    .replace(/from '(\.\/[^']+)'/g, (_match, path) => `from '${new URL(path, url).href}'`);
  const source = Buffer.from(code + `\n// fixture ${++moduleNonce}`).toString('base64');
  return import(`data:text/javascript;base64,${source}`);
}

async function setup({ inputMode = () => 1, clipboardRead, keyboardRequest, scanResponse, pairRequest=pairingCameraFixture().request, clipboardWrite, pairAcceptStored=true, hostRemove, hostCleanupRetry, pairCreate, pairRecover, pendingStatus, read = null, compactEntry = null, tabInvoke, sshInvoke } = {}) {
  const previous = {
    document: globalThis.document,
    window: globalThis.window,
    confirm: globalThis.confirm,
    fixture: globalThis.__directGuiDeps,
    requestAnimationFrame: globalThis.requestAnimationFrame,
  };
  const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
  const nodes = Object.fromEntries(
    [...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], new Element(match[1])]),
  );
  nodes['remote-rejected-drafts'].hidden = true;
  nodes['remote-page'].hidden = true;
  nodes['fixture-workbench'].hidden = true;
  nodes['remote-port'].value = '22';
  nodes['remote-canvas'].value = '80x24';
  nodes['pair-device'].value = 'Fixture';
  const viewport=new Element('remote-viewport');
  Object.assign(viewport,{clientWidth:320,scrollWidth:800,clientHeight:200,scrollHeight:400,scrollLeft:0,scrollTop:0});
  nodes['remote-terminal'].parentElement=viewport;

  const documentEvents={},windowEvents={};
  globalThis.document = {
    body: new Element('body'),
    hidden: false,
    hasFocus: () => true,
    activeElement: null,
    getElementById: id => nodes[id] ?? null,
    createElement: tag => {
      const node = new Element();
      node.tagName = tag;
      return node;
    },
    createElementNS: (_ns, tag) => { const node = new Element(); node.tagName = tag; return node; },
    addEventListener(name,fn) { (documentEvents[name] ??= []).push(fn); },
  };
  globalThis.window = { addEventListener(name,fn) { (windowEvents[name] ??= []).push(fn); }, confirm: () => true };
  if (sshInvoke) globalThis.requestAnimationFrame = () => 1;
  if (compactEntry) {
    window.matchMedia = () => compactEntry;
    nodes['home-open-ssh'].parentElement = nodes['host-board-intro'];
    nodes['host-empty'].toggleAttribute = (name, on) => {
      if (on) nodes['host-empty'].setAttribute(name, '');
      else delete nodes['host-empty'].attrs[name];
    };
  }
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
  let readOverride = read;
  let sendResult = null;
  const calls = [];

  const invoke = async (name, args = {}) => {
    calls.push({ name, args });
    if (tabInvoke && name.startsWith('remote_tab_')) return tabInvoke(name,args);
    if (sshInvoke && name.startsWith('ssh_shell_')) return sshInvoke(name,args);
    if (name === 'ssh_host_key_probe') return {...args,publicKey:'ssh-ed25519 FIXTURE',fingerprint:'SHA256:fixture'};
    if (name === 'ssh_shell_open') return 'ssh-fixture';
    if (name === 'ssh_shell_close') return;
    if (['host_init', 'host_new', 'remote_cancel', 'remote_select', 'remote_ack', 'remote_input_recover'].includes(name)) return;
    if (name === 'pair_scan_response') return scanResponse ? scanResponse() : '';
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
    if (name === 'host_select') return structuredClone(records.find(h=>h.id===args.id));
    if (name === 'host_restore') return {state:records.find(x=>x.id===args.id)?.pairingStatus==='revoked'?'revoked':'authorized-unverified',fingerprint:'device-fingerprint',request:pairRequest};
    if (name === 'host_save') {
      if (!records.length) {
        records = [{
          id: 'a'.repeat(32), name: 'Fixture', enabled: true, retired: false,
          target, requiresNetworkBinding:['tailscale','easytier','zerotier'].includes(args.providerHint), provider: args.providerHint || 'unspecified', deviceFingerprint: null, hostFingerprint: 'host-key', networkProfileId: null,
        }];
      }
      return structuredClone(records[0]);
    }
    if (name === 'pair_pending_status') return pendingStatus ? pendingStatus(args,records) : false;
    if (name === 'pair_recover_pending') return pairRecover ? pairRecover(args,records) : Promise.reject('key_creation_missing');
    if (name === 'pair_discard_pending') return null;
    if (name === 'pair_create' && pairCreate) return pairCreate(args,records);
    if (name === 'pair_create') {
      records[0].deviceFingerprint = 'device-fingerprint';
      records[0].pairingStatus = 'awaiting-host';
      return { stored: true, state: 'awaiting-host', request: pairRequest, fingerprint: 'device-fingerprint' };
    }
    if (name === 'host_remove' && hostRemove) return hostRemove(args,records);
    if (name === 'host_cleanup_retry' && hostCleanupRetry) return hostCleanupRetry(args,records);
    if (name === 'pair_cancel') {records[0].pairingStatus='cancelled';return;}
    if (name === 'pair_reset') {records[0].deviceFingerprint=null;records[0].pairingStatus=null;return;}
    if (name === 'pair_accept') {
      const revoked=JSON.parse(args.response).status==='revoked';if(!revoked || pairAcceptStored)records[0].pairingStatus=revoked?'revoked':'authorized';
      return { state: revoked?'revoked':'authorized-unverified', fingerprint: 'device-fingerprint',stored:pairAcceptStored };
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
      this.cols=options.cols;this.rows=options.rows;
      this.element={querySelector:()=>({getBoundingClientRect:()=>({width:800*this.options.fontSize/14})})};
      this.unicode = {};
      this.textarea = new Element();
      this.focusedAs = [];
      this.modes = { bracketedPasteMode: false };
      this.parser = { registerOscHandler() {} };
    }
    resize(cols,rows) {this.cols=cols;this.rows=rows;}
    reset() {}
    loadAddon() {}
    open() {}
    dispose() {}
    focus() {
      this.focusedAs.push([this.options.disableStdin, this.textarea.attrs.inputmode]);
      this.textarea.focus();
    }
    onData(handler) { this.data = handler; }
    write(bytes, ack) { (this.writes ??= []).push(bytes);ack(); }
  }
  globalThis.__directGuiDeps = { Terminal, invoke, Channel };
  const { initRemote } = await importedRemote();
  initRemote({ native: true, theme: { terminal: {} }, onFixture() {}, onLeaveFixture() {}, clipboardRead, keyboardRequest, clipboardWrite });
  await flush();
  await flush();

  return {
    nodes, calls, target, get terminal() { return terminal; },
    setRead: fn => { readOverride = fn; },
    setSendResult: result => { sendResult = result; },
    updateHost: update => { Object.assign(records[0], update); },
    emit: event => channel.onmessage(event),
    windowEvent: name => (windowEvents[name] || []).forEach(fn=>fn()),
    background: () => { document.hidden=true;(documentEvents.visibilitychange || []).forEach(fn=>fn()); },
    foreground: () => { document.hidden=false;(documentEvents.visibilitychange || []).forEach(fn=>fn()); },
    finish: () => resolveObserve?.(),
    fail: (error=Error('fixture failure')) => rejectObserve?.(error),
    restore() {
      globalThis.document = previous.document;
      globalThis.window = previous.window;
      globalThis.confirm = previous.confirm;
      globalThis.__directGuiDeps = previous.fixture;
      globalThis.requestAnimationFrame = previous.requestAnimationFrame;
    },
  };
}

async function pairAndConnect(h, canvas='80x24') {
  const n = h.nodes;
  n['host-open-remote'].click();n['add-herdr'].click();
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
  const request=JSON.parse(n['pair-request'].value);
  n['pair-response'].value = JSON.stringify({version:2,type:'pairing-binding-response',
    account: request.account, host_key: request.host_key, fingerprint: 'device-fingerprint',
    status: 'authorized', request_id: request.request_id, issued_at: request.issued_at, expires_at: request.expires_at,
    authorization_added: true,
  });
  n['pair-preview'].click();
  n['pair-source-review'].checked = true;
  n['pair-accept'].click();
  await flush(); await flush(); await flush();
  n['remote-review'].checked = true;
  n['remote-form'].dispatch('input', { target: n['remote-review'] });
  n['remote-canvas'].value=canvas;n['remote-form'].dispatch('input', {target:n['remote-canvas']});
  n['remote-form'].dispatch('submit');
  await flush();
}

function publishDashboard(h, panes) {
  h.emit({ kind: 'stage', generation: 9, stage: 'authenticated' });
  h.emit({ kind: 'observation', generation: 9, snapshot:{epoch:1,phase:'starting'} });
  h.emit({ kind: 'dashboard_watch', generation: 9, update:{epoch:1,revision:1,phase:'fresh',reason:'fixture',panes} });
  h.emit({ kind: 'selection_ready', generation: 9, epoch:1 });
}
function blockedPane() {
  return [{ paneId: 'w1:p1', terminalId: 'term_a001', agentStatus: 'blocked' }];
}

async function openInput(h) {
  await pairAndConnect(h);
  publishDashboard(h, blockedPane());
  h.nodes['remote-panes'].children.find(e=>e.tagName==='button' && e.textContent.startsWith('w1:p1')).click();
  h.emit({kind:'target_bound',generation:9,epoch:1,pane_id:'w1:p1',terminal_id:'term_a001'});
  h.emit({ kind: 'frame', generation: 9, epoch:1, frame: { seq: 1, full: true,cols:80,rows:24, bytes: [65] } });
  h.emit({ kind: 'input_ready', generation: 9, epoch:1, unknown: false, recovery_status: 'ready' });
}

test('paired direct and draft show matched receipts without a live region and clear on failure',async()=>{
  const h=await setup(),n=h.nodes;
  try {
    await openInput(h);n['remote-input-direct'].click();await flush();await flush();
    h.terminal.data('中');await flush();await flush();
    assert.equal(n['remote-receipt'].hidden,false);
    assert.match(n['remote-receipt-text'].textContent,/请求 ID：a{32}.*w1:p1.*term_a001.*受理 3 字节.*命令结果/);
    assert.equal(n['remote-receipt'].attrs['aria-live'],undefined);
    n['remote-input-draft-mode'].click();await flush();await flush();
    n['remote-input-draft'].value='你好';n['remote-input-draft'].dispatch('input');
    n['remote-input-preview'].click();n['remote-input-confirm'].click();await flush();await flush();
    assert.match(n['remote-receipt-text'].textContent,/受理 6 字节/);
    h.setSendResult({status:'unknown'});n['remote-input-draft'].value='x';n['remote-input-draft'].dispatch('input');
    n['remote-input-preview'].click();n['remote-input-confirm'].click();await flush();await flush();
    assert.equal(n['remote-receipt'].hidden,true);assert.equal(n['remote-receipt-text'].textContent,'');
  } finally {h.finish();await flush();h.restore();}
});

test('paired form keyboard controls use the current editor, revoke on hide and reject late IME', async () => {
  const previous=Object.getOwnPropertyDescriptor(globalThis,'navigator');const keyboard=[];
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{virtualKeyboard:{show:()=>keyboard.push('show'),hide:()=>keyboard.push('hide')}}});
  const h=await setup();const n=h.nodes;
  try {
    await openInput(h);
    assert.equal(n['remote-keyboard-show'].disabled,true);
    n['remote-keyboard-show'].click();assert.equal(h.calls.filter(c=>c.name==='remote_input_mode').length,0);
    n['remote-input-direct'].click();await flush();await flush();
    assert.equal(n['remote-keyboard-show'].disabled,false);
    n['remote-keyboard-show'].click();assert.deepEqual(keyboard,['show']);
    h.terminal.textarea.dispatch('compositionstart');
    assert.equal(n['remote-keyboard-show'].disabled,true);
    n['remote-keyboard-hide'].click();assert.deepEqual(keyboard,['show','hide']);
    h.terminal.textarea.dispatch('compositionend');h.terminal.data('迟到');await flush();
    assert.equal(h.calls.filter(c=>c.name==='remote_input_send').length,0);
    assert.equal(n['remote-keyboard-show'].disabled,true);
    assert.ok(h.calls.some(c=>c.name==='remote_input_mode' && c.args.mode==='observe'));
    n['remote-input-draft-mode'].click();await flush();await flush();
    assert.equal(document.activeElement,n['remote-input-draft']);
    n['remote-keyboard-show'].click();assert.deepEqual(keyboard,['show','hide','show']);
    n['remote-input-draft'].value='草稿';n['remote-input-draft'].dispatch('compositionstart');
    n['remote-input-preview'].click();assert.equal(n['remote-input-preview-area'].hidden,true);
    n['remote-keyboard-hide'].click();n['remote-input-draft'].dispatch('compositionend');
    n['remote-input-confirm'].click();await flush();
    assert.equal(h.calls.filter(c=>c.name==='remote_input_send').length,0);
    assert.equal(h.calls.filter(c=>c.name.includes('resize')).length,0);
  } finally {h.finish();await flush();h.restore();if(previous)Object.defineProperty(globalThis,'navigator',previous);else delete globalThis.navigator;}
});

test('paired keyboard late native requests lose authority after hide or target navigation',async()=>{
  const requests=[],h=await setup({keyboardRequest:(action,editor,current)=>requests.push({action,editor,current})});
  try {
    await openInput(h);h.nodes['remote-input-direct'].click();await flush();await flush();
    h.nodes['remote-keyboard-show'].click();assert.equal(requests[0].current(),true);
    h.nodes['remote-keyboard-hide'].click();assert.equal(requests[0].current(),false);
    assert.equal(requests[1].action,'hide');assert.equal(requests[1].current(),true);
    h.nodes['remote-input-draft-mode'].click();await flush();await flush();
    assert.equal(requests[1].current(),false);
    h.nodes['remote-keyboard-show'].click();assert.equal(requests.at(-1).current(),true);
    h.nodes['host-return-home'].click();await flush();assert.equal(requests.at(-1).current(),false);
    assert.equal(h.calls.filter(c=>c.name==='remote_input_send' || c.name.includes('resize')).length,0);
  }finally{h.finish();await flush();h.restore();}
});

test('paired hide during pending direct permission invalidates its late grant',async()=>{
  let grant;const h=await setup({inputMode:args=>args.mode==='direct'?new Promise(r=>grant=r):1,keyboardRequest:()=>{}});
  try{
    await openInput(h);h.nodes['remote-input-direct'].click();await flush();
    assert.equal(h.nodes['remote-keyboard-hide'].disabled,false);
    h.nodes['remote-keyboard-hide'].click();grant(7);await flush();await flush();
    h.terminal.data('迟到');assert.equal(h.calls.filter(c=>c.name==='remote_input_send').length,0);
    assert.equal(h.terminal.options.disableStdin,true);assert.equal(h.nodes['remote-keyboard-show'].disabled,true);
  }finally{h.finish();await flush();h.restore();}
});

test('paired draft cannot confirm an existing preview during IME composition',async()=>{
  const h=await setup();try{
    await openInput(h);h.nodes['remote-input-draft-mode'].click();await flush();await flush();
    const draft=h.nodes['remote-input-draft'];draft.value='待核对';draft.dispatch('input');
    h.nodes['remote-input-preview'].click();assert.equal(h.nodes['remote-input-preview-area'].hidden,false);
    draft.dispatch('compositionstart');h.nodes['remote-input-confirm'].click();await flush();
    assert.equal(h.calls.filter(c=>c.name==='remote_input_send').length,0);
  }finally{h.finish();await flush();h.restore();}
});

test('paired font diagnostics use a separate read-only terminal, revoke input and retain draft',async()=>{
  const prior=globalThis.fetch,fixture=JSON.parse(await readFile(new URL('../../shared/terminal-font-diagnostics-v1.json',import.meta.url),'utf8'));
  globalThis.fetch=async()=>({ok:true,json:async()=>fixture});const h=await setup();
  try{
    await openInput(h);h.nodes['remote-input-draft-mode'].click();await flush();await flush();
    const draft=h.nodes['remote-input-draft'];draft.value='原目标草稿';draft.dispatch('input');
    const observed=h.terminal;h.nodes['remote-font-diagnostics'].click();await flush();await flush();
    const panel=document.body.children.find(e=>e.attrs['aria-label']==='字体与字符诊断');assert.ok(panel);assert.equal(panel.tagName,'dialog');assert.equal(panel.modal,true);
    const legend=panel.children.find(e=>e.className==='font-diagnostics-legend');assert.deepEqual(legend.children.map(e=>e.textContent),fixture.samples.map(item=>`${item.label} · 预期 ${item.cells} 列`));
    const sample=h.terminal;assert.notEqual(sample,observed);assert.equal(sample.options.cols,16);assert.equal(sample.options.rows,8);
    assert.equal(sample.options.disableStdin,true);assert.equal(sample.options.fontFamily,'ProbeNerd, monospace');assert.deepEqual(sample.writes,[fixture.write]);assert.equal(sample.textarea.disabled,true);assert.equal(sample.textarea.attrs.tabindex,'-1');
    assert.equal(draft.value,'原目标草稿');assert.ok(h.calls.some(c=>c.name==='remote_input_mode' && c.args.mode==='observe'));
    panel.children.find(e=>e.textContent==='关闭诊断').click();assert.equal(panel.removed,true);assert.equal(document.activeElement,h.nodes['remote-font-diagnostics']);
    observed.data('旧输入');await flush();assert.equal(h.calls.filter(c=>c.name==='remote_input_send'||c.name.includes('resize')).length,0);
    assert.equal(draft.value,'原目标草稿');
  }finally{h.finish();await flush();h.restore();globalThis.fetch=prior;}
});

test('stock paired observation opens local diagnostics without input_ready',async()=>{
  const prior=globalThis.fetch,fixture=JSON.parse(await readFile(new URL('../../shared/terminal-font-diagnostics-v1.json',import.meta.url),'utf8'));
  globalThis.fetch=async()=>({ok:true,json:async()=>fixture});const h=await setup();
  try{
    await pairAndConnect(h);publishDashboard(h,blockedPane());h.nodes['remote-panes'].children.find(e=>e.tagName==='button' && e.textContent.startsWith('w1:p1')).click();
    h.emit({kind:'target_bound',generation:9,epoch:1,pane_id:'w1:p1',terminal_id:'term_a001'});h.emit({kind:'frame',generation:9,epoch:1,frame:{seq:1,full:true,cols:80,rows:24,bytes:[65]}});await flush();
    const observed=h.terminal;assert.equal(h.nodes['remote-font-diagnostics'].disabled,false);h.nodes['remote-font-diagnostics'].click();await flush();await flush();
    assert.deepEqual(h.terminal.writes,[fixture.write]);assert.equal(h.terminal.options.disableStdin,true);
    assert.equal(observed.options.disableStdin,true);assert.equal(h.calls.filter(c=>c.name==='remote_input_mode').length,0);
    assert.equal(h.calls.filter(c=>c.name==='remote_input_send'||c.name.includes('resize')).length,0);
  }finally{h.finish();await flush();h.restore();globalThis.fetch=prior;}
});

test('paired font diagnostics revoke direct input and reject late composition after close',async()=>{
  const prior=globalThis.fetch,fixture=JSON.parse(await readFile(new URL('../../shared/terminal-font-diagnostics-v1.json',import.meta.url),'utf8'));
  globalThis.fetch=async()=>({ok:true,json:async()=>fixture});const h=await setup();
  try{
    await openInput(h);h.nodes['remote-input-direct'].click();await flush();await flush();const observed=h.terminal;
    observed.textarea.dispatch('compositionstart');h.nodes['remote-font-diagnostics'].click();await flush();
    const panel=document.body.children.find(e=>e.attrs['aria-label']==='字体与字符诊断');assert.ok(panel);
    panel.children.find(e=>e.textContent==='关闭诊断').click();observed.textarea.dispatch('compositionend');observed.data('迟到');await flush();
    assert.equal(observed.options.disableStdin,true);assert.equal(h.calls.filter(c=>c.name==='remote_input_send'||c.name.includes('resize')).length,0);
  }finally{h.finish();await flush();h.restore();globalThis.fetch=prior;}
});

test('paired font diagnostics show local fixture failure without ending observation',async()=>{
  const prior=globalThis.fetch;globalThis.fetch=async()=>({ok:false});const h=await setup();
  try{
    await openInput(h);const observed=h.terminal;h.nodes['remote-font-diagnostics'].click();await flush();await flush();
    const panel=document.body.children.find(e=>e.attrs['aria-label']==='字体与字符诊断');assert.match(panel.children.find(e=>e.attrs.role==='status').textContent,/本地诊断样例不可用/);
    assert.equal(h.terminal,observed);assert.equal(h.calls.filter(c=>c.name==='remote_cancel'||c.name==='remote_input_send').length,0);
    panel.children.find(e=>e.textContent==='关闭诊断').click();assert.equal(panel.removed,true);
  }finally{h.finish();await flush();h.restore();globalThis.fetch=prior;}
});

test('paired diagnostics blocks input entry and cancel closes modal safely',async()=>{
  const prior=globalThis.fetch,fixture=JSON.parse(await readFile(new URL('../../shared/terminal-font-diagnostics-v1.json',import.meta.url),'utf8'));
  globalThis.fetch=async()=>({ok:true,json:async()=>fixture});const h=await setup();
  try{
    await openInput(h);h.nodes['remote-font-diagnostics'].click();await flush();await flush();
    const panel=document.body.children.find(e=>e.attrs['aria-label']==='字体与字符诊断'),before=h.calls.filter(c=>c.name==='remote_input_mode').length;
    h.nodes['remote-input-direct'].click();h.nodes['remote-input-draft-mode'].click();await flush();
    assert.equal(h.calls.filter(c=>c.name==='remote_input_mode').length,before);
    let prevented=false;panel.dispatch('cancel',{preventDefault(){prevented=true;}});assert.equal(prevented,true);assert.equal(panel.removed,true);
    assert.equal(document.activeElement,h.nodes['remote-font-diagnostics']);assert.equal(h.calls.filter(c=>c.name==='remote_input_send').length,0);
  }finally{h.finish();await flush();h.restore();globalThis.fetch=prior;}
});

test('paired font diagnostics ignore a fixture arriving after leaving the target',async()=>{
  const prior=globalThis.fetch;let release;globalThis.fetch=()=>new Promise(r=>release=r);const h=await setup();
  try{
    await openInput(h);const observed=h.terminal;h.nodes['remote-font-diagnostics'].click();
    const panel=document.body.children.find(e=>e.attrs['aria-label']==='字体与字符诊断');assert.ok(panel);
    h.nodes['host-return-home'].click();release({ok:true,json:async()=>JSON.parse(await readFile(new URL('../../shared/terminal-font-diagnostics-v1.json',import.meta.url),'utf8'))});
    await flush();await flush();assert.equal(panel.removed,true);assert.notEqual(document.activeElement,h.nodes['remote-font-diagnostics']);assert.equal(h.terminal,observed);
    assert.equal(h.calls.filter(c=>c.name==='remote_input_send'||c.name.includes('resize')).length,0);
  }finally{h.finish();await flush();h.restore();globalThis.fetch=prior;}
});

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
    : nodes['host-list'].children[0].children.flatMap(node => [node, ...node.children]).find(node => node.attrs['data-host-task-summary']);
}

test('normal new pairing form keeps summary live after pane selection and marks it stale on home return', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await pairAndConnect(h);
    assert.equal(h.calls.filter(call => call.name === 'remote_observe').length, 1);
    publishDashboard(h, blockedPane());
    assert.match(summary(n).textContent, /当前快照.*会话 work.*受阻 1.*同步/);
    const pane = n['remote-panes'].children.find(node => node.textContent.startsWith('w1:p1'));
    assert.ok(pane);
    pane.click();
    await flush();
    assert.match(summary(n).textContent, /当前快照/);
    n['host-return-home'].click();
    await flush(); await flush();
    assert.match(summary(n, false).textContent, /上次快照.*受阻 1/);
    assert.equal(h.calls.filter(call => call.name === 'remote_observe').length, 1);
  } finally { h.finish(); await flush(); h.restore(); }
});

test('live paired board updates summary and rejects old reviewed buttons and revisions', async () => {
  const h=await setup(),n=h.nodes;
  try {
    await pairAndConnect(h);publishDashboard(h,blockedPane());
    const old=n['remote-panes'].children.find(e=>e.textContent.startsWith('w1:p1'));
    const changed={paneId:'w1:p1',terminalId:'term_a002',agentStatus:'working'};
    h.emit({kind:'dashboard_watch',generation:9,update:{epoch:1,revision:2,phase:'fresh',reason:'changed',panes:[changed]}});
    assert.match(summary(n).textContent,/当前快照.*受阻 0/);
    old.click();assert.equal(h.calls.filter(c=>c.name==='remote_select').length,0);
    h.emit({kind:'dashboard_watch',generation:9,update:{epoch:1,revision:1,phase:'fresh',reason:'late',panes:blockedPane()}});
    const current=n['remote-panes'].children.find(e=>e.textContent.startsWith('w1:p1'));
    assert.match(current.textContent,/term_a002/);current.click();await flush();
    assert.deepEqual(h.calls.filter(c=>c.name==='remote_select').at(-1).args,{generation:9,epoch:1,revision:2,paneId:'w1:p1',terminalId:'term_a002'});
    h.emit({kind:'target_bound',generation:9,epoch:1,pane_id:'w1:p1',terminal_id:'term_a002'});
    h.emit({kind:'frame',generation:9,epoch:1,frame:{seq:1,full:true,cols:80,rows:24,bytes:[65]}});
    h.emit({kind:'dashboard_watch',generation:9,update:{epoch:1,revision:3,phase:'fresh',reason:'changed',panes:blockedPane()}});
    assert.match(summary(n).textContent,/当前快照.*受阻 1/);
    assert.equal(h.calls.filter(c=>c.name==='remote_observe').length,1);
    assert.equal(h.calls.filter(c=>c.name.includes('resize') || c.name==='remote_input_send').length,0);
    assert.deepEqual(h.calls.find(c=>c.name==='remote_ack').args,{generation:9,epoch:1,seq:1});
  } finally {h.finish();await flush();h.restore();}
});

test('refreshing stales summary and disables selection; unsupported snapshot is explicitly labelled', async()=>{
  const h=await setup(),n=h.nodes;
  try {
    await pairAndConnect(h);publishDashboard(h,blockedPane());
    const old=n['remote-panes'].children.find(e=>e.textContent.startsWith('w1:p1'));
    h.emit({kind:'dashboard_watch',generation:9,update:{epoch:1,revision:2,phase:'refreshing',reason:'watch_lost',panes:null}});
    assert.match(summary(n).textContent,/上次快照/);old.click();assert.equal(h.calls.filter(c=>c.name==='remote_select').length,0);
    h.emit({kind:'dashboard_watch',generation:9,update:{epoch:1,revision:3,phase:'unavailable',reason:'unsupported',panes:blockedPane()}});
    assert.match(summary(n).textContent,/本次快照（持续更新不可用）/);
    assert.match(n['remote-panes'].children[0].textContent,/持续更新不可用/);
    assert.equal(n['remote-panes'].children.find(e=>e.textContent.startsWith('w1:p1')).disabled,false);
  } finally {h.finish();await flush();h.restore();}
});

test('window blur keeps a visible host board subscribed', async () => {
  const h=await setup();
  try {
    await pairAndConnect(h);publishDashboard(h,blockedPane());h.windowEvent('blur');
    h.emit({kind:'dashboard_watch',generation:9,update:{epoch:1,revision:2,phase:'fresh',reason:'snapshot',panes:[]}});
    assert.match(summary(h.nodes).textContent,/当前快照.*受阻 0/);
    assert.equal(h.calls.filter(c=>c.name==='remote_cancel').length,0);
  } finally {h.finish();await flush();h.restore();}
});

for(const reason of ['offline','background'])test(`${reason} invalidates the live board and rejects late updates`,async()=>{
  const h=await setup(),n=h.nodes;
  try {
    await pairAndConnect(h);publishDashboard(h,blockedPane());
    if(reason==='background')h.background();else h.windowEvent(reason);
    assert.match(summary(n).textContent,/上次快照/);
    h.emit({kind:'dashboard_watch',generation:9,update:{epoch:1,revision:2,phase:'fresh',reason:'late',panes:[]}});
    assert.match(summary(n).textContent,/上次快照.*受阻 1/);
    assert.equal(h.calls.filter(c=>c.name==='remote_cancel').length,1);
  } finally {h.finish();await flush();h.restore();}
});

test('saved system-route workspace stops on offline and needs explicit review and a new snapshot',async()=>{
  const streams=[];
  const h=await setup({tabInvoke(name,args) {
    if(name==='remote_tab_reserve')return 10+streams.length;
    if(name==='remote_tab_observe')return new Promise(finish=>streams.push({args,finish}));
    if(name==='remote_tab_input_mode')return 1;
  }});
  const n=h.nodes, count=name=>h.calls.filter(call=>call.name===name).length;
  const button=text=>n['view-content'].all().find(node=>node.tagName==='button' && node.textContent===text);
  const review=()=>n['view-content'].all().find(node=>node.type==='checkbox');
  const connect=async()=>{const check=review();check.checked=true;check.onchange();button('连接').click();await flush();};
  const emit=(stream,event)=>stream.args.onEvent.onmessage({generation:stream.args.generation,...event});
  const snapshot=(stream,revision,panes)=>emit(stream,{kind:'dashboard_watch',update:{epoch:1,revision,phase:'fresh',reason:'fixture',panes}});
  try {
    await pairAndConnect(h);h.finish();await flush();
    n['host-return-home'].click();await flush();await flush();
    n['host-list'].children[0].all().find(node=>node.textContent==='新终端标签').click();
    await flush();
    h.windowEvent('offline');assert.equal(count('remote_tab_cancel'),0);
    await connect();
    const [first]=streams;
    assert.equal(h.calls.find(call=>call.name==='remote_tab_reserve').args.expectedNetworkProfileId,null);
    emit(first,{kind:'observation',snapshot:{epoch:1,phase:'starting'}});
    snapshot(first,1,blockedPane());
    const before=summary(n).textContent;
    assert.match(before,/当前快照.*受阻 1/);
    emit(first,{kind:'selection_ready',epoch:1});
    const pane=n['view-content'].all().find(node=>node.dataset.paneId==='w1:p1');
    assert.equal(pane.disabled,false);pane.click();await flush();
    emit(first,{kind:'target_bound',epoch:1,pane_id:'w1:p1',terminal_id:'term_a001'});
    emit(first,{kind:'observation',snapshot:{epoch:1,phase:'active'}});
    emit(first,{kind:'frame',epoch:1,frame:{seq:1,full:true,cols:80,rows:24,bytes:[65]}});
    emit(first,{kind:'input_ready',epoch:1,unknown:false,recovery_status:'ready'});
    const direct=button('逐键输入');
    assert.equal(direct.disabled,false);direct.click();await flush();
    const terminal=h.terminal;
    assert.equal(terminal.options.disableStdin,false);

    h.windowEvent('offline');h.windowEvent('offline');
    const after=summary(n).textContent;
    assert.equal(after,before.replace('当前快照','上次快照（状态已陈旧）'));
    assert.equal(terminal.options.disableStdin,true);
    assert.equal(button('逐键输入'),undefined);
    terminal.data('x');
    assert.ok(n['view-content'].all().some(node=>node.textContent.includes('重新连接需主动核验')));
    snapshot(first,2,[]);
    emit(first,{kind:'frame',epoch:1,frame:{seq:2,full:false,cols:80,rows:24,bytes:[66]}});
    assert.equal(summary(n).textContent,after);
    assert.equal(count('remote_tab_ack'),1);
    assert.equal(count('remote_tab_cancel'),1);
    const {tabId,clientGeneration,generation}=first.args;
    assert.deepEqual(h.calls.find(call=>call.name==='remote_tab_cancel').args,{tabId,clientGeneration,generation});
    first.finish();await flush();
    assert.equal(review().checked,false);
    assert.equal(button('连接').disabled,true);
    h.windowEvent('online');h.foreground();await flush();
    assert.equal(count('remote_tab_reserve'),1);
    assert.equal(summary(n).textContent,after);

    await connect();
    const second=streams[1];
    assert.ok(second);
    assert.equal(summary(n).textContent,after);
    snapshot(first,3,[]);
    assert.equal(summary(n).textContent,after);
    emit(second,{kind:'observation',snapshot:{epoch:1,phase:'starting'}});
    snapshot(second,1,[]);
    assert.match(summary(n).textContent,/当前快照.*受阻 0/);
    assert.notEqual(second.args.generation,generation);
    assert.equal(count('remote_tab_observe'),2);
    assert.equal(count('remote_tab_cancel'),1);
    assert.equal(h.calls.filter(call=>/input_send|resize/.test(call.name)).length,0);
  } finally {for(const stream of streams)stream.finish();await flush();h.restore();}
});

test('unexpected bound terminal stops without enabling input or sending',async()=>{
  const h=await setup();try{
    await pairAndConnect(h);publishDashboard(h,blockedPane());
    h.nodes['remote-panes'].children.find(e=>e.textContent.startsWith('w1:p1')).click();
    h.emit({kind:'target_bound',generation:9,epoch:1,pane_id:'w1:p1',terminal_id:'term_replaced'});
    h.emit({kind:'frame',generation:9,epoch:1,frame:{seq:1,full:true,cols:80,rows:24,bytes:[65]}});
    assert.equal(h.calls.filter(c=>c.name==='remote_cancel').length,1);
    assert.equal(h.calls.filter(c=>c.name==='remote_ack' || c.name==='remote_input_send').length,0);
  }finally{h.finish();await flush();h.restore();}
});

test('cancel and late dashboard cannot restore current summary', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await pairAndConnect(h);
    publishDashboard(h, blockedPane());
    n['remote-cancel'].click();
    assert.match(summary(n).textContent, /上次快照/);
    h.emit({ kind: 'dashboard_watch', generation: 9, update:{epoch:1,revision:2,phase:'fresh',reason:'fixture',panes:[]} });
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
    h.emit({ kind: 'dashboard_watch', generation: 10, update:{epoch:1,revision:1,phase:'fresh',reason:'fixture',panes:blockedPane()} });
    assert.match(summary(n).textContent, /上次快照.*受阻 0/);
  } finally { h.finish(); await flush(); h.restore(); }
});

test('dashboard before native authentication never claims a saved host summary', async () => {
  const h = await setup(), n = h.nodes;
  try {
    await pairAndConnect(h);
    h.emit({ kind: 'dashboard_watch', generation: 9, update:{epoch:1,revision:1,phase:'fresh',reason:'fixture',panes:blockedPane()} });
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
    assert.equal(n['host-list'].children[0].children[0].children[0].textContent, 'New identity');
    assert.equal(summary(n, false).hidden, true);
    release();
    await flush(); await flush();
    assert.equal(n['host-list'].children[0].children[0].children[0].textContent, 'New identity');
    assert.equal(summary(n, false).hidden, true);
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
    h.emit({ kind: 'dashboard_watch', generation: 9, update:{epoch:1,revision:2,phase:'fresh',reason:'fixture',panes:[]} });
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
  h.nodes['remote-panes'].children.find(e=>e.tagName==='button' && e.textContent.startsWith(pane.paneId)).click();
  assert.equal(h.nodes['remote-input-draft'].value, '', 'unbound row must not expose its saved draft');
  h.emit({kind:'target_bound',generation:9,epoch:1,pane_id:pane.paneId,terminal_id:pane.terminalId});
  h.emit({ kind: 'frame', generation: 9, epoch:1, frame: { seq: 1, full: true,cols:80,rows:24, bytes: [65] } });
  h.emit({ kind: 'input_ready', generation: 9, epoch:1, unknown: false, recovery_status: 'ready' });
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
    const review=n['remote-result'].all().find(node=>node.className==='unknown-input-review');
    assert.equal(review.hidden,false);
    assert.ok(review.all().some(node=>node.textContent.includes('w1:p1') && node.textContent.includes('term_a001')));
    assert.ok(review.all().some(node=>node.textContent.startsWith('发送时间：')));
    assert.ok(review.all().some(node=>node.tagName==='pre' && node.textContent==='不重放'));
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

test('touch clipboard reviews paired direct and draft without sending', async () => {
  for (const mode of ['direct', 'draft']) {
    const h=await setup({clipboardRead:async()=> '触摸文本'}), n=h.nodes;
    try {
      await openInput(h);
      const draft=n['remote-input-draft'];draft.value='原';draft.dispatch('input');
      n[mode==='direct'?'remote-input-direct':'remote-input-draft-mode'].click();await flush();await flush();
      n['remote-read-paste'].click();await flush();await flush();
      assert.equal(n['remote-paste-review'].hidden,false);
      assert.equal(draft.value,'原');n['remote-paste-append'].click();assert.equal(draft.value,'原触摸文本');
      assert.equal(h.calls.filter(c=>c.name==='remote_input_send').length,0);
    } finally {h.finish();await flush();h.restore();}
  }
});

test('touch clipboard rejects stale double reads and changed draft', async () => {
  let resolves=[];const h=await setup({clipboardRead:()=>new Promise(resolve=>resolves.push(resolve))}),n=h.nodes;
  try {
    await readyDirectPaste(h);n['remote-read-paste'].click();n['remote-read-paste'].click();
    resolves[0]('旧');await flush();assert.equal(n['remote-paste-review'].hidden,true);
    n['remote-input-draft'].value='改变';n['remote-input-draft'].dispatch('input');resolves[1]('新');await flush();
    assert.equal(n['remote-paste-review'].hidden,true);assert.equal(n['remote-input-draft'].value,'改变');
  } finally {h.finish();await flush();h.restore();}
});

test('touch clipboard reports denial and oversized text without exposing it',async()=>{
  for(const [read,expected] of [[async()=>{throw Error('clipboard_denied');},/未允许/],[async()=> 'x'.repeat(4097),/4096/]]){
    const h=await setup({clipboardRead:read}),n=h.nodes;
    try{await readyDirectPaste(h);n['remote-read-paste'].click();await flush();assert.equal(n['remote-paste-review'].hidden,true);assert.match(n['remote-input-status'].textContent,expected);assert.equal(n['remote-paste-preview'].textContent,'');}finally{h.finish();await flush();h.restore();}
  }
});

test('browser non-text clipboard is rejected with visible feedback',async()=>{
 const h=await setup(),n=h.nodes;try{await readyDirectPaste(h);h.terminal.textarea.dispatch('paste',{preventDefault(){},stopImmediatePropagation(){},clipboardData:{types:['image/png'],getData:()=> 'not text'}});await flush();assert.equal(n['remote-paste-review'].hidden,true);assert.match(n['remote-input-status'].textContent,/纯文本/);}finally{h.finish();await flush();h.restore();}
});

test('fresh pairing viewport returns through saved identity only after new full, keeping local columns',async()=>{
  const h=await setup(),n=h.nodes,v=n['remote-terminal'].parentElement;
  try {
    await openInput(h);v.scrollLeft=240;v.scrollTop=60;v.dispatch('scroll');
    n['host-return-home'].click();h.finish();await flush();await flush();
    const open=n['host-list'].all().find(e=>e.tagName==='button' && e.textContent==='打开主机');assert.ok(open);open.click();await flush();
    n['host-restore-review'].checked=true;n['host-restore'].click();await flush();await flush();
    n['remote-review'].checked=true;n['remote-form'].dispatch('input',{target:n['remote-review']});
    n['remote-form'].dispatch('submit');await flush();
    v.scrollLeft=0;v.scrollTop=0;publishDashboard(h,blockedPane());
    n['remote-panes'].children.find(e=>e.tagName==='button' && e.textContent.startsWith('w1:p1')).click();
    h.emit({kind:'target_bound',generation:9,epoch:1,pane_id:'w1:p1',terminal_id:'term_a001'});
    assert.equal(v.scrollLeft,0,'target proof alone must not restore before a new full');
    h.emit({kind:'frame',generation:9,epoch:1,frame:{seq:1,full:true,cols:80,rows:24,bytes:[66]}});
    assert.equal(v.scrollLeft,240);assert.equal(v.scrollTop,60);
    const count=h.calls.length;v.scrollLeft=180;v.dispatch('scroll');
    assert.equal(h.calls.length,count,'local scrolling must not invoke transport');
    assert.equal(h.calls.filter(c=>c.name.includes('resize') || c.name==='remote_input_send').length,0);
  } finally {h.finish();await flush();h.restore();}
});

for(const [code,pattern] of [['host_key_mismatch',/主机公钥不匹配.*独立可信渠道.*不要直接替换/],['authentication_failed',/公钥认证失败/],['secret transport details',/连接或观察未完成/]]) {
  test(`fresh pairing failure explains ${code} without changing pin or retrying`,async()=>{
    const h=await setup();try {
      await pairAndConnect(h);const before=h.calls.filter(c=>c.name==='remote_observe').length;
      h.fail(code);await flush();await flush();
      assert.match(h.nodes['remote-status'].textContent,pattern);
      assert.doesNotMatch(h.nodes['remote-status'].textContent,/secret transport details/);
      assert.equal(h.nodes['remote-pin'].value,h.target.expectedHostKey);
      assert.equal(h.calls.filter(c=>c.name==='remote_observe').length,before);
      assert.equal(h.nodes['remote-connect'].disabled,true,'fresh review is required');
    } finally {h.finish();await flush();h.restore();}
  });
}

test('normal new host entry previews profile, fills every target field without writes, then requires independent device review',async()=>{
  const h=await setup(),n=h.nodes;
  try {
    n['host-open-remote'].click();n['add-herdr'].click();await flush();await flush();
    const before=h.calls.length;
    n['pair-target-review'].checked=true;n['pair-source-review'].checked=true;n['remote-review'].checked=true;n['host-restore-review'].checked=true;
    n['remote-private-key'].value='discard this temporary fixture';
    n['connection-profile-raw'].value=connectionProfiles.valid[3].raw;
    await n['connection-profile-preview'].onclick();
    assert.equal(h.calls.length,before);assert.equal(n['remote-host'].value,'');
    assert.ok(n['connection-profile-details'].textContent.includes(connectionProfiles.valid[3].fingerprint));
    n['connection-profile-apply'].click();
    const expected=JSON.parse(connectionProfiles.valid[3].raw);
    for(const [id,key] of [['remote-host','host'],['remote-port','port'],['remote-user','username'],['remote-session','session'],['remote-socket','socketPath'],['remote-herdr','herdrPath'],['remote-pin','expectedHostKey'],['remote-profile-provider','provider']]) assert.equal(String(n[id].value),String(expected[key]));
    assert.equal(h.calls.length,before);assert.equal(n['pair-mode'].checked,true);assert.equal(n['remote-private-key'].value,'');
    for(const id of ['pair-target-review','pair-source-review','remote-review','host-restore-review'])assert.equal(n[id].checked,false,id);
    assert.equal(n['pair-create'].disabled,true);n['pair-create'].click();await flush();assert.equal(h.calls.length,before);
    n['pair-target-review'].checked=true;n['remote-form'].dispatch('input',{target:n['pair-target-review']});
    n['pair-create'].click();await flush();await flush();await flush();
    assert.equal(h.calls.filter(x=>x.name==='pair_create').length,1);
    const created=h.calls.find(x=>x.name==='pair_create');assert.equal(created.args.config.expectedHostKey,expected.expectedHostKey);
    assert.equal(created.args.config.session,expected.session);assert.equal(h.calls.find(x=>x.name==='host_save').args.providerHint,expected.provider);assert.equal(n['remote-connect'].disabled,true);assert.equal(h.calls.filter(x=>x.name==='remote_observe').length,0);
    assert.equal(n['connection-profile-preview'].disabled,true);
    await n['connection-profile-preview'].onclick();n['connection-profile-apply'].click();
    assert.equal(h.calls.filter(x=>x.name==='pair_create').length,1);
  }finally{h.restore();}
});
test('uncertain key creation requires explicit same-host recovery without creating another key',async()=>{
  const h=await setup({pairCreate:()=>{throw 'key_write_unknown';},pendingStatus:()=>true,
    pairRecover:()=>({stored:true,state:'awaiting-host',request:pairingCameraFixture().request,fingerprint:'device-fingerprint'})}),n=h.nodes;
  try {
    n['host-open-remote'].click();n['add-herdr'].click();await flush();await flush();
    n['connection-profile-raw'].value=connectionProfiles.valid[0].raw;
    await n['connection-profile-preview'].onclick();n['connection-profile-apply'].click();
    n['pair-target-review'].checked=true;n['remote-form'].dispatch('input',{target:n['pair-target-review']});
    n['pair-create'].click();await flush();await flush();await flush();
    assert.equal(h.calls.filter(x=>x.name==='pair_create').length,1);
    assert.match(n['pair-status'].textContent,/创建结果未确认/);
    assert.equal(n['pair-pending-recover'].hidden,false);
    n['pair-pending-recover'].click();await flush();await flush();
    assert.equal(h.calls.filter(x=>x.name==='pair_recover_pending').length,1);
    assert.equal(h.calls.filter(x=>x.name==='pair_create').length,1);
    assert.equal(h.calls.filter(x=>x.name==='remote_observe').length,0);
  } finally {h.restore();}
});
test('discarding an uncertain identity needs confirmation and never creates another',async()=>{
  const h=await setup({pairCreate:()=>{throw 'key_write_unknown';},pendingStatus:()=>true}),n=h.nodes;
  try {
    n['host-open-remote'].click();n['add-herdr'].click();await flush();await flush();
    n['connection-profile-raw'].value=connectionProfiles.valid[0].raw;
    await n['connection-profile-preview'].onclick();n['connection-profile-apply'].click();
    n['pair-target-review'].checked=true;n['remote-form'].dispatch('input',{target:n['pair-target-review']});
    n['pair-create'].click();await flush();await flush();await flush();
    assert.equal(n['pair-pending-discard'].hidden,false);
    window.confirm=()=>false;n['pair-pending-discard'].click();await flush();
    assert.equal(h.calls.filter(x=>x.name==='pair_discard_pending').length,0);
    window.confirm=()=>true;n['pair-pending-discard'].click();await flush();await flush();
    assert.equal(h.calls.filter(x=>x.name==='pair_discard_pending').length,1);
    assert.equal(h.calls.filter(x=>x.name==='pair_create').length,1);
  } finally {h.restore();}
});
test('real new host camera entry previews before fill and rejects edits / saved-host identity',async()=>{
  const h=await setup({scanResponse:()=>connectionProfiles.valid[0].raw}),n=h.nodes;
  try {
    n['host-open-remote'].click();n['add-herdr'].click();await flush();await flush();const before=h.calls.length;
    await n['connection-profile-scan'].onclick();assert.equal(h.calls.length,before+1);assert.equal(n['remote-host'].value,'');
    n['remote-host'].value='edited.invalid';n['remote-form'].dispatch('input',{target:n['remote-host']});
    n['connection-profile-apply'].click();assert.equal(n['remote-host'].value,'edited.invalid');
    await n['connection-profile-preview'].onclick();n['connection-profile-apply'].click();
    assert.equal(n['remote-host'].value,JSON.parse(connectionProfiles.valid[0].raw).host);
    n['host-save'].click();await flush();await flush();await flush();
    assert.equal(n['connection-profile-preview'].disabled,true);
    const pin=n['remote-pin'].value;await n['connection-profile-scan'].onclick();assert.equal(n['remote-pin'].value,pin);
    assert.equal(h.calls.filter(x=>x.name==='pair_scan_response').length,1);
    assert.equal(h.calls.filter(x=>x.name==='pair_create'||x.name==='remote_observe').length,0);
  }finally{h.restore();}
});
test('real camera entry discards a result after home navigation, background or form edit',async()=>{
 for(const reason of ['home','background','edit']){
  let finish;const result=new Promise(resolve=>finish=resolve),h=await setup({scanResponse:()=>result}),n=h.nodes;
  try{n['host-open-remote'].click();n['add-herdr'].click();await flush();await flush();const work=n['connection-profile-scan'].onclick();
   if(reason==='home')n['host-return-home'].click();if(reason==='background')h.background();if(reason==='edit'){n['remote-host'].value='manual.invalid';n['remote-form'].dispatch('input',{target:n['remote-host']});}
   finish(connectionProfiles.valid[0].raw);await work;await flush();await flush();
   assert.equal(n['connection-profile-raw'].value,'');assert.equal(n['connection-profile-apply'].disabled,true);
   assert.equal(h.calls.filter(x=>['host_save','pair_create','remote_observe'].includes(x.name)).length,0);
  }finally{h.restore();}
 }
});

test('applied profile retains its visible overlay intent after target edits without retaining trust',async()=>{
 const h=await setup(),n=h.nodes;try{
  n['host-open-remote'].click();n['add-herdr'].click();await flush();await flush();
  n['connection-profile-raw'].value=connectionProfiles.valid[2].raw;await n['connection-profile-preview'].onclick();n['connection-profile-apply'].click();
  assert.match(n['remote-profile-network-note'].textContent,/zerotier/);
  n['remote-review'].checked=true;n['remote-form'].dispatch('input',{target:n['remote-review']});n['remote-form'].dispatch('submit');await flush();
  assert.equal(h.calls.filter(x=>x.name==='remote_observe').length,0);
  n['pair-target-review'].checked=true;
  n['remote-host'].value='manual-change.invalid';n['remote-form'].dispatch('input',{target:n['remote-host']});
  n['remote-port'].value='2202';n['remote-form'].dispatch('input',{target:n['remote-port']});
  assert.equal(n['remote-profile-provider'].value,'zerotier');assert.equal(n['pair-target-review'].checked,false);
  assert.equal(n['remote-review'].checked,false);assert.equal(n['connection-profile-fingerprint'].hidden,true);
  assert.equal(n['connection-profile-apply'].disabled,true);assert.equal(n['remote-connect'].disabled,true);
  n['remote-review'].checked=true;n['remote-form'].dispatch('input',{target:n['remote-review']});n['remote-form'].dispatch('submit');await flush();
  assert.equal(h.calls.filter(x=>x.name==='remote_observe').length,0);
  n['host-save'].click();await flush();await flush();await flush();
  const saved=h.calls.find(x=>x.name==='host_save');assert.equal(saved.args.providerHint,'zerotier');
  assert.equal(saved.args.config.host,'manual-change.invalid');assert.equal(saved.args.config.port,2202);
  n['host-save'].click();await flush();await flush();await flush();
  assert.equal(Object.hasOwn(h.calls.filter(x=>x.name==='host_save')[1].args,'providerHint'),false);
 }finally{h.restore();}
});
test('a saved bound overlay host keeps the ordinary reviewed pairing connection route',async()=>{
 const h=await setup(),n=h.nodes;try{
  n['host-open-remote'].click();n['add-herdr'].click();await flush();await flush();n['connection-profile-raw'].value=connectionProfiles.valid[1].raw;
  await n['connection-profile-preview'].onclick();n['connection-profile-apply'].click();n['host-save'].click();await flush();await flush();await flush();
  h.updateHost({provider:'tailscale',requiresNetworkBinding:true,networkProfileId:'net-fixture',deviceFingerprint:'device-fixture'});
  n['host-return-home'].click();await flush();await flush();await flush();
  const open=n['host-list'].children[0].children.find(x=>x.className==='saved-host-actions').children.find(x=>x.textContent==='打开主机');open.click();await flush();await flush();
  assert.equal(n['remote-profile-provider'].value,'tailscale');assert.equal(n['remote-connect'].disabled,true);
  n['host-restore-review'].checked=true;n['host-restore'].click();await flush();await flush();
  n['remote-review'].checked=true;n['remote-form'].dispatch('input',{target:n['remote-review']});
  assert.equal(n['remote-connect'].disabled,false);n['remote-form'].dispatch('submit');await flush();
  assert.equal(h.calls.filter(x=>x.name==='remote_observe').length,1);assert.equal(h.calls.find(x=>x.name==='remote_observe').args.hostId,'a'.repeat(32));
  h.finish();await flush();
 }finally{h.restore();}
});

test('manual targets do not receive provider hints, and rebuilding a new host isolates prior network intent',async()=>{
 const h=await setup(),n=h.nodes;try{
  n['host-open-remote'].click();n['add-herdr'].click();await flush();await flush();
  n['remote-host'].value='manual.invalid';n['remote-form'].dispatch('input',{target:n['remote-host']});
  n['host-save'].click();await flush();await flush();await flush();
  assert.equal(Object.hasOwn(h.calls.find(x=>x.name==='host_save').args,'providerHint'),false);
  n['host-return-home'].click();await flush();await flush();await flush();
  n['host-open-remote'].click();n['add-herdr'].click();await flush();await flush();
  n['connection-profile-raw'].value=connectionProfiles.valid[3].raw;await n['connection-profile-preview'].onclick();n['connection-profile-apply'].click();
  assert.equal(n['remote-profile-provider'].value,'easytier');
  n['host-save'].click();await flush();await flush();await flush();
  assert.equal(h.calls.filter(x=>x.name==='host_save')[1].args.providerHint,'easytier');
  n['host-return-home'].click();await flush();await flush();await flush();
  n['host-open-remote'].click();n['add-herdr'].click();await flush();await flush();
  assert.equal(n['remote-profile-provider'].value,'');assert.equal(n['remote-host'].value,'');
  n['remote-host'].value='another-manual.invalid';n['remote-form'].dispatch('input',{target:n['remote-host']});
  n['host-save'].click();await flush();await flush();await flush();
  assert.equal(Object.hasOwn(h.calls.filter(x=>x.name==='host_save')[2].args,'providerHint'),false);
 }finally{h.restore();}
});
test('explicitly adopting another profile changes network intent while a source edit alone does not',async()=>{
 const h=await setup(),n=h.nodes;try{
  n['host-open-remote'].click();n['add-herdr'].click();await flush();await flush();
  n['connection-profile-raw'].value=connectionProfiles.valid[1].raw;await n['connection-profile-preview'].onclick();n['connection-profile-apply'].click();
  n['connection-profile-raw'].value=connectionProfiles.valid[0].raw;n['connection-profile-raw'].dispatch('input');
  assert.equal(n['remote-profile-provider'].value,'tailscale');assert.equal(n['remote-connect'].disabled,true);
  await n['connection-profile-preview'].onclick();assert.equal(n['remote-profile-provider'].value,'tailscale');
  n['connection-profile-apply'].click();assert.equal(n['remote-profile-provider'].value,'direct');
  n['host-save'].click();await flush();await flush();await flush();
  assert.equal(h.calls.find(x=>x.name==='host_save').args.providerHint,'direct');
 }finally{h.restore();}
});

for(const timing of ['before-visible','after-visible'])test(`ordinary new-host native scan survives its single Activity round trip ${timing} without preserving trust`,async()=>{
 let finish;const pending=new Promise(resolve=>finish=resolve),h=await setup({scanResponse:()=>pending}),n=h.nodes;
 try{
  n['host-open-remote'].click();n['add-herdr'].click();await flush();await flush();
  n['remote-private-key'].value='fixture temporary credential';n['pair-target-review'].checked=true;
  n['remote-review'].checked=true;n['remote-form'].dispatch('input',{target:n['remote-review']});
  const before=h.calls.length,work=n['connection-profile-scan'].onclick();h.background();
  assert.equal(n['remote-private-key'].value,'');assert.equal(n['pair-target-review'].checked,false);assert.equal(n['remote-review'].checked,false);
  if(timing==='after-visible')h.foreground();finish(connectionProfiles.valid[0].raw);await work;
  assert.equal(n['remote-host'].value,'');assert.equal(n['connection-profile-raw'].value,'');assert.equal(n['connection-profile-apply'].disabled,true);
  if(timing==='before-visible')h.foreground();
  assert.equal(n['connection-profile-preview'].textContent,'重新查看本次扫描结果');assert.equal(n['connection-profile-preview'].disabled,false);
  await n['connection-profile-preview'].onclick();assert.equal(n['remote-host'].value,'');assert.equal(n['connection-profile-apply'].disabled,false);
  assert.deepEqual(h.calls.slice(before).filter(x=>x.name!=='network_list').map(x=>x.name),['pair_scan_response']);
  n['connection-profile-apply'].click();assert.equal(n['remote-host'].value,JSON.parse(connectionProfiles.valid[0].raw).host);
  assert.deepEqual(h.calls.slice(before).filter(x=>x.name!=='network_list').map(x=>x.name),['pair_scan_response']);assert.equal(n['pair-target-review'].checked,false);assert.equal(n['remote-review'].checked,false);
 }finally{h.restore();}
});

function pairingCameraFixture(now=Math.floor(Date.now()/1000)) {
 const request={version:2,type:'pairing-public-key-request',request_id:'c'.repeat(32),account:'u',host_key:'host-key',device:'Fixture',public_key:JSON.parse(connectionProfiles.valid[0].raw).expectedHostKey,issued_at:now,expires_at:now+300};
 const response={version:2,type:'pairing-binding-response',request_id:request.request_id,account:request.account,host_key:request.host_key,fingerprint:'device-fingerprint',issued_at:now,expires_at:now+200,status:'authorized',authorization_added:true};
 return {request:JSON.stringify(request),response:JSON.stringify(response),expires:request.expires_at};
}
async function createCameraPair(h) {
 const n=h.nodes;n['host-open-remote'].click();n['add-herdr'].click();await flush();await flush();
 const fields={'remote-host':h.target.host,'remote-port':'22','remote-user':'u','remote-pin':h.target.expectedHostKey,'remote-socket':h.target.socketPath,'remote-herdr':h.target.herdrPath,'remote-session':'work','host-save-name':'Fixture'};
 for(const [id,value] of Object.entries(fields))n[id].value=value;
 n['pair-mode'].checked=true;n['pair-target-review'].checked=true;n['pair-create'].click();await flush();await flush();await flush();
}
for(const timing of ['before-visible','after-visible','foreground'])test(`response scanner ${timing} requires explicit original-request re-view and separate authorization review`,async()=>{
 const fixture=pairingCameraFixture();let finish;const pending=new Promise(resolve=>finish=resolve),h=await setup({pairRequest:fixture.request,scanResponse:()=>pending}),n=h.nodes;
 try{
  await createCameraPair(h);assert.equal(n['pair-scan'].disabled,false);
  n['pair-source-review'].checked=true;n['remote-review'].checked=true;n['remote-private-key'].value='temporary fixture';
  const before=h.calls.length,work=n['pair-scan'].onclick();
  if(timing!=='foreground'){h.background();assert.equal(n['pair-source-review'].checked,false);assert.equal(n['remote-review'].checked,false);assert.equal(n['remote-private-key'].value,'');}
  if(timing==='after-visible')h.foreground();finish(fixture.response);await work;
  assert.equal(n['pair-response'].value,'');assert.equal(n['pair-accept'].disabled,true);assert.equal(n['pair-response-preview'].hidden,true);
  if(timing==='before-visible')h.foreground();
  assert.equal(n['pair-preview'].textContent,'重新查看本次响应扫描');n['pair-preview'].click();
  assert.equal(n['pair-response'].value,fixture.response);assert.equal(n['pair-response-preview'].hidden,false);assert.equal(n['pair-source-review'].checked,false);assert.equal(n['pair-accept'].disabled,true);
  assert.equal(n['remote-review'].checked,false);assert.deepEqual(h.calls.slice(before).filter(x=>x.name!=='network_list').map(x=>x.name),['pair_scan_response']);
  n['pair-accept'].click();await flush();assert.equal(h.calls.filter(x=>x.name==='pair_accept').length,0);
  n['pair-source-review'].checked=true;n['remote-form'].dispatch('input',{target:n['pair-source-review']});n['pair-accept'].click();await flush();await flush();await flush();
  assert.equal(h.calls.filter(x=>x.name==='pair_accept').length,1);assert.equal(h.calls.filter(x=>x.name==='pair_create').length,1);assert.equal(h.calls.filter(x=>x.name==='remote_observe').length,0);
 }finally{h.restore();}
});
for(const reason of ['edit','session','host-switch','expiry','cancel','pagehide','second-background'])test(`response scanner drops a late callback after ${reason}`,async()=>{
 const realNow=Date.now;let clock=realNow();Date.now=()=>clock;
 const fixture=pairingCameraFixture(Math.floor(clock/1000));let finish;const pending=new Promise(resolve=>finish=resolve),h=await setup({pairRequest:fixture.request,scanResponse:()=>pending}),n=h.nodes;
 try{
  await createCameraPair(h);const work=n['pair-scan'].onclick();h.background();
  if(reason==='edit'){n['pair-response'].value='manual';n['remote-form'].dispatch('input',{target:n['pair-response']});}
  if(reason==='session'){n['remote-session'].value='other';n['remote-form'].dispatch('input',{target:n['remote-session']});}
  if(reason==='host-switch'){h.foreground();n['host-return-home'].click();await flush();await flush();await flush();n['host-open-remote'].click();n['add-herdr'].click();await flush();await flush();}
  if(reason==='expiry')clock=fixture.expires*1000+1;
  if(reason==='cancel'){h.foreground();n['pair-cancel'].click();await flush();}
  if(reason==='pagehide')h.windowEvent('pagehide');if(reason==='second-background'){h.foreground();h.background();}
  finish(fixture.response);await work;h.foreground();await flush();await flush();
  assert.notEqual(n['pair-preview'].textContent,'重新查看本次响应扫描');n['pair-preview'].click();
  assert.notEqual(n['pair-response'].value,fixture.response);assert.equal(n['pair-accept'].disabled,true);
  assert.equal(h.calls.filter(x=>x.name==='pair_accept'||x.name==='remote_observe').length,0);
 }finally{h.restore();Date.now=realNow;}
});
test('response scan rejects another request/device and connection-profile bytes without crossing purposes',async()=>{
 for(const kind of ['other-request','other-device','connection-profile']){
  const fixture=pairingCameraFixture(),wrong=JSON.parse(fixture.response);if(kind==='other-request')wrong.request_id='d'.repeat(32);if(kind==='other-device')wrong.fingerprint='foreign-device';
  const h=await setup({pairRequest:fixture.request,scanResponse:()=>kind==='connection-profile'?connectionProfiles.valid[0].raw:JSON.stringify(wrong)}),n=h.nodes;
  try{await createCameraPair(h);await n['pair-scan'].onclick();assert.equal(n['pair-response'].value,'');assert.equal(n['connection-profile-raw'].value,'');assert.equal(n['pair-accept'].disabled,true);assert.notEqual(n['pair-preview'].textContent,'重新查看本次响应扫描');}finally{h.restore();}
 }
});

async function reviewResponse(h,raw,{accept=false}={}) {
 const n=h.nodes;n['pair-response'].value=raw;n['remote-form'].dispatch('input',{target:n['pair-response']});n['pair-preview'].click();
 if(accept){n['pair-source-review'].checked=true;n['remote-form'].dispatch('input',{target:n['pair-source-review']});n['pair-accept'].click();await flush();await flush();await flush();}
}
function revokedResponse(fixture,now=Math.floor(Date.now()/1000),changes={}) {
 return JSON.stringify({...JSON.parse(fixture.response),status:'revoked',issued_at:now,expires_at:now+120,...changes});
}
test('explicit public-request copy uses the exact awaiting-host bytes and displays independent handoff details',async()=>{
 const copied=[],fixture=pairingCameraFixture(),h=await setup({pairRequest:fixture.request,clipboardWrite:raw=>{copied.push(raw);return Promise.resolve();}}),n=h.nodes;
 try{await createCameraPair(h);const before=h.calls.length;
  assert.equal(n['pair-request-copy'].disabled,false);for(const value of ['c'.repeat(32),'u','host-key','device-fingerprint',String(fixture.expires)])assert.ok(n['pair-request-summary'].textContent.includes(value),value);
  await n['pair-request-copy'].onclick();assert.deepEqual(copied,[fixture.request]);assert.equal(n['pair-request'].value,fixture.request);assert.match(n['pair-handoff-status'].textContent,/已复制/);
  assert.equal(h.calls.length,before);assert.equal(n['pair-source-review'].checked,false);assert.equal(n['remote-review'].checked,false);
 }finally{h.restore();}
});
test('clipboard denial retains the readonly original and supports explicit system selection',async()=>{
 const fixture=pairingCameraFixture(),h=await setup({pairRequest:fixture.request,clipboardWrite:()=>Promise.reject(Error('NotAllowedError'))}),n=h.nodes;
 try{await createCameraPair(h);await n['pair-request-copy'].onclick();assert.equal(n['pair-request'].value,fixture.request);assert.match(n['pair-handoff-status'].textContent,/系统剪贴板写入不可用/);n['pair-request-select'].click();assert.equal(n['pair-request'].selected,true);assert.deepEqual(n['pair-request'].selection,[0,fixture.request.length]);}finally{h.restore();}
});
for(const reason of ['hidden','navigation','edit'])test(`late public clipboard completion cannot publish old handoff status after ${reason}`,async()=>{
 let finish;const pending=new Promise(resolve=>finish=resolve),copied=[],h=await setup({clipboardWrite:raw=>{copied.push(raw);return pending;}}),n=h.nodes;
 try{await createCameraPair(h);const original=n['pair-request'].value,work=n['pair-request-copy'].onclick();assert.deepEqual(copied,[original]);
  if(reason==='hidden')h.background();if(reason==='navigation'){n['host-return-home'].click();await flush();await flush();await flush();n['host-open-remote'].click();n['add-herdr'].click();await flush();await flush();}if(reason==='edit')n['remote-form'].dispatch('input',{target:n['pair-response']});
  finish();await work;assert.equal(n['pair-handoff-status'].textContent,'');assert.equal(copied.length,1);
  if(reason==='navigation'){assert.equal(n['pair-request'].value,'');assert.equal(n['pair-request-summary'].textContent,'');}
 }finally{h.restore();}
});
for(const condition of ['expired','cancelled','authorized','explicit-revocation'])test(`request handoff is locked for ${condition}`,async()=>{
 const realNow=Date.now;let clock=realNow();Date.now=()=>clock;const fixture=pairingCameraFixture(Math.floor(clock/1000)),copied=[],h=await setup({pairRequest:fixture.request,clipboardWrite:raw=>copied.push(raw)}),n=h.nodes;
 try{await createCameraPair(h);if(condition==='expired')clock=(fixture.expires+1)*1000;if(condition==='cancelled'){n['pair-cancel'].click();await flush();}if(condition==='authorized')await reviewResponse(h,fixture.response,{accept:true});if(condition==='explicit-revocation'){n['pair-revocation-mode'].checked=true;n['remote-form'].dispatch('input',{target:n['pair-revocation-mode']});}
  await n['pair-request-copy'].onclick();assert.equal(n['pair-request-copy'].disabled,true);assert.deepEqual(copied,[]);
 }finally{h.restore();Date.now=realNow;}
});
for(const state of ['expired','cancelled','authorized'])test(`fresh manual revocation of an ${state} original rejects authorization and invalidates retained device without deleting it`,async()=>{
 const realNow=Date.now;let clock=realNow();Date.now=()=>clock;const fixture=pairingCameraFixture(Math.floor(clock/1000)),h=await setup({pairRequest:fixture.request}),n=h.nodes;
 try{await createCameraPair(h);if(state==='expired')clock=(fixture.expires+10)*1000;if(state==='cancelled'){n['pair-cancel'].click();await flush();}if(state==='authorized')await reviewResponse(h,fixture.response,{accept:true});
  const baseline=h.calls.length,now=Math.floor(clock/1000),authorization=JSON.stringify({...JSON.parse(fixture.response),issued_at:now,expires_at:now+120});
  await reviewResponse(h,authorization,{accept:true});assert.equal(h.calls.slice(baseline).filter(x=>x.name==='pair_accept').length,0);assert.equal(n['pair-accept'].disabled,true);
  await reviewResponse(h,revokedResponse(fixture,now));assert.equal(n['pair-revocation-mode'].checked,true);assert.equal(n['pair-source-review'].checked,false);
  n['remote-review'].checked=true;n['remote-form'].dispatch('input',{target:n['remote-review']});n['remote-form'].dispatch('submit');n['pair-create'].click();await flush();assert.equal(h.calls.slice(baseline).filter(x=>x.name==='remote_observe'||x.name==='pair_create').length,0);
  await reviewResponse(h,revokedResponse(fixture,now),{accept:true});assert.match(n['pair-status'].textContent,/目录已确认撤销/);assert.equal(n['remote-connect'].disabled,true);assert.equal(n['pair-request-copy'].disabled,true);
  assert.equal(h.calls.slice(baseline).filter(x=>x.name==='pair_accept').length,1);assert.equal(h.calls.slice(baseline).filter(x=>x.name==='pair_reset').length,0);
  const actions=n['host-list'].children[0].children.find(x=>x.className==='saved-host-actions');assert.equal(expandedActions(actions).find(x=>x.textContent==='新终端标签').disabled,true);
  assert.ok(n['pair-request-summary'].textContent.includes('device-fingerprint'));
 }finally{h.restore();Date.now=realNow;}
});
for(const originalState of ['expired','cancelled','authorized'])for(const timing of ['before-visible','after-visible'])test(`${originalState} original accepts only fresh revocation camera return ${timing}`,async()=>{
 const realNow=Date.now;let clock=realNow();Date.now=()=>clock;const fixture=pairingCameraFixture(Math.floor(clock/1000));let finish;const pending=new Promise(resolve=>finish=resolve),h=await setup({pairRequest:fixture.request,scanResponse:()=>pending}),n=h.nodes;
 try{await createCameraPair(h);if(originalState==='cancelled'){n['pair-cancel'].click();await flush();}if(originalState==='authorized')await reviewResponse(h,fixture.response,{accept:true});clock=(fixture.expires+10)*1000;n['remote-form'].dispatch('input',{target:n['pair-response']});assert.equal(n['pair-scan'].disabled,false);
  const previous=n['pair-response'].value,work=n['pair-scan'].onclick();h.background();if(timing==='after-visible')h.foreground();const receipt=revokedResponse(fixture,Math.floor(clock/1000));finish(receipt);await work;if(timing==='before-visible')h.foreground();
  assert.equal(n['pair-response'].value,previous);n['pair-preview'].click();assert.equal(n['pair-response'].value,receipt);assert.equal(n['pair-source-review'].checked,false);assert.equal(n['pair-accept'].disabled,true);
  n['pair-source-review'].checked=true;n['remote-form'].dispatch('input',{target:n['pair-source-review']});n['pair-accept'].click();await flush();await flush();await flush();assert.match(n['pair-status'].textContent,/目录已确认撤销/);
 }finally{h.restore();Date.now=realNow;}
});
test('manual and scanned revocation reject wrong identities, old receipts and future receipts identically',async()=>{
 for(const changes of [{request_id:'d'.repeat(32)},{account:'other'},{host_key:'foreign'},{fingerprint:'other-device'},{issued_at:1,expires_at:2},{issued_at:Math.floor(Date.now()/1000)+60}]){
  const fixture=pairingCameraFixture(),raw=revokedResponse(fixture,Math.floor(Date.now()/1000),changes),h=await setup({pairRequest:fixture.request,scanResponse:()=>raw}),n=h.nodes;
  try{await createCameraPair(h);n['pair-cancel'].click();await flush();const before=h.calls.length;await reviewResponse(h,raw,{accept:true});await n['pair-scan'].onclick();n['pair-preview'].click();assert.equal(n['pair-accept'].disabled,true);assert.equal(h.calls.slice(before).filter(x=>x.name==='pair_accept').length,0);}finally{h.restore();}
 }
});
test('revocation persistence failure locks runtime routes without claiming durable success or deleting the key',async()=>{
 const fixture=pairingCameraFixture(),h=await setup({pairRequest:fixture.request,pairAcceptStored:false}),n=h.nodes;
 try{await createCameraPair(h);await reviewResponse(h,fixture.response,{accept:true});const baseline=h.calls.length;await reviewResponse(h,revokedResponse(fixture),{accept:true});
  assert.match(n['pair-status'].textContent,/本次运行已停用/);assert.match(n['pair-status'].textContent,/保存未确认/);assert.doesNotMatch(n['pair-status'].textContent,/目录已确认撤销/);assert.equal(n['remote-connect'].disabled,true);
  n['host-return-home'].click();await flush();await flush();await flush();const actions=n['host-list'].children[0].children.find(x=>x.className==='saved-host-actions');assert.equal(expandedActions(actions).find(x=>x.textContent==='新终端标签').disabled,true);expandedActions(actions).find(x=>x.textContent==='打开主机').click();await flush();
  assert.equal(h.calls.slice(baseline).filter(x=>['host_restore','host_select','pair_reset','remote_observe'].includes(x.name)).length,0);assert.match(n['host-home-status'].textContent,/不能恢复旧授权/);
 }finally{h.restore();}
});
test('restoring a retained revoked record displays the original but cannot copy, create or connect',async()=>{
 const fixture=pairingCameraFixture(),h=await setup({pairRequest:fixture.request}),n=h.nodes;
 try{await createCameraPair(h);await reviewResponse(h,revokedResponse(fixture),{accept:true});n['host-return-home'].click();await flush();await flush();await flush();const actions=n['host-list'].children[0].children.find(x=>x.className==='saved-host-actions');expandedActions(actions).find(x=>x.textContent==='打开主机').click();await flush();await flush();
  n['host-restore-review'].checked=true;n['host-restore'].click();await flush();await flush();assert.match(n['pair-status'].textContent,/原设备记录已撤销/);assert.equal(n['pair-request'].value,fixture.request);assert.equal(n['pair-request-copy'].disabled,true);assert.equal(n['pair-create'].disabled,true);assert.equal(n['remote-connect'].disabled,true);
 }finally{h.restore();}
});
test('an existing observation remains guarded until explicit stop before revocation review',async()=>{
 const h=await setup(),n=h.nodes;try{await pairAndConnect(h);h.emit({kind:'stage',generation:9,stage:'authenticated'});const fixture={response:n['pair-response'].value};n['pair-response'].value=revokedResponse(fixture);const before=h.calls.length;n['pair-preview'].click();n['pair-source-review'].checked=true;n['pair-accept'].click();await flush();assert.equal(h.calls.slice(before).filter(x=>x.name==='pair_accept').length,0);
  n['remote-cancel'].click();h.finish();await flush();await flush();await reviewResponse(h,revokedResponse(fixture),{accept:true});assert.match(n['pair-status'].textContent,/目录已确认撤销/);assert.equal(n['remote-input-controls'].hidden,true);
 }finally{h.restore();}
});
test('a successful native revoke still requires matching catalog readback before durable confirmation',async()=>{
 const fixture=pairingCameraFixture(),h=await setup({pairRequest:fixture.request}),n=h.nodes;
 try{await createCameraPair(h);h.setRead((name,value)=>name==='host_list'?value.map(host=>({...host,pairingStatus:'authorized'})):value);
  await reviewResponse(h,revokedResponse(fixture),{accept:true});assert.match(n['pair-status'].textContent,/目录读回未确认/);assert.doesNotMatch(n['pair-status'].textContent,/目录已确认撤销/);assert.equal(n['remote-connect'].disabled,true);
  const actions=n['host-list'].children[0].children.find(x=>x.className==='saved-host-actions');assert.equal(expandedActions(actions).find(x=>x.textContent==='新终端标签').disabled,true);
 }finally{h.restore();}
});

test('ordinary Android pairing handoff sends only matching native record IDs and checks page completion identity',async()=>{
 const commands=[],fixture=pairingCameraFixture(),copy=createPublicRequestClipboard({shell:{current:()=> 'android'},callNative:async(name,args)=>{commands.push({name,args});return {...args,copied:true};},webClipboard:()=>{throw Error('must not fall back');}}),h=await setup({pairRequest:fixture.request,clipboardWrite:copy}),n=h.nodes;
 try{await createCameraPair(h);await n['pair-request-copy'].onclick();assert.deepEqual(commands,[{name:'pair_copy_request',args:{hostId:'a'.repeat(32),requestId:'c'.repeat(32)}}]);assert.match(n['pair-handoff-status'].textContent,/已复制/);assert.equal(n['pair-request'].value,fixture.request);}finally{h.restore();}
});


for(const mode of ['identity','host'])test(`pending ${mode} cleanup retains its narrow intent across a failed retry and requires fresh confirmation`,async()=>{
 let attempts=0;const h=await setup({hostCleanupRetry:(args,records)=>{attempts++;assert.deepEqual(args,{id:'a'.repeat(32)});if(attempts===1)throw Error('device_key_delete_unconfirmed');if(mode==='host')records.length=0;else Object.assign(records[0],{keyDeletionPending:false,keyCleanupMode:null,deviceFingerprint:null,pairingStatus:null});return {hostId:args.id,keyDeleted:true,hostRemoved:mode==='host',mode};}}),n=h.nodes;
 try{
  await createCameraPair(h);h.updateHost({keyDeletionPending:true,keyCleanupMode:mode,enabled:false});n['host-return-home'].click();await flush();await flush();
  const actions=()=>n['host-list'].children[0].children.find(x=>x.className==='saved-host-actions');
  assert.ok(n['host-list'].children[0].all().some(x=>x.textContent.includes('待确认')));
  assert.equal(expandedActions(actions()).find(x=>x.textContent==='打开主机').disabled,true);assert.equal(expandedActions(actions()).some(x=>x.textContent==='启用'),false);
  const retryLabel=mode==='identity'?'重试仅清理设备身份':'重试移除主机资料';
  let retry=expandedActions(actions()).find(x=>x.textContent===retryLabel);retry.click();await flush();assert.equal(attempts,0);
  if(mode==='identity')assert.match(retry.textContent,/仅清身份，保留主机资料/);retry.click();await flush();await flush();assert.equal(attempts,1);
  assert.ok(n['host-list'].children.length);assert.match(n['host-home-status'].textContent,/删除未确认/);assert.doesNotMatch(n['host-home-status'].textContent,/连接已停用/);
  retry=expandedActions(actions()).find(x=>x.textContent===retryLabel);retry.click();await flush();assert.equal(attempts,1);
  retry.click();await flush();await flush();assert.equal(attempts,2);assert.equal(n['host-list'].children.length,mode==='host'?0:1);
  assert.equal(h.calls.filter(x=>x.name==='host_remove').length,0);
  if(mode==='identity'){assert.match(n['host-home-status'].textContent,/主机公开资料已保留/);assert.equal(n['host-list'].children[0].children[0].children[0].textContent,'Fixture');assert.ok(expandedActions(actions()).find(x=>x.textContent==='启用'));}
 }finally{h.restore();}
});
for(const error of ['connection_active','host_storage_unavailable'])test(`delete failure before disable (${error}) never claims the host stopped`,async()=>{
 const h=await setup({hostRemove:()=>{throw Error(error);}}),n=h.nodes;
 try{await createCameraPair(h);n['host-return-home'].click();await flush();await flush();
  const actions=()=>n['host-list'].children[0].children.find(x=>x.className==='saved-host-actions');const remove=expandedActions(actions()).find(x=>x.textContent==='移除');remove.click();remove.click();await flush();await flush();
  assert.match(n['host-home-status'].textContent,/本机删除未确认/);assert.doesNotMatch(n['host-home-status'].textContent,/连接已停用|原引用保留/);assert.equal(expandedActions(actions()).find(x=>x.textContent==='打开主机').disabled,false);
 }finally{h.restore();}
});

test('delete failure with unavailable directory readback still reports an unconfirmed result neutrally',async()=>{
 let failed=false;const h=await setup({hostRemove:()=>{failed=true;throw Error('host_storage_unavailable');}}),n=h.nodes;
 try{await createCameraPair(h);n['host-return-home'].click();await flush();await flush();h.setRead((name,value)=>{if(failed && name==='host_list')throw Error('readback_unavailable');return value;});
  const actions=n['host-list'].children[0].children.find(x=>x.className==='saved-host-actions');const remove=expandedActions(actions).find(x=>x.textContent==='移除');remove.click();remove.click();await flush();await flush();
  assert.match(n['host-home-status'].textContent,/本机删除未确认/);assert.doesNotMatch(n['host-home-status'].textContent,/连接已停用|原引用保留/);
 }finally{h.restore();}
});

test('paired observation sizes its local canvas before write and acknowledges only after render',async()=>{
  const h=await setup();try {
    await pairAndConnect(h);publishDashboard(h,blockedPane());
    h.nodes['remote-panes'].children.find(e=>e.tagName==='button' && e.textContent.startsWith('w1:p1')).click();
    h.emit({kind:'target_bound',generation:9,epoch:1,pane_id:'w1:p1',terminal_id:'term_a001'});
    h.emit({kind:'frame',generation:9,epoch:1,frame:{seq:1,full:true,cols:119,rows:40,bytes:[65]}});
    const terminal=h.terminal;assert.equal(terminal.cols,119);assert.equal(terminal.rows,40);
    let done;const events=[];terminal.resize=(cols,rows)=>{events.push(['resize',cols,rows]);terminal.cols=cols;terminal.rows=rows;};
    terminal.write=(_bytes,ack)=>{events.push(['write',terminal.cols,terminal.rows]);done=ack;};
    const ackCount=()=>h.calls.filter(c=>c.name==='remote_ack').length;
    assert.equal(ackCount(),1);
    h.emit({kind:'frame',generation:9,epoch:1,frame:{seq:2,full:true,cols:100,rows:30,bytes:[66]}});
    assert.deepEqual(events,[['resize',100,30],['write',100,30]]);assert.equal(ackCount(),1);
    done();assert.equal(ackCount(),2);assert.match(h.nodes['remote-captured'].textContent,/100 × 30/);
    assert.equal(h.calls.some(c=>/resize/i.test(c.name)),false);await flush();
  } finally {h.restore();}
});


test('paired form sends the explicitly selected observer canvas on connect',async()=>{
  const h=await setup();try {
    await pairAndConnect(h,'160x50');
    const call=h.calls.find(c=>c.name==='remote_observe');assert.deepEqual(call.args.canvas,{cols:160,rows:50});
    assert.equal(h.nodes['remote-fields'].disabled,true);assert.equal(h.calls.some(c=>/resize/i.test(c.name)),false);
    await flush();
  } finally {h.restore();}
});

test('paired function keys send once only with active focus and consume rejected modifiers',async()=>{
  const h=await setup(), n=h.nodes;try {
    await openInput(h);
    const all=()=>n['remote-input-keys'].all();
    const expand=all().find(e=>e.textContent==='更多键');
    const key=name=>all().find(e=>e.dataset.remoteKey===name);
    assert.equal(expand.disabled,true);key('f1').click();assert.equal(h.calls.filter(c=>c.name==='remote_input_send').length,0);
    n['remote-input-direct'].click();await flush();await flush();assert.equal(document.activeElement,h.terminal.textarea);
    expand.click();assert.equal(expand.attrs['aria-expanded'],'true');
    key('f1').click();await flush();await flush();
    n['remote-modifier-ctrl'].click();n['remote-modifier-alt'].click();key('f4').click();await flush();await flush();
    n['remote-modifier-alt'].click();key('insert').click();await flush();await flush();
    n['remote-modifier-ctrl'].click();key('backspace').click();await flush();await flush();
    key('backspace').click();await flush();await flush();
    key('shift-tab').click();await flush();await flush();
    const writes=h.calls.filter(c=>c.name==='remote_input_send').map(c=>Buffer.from(c.args.bytes).toString('hex'));
    assert.deepEqual(writes,['1b4f50','1b5b313b3753','1b5b323b337e','7f','1b5b5a']);
    n['remote-modifier-ctrl'].click();expand.click();key('f2').click();await flush();
    assert.equal(h.calls.filter(c=>c.name==='remote_input_send').length,5);
    expand.click();key('f2').click();await flush();await flush();
    assert.equal(Buffer.from(h.calls.filter(c=>c.name==='remote_input_send').at(-1).args.bytes).toString('hex'),'1b4f51');
    h.background();key('f3').click();await flush();assert.equal(h.calls.filter(c=>c.name==='remote_input_send').length,6);
  } finally {h.finish();await flush();h.restore();}
});

test('paired function keys cannot send while composing or in draft',async()=>{
  const h=await setup(),n=h.nodes;try {
    await openInput(h);n['remote-input-direct'].click();await flush();await flush();
    const all=()=>n['remote-input-keys'].all(),expand=all().find(e=>e.textContent==='更多键'),key=all().find(e=>e.dataset.remoteKey==='f1');
    expand.click();h.terminal.textarea.dispatch('compositionstart');assert.equal(expand.disabled,true);key.click();
    h.terminal.textarea.dispatch('compositionend');await flush();assert.equal(h.calls.filter(c=>c.name==='remote_input_send').length,0);
    n['remote-input-draft-mode'].click();await flush();await flush();key.click();assert.equal(h.calls.filter(c=>c.name==='remote_input_send').length,0);
  } finally {h.finish();await flush();h.restore();}
});

test('keyboard navigation inside auxiliary toolbar retains lease only until focus leaves it',async()=>{
  const h=await setup(),n=h.nodes;try {
    await openInput(h);n['remote-input-direct'].click();await flush();await flush();
    const all=()=>n['remote-input-keys'].all(),expand=all().find(e=>e.textContent==='更多键');
    h.terminal.textarea.dispatch('blur',{relatedTarget:expand});document.activeElement=expand;
    expand.click();const key=all().find(e=>e.dataset.remoteKey==='f1');document.activeElement=key;key.click();await flush();await flush();
    assert.equal(Buffer.from(h.calls.filter(c=>c.name==='remote_input_send')[0].args.bytes).toString('hex'),'1b4f50');
    document.activeElement=document.body;n['remote-input-keys'].dispatch('focusout',{relatedTarget:document.body});key.click();await flush();
    assert.equal(h.calls.filter(c=>c.name==='remote_input_send').length,1);
  } finally {h.finish();await flush();h.restore();}
});

test('paired frame updates preserve accurate input status without repeating live announcements',async()=>{
  const h=await setup(),n=h.nodes;
  try {
    await openInput(h);
    assert.match(n['remote-status'].textContent,/观察已连接/);
    assert.match(n['remote-input-status'].textContent,/观察模式/);
    n['remote-input-direct'].click();await flush();await flush();
    assert.match(n['remote-input-status'].textContent,/逐键输入已启用/);
    let status=n['remote-status'].textContent,writes=0;
    Object.defineProperty(n['remote-status'],'textContent',{configurable:true,get:()=>status,set:value=>{writes++;status=value;}});
    for(const [seq,full] of [[2,false],[3,true]])h.emit({kind:'frame',generation:9,epoch:1,frame:{seq,full,cols:80,rows:24,bytes:[65]}});
    assert.equal(writes,0);assert.match(n['remote-input-status'].textContent,/逐键输入已启用/);
    assert.doesNotMatch(n['remote-captured'].textContent,/只读/);
    n['remote-input-draft-mode'].click();await flush();await flush();
    assert.match(n['remote-input-status'].textContent,/草稿仅在核对/);
    h.emit({kind:'frame',generation:9,epoch:1,frame:{seq:4,full:false,cols:80,rows:24,bytes:[65]}});
    assert.match(n['remote-input-status'].textContent,/草稿仅在核对/);assert.equal(writes,0);
    h.emit({kind:'input_ready',generation:9,epoch:1,unknown:true,recovery_status:'pending'});
    h.emit({kind:'frame',generation:9,epoch:1,frame:{seq:5,full:true,cols:80,rows:24,bytes:[65]}});
    assert.match(n['remote-input-status'].textContent,/未确认/);assert.equal(writes,0);
    n['remote-cancel'].click();assert.match(n['remote-captured'].textContent,/陈旧/);
  } finally {h.restore();}
});

test('stopping after a finished TUI session still marks the frame stale',async()=>{
  const h=await setup(),n=h.nodes;
  try {
    await openInput(h);
    n['remote-input-direct'].click();await flush();await flush();
    const all=()=>n['remote-input-keys'].all(),expand=all().find(e=>e.textContent==='更多键');
    expand.click();
    // The auxiliary keys mirror the guarded TUI run's closing sequence: focus
    // stays on the terminal textarea and the expanded panel remains open.
    for(const name of ['f1','f1','insert','delete','backspace','shift-tab','f5','f10']) {
      const key=all().find(e=>e.dataset.remoteKey===name);
      if(!key)throw Error('missing key '+name);
      key.click();await flush();await flush();
    }
    assert.equal(document.activeElement,h.terminal.textarea);
    n['remote-cancel'].click();
    assert.match(n['remote-captured'].textContent,/陈旧/);
    assert.equal(n['remote-captured'].dataset.state,'stale');
  } finally {h.finish();await flush();h.restore();}
});

test('live task snapshots retain focused task buttons, revoke old tickets and refresh after focus leaves',async()=>{
 const h=await setup(),n=h.nodes;
 try {
  await pairAndConnect(h);publishDashboard(h,blockedPane());
  const panel=n['host-task-board'],button=panel.all().find(e=>e.dataset.blockedTarget);
  assert.ok(button);button.focus();const oldChildren=[...panel.children];
  h.emit({kind:'dashboard_watch',generation:9,update:{epoch:1,revision:2,phase:'fresh',reason:'updated',panes:blockedPane()}});
  assert.equal(document.activeElement,button);assert.ok(panel.contains(button));assert.deepEqual(panel.children.slice(0,oldChildren.length),oldChildren);
  assert.equal(panel.children.filter(e=>e.dataset.summaryDeferred).length,1);
  h.emit({kind:'dashboard_watch',generation:9,update:{epoch:1,revision:3,phase:'fresh',reason:'updated again',panes:blockedPane()}});
  assert.equal(panel.children.filter(e=>e.dataset.summaryDeferred).length,1);button.click();await flush();
  assert.equal(n['view-tabs'].children.length,0,'old ticket cannot open a new target after a newer snapshot');
  document.activeElement=n['remote-cancel'];panel.dispatch('focusout',{relatedTarget:n['remote-cancel']});await flush();
  assert.ok(!panel.contains(button));assert.equal(panel.children.filter(e=>e.dataset.summaryDeferred).length,0);assert.match(panel.all().find(e=>e.dataset.blockedTarget).textContent,/观察受阻目标/);
  const current=panel.all().find(e=>e.dataset.blockedTarget);current.focus();h.finish();await flush();assert.ok(panel.contains(current));
  document.activeElement=document.body;panel.dispatch('focusout',{relatedTarget:document.body});await flush();
  assert.match(panel.all().find(e=>e.dataset.blockedTarget).textContent,/重新核查此目标/);
  assert.equal(h.calls.filter(c=>c.name==='remote_input_send'||c.name==='remote_tab_input_send'||/resize/.test(c.name)).length,0);
 } finally {h.finish();await flush();h.restore();}
});

test('normal paired font page switches both real theme samples without input or remote calls',async()=>{
 const prior=globalThis.fetch,glyphs=JSON.parse(await readFile(new URL('../../shared/terminal-font-diagnostics-v1.json',import.meta.url),'utf8')),text=await readFile(new URL('../../shared/theme-prompt-samples-v1.json',import.meta.url),'utf8'),themes=JSON.parse(text),reads=[];
 globalThis.fetch=async url=>{reads.push(url);return url==='/shared/theme-prompt-samples-v1.json'?{ok:true,text:async()=>text}:{ok:true,json:async()=>glyphs};};
 let clipboardReads=0;const h=await setup({clipboardRead:async()=>{clipboardReads++;return 'never';}});
 try {
  await openInput(h);const observed=h.terminal;h.nodes['remote-font-diagnostics'].click();await flush();await flush();
  const panel=document.body.children.find(e=>e.attrs['aria-label']==='字体与字符诊断'),choice=panel.all().find(e=>e.attrs['aria-label']==='诊断样例');const before=h.calls.length;
  for(const sample of themes.samples){choice.focus();choice.value=sample.id;choice.onchange();await flush();await flush();assert.equal(document.activeElement,choice);assert.deepEqual(h.terminal.writes,[sample.ansi]);assert.equal(h.terminal.options.cols,40);assert.equal(h.terminal.options.rows,3);assert.equal(h.terminal.textarea.disabled,true);const status=panel.all().find(e=>e.attrs.role==='status');assert.equal(status.dataset.expectedCursorColumn,String(sample.cursorColumn));assert.equal(status.dataset.expectedCursorRow,String(sample.cursorRow));assert.equal(status.dataset.sampleId,sample.id);assert.equal(status.dataset.columns,'40');assert.equal(status.dataset.rows,'3');}
  assert.equal(h.calls.length,before);assert.equal(clipboardReads,0);observed.data('disabled');assert.equal(h.calls.filter(c=>c.name==='remote_input_send'||/resize/.test(c.name)).length,0);
  panel.children.find(e=>e.textContent==='关闭诊断').click();assert.equal(document.activeElement,h.nodes['remote-font-diagnostics']);assert.ok(reads.includes('/shared/theme-prompt-samples-v1.json'));
 } finally {h.finish();await flush();h.restore();globalThis.fetch=prior;}
});

test('paired normal entry retains staged connection facts after auth failure without disclosing native content',async()=>{
 const h=await setup(),n=h.nodes;try{
  await pairAndConnect(h);const box=n['remote-connection-diagnostics'],row=id=>box.all().find(e=>e.dataset.connectionStage===id);
  assert.equal(row('network').dataset.stageState,'pending');h.emit({kind:'stage',generation:9,stage:'host-key-verified'});assert.equal(row('hostKey').dataset.stageState,'verified');assert.equal(row('network').dataset.stageState,'verified');
  h.fail('authentication_failed');await flush();await flush();assert.equal(row('hostKey').dataset.stageState,'verified');assert.equal(row('authentication').dataset.stageState,'failed');assert.equal(row('dashboard').dataset.stageState,'unknown');assert.equal(row('terminal').dataset.stageState,'unknown');
  h.emit({kind:'stage',generation:9,stage:'authenticated'});assert.equal(row('authentication').dataset.stageState,'failed');
  n['host-return-home'].click();await flush();await flush();n['host-list'].children[0].all().find(e=>e.textContent==='打开主机').click();await flush();await flush();assert.equal(box.children[0].hidden,false);assert.equal(row('hostKey').dataset.stageState,'verified');
  assert.equal(h.calls.filter(c=>c.name==='remote_observe').length,1);assert.equal(h.calls.filter(c=>c.name==='remote_input_send'||/resize/.test(c.name)).length,0);
 }finally{h.finish();await flush();h.restore();}
});

test('paired diagnostics require accepted dashboard and original target full render; pane selectors bind actual ids',async()=>{
 const h=await setup(),n=h.nodes;try{
  await pairAndConnect(h);h.emit({kind:'stage',generation:9,stage:'host-key-verified'});h.emit({kind:'stage',generation:9,stage:'authenticated'});publishDashboard(h,blockedPane());const row=id=>n['remote-connection-diagnostics'].all().find(e=>e.dataset.connectionStage===id);
  assert.equal(row('dashboard').dataset.stageState,'verified');assert.equal(row('terminal').dataset.stageState,'unknown');
  const button=n['remote-panes'].children.find(e=>e.dataset.paneId==='w1:p1');assert.equal(button.dataset.terminalId,'term_a001');button.click();await flush();h.emit({kind:'target_bound',generation:9,epoch:1,pane_id:'w1:p1',terminal_id:'term_a001'});assert.equal(row('terminal').dataset.stageState,'pending');
  h.emit({kind:'frame',generation:9,epoch:1,frame:{seq:1,full:true,cols:80,rows:24,bytes:[65]}});assert.equal(row('terminal').dataset.stageState,'verified');n['remote-cancel'].click();assert.equal(row('terminal').dataset.stageState,'verified');assert.match(n['remote-connection-diagnostics'].all().find(e=>e.dataset.attemptState).children[2].textContent,/已结束/);
 }finally{h.finish();await flush();h.restore();}
});

test('saved host search intersects public fields, keeps card identity and never touches native state', async () => {
  const h = await setup(), n = h.nodes;
  try {
    const host = (id, session, provider, extra={}) => ({
      id, name:'同名主机', enabled:true, provider,
      target:{...h.target, session, host:id+'.example', username:'not-searchable-user'},
      ...extra,
    });
    const records = [
      host('first','Board-中文','direct'),
      host('second','Night','direct',{networkProfileId:'net1'}),
      host('third','Day','tailscale',{networkProfileId:'removed'}),
    ];
    h.setRead((name,value) => name === 'host_list' ? records :
      {...value,profiles:[{id:'net1',revision:1,provider:'easytier'}]});
    n['host-return-home'].click(); await flush(); await flush();
    const cards=[...n['host-list'].children];
    const visible=()=>cards.filter(card=>!card.hidden).map(card=>card.dataset.hostId);
    const search=value=>{n['host-query'].value=value;n['host-query'].dispatch('input');};
    const callCount=h.calls.length;
    assert.deepEqual(visible(),['first','second','third']);
    assert.match(cards[1].children[1].textContent,/已绑定 EasyTier/);
    assert.match(cards[2].children[1].textContent,/绑定网络资料不可用/);
    for (const [query,expected] of [
      ['同名',['first','second','third']], ['中文',['first']], [' nIgHt ',['second']],
      ['second.example',['second']], ['easyTier',['second']], ['direct',['first']],
      ['tailscale',[]], ['not-searchable-user',[]], ['fixture private',[]],
    ]) {
      search(query);assert.deepEqual(visible(),expected);
    }
    assert.match(n['host-filter-status'].textContent,/没有匹配.*0 \/ 3/);
    n['host-query-clear'].click();
    assert.deepEqual(visible(),['first','second','third']);
    assert.equal(n['host-query'].value,'');
    assert.equal(document.activeElement,n['host-query']);
    assert.deepEqual(n['host-list'].children,cards);
    assert.equal(n['host-tabs'].children.length,3);
    assert.equal(h.calls.length,callCount);
  } finally { h.restore(); }
});

test('home can filter historical blocked tasks without turning a stopped connection into a current one', async () => {
  const h=await setup(),n=h.nodes;
  try {
    await pairAndConnect(h);publishDashboard(h,blockedPane());
    n['host-return-home'].click();await flush();await flush();
    const baseline=h.calls.length,card=n['host-list'].children[0];
    const state=value=>{n['host-attention'].value=value;n['host-attention'].dispatch('change');};
    n['host-filter-current'].click();assert.equal(n['host-attention'].value,'current');assert.equal(card.hidden,true);assert.match(n['host-attention-current'].textContent,/（0）/);
    n['host-filter-history'].click();assert.equal(n['host-attention'].value,'history');assert.equal(n['host-filter-history'].attrs['aria-pressed'],'true');assert.equal(card.hidden,false);assert.match(n['host-attention-history'].textContent,/（1）/);
    const button=card.all().find(e=>e.dataset.blockedTarget==='w1:p1/term_a001');
    assert.match(button.textContent,/重新核查/);
    n['host-query'].value='absent';n['host-query'].dispatch('input');assert.equal(card.hidden,true);
    n['host-query-clear'].click();assert.equal(n['host-attention'].value,'history');assert.equal(card.hidden,false);
    state('current');n['host-filter-reset'].click();
    assert.equal(n['host-attention'].value,'all');assert.equal(card.hidden,false);
    assert.equal(h.calls.length,baseline);
  } finally {h.finish();await flush();h.restore();}
});

test('primary navigation returns from network and settings without losing the board', async () => {
  const h=await setup(), n=h.nodes;
  try {
    n['nav-network'].click(); await flush();
    assert.equal(n['home-network'].hidden,false);
    n['nav-settings'].click(); await flush();
    assert.equal(n['home-settings'].hidden,false);
    assert.equal(n['home-network'].hidden,true);
    n['show-remote'].dispatch('click'); n['show-remote'].click(); await flush();
    assert.equal(n['home-dashboard'].hidden,false);
    assert.equal(n['home-settings'].hidden,true);
  } finally { h.finish(); h.restore(); }
});

test('board direct SSH entry uses the existing setup route without connecting', async () => {
  const h=await setup(), n=h.nodes;
  try {
    n['home-open-ssh'].click();
    assert.equal(n['home-ssh'].hidden,false);
    assert.equal(n['home-dashboard'].hidden,true);
    assert.equal(h.calls.some(c=>c.name==='ssh_shell_open' || c.name==='ssh_host_key_probe'),false);
  } finally {h.finish();h.restore();}
});

test('native catalog error remains visible on board after navigation', async () => {
  const h=await setup(), n=h.nodes;
  try {
    h.setRead((name,value)=>{if(name==='host_list')throw Error('storage unavailable');return value;});
    n['show-remote'].dispatch('click'); n['show-remote'].click(); await flush(); await flush();
    assert.match(n['host-home-status'].textContent,/不可用/);
    n['nav-settings'].click(); n['show-remote'].dispatch('click'); n['show-remote'].click(); await flush(); await flush();
    assert.match(n['host-home-status'].textContent,/不可用/);
  } finally { h.finish(); h.restore(); }
});

test('SSH credential input preserves reviewed host key; endpoint and identity edits require review', async () => {
  const h=await setup(), n=h.nodes;
  try {
    n['ssh-review'].checked=true;
    n['ssh-password'].value='test password'; n['ssh-password'].dispatch('input');
    assert.equal(n['ssh-review'].checked,true);
    n['ssh-key'].value='test key'; n['ssh-key'].dispatch('input');
    assert.equal(n['ssh-review'].checked,true);
    n['ssh-user'].dispatch('input'); assert.equal(n['ssh-review'].checked,false);
    n['ssh-review'].checked=true; n['ssh-host'].dispatch('input'); assert.equal(n['ssh-review'].checked,false);
    assert.match(n['ssh-fingerprint'].textContent,/请先探测/);
  } finally { h.finish(); h.restore(); }
});

test('SSH authentication selection clears abandoned secrets and sends only the chosen credential', async () => {
  const h=await setup(), n=h.nodes;
  try {
    n['ssh-host'].value='fixture.invalid';n['ssh-port'].value='22';n['ssh-user'].value='fixture';
    await n['ssh-probe'].onclick();n['ssh-review'].checked=true;
    n['ssh-password'].value='password fixture';
    n['ssh-auth-method'].value='key';n['ssh-auth-method'].dispatch('change');
    assert.equal(n['ssh-password'].value,'');assert.equal(n['ssh-password-fields'].hidden,true);
    assert.equal(n['ssh-key-fields'].hidden,false);assert.equal(n['ssh-review'].checked,true);
    n['ssh-key'].value='-----BEGIN PRIVATE KEY-----\nQUJDREVGR0hJSktM\n-----END PRIVATE KEY-----';
    n['ssh-passphrase'].value='passphrase fixture';
    await n['ssh-form'].onsubmit({preventDefault(){}});
    const keyConfig=h.calls.filter(c=>c.name==='ssh_shell_open').at(-1).args.config;
    assert.match(keyConfig.privateKeyPem,/\nQUJDREVGR0hJSktM\n/);assert.equal(keyConfig.privateKeyPassphrase,'passphrase fixture');assert.equal('password' in keyConfig,false);
    assert.equal(n['ssh-key'].value,'');assert.equal(n['ssh-passphrase'].value,'');
    assert.equal(n['ssh-key-summary'].hidden,true);
    n['ssh-key-summary'].click();
    assert.equal(n['ssh-key'].value,'');assert.equal(n['ssh-key-summary'].hidden,true);
    n['ssh-cancel'].click();await flush();
    n['ssh-key'].value='unused key';n['ssh-passphrase'].value='unused phrase';
    n['ssh-auth-method'].value='password';n['ssh-auth-method'].dispatch('change');
    assert.equal(n['ssh-key'].value,'');assert.equal(n['ssh-passphrase'].value,'');assert.equal(n['ssh-key-fields'].hidden,true);assert.equal(n['ssh-key-summary'].hidden,true);
    n['ssh-password'].value='password fixture';await n['ssh-form'].onsubmit({preventDefault(){}});
    const passwordConfig=h.calls.filter(c=>c.name==='ssh_shell_open').at(-1).args.config;
    assert.equal(passwordConfig.password,'password fixture');assert.equal('privateKeyPem' in passwordConfig,false);
    n['ssh-password'].value='cancel secret';n['ssh-cancel'].click();assert.equal(n['ssh-password'].value,'');
    n['ssh-key'].value='disconnect secret';n['ssh-passphrase'].value='disconnect phrase';n['ssh-disconnect'].click();
    assert.equal(n['ssh-key'].value,'');assert.equal(n['ssh-passphrase'].value,'');assert.equal(n['ssh-key-summary'].hidden,true);
    n['ssh-key-summary'].click();assert.equal(n['ssh-key'].value,'');assert.equal(n['ssh-key-summary'].hidden,true);
  } finally { h.finish(); await flush(); h.restore(); }
});

test('any non-empty private-key draft collapses on blur and submits from memory', async () => {
  const h=await setup(), n=h.nodes;
  try {
    n['ssh-host'].value='fixture.invalid';n['ssh-port'].value='22';n['ssh-user'].value='fixture';
    await n['ssh-probe'].onclick();n['ssh-review'].checked=true;
    n['ssh-auth-method'].value='key';n['ssh-auth-method'].dispatch('change');
    n['ssh-key'].value='';n['ssh-key'].dispatch('input');
    n['ssh-passphrase'].focus();n['ssh-key'].dispatch('blur');
    assert.equal(n['ssh-key'].hidden,false);assert.equal(n['ssh-key-summary'].hidden,true);
    n['ssh-key'].value='   ';n['ssh-key'].dispatch('input');
    n['ssh-key'].dispatch('blur');
    assert.equal(n['ssh-key'].hidden,true);assert.equal(n['ssh-key'].value,'');
    assert.equal(n['ssh-key-summary'].hidden,false);
    assert.equal(n['ssh-key-summary'].textContent,'已填写私钥 · 重新编辑');
    assert.equal(document.activeElement,n['ssh-passphrase']);
    n['ssh-key-summary'].click();
    assert.equal(n['ssh-key'].hidden,false);assert.equal(n['ssh-key-summary'].hidden,true);
    assert.equal(n['ssh-key'].value,'   ');assert.equal(document.activeElement,n['ssh-key']);
    n['ssh-key'].value='single incomplete line';n['ssh-key'].dispatch('input');
    n['ssh-passphrase'].focus();n['ssh-key'].dispatch('blur');
    assert.equal(n['ssh-key'].hidden,true);assert.equal(n['ssh-key-summary'].hidden,false);
    n['ssh-key-summary'].click();
    const pemMarker=word=>`-----${word}-----`;
    const pem=[pemMarker('BEGIN PRIVATE KEY'),'A'.repeat(136),pemMarker('END PRIVATE KEY'),''].join('\n');
    n['ssh-key'].value=pem;n['ssh-key'].dispatch('input');
    n['ssh-passphrase'].value='passphrase fixture';
    n['ssh-passphrase'].focus();n['ssh-key'].dispatch('blur');
    assert.equal(n['ssh-key'].hidden,true);assert.equal(n['ssh-key'].value,'');
    await n['ssh-form'].onsubmit({preventDefault(){}});
    const keyConfig=h.calls.filter(c=>c.name==='ssh_shell_open').at(-1).args.config;
    assert.equal(keyConfig.privateKeyPem,pem);assert.equal(keyConfig.privateKeyPassphrase,'passphrase fixture');
    assert.equal(n['ssh-key'].hidden,false);assert.equal(n['ssh-key'].value,'');
    assert.equal(n['ssh-key-summary'].hidden,true);assert.equal(n['ssh-passphrase'].value,'');
  } finally { h.finish(); await flush(); h.restore(); }
});

test('paste keeps the collapsed draft and focus when the system grants or denies clipboard', async () => {
  const pemMarker=word=>`-----${word}-----`;
  const pasted=[pemMarker('BEGIN PRIVATE KEY'),'B'.repeat(64),pemMarker('END PRIVATE KEY'),''].join('\n');
  const granted=await setup({clipboardRead:async()=>pasted});
  try {
    const n=granted.nodes;
    n['ssh-host'].value='fixture.invalid';n['ssh-port'].value='22';n['ssh-user'].value='fixture';
    await n['ssh-probe'].onclick();n['ssh-review'].checked=true;
    n['ssh-auth-method'].value='key';n['ssh-auth-method'].dispatch('change');
    n['ssh-key'].value='old incomplete draft';n['ssh-key'].dispatch('input');
    n['ssh-paste-key'].focus();n['ssh-key'].dispatch('blur',{relatedTarget:n['ssh-paste-key']});
    assert.equal(n['ssh-key'].hidden,true);assert.equal(n['ssh-key'].value,'');
    assert.equal(n['ssh-key-summary'].hidden,false);assert.equal(document.activeElement,n['ssh-paste-key']);
    await n['ssh-paste-key'].onclick();await flush();
    assert.equal(n['ssh-key'].hidden,true);assert.equal(n['ssh-key-summary'].hidden,false);
    assert.equal(document.activeElement,n['ssh-paste-key']);
    n['ssh-passphrase'].value='passphrase fixture';
    await n['ssh-form'].onsubmit({preventDefault(){}});
    const keyConfig=granted.calls.filter(c=>c.name==='ssh_shell_open').at(-1).args.config;
    assert.equal(keyConfig.privateKeyPem,pasted);
  } finally { granted.finish(); await flush(); granted.restore(); }
  const denied=await setup({clipboardRead:async()=>{throw Error('denied');}});
  try {
    const n=denied.nodes;
    n['ssh-host'].value='fixture.invalid';n['ssh-port'].value='22';n['ssh-user'].value='fixture';
    await n['ssh-probe'].onclick();n['ssh-review'].checked=true;
    n['ssh-auth-method'].value='key';n['ssh-auth-method'].dispatch('change');
    n['ssh-key'].value='old incomplete draft';n['ssh-key'].dispatch('input');
    n['ssh-paste-key'].focus();n['ssh-key'].dispatch('blur',{relatedTarget:n['ssh-paste-key']});
    await n['ssh-paste-key'].onclick();await flush();
    assert.equal(n['ssh-key'].hidden,true);assert.equal(n['ssh-key'].value,'');
    assert.equal(n['ssh-key-summary'].hidden,false);assert.equal(document.activeElement,n['ssh-paste-key']);
    n['ssh-key-summary'].click();
    assert.equal(n['ssh-key'].hidden,false);assert.equal(n['ssh-key'].value,'old incomplete draft');
    n['ssh-passphrase'].focus();n['ssh-key'].dispatch('blur');
    n['ssh-auth-method'].value='password';n['ssh-auth-method'].dispatch('change');
    assert.equal(n['ssh-key'].hidden,false);assert.equal(n['ssh-key'].value,'');
    assert.equal(n['ssh-key-summary'].hidden,true);
  } finally { denied.finish(); await flush(); denied.restore(); }
});

async function openOrdinary(h, id, host = 'fixture.invalid') {
  const n = h.nodes;
  n['home-open-ssh'].click();
  assert.equal(n['home-ssh'].hidden, false);
  n['ssh-host'].value = host;
  n['ssh-host'].dispatch('input');
  n['ssh-port'].value = '2222';
  n['ssh-user'].value = 'fixture';
  await n['ssh-probe'].onclick();
  n['ssh-review'].checked = true;
  n['ssh-review'].dispatch('change');
  n['ssh-password'].value = 'temporary fixture';
  n['ssh-password'].dispatch('input');
  await n['ssh-form'].onsubmit({preventDefault(){}});
  const channel = h.calls.filter(c => c.name === 'ssh_shell_open').at(-1).args.onEvent;
  channel.onmessage({sessionId:id, seq:1, kind:'ready'});
  assert.equal(n['ssh-live'].hidden, false);
  assert.equal(n['ssh-disconnect'].disabled, false);
  return channel;
}

test('entry sidebar toggle changes and restores its real expanded state', async () => {
  const h = await setup(), button = h.nodes['sidebar-toggle'];
  try {
    const initial = button.getAttribute('aria-expanded');
    button.click();
    assert.notEqual(button.getAttribute('aria-expanded'), initial);
    assert.equal(document.body.dataset.entrySidebar, initial === 'true' ? 'collapsed' : 'expanded');
    button.click();
    assert.equal(button.getAttribute('aria-expanded'), initial);
    assert.equal(document.body.dataset.entrySidebar, initial === 'true' ? 'expanded' : 'collapsed');
  } finally { h.restore(); }
});

test('active ordinary SSH advertises its session on the board, network and sidebar only while ready', async () => {
  const h = await setup({compactEntry:{matches:false, addEventListener(){}}, sshInvoke:name => name === 'ssh_shell_open' ? 's1' : null});
  const n = h.nodes;
  try {
    await openOrdinary(h, 's1');
    for (const id of ['ssh-board-active', 'ssh-network-active', 'ssh-nav-live']) assert.equal(n[id].hidden, false);
    n['ssh-disconnect'].click();
    await flush();
    for (const id of ['ssh-board-active', 'ssh-network-active', 'ssh-nav-live']) assert.equal(n[id].hidden, true);
  } finally { h.restore(); }
});

test('ordinary SSH natural exit shows confirmed local retirement and genuine remote evidence', async () => {
  let finishClose;
  const close = new Promise(resolve => { finishClose = resolve; });
  const h = await setup({compactEntry:{matches:true, addEventListener(){}}, sshInvoke:name => name === 'ssh_shell_open' ? 's1' : close});
  const n = h.nodes;
  try {
    const channel = await openOrdinary(h, 's1');
    channel.onmessage({sessionId:'s1', seq:2, kind:'exit', exitSignal:'USR2'});
    assert.equal(n['ssh-live'].hidden, true);
    assert.equal(n['ssh-closed-feedback'].hidden, false);
    assert.equal(n['ssh-closed-title'].textContent, '正在断开…');
    assert.equal(n['ssh-closed-feedback'].dataset.phase, 'pending');
    assert.equal(n['ssh-password'].value, '');
    finishClose(null);
    await flush();
    assert.equal(n['ssh-closed-title'].textContent, '本机已断开');
    assert.equal(n['ssh-closed-feedback'].dataset.phase, 'confirmed');
    assert.equal(n['ssh-closed-detail'].textContent, '远端已报告结束，凭据已清空。重连时请重新填写。');
    assert.equal(n['ssh-return-home'].hidden, false);
    n['ssh-return-home'].click();
    assert.equal(n['home-dashboard'].hidden, false);
    assert.match(n['host-ssh-disconnected'].textContent, /^本机已断开/);
  } finally { finishClose(null); await flush(); h.restore(); }
});

test('returning home before ordinary SSH close resolves updates only that dashboard notice', async () => {
  let finishClose;
  const close = new Promise(resolve => { finishClose = resolve; });
  const h = await setup({compactEntry:{matches:true, addEventListener(){}}, sshInvoke:name => name === 'ssh_shell_open' ? 's1' : close});
  const n = h.nodes;
  try {
    const channel = await openOrdinary(h, 's1');
    n['ssh-disconnect'].click();
    assert.equal(n['ssh-return-home'].hidden, false);
    n['ssh-return-home'].click();
    assert.equal(n['home-dashboard'].hidden, false);
    assert.equal(n['home-ssh'].hidden, true);
    assert.equal(n['host-ssh-disconnected'].textContent, '正在断开…');
    assert.equal(n['host-ssh-disconnected'].dataset.phase, 'pending');
    channel.onmessage({sessionId:'s1', seq:2, kind:'exit'});
    assert.equal(n['host-ssh-disconnected'].textContent, '正在断开…');
    finishClose(null);
    await flush();
    assert.equal(n['home-dashboard'].hidden, false);
    assert.equal(n['host-ssh-disconnected'].textContent, '本机已断开');
    assert.equal(n['host-ssh-disconnected'].dataset.phase, 'confirmed');
    channel.onmessage({sessionId:'s1', seq:3, kind:'exit', exitSignal:'other'});
    assert.equal(n['host-ssh-disconnected'].textContent, '本机已断开；远端已报告结束。');
    assert.deepEqual(h.calls.filter(c => c.name === 'ssh_shell_close').map(c => c.args.sessionId), ['s1']);
  } finally { finishClose(null); await flush(); h.restore(); }
});

test('ordinary SSH failed close retains its phase on the returned dashboard', async () => {
  const h = await setup({compactEntry:{matches:false, addEventListener(){}}, sshInvoke:name => name === 'ssh_shell_open' ? 's1' : false});
  const n = h.nodes;
  try {
    await openOrdinary(h, 's1');
    n['ssh-disconnect'].click();
    await flush();
    assert.equal(n['ssh-closed-feedback'].dataset.phase, 'failed');
    n['ssh-return-home'].click();
    assert.equal(n['host-ssh-disconnected'].dataset.phase, 'failed');
    assert.equal(n['host-ssh-disconnected'].textContent, '本机连接关闭失败');
  } finally { h.restore(); }
});

test('ordinary SSH late failure and exit cannot overwrite another route or newer terminal', async () => {
  let finishClose;
  const close = new Promise(resolve => { finishClose = resolve; });
  let opened = 0;
  const h = await setup({compactEntry:{matches:false, addEventListener(){}},
    sshInvoke:(name, args) => name === 'ssh_shell_open' ? `s${++opened}`
      : name === 'ssh_shell_close' && args.sessionId === 's1' ? close : null});
  const n = h.nodes;
  try {
    const old = await openOrdinary(h, 's1');
    n['ssh-disconnect'].click();
    n['show-remote'].dispatch('click');
    assert.equal(n['home-dashboard'].hidden, false);
    assert.equal(n['host-ssh-disconnected'].textContent, '正在断开…');
    n['nav-settings'].click();
    assert.equal(n['home-settings'].hidden, false);
    assert.equal(n['host-ssh-disconnected'].hidden, true);
    n['show-remote'].dispatch('click');
    assert.equal(n['home-dashboard'].hidden, false);
    assert.equal(n['host-ssh-disconnected'].hidden, true);
    await openOrdinary(h, 's2', 'second.invalid');
    old.onmessage({sessionId:'s1', seq:2, kind:'exit', exitStatus:0});
    finishClose(false);
    await flush();
    assert.equal(n['home-ssh'].hidden, false);
    assert.equal(n['host-ssh-disconnected'].hidden, true);
    assert.equal(n['ssh-live'].hidden, false);
    assert.match(n['ssh-live-endpoint'].textContent, /second\.invalid/);
    assert.equal(n['ssh-status'].textContent, '已连接，可以输入。');
    n['ssh-disconnect'].click();
    await flush();
  } finally { finishClose(false); await flush(); h.restore(); }
});

test('mobile mode controls retain editor focus until intentional mode transition', async () => {
  const h=await setup(), n=h.nodes;
  try {
    await openInput(h);
    let prevented=false;
    n['remote-input-direct'].dispatch('pointerdown',{preventDefault(){prevented=true;}});
    assert.equal(prevented,true);
    n['remote-input-direct'].click();await flush();await flush();
    assert.equal(n['remote-input-controls'].dataset.mode,'direct');
    assert.equal(n['remote-input-direct'].attrs['aria-pressed'],'true');
    prevented=false;
    n['remote-input-draft-mode'].dispatch('pointerdown',{preventDefault(){prevented=true;}});
    assert.equal(prevented,true);
    n['remote-input-draft-mode'].click();await flush();await flush();
    assert.equal(n['remote-input-controls'].dataset.mode,'draft');
    assert.equal(n['remote-input-draft-mode'].attrs['aria-pressed'],'true');
    assert.equal(n['remote-input-draft-area'].hidden,false);
  } finally {h.finish();await flush();h.restore();}
});

test('dock stop cancels the focused direct session without sending another byte',async()=>{
  const h=await setup(),n=h.nodes;
  try {
    await openInput(h);n['remote-input-direct'].click();await flush();await flush();
    assert.equal(n['remote-stop-dock'].disabled,false);
    const before=h.calls.filter(c=>c.name==='remote_input_send').length;
    let prevented=false;n['remote-stop-dock'].dispatch('pointerdown',{preventDefault(){prevented=true;}});
    assert.equal(prevented,true);n['remote-stop-dock'].click();await flush();
    h.terminal.data('late');await flush();
    assert.equal(h.calls.filter(c=>c.name==='remote_input_send').length,before);
    assert.match(n['remote-captured'].textContent,/陈旧/);
  } finally {h.finish();await flush();h.restore();}
});

test('main recovery waits for a rendered full and explicit user confirmation',async()=>{
  const h=await setup(),n=h.nodes;
  try {
    await pairAndConnect(h);publishDashboard(h,blockedPane());
    n['remote-panes'].children.find(e=>e.tagName==='button' && e.textContent.startsWith('w1:p1')).click();
    h.emit({kind:'target_bound',generation:9,epoch:1,pane_id:'w1:p1',terminal_id:'term_a001'});
    h.emit({kind:'input_ready',generation:9,epoch:1,unknown:true,recovery_status:'pending'});
    assert.equal(n['remote-input-recover'].disabled,true);assert.equal(n['remote-input-direct'].disabled,true);
    await n['remote-input-recover'].onclick();assert.equal(h.calls.filter(c=>c.name==='remote_input_recover').length,0);
    h.emit({kind:'frame',generation:9,epoch:1,frame:{seq:1,full:true,cols:80,rows:24,bytes:[65]}});await flush();
    assert.equal(n['remote-input-recover'].disabled,false);
    window.confirm=()=>false;await n['remote-input-recover'].onclick();
    assert.equal(h.calls.filter(c=>c.name==='remote_input_recover').length,0);
    window.confirm=()=>true;await n['remote-input-recover'].onclick();
    assert.equal(h.calls.filter(c=>c.name==='remote_input_recover').length,1);
    assert.equal(n['remote-input-recover'].hidden,true);
  } finally {h.finish();await flush();h.restore();}
});

const emptyCatalog = { revision: 'r1', profiles: [], bindings: [], preferences: { terminalFontSize: 14 } };

test('a known-empty catalog publishes the home and ordinary SSH entry before network preferences resolve', async () => {
  let releaseNetwork;
  const pending = new Promise(resolve => { releaseNetwork = resolve; });
  const h = await setup({ read: (name, value) => name === 'network_list' ? pending : value });
  const n = h.nodes;
  try {
    assert.equal(n['brand-caption'].textContent, '0 台已存主机');
    assert.equal(n['host-empty'].hidden, false);
    assert.equal(n['host-home-status'].hidden, true);
    assert.equal(n['host-list'].children.length, 0);
    n['home-open-ssh'].click();
    assert.equal(n['home-ssh'].hidden, false);
    assert.equal(n['ssh-probe'].disabled, false);
    releaseNetwork(emptyCatalog);
    await flush();
    assert.equal(n['brand-caption'].textContent, '0 台已存主机');
  } finally { releaseNetwork(emptyCatalog); await flush(); h.restore(); }
});

test('compact empty home uses the same direct SSH action and can return from the chooser', async () => {
  const listeners = [];
  const compactEntry = { matches: true, addEventListener: (_event, callback) => { listeners.push(callback); } };
  const h = await setup({ compactEntry });
  const n = h.nodes;
  try {
    assert.equal(n['home-open-ssh'].parentElement, n['host-empty']);
    assert.equal(n['home-open-ssh'].textContent, '普通 SSH 终端');
    n['host-empty-add'].click();
    assert.equal(n['home-add'].hidden, false);
    n['add-back'].click();
    assert.equal(n['home-dashboard'].hidden, false);
    n['home-open-ssh'].click();
    assert.equal(n['home-ssh'].hidden, false);
    compactEntry.matches = false;
    listeners.forEach(resize=>resize());
    assert.equal(n['home-open-ssh'].parentElement, n['host-board-intro']);
    assert.equal(n['home-open-ssh'].textContent, '普通 SSH');
    assert.equal(Object.hasOwn(n['host-empty'].attrs, 'data-compact'), false);
  } finally { h.restore(); }
});

test('an empty home keeps its identity when only network preferences are unavailable', async () => {
  const h = await setup({ read: (name, value) => {
    if (name === 'network_list') throw Error('network_preferences_unavailable');
    return value;
  } });
  const n = h.nodes;
  try {
    assert.equal(n['brand-caption'].textContent, '0 台已存主机');
    assert.equal(n['host-empty'].hidden, false);
    assert.equal(n['host-list'].children.length, 0);
    assert.doesNotMatch(n['host-home-status'].textContent, /本机资料不可用/);
    assert.match(n['host-home-status'].textContent, /网络配置暂不可读/);
    n['home-open-ssh'].click();
    assert.equal(n['home-ssh'].hidden, false);
    assert.equal(n['ssh-probe'].disabled, false);
  } finally { h.restore(); }
});

test('a host_list error never fakes a known-empty home', async () => {
  const h = await setup({ read: (name, value) => {
    if (name === 'host_list') throw Error('storage unavailable');
    return value;
  } });
  const n = h.nodes;
  try {
    assert.equal(n['brand-caption'].textContent, '本机主机资料不可用');
    assert.equal(n['host-empty'].hidden, true);
    assert.match(n['host-home-status'].textContent, /不可用/);
  } finally { h.restore(); }
});

test('a known-empty catalog still applies network profiles and the font after the deferred read', async () => {
  const h = await setup({ read: (name, value) => name === 'network_list'
    ? { revision: 'r7', profiles: [{ id: 'net1', revision: 7, provider: 'easytier' }], bindings: [], preferences: { terminalFontSize: 18 } }
    : value });
  const n = h.nodes;
  try {
    assert.equal(n['brand-caption'].textContent, '0 台已存主机');
    assert.equal(n['host-empty'].hidden, false);
    assert.equal(n['terminal-font-size'].value, 18);
    assert.deepEqual(globalThis.__remoteCatalogState(), { revisions: [['net1', 7]], providers: [['net1', 'easytier']], font: 18 });
    // 一次目录读取 + 既有网络页刷新，不产生第三次网络刷新。
    assert.equal(h.calls.filter(c => c.name === 'network_list').length, 2);
  } finally { h.restore(); }
});

test('a stale network catalog cannot overwrite a newer empty-home refresh', async () => {
  let releaseStale;
  const staleRead = new Promise(resolve => { releaseStale = resolve; });
  let phase = 'stale';
  const staleCatalog = { revision: 'r0', profiles: [{ id: 'old', revision: 1, provider: 'tailscale' }], bindings: [], preferences: { terminalFontSize: 22 } };
  const h = await setup({ read: (name, value) => {
    if (name !== 'network_list') return value;
    if (phase === 'stale') return staleRead;
    return { revision: 'r2', profiles: [{ id: 'net2', revision: 9, provider: 'zerotier' }], bindings: [], preferences: { terminalFontSize: 16 } };
  } });
  const n = h.nodes;
  try {
    assert.equal(n['brand-caption'].textContent, '0 台已存主机');
    phase = 'current';
    n['host-return-home'].click();await flush();await flush();
    const current = { revisions: [['net2', 9]], providers: [['net2', 'zerotier']], font: 16 };
    assert.equal(n['terminal-font-size'].value, 16);
    assert.deepEqual(globalThis.__remoteCatalogState(), current);
    releaseStale(staleCatalog);await flush();
    assert.equal(n['terminal-font-size'].value, 16);
    assert.deepEqual(globalThis.__remoteCatalogState(), current);
  } finally { releaseStale(staleCatalog);await flush();h.restore(); }
});

for (const [outcome, phase] of [[null, 'confirmed'], [false, 'failed']]) test(`pending ordinary close retains ${phase} when target receives an input event`, async () => {
  let finishClose;
  const pending = new Promise(resolve => { finishClose = resolve; });
  const h = await setup({compactEntry:{matches:true, addEventListener(){}},
    sshInvoke:name => name === 'ssh_shell_open' ? 's1' : pending});
  const n = h.nodes;
  try {
    await openOrdinary(h, 's1');
    n['ssh-disconnect'].click();
    assert.equal(n['ssh-closed-feedback'].dataset.phase, 'pending');
    for (const id of ['ssh-host','ssh-port','ssh-user']) assert.equal(n[id].disabled, true);
    n['ssh-port'].value = '2223';
    n['ssh-port'].dispatch('input');
    assert.equal(n['ssh-port'].value, '2222');
    assert.equal(n['ssh-probe'].disabled, true);
    finishClose(outcome);
    await flush();
    assert.equal(n['ssh-closed-feedback'].dataset.phase, phase);
    for (const id of ['ssh-host','ssh-port','ssh-user']) assert.equal(n[id].disabled, false);
    assert.equal(n['ssh-return-home'].hidden, false);
    n['ssh-return-home'].click();
    assert.equal(n['home-dashboard'].hidden, false);
    assert.equal(n['host-ssh-disconnected'].dataset.phase, phase);
  } finally { finishClose(outcome); await flush(); h.restore(); }
});

test('back while ordinary SSH open is pending restores the target after retiring its late session', async () => {
  let finishOpen;
  const pending = new Promise(resolve => { finishOpen = resolve; });
  const h = await setup({compactEntry:{matches:true, addEventListener(){}},
    sshInvoke:name => name === 'ssh_shell_open' ? pending : null});
  const n = h.nodes;
  try {
    n['home-open-ssh'].click();
    n['ssh-host'].value='fixture.invalid';n['ssh-port'].value='2222';n['ssh-user'].value='fixture';
    await n['ssh-probe'].onclick();n['ssh-trust-confirm'].click();
    n['ssh-password'].value='temporary fixture';
    const opening = n['ssh-form'].onsubmit({preventDefault(){}});
    await flush();
    n['ssh-step-back'].click();
    assert.equal(n['home-ssh'].dataset.sshStep, 'target');
    assert.doesNotMatch(n['ssh-status'].textContent, /正在连接/);
    assert.equal(n['ssh-password'].value, '');
    finishOpen('s1');
    await opening;await flush();
    assert.equal(n['home-ssh'].dataset.sshStep, 'target');
    assert.equal(n['ssh-probe'].disabled, false);
    assert.doesNotMatch(n['ssh-status'].textContent, /正在连接/);
    assert.equal(n['ssh-password'].value, '');
    assert.deepEqual(h.calls.filter(c=>c.name==='ssh_shell_close').map(c=>c.args.sessionId), ['s1']);
  } finally { finishOpen('s1'); await flush(); h.restore(); }
});

for (const route of ['network', 'settings']) for (const accepted of [true, false]) test(`cancelled opening stays cancelled on ${route} after late ${accepted ? 'success' : 'failure'} and permits a new connection`, async () => {
  let finishOpen, failOpen, opens = 0;
  const pending = new Promise((resolve, reject) => { finishOpen = resolve; failOpen = reject; });
  const h = await setup({compactEntry:{matches:true, addEventListener(){}},
    sshInvoke:name => name === 'ssh_shell_open' ? (++opens === 1 ? pending : 's2') : null});
  const n = h.nodes;
  try {
    n['home-open-ssh'].click();
    n['ssh-host'].value='fixture.invalid';n['ssh-port'].value='2222';n['ssh-user'].value='fixture';
    await n['ssh-probe'].onclick();n['ssh-trust-confirm'].click();n['ssh-password'].value='temporary fixture';
    const opening = n['ssh-form'].onsubmit({preventDefault(){}});await flush();
    n['ssh-step-back'].click();n['ssh-step-back'].click();
    assert.equal(n['home-dashboard'].hidden, false);
    n[`nav-${route}`].click();
    if (accepted) finishOpen('s1'); else failOpen(Error('fixture-open-failure'));
    await opening;await flush();
    assert.equal(n[`home-${route}`].hidden, false);
    assert.deepEqual(h.calls.filter(c=>c.name==='ssh_shell_close').map(c=>c.args.sessionId), accepted ? ['s1'] : []);
    assert.equal(h.calls.filter(c=>c.name==='ssh_shell_write').length, 0);
    n['show-remote'].dispatch('click');
    await openOrdinary(h, 's2', 'new.invalid');
    assert.equal(n['ssh-live'].hidden, false);
    assert.match(n['ssh-live-endpoint'].textContent, /new\.invalid/);
    assert.equal(h.calls.filter(c=>c.name==='ssh_shell_open').length, 2);
    assert.equal(h.calls.filter(c=>c.name==='ssh_shell_write').length, 0);
  } finally { finishOpen('s1'); await flush(); h.restore(); }
});

test('after a completed close a deliberate target edit can be freshly probed without replay', async () => {
  const h = await setup({compactEntry:{matches:true, addEventListener(){}},
    sshInvoke:name => name === 'ssh_shell_open' ? 's1' : null});
  const n = h.nodes;
  try {
    await openOrdinary(h, 's1');
    n['ssh-disconnect'].click();await flush();
    assert.equal(n['ssh-closed-feedback'].dataset.phase, 'confirmed');
    assert.equal(n['ssh-port'].disabled, false);
    n['ssh-port'].value='2223';n['ssh-port'].dispatch('input');
    assert.equal(n['ssh-probe'].disabled, false);
    await n['ssh-probe'].onclick();
    assert.equal(h.calls.filter(c=>c.name==='ssh_host_key_probe').at(-1).args.port, 2223);
    assert.equal(h.calls.filter(c=>c.name==='ssh_shell_open').length, 1);
    assert.equal(h.calls.filter(c=>c.name==='ssh_shell_write').length, 0);
  } finally { await flush(); h.restore(); }
});
