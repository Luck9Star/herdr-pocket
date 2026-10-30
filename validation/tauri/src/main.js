import { Terminal } from '@xterm/xterm';
import { invoke, Channel, isTauri } from '@tauri-apps/api/core';
import '@xterm/xterm/css/xterm.css';
import './style.css';
import { ViewGate, byteLength, readBoundClipboard, WaitRegistry } from './gate.js';
import { viewState } from './view-state.js';
import { readTheme } from './theme.js';

const $ = id => document.getElementById(id);
const fixture = await fetch('/shared/fixture.json').then(r => { if (!r.ok) throw Error('fixture missing'); return r.json(); });
const loadChunk = await fetch('/shared/load-chunk.txt').then(r => r.text());
const designTokens = await fetch('/shared/design-tokens-v2.json').then(r => { if (!r.ok) throw Error('design tokens missing'); return r.json(); });
const theme = readTheme(designTokens);
for (const [name, value] of Object.entries(theme.css)) document.documentElement.style.setProperty(name, value);
await document.fonts.load(`${fixture.terminal.fontSize}px ProbeNerd`);
const native = isTauri();
const logs = [];
let active = 'a', split = false, preview = null;
function log(message) { logs.unshift(`${new Date().toISOString().slice(11,23)} ${message}`); logs.splice(100); $('log').textContent = logs.join('\n'); }
function error(err) { log(`失败: ${String(err)}`); }
const panels = Object.fromEntries(['a', 'b'].map(id => {
  const node = document.createElement('article'); node.className = 'panel'; node.dataset.id = id;
  node.innerHTML = `<div class="panel-head"><span class="panel-title"><strong>${id === 'a' ? 'build-lab · Tailscale' : 'review-lab · EasyTier'}</strong><small>session-fixture / pane-${id} · 80 × 24</small></span><button>设为输入焦点</button></div><div class="term-scroll"><div class="terminal-host"></div></div>`;
  $('workspace').append(node);
  const p = { id, node, host:node.querySelector('.terminal-host'), gate:new ViewGate(id, fixture.load.maxQueuedBytes, fixture.load.maxInputBytes), draft:'', term:null, composing:null, keyToken:null, lease:null, tui:false, writes:new Map(), waits:new WaitRegistry() };
  node.querySelector('button').onclick = () => activate(id);
  return [id, p];
}));
const current = () => panels[active];
async function cancelNative(p) { p.waits.cancel(); const lease=p.lease; p.lease=null; if (native && lease) await invoke('fixture_cancel', { lease }).catch(error); }
function cancelWrites(p) { for (const resolve of p.writes.values()) resolve(false); p.writes.clear(); }
function buildTerminal(p) {
  cancelWrites(p); p.term?.dispose(); p.host.replaceChildren(); p.composing=null; p.keyToken=null;
  const t = new Terminal({cols:80,rows:24,fontFamily:'ProbeNerd, monospace',fontSize:14,scrollback:fixture.terminal.scrollback,disableStdin:true,cursorBlink:false,convertEol:false,allowProposedApi:false,theme:theme.terminal});
  p.term=t; t.open(p.host);
  // xterm owns platform IME. We bind its committed data to the view/focus at composition start.
  t.textarea.addEventListener('compositionstart', () => { p.composing=p.gate.token(); }, true);
  t.textarea.addEventListener('keydown', event => { if (!event.isComposing && event.keyCode !== 229) { p.composing=null; p.keyToken=p.gate.token(); } }, true);
  t.textarea.addEventListener('paste', event => {
    event.preventDefault(); event.stopImmediatePropagation();
    showPreview(event.clipboardData?.getData('text/plain') || '', false, p);
  }, true);
  t.onData(data => {
    const token=p.composing || p.keyToken || p.gate.token();
    capture(p, data, token); p.composing=null;
  });
}
function capture(p, text, token, draft=false) {
  const result=p.gate.input(text,token,{draft});
  if (!result.accepted) { log(`拒绝 ${p.id}: ${result.reason}`); return false; }
  const hex=[...result.bytes].map(x=>x.toString(16).padStart(2,'0')).join(' ');
  log(`本地捕获 ${p.id} g${result.generation}/e${result.epoch}: ${result.bytes.length} bytes [${hex}]`);
  // There is deliberately no SSH transport or retry queue in this renderer probe.
  return true;
}
function write(p, kind, data, token) {
  const receipt=p.gate.receive(kind,data,token);
  if (!receipt) { log(`拒绝帧 ${p.id}: 旧代 / 暂停 / 待全量 / 超限`); update(); return Promise.resolve(false); }
  const term=p.term;
  return new Promise(resolve => { p.writes.set(receipt.id, resolve); term.write(data, () => { p.writes.delete(receipt.id); const accepted=p.gate.consumed(receipt); update(); resolve(accepted); }); });
}
async function restore(p=current()) {
  await cancelNative(p);
  const token=p.gate.reconnect(); buildTerminal(p);
  await write(p,'full',fixture.frames[0].data,token);
  if (p.gate.sameStream(token)) await write(p,'delta',fixture.frames[1].data,token);
  update();
}
function update() {
  for (const p of Object.values(panels)) {
    const visible=p.id===active || (split && window.innerWidth>=900);
    p.node.hidden=!visible; p.node.classList.toggle('active',p.id===active);
    const state=viewState(p.gate);
    p.term.options.disableStdin=p.id!==active || !state.canType;
    p.term.options.cursorBlink=p.id===active && state.canType;
    p.node.querySelector('.panel-head button').textContent=p.id===active ? '当前输入焦点' : '设为输入焦点';
    p.node.querySelector('.panel-head button').setAttribute('aria-pressed',String(p.id===active));
  }
  const p=current(), state=viewState(p.gate);
  for (const b of document.querySelectorAll('[data-mode]')) {
    b.setAttribute('aria-pressed',String(b.dataset.mode===p.gate.mode));
    b.disabled=!state.canChooseMode;
  }
  for (const b of document.querySelectorAll('[data-target]')) b.setAttribute('aria-pressed',String(b.dataset.target===active));
  $('active-target').textContent=`目标 ${active.toUpperCase()} / session-fixture / pane-${active}`;
  $('draft').value=p.draft; $('draft-area').hidden=p.gate.mode!=='draft';
  $('draft').disabled=!state.canSendDraft; $('send-draft').disabled=!state.canSendDraft;
  for (const b of $('keys').querySelectorAll('button')) b.disabled=!state.canType;
  $('keyboard').disabled=!state.canType;
  $('verified').disabled=!state.canAcknowledge;
  $('verified').hidden=!p.gate.unknown;
  $('paste').disabled=!state.canPaste;
  $('mode-message').dataset.tone=state.tone;
  $('mode-title').textContent=state.title; $('mode-detail').textContent=state.detail;
  $('recovery-actions').hidden=!state.showRecovery;
  $('status').textContent=`焦点 ${p.id.toUpperCase()} · ${p.gate.reason} · 待消费 ${p.gate.pendingBytes}/${p.gate.maxQueuedBytes} bytes`;
  $('tab-a').setAttribute('aria-pressed',String(active==='a')); $('tab-b').setAttribute('aria-pressed',String(active==='b')); $('split').setAttribute('aria-pressed',String(split));
}

