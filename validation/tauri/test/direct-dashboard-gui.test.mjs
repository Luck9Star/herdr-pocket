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
  append(...nodes) { this.children.push(...nodes); }
  prepend(...nodes) { this.children.unshift(...nodes); }
  remove() { this.removed=true; }
  showModal() { this.previousFocus=document.activeElement; this.open=true; this.modal=true; }
  close() { this.open=false; this.previousFocus?.focus(); }
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
let moduleNonce = 0;

// Exercise the real entry module while replacing only external browser/native imports.
async function importedRemote() {
  const url = new URL('../src/remote.js', import.meta.url);
  let code = await readFile(url, 'utf8');
  code = code
    .replace("import {createUnicodeTerminal} from './terminal-unicode.js';", 'const createUnicodeTerminal=(Terminal,options)=>new Terminal(options);')
    .replace("import { Terminal } from '@xterm/xterm';", 'const {Terminal}=globalThis.__directGuiDeps;')
    .replace("import { invoke, Channel } from '@tauri-apps/api/core';", 'const {invoke,Channel}=globalThis.__directGuiDeps;')
    .replace(/from '(\.\/[^']+)'/g, (_match, path) => `from '${new URL(path, url).href}'`);
  const source = Buffer.from(code + `\n// fixture ${++moduleNonce}`).toString('base64');
  return import(`data:text/javascript;base64,${source}`);
}

async function setup({ inputMode = () => 1, clipboardRead, keyboardRequest, scanResponse, pairRequest=pairingCameraFixture().request, clipboardWrite, pairAcceptStored=true } = {}) {
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
    addEventListener(name,fn) { (documentEvents[name] ??= []).push(fn); },
  };
  globalThis.window = { addEventListener(name,fn) { (windowEvents[name] ??= []).push(fn); }, confirm: () => true };
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
    if (name === 'pair_create') {
      records[0].deviceFingerprint = 'device-fingerprint';
      records[0].pairingStatus = 'awaiting-host';
      return { stored: true, state: 'awaiting-host', request: pairRequest, fingerprint: 'device-fingerprint' };
    }
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
      this.cols=options.cols;
      this.element={querySelector:()=>({getBoundingClientRect:()=>({width:800*this.options.fontSize/14})})};
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
  h.emit({ kind: 'frame', generation: 9, epoch:1, frame: { seq: 1, full: true, bytes: [65] } });
  h.emit({ kind: 'input_ready', generation: 9, epoch:1, unknown: false, recovery_status: 'ready' });
}

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
    h.emit({kind:'target_bound',generation:9,epoch:1,pane_id:'w1:p1',terminal_id:'term_a001'});h.emit({kind:'frame',generation:9,epoch:1,frame:{seq:1,full:true,bytes:[65]}});await flush();
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
    : nodes['host-list'].children[0].children.find(node => node.attrs['data-host-task-summary']);
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
    h.emit({kind:'frame',generation:9,epoch:1,frame:{seq:1,full:true,bytes:[65]}});
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

test('unexpected bound terminal stops without enabling input or sending',async()=>{
  const h=await setup();try{
    await pairAndConnect(h);publishDashboard(h,blockedPane());
    h.nodes['remote-panes'].children.find(e=>e.textContent.startsWith('w1:p1')).click();
    h.emit({kind:'target_bound',generation:9,epoch:1,pane_id:'w1:p1',terminal_id:'term_replaced'});
    h.emit({kind:'frame',generation:9,epoch:1,frame:{seq:1,full:true,bytes:[65]}});
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
  h.emit({ kind: 'frame', generation: 9, epoch:1, frame: { seq: 1, full: true, bytes: [65] } });
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
    const open=n['host-list'].all().find(e=>e.tagName==='button' && e.textContent==='打开');assert.ok(open);open.click();await flush();
    n['host-restore-review'].checked=true;n['host-restore'].click();await flush();await flush();
    n['remote-review'].checked=true;n['remote-form'].dispatch('input',{target:n['remote-review']});
    n['remote-form'].dispatch('submit');await flush();
    v.scrollLeft=0;v.scrollTop=0;publishDashboard(h,blockedPane());
    n['remote-panes'].children.find(e=>e.tagName==='button' && e.textContent.startsWith('w1:p1')).click();
    h.emit({kind:'target_bound',generation:9,epoch:1,pane_id:'w1:p1',terminal_id:'term_a001'});
    assert.equal(v.scrollLeft,0,'target proof alone must not restore before a new full');
    h.emit({kind:'frame',generation:9,epoch:1,frame:{seq:1,full:true,bytes:[66]}});
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
    n['host-open-remote'].click();await flush();await flush();
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
test('real new host camera entry previews before fill and rejects edits / saved-host identity',async()=>{
  const h=await setup({scanResponse:()=>connectionProfiles.valid[0].raw}),n=h.nodes;
  try {
    n['host-open-remote'].click();await flush();await flush();const before=h.calls.length;
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
  try{n['host-open-remote'].click();await flush();await flush();const work=n['connection-profile-scan'].onclick();
   if(reason==='home')n['host-return-home'].click();if(reason==='background')h.background();if(reason==='edit'){n['remote-host'].value='manual.invalid';n['remote-form'].dispatch('input',{target:n['remote-host']});}
   finish(connectionProfiles.valid[0].raw);await work;await flush();await flush();
   assert.equal(n['connection-profile-raw'].value,'');assert.equal(n['connection-profile-apply'].disabled,true);
   assert.equal(h.calls.filter(x=>['host_save','pair_create','remote_observe'].includes(x.name)).length,0);
  }finally{h.restore();}
 }
});

test('applied profile retains its visible overlay intent after target edits without retaining trust',async()=>{
 const h=await setup(),n=h.nodes;try{
  n['host-open-remote'].click();await flush();await flush();
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
  n['host-open-remote'].click();await flush();await flush();n['connection-profile-raw'].value=connectionProfiles.valid[1].raw;
  await n['connection-profile-preview'].onclick();n['connection-profile-apply'].click();n['host-save'].click();await flush();await flush();await flush();
  h.updateHost({provider:'tailscale',requiresNetworkBinding:true,networkProfileId:'net-fixture',deviceFingerprint:'device-fixture'});
  n['host-return-home'].click();await flush();await flush();await flush();
  const open=n['host-list'].children[0].children.find(x=>x.className==='saved-host-actions').children.find(x=>x.textContent==='打开');open.click();await flush();await flush();
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
  n['host-open-remote'].click();await flush();await flush();
  n['remote-host'].value='manual.invalid';n['remote-form'].dispatch('input',{target:n['remote-host']});
  n['host-save'].click();await flush();await flush();await flush();
  assert.equal(Object.hasOwn(h.calls.find(x=>x.name==='host_save').args,'providerHint'),false);
  n['host-return-home'].click();await flush();await flush();await flush();
  n['host-open-remote'].click();await flush();await flush();
  n['connection-profile-raw'].value=connectionProfiles.valid[3].raw;await n['connection-profile-preview'].onclick();n['connection-profile-apply'].click();
  assert.equal(n['remote-profile-provider'].value,'easytier');
  n['host-save'].click();await flush();await flush();await flush();
  assert.equal(h.calls.filter(x=>x.name==='host_save')[1].args.providerHint,'easytier');
  n['host-return-home'].click();await flush();await flush();await flush();
  n['host-open-remote'].click();await flush();await flush();
  assert.equal(n['remote-profile-provider'].value,'');assert.equal(n['remote-host'].value,'');
  n['remote-host'].value='another-manual.invalid';n['remote-form'].dispatch('input',{target:n['remote-host']});
  n['host-save'].click();await flush();await flush();await flush();
  assert.equal(Object.hasOwn(h.calls.filter(x=>x.name==='host_save')[2].args,'providerHint'),false);
 }finally{h.restore();}
});
test('explicitly adopting another profile changes network intent while a source edit alone does not',async()=>{
 const h=await setup(),n=h.nodes;try{
  n['host-open-remote'].click();await flush();await flush();
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
  n['host-open-remote'].click();await flush();await flush();
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
 const n=h.nodes;n['host-open-remote'].click();await flush();await flush();
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
  if(reason==='host-switch'){h.foreground();n['host-return-home'].click();await flush();await flush();await flush();n['host-open-remote'].click();await flush();await flush();}
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
  if(reason==='hidden')h.background();if(reason==='navigation'){n['host-return-home'].click();await flush();await flush();await flush();n['host-open-remote'].click();await flush();await flush();}if(reason==='edit')n['remote-form'].dispatch('input',{target:n['pair-response']});
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
  const actions=n['host-list'].children[0].children.find(x=>x.className==='saved-host-actions');assert.equal(actions.children.find(x=>x.textContent==='新终端标签').disabled,true);
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
  n['host-return-home'].click();await flush();await flush();await flush();const actions=n['host-list'].children[0].children.find(x=>x.className==='saved-host-actions');assert.equal(actions.children.find(x=>x.textContent==='新终端标签').disabled,true);actions.children.find(x=>x.textContent==='打开').click();await flush();
  assert.equal(h.calls.slice(baseline).filter(x=>['host_restore','host_select','pair_reset','remote_observe'].includes(x.name)).length,0);assert.match(n['host-home-status'].textContent,/不能恢复旧授权/);
 }finally{h.restore();}
});
test('restoring a retained revoked record displays the original but cannot copy, create or connect',async()=>{
 const fixture=pairingCameraFixture(),h=await setup({pairRequest:fixture.request}),n=h.nodes;
 try{await createCameraPair(h);await reviewResponse(h,revokedResponse(fixture),{accept:true});n['host-return-home'].click();await flush();await flush();await flush();const actions=n['host-list'].children[0].children.find(x=>x.className==='saved-host-actions');actions.children.find(x=>x.textContent==='打开').click();await flush();await flush();
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
  const actions=n['host-list'].children[0].children.find(x=>x.className==='saved-host-actions');assert.equal(actions.children.find(x=>x.textContent==='新终端标签').disabled,true);
 }finally{h.restore();}
});

test('ordinary Android pairing handoff sends only matching native record IDs and checks page completion identity',async()=>{
 const commands=[],fixture=pairingCameraFixture(),copy=createPublicRequestClipboard({shell:{current:()=> 'android'},callNative:async(name,args)=>{commands.push({name,args});return {...args,copied:true};},webClipboard:()=>{throw Error('must not fall back');}}),h=await setup({pairRequest:fixture.request,clipboardWrite:copy}),n=h.nodes;
 try{await createCameraPair(h);await n['pair-request-copy'].onclick();assert.deepEqual(commands,[{name:'pair_copy_request',args:{hostId:'a'.repeat(32),requestId:'c'.repeat(32)}}]);assert.match(n['pair-handoff-status'].textContent,/已复制/);assert.equal(n['pair-request'].value,fixture.request);}finally{h.restore();}
});