async function activate(id) {
  if (id!==active) {
    const old=current(); old.gate.focus(false); old.term.blur();
    if (!split || window.innerWidth<900) { old.gate.hide(); cancelWrites(old); await cancelNative(old); }
    active=id;
    const p=current(); p.gate.focus(true);
    if (!p.gate.visible || !p.gate.ready) await restore(p);
    // Entering a different target always returns to observation, even in a visible split.
    p.gate.setMode('observe'); update();
  }
}
function showPreview(text,draft,p=current(),token=p.gate.token()) {
  if (!p.gate.ready || p.gate.unknown || !p.gate.sameInput(token) || p.gate.mode==='observe' || !p.gate.focused) { log('当前目标不可发送'); return; }
  preview={ id:p.id,token,draft,original:text };
  $('paste-target').textContent=`目标 ${p.id.toUpperCase()} / session-fixture / pane-${p.id} · ${byteLength(text)} bytes`;
  $('paste-text').value=text; $('paste-dialog').returnValue=''; $('paste-dialog').showModal();
}
$('paste-dialog').addEventListener('close', () => {
  const pending=preview; preview=null;
  if ($('paste-dialog').returnValue!=='send' || !pending) return;
  const p=panels[pending.id]; const text=$('paste-text').value;
  if (capture(p,text,pending.token,pending.draft) && pending.draft && p.draft===pending.original) { p.draft=''; update(); }
});
$('tab-a').onclick=()=>activate('a').catch(error); $('tab-b').onclick=()=>activate('b').catch(error);
$('split').onclick=async()=>{
  split=!split; $('workspace').classList.toggle('split',split);
  for(const p of Object.values(panels)) {
    if(p.id!==active && split && window.innerWidth>=900) { await restore(p); p.gate.focus(false); }
    else if(p.id!==active) { p.gate.hide(); cancelWrites(p); await cancelNative(p); }
  }
  update(); log('只变更本地布局；未发送 PTY resize');
};
for (const b of document.querySelectorAll('[data-mode]')) b.onclick=()=>{ const p=current(); if(!viewState(p.gate).canChooseMode)return; p.gate.setMode(b.dataset.mode); update(); if(p.gate.mode==='direct')p.term.focus(); };
for (const b of document.querySelectorAll('[data-target]')) b.onclick=()=>activate(b.dataset.target).catch(error);
$('keyboard').onclick=()=>current().term.focus(); $('blur').onclick=()=>current().term.blur();
const keys={esc:'\x1b',tab:'\t','ctrl-c':'\x03',up:'\x1b[A',down:'\x1b[B',left:'\x1b[D',right:'\x1b[C',enter:'\r'};
for(const b of $('keys').querySelectorAll('button')) b.onclick=()=>capture(current(),keys[b.dataset.key],current().gate.token());
$('draft').oninput=()=>{ current().draft=$('draft').value; };
$('send-draft').onclick=()=>showPreview(current().draft,true);
$('paste').onclick=async()=>{ const p=current(), draft=p.gate.mode==='draft'; const result=await readBoundClipboard(p.gate, async()=>{ try{return await navigator.clipboard.readText();}catch{log('剪贴板权限不可用；在预览框手动粘贴');return '';} }); if(result)showPreview(result.text,draft,p,result.token);else log('粘贴已取消：读取期间目标或模式变化'); };
$('copy').onclick=async()=>{ const selected=current().term.getSelection(); if(!selected){log('先选择终端文字');return;} try{await navigator.clipboard.writeText(selected);log('已复制选区');}catch{log('复制权限不可用；使用系统选区复制');} };
$('restore').onclick=()=>restore().catch(error);
$('refresh-fixture').onclick=()=>restore().catch(error);
$('verified').onclick=()=>{ const p=current(); if(p.gate.acknowledgeUnknown(p.gate.token()))log('用户已核实原目标结果；仍须显式进入输入'); update(); };
$('unknown').onclick=()=>{const p=current();p.gate.unknownSend();cancelNative(p).catch(error);update();log(`目标 ${p.id} 发送结果未知；不自动重放，草稿不回填已发送内容`);};
$('late').onclick=()=>{const p=current();const old={...p.gate.token(),epoch:p.gate.epoch-1};write(p,'delta','LATE MUST NOT APPEAR',old);};
$('tui').onclick=()=>{const p=current();p.tui=!p.tui;write(p,'delta',fixture.frames[p.tui?2:3].data,p.gate.token());};
$('load').onclick=async()=>{
  const p=current(),token=p.gate.token(); if(!p.gate.ready)return;
  $('load').disabled=true; let count=0; const started=performance.now();
  try {
    if(native) {
      const lease=await invoke('fixture_begin',{target:p.id,generation:token.generation,epoch:token.epoch}); p.lease=lease;
      for(let i=0;i<fixture.load.chunks && p.gate.sameStream(token) && p.gate.visible;i++) {
        // Each chunk awaits xterm consumption before returning native credit.
        const wait=p.waits.create();
        const onChunk=new Channel(); onChunk.onmessage=data=>{
          if(!(data instanceof ArrayBuffer)){log('原生 Channel 未返回二进制');wait.settle(false);return;}
          const text=new TextDecoder().decode(data); write(p,'delta',text,token).then(wait.settle,()=>wait.settle(false));
        };
        const bytes=await invoke('fixture_next',{lease,onChunk});
        const accepted=await wait.promise;
        if(!accepted)break;
        await invoke('fixture_ack',{lease,bytes}); count++;
      }
      await cancelNative(p);
    } else {
      for(let i=0;i<fixture.load.chunks && p.gate.sameStream(token) && p.gate.visible;i++) { if(!await write(p,'delta',loadChunk,token))break; count++; }
    }
    log(`${native?'原生二进制 Channel':'浏览器 fixture'}: ${count*fixture.load.chunkBytes} bytes / ${(performance.now()-started).toFixed(1)} ms；仅负载耗时，非性能验收`);
  } catch(err){error(err); await cancelNative(p);} finally{$('load').disabled=false;}
};
let lastWide=window.innerWidth>=900;
window.addEventListener('resize',async()=>{
  const wide=window.innerWidth>=900;
  if(wide!==lastWide && split){lastWide=wide;for(const p of Object.values(panels)){if(p.id!==active){if(wide)await restore(p);else{p.gate.hide();await cancelNative(p);}}}}
  update();
});
document.addEventListener('visibilitychange',()=>{
  if(document.hidden){for(const p of Object.values(panels)){p.gate.hide();cancelWrites(p);cancelNative(p).catch(error);}update();}
  else{log('回到前台：等待用户主动恢复全量画面');update();}
});
for(const p of Object.values(panels))buildTerminal(p);
panels.a.gate.focus(true); panels.b.gate.hide();
await restore(panels.a);update();
$('versions').textContent=`${designTokens.name} · xterm.js 6.0.0 · Tauri core 2.12.5 / API+CLI 2.12.4 · ${native?'原生壳':'浏览器预览（不代表 Tauri / 手机结果）'} · fixture ${fixture.id} · font SHA256 ${fixture.font.sha256} · ${navigator.userAgent}`;
log('固定 80×24；对远端没有连接、命令、重放或 resize。');
