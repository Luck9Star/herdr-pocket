import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {readFile} from 'node:fs/promises';
const fixture=JSON.parse(readFileSync(new URL('../../shared/mobile-tabs-v1.json', import.meta.url)));
const target=id=>fixture.targets.find(t=>t.id===id);
import {initTabWorkspace} from '../src/tab-workspace.js';

// 桌面分屏（切片 2）：多面板同观 + 单一输入焦点 + 不 resize 远端（docs/05:137、docs/04:82）。
class Element {
  constructor(tag){this.isConnected=true;this.tagName=tag;this.children=[];this.attrs={};this.dataset={};this.value='';this.disabled=false;this.hidden=false;this.textContent='';this.selectionStart=0;this.selectionEnd=0;}
  append(...xs){for(const x of xs)this.children.push(x);}
  replaceChildren(...xs){this.children=[];this.append(...xs);}
  setAttribute(k,v){this.attrs[k]=v;}
  getAttribute(k){return this.attrs[k] ?? null;}
  addEventListener(name,fn){this['event_'+name]=fn;}
  focus(){globalThis.document.activeElement=this;}
  blur(){if(globalThis.document.activeElement===this){globalThis.document.activeElement=null;this.event_blur?.({relatedTarget:null});}}
  setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;}
  contains(node){return node===this || this.all().includes(node);}
  all(){return this.children.flatMap(x=>[x,...x.all()]);}
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));

function setup({innerWidth=1280,rejectDrafts=false}={}) {
  const oldDocument=globalThis.document, oldWindow=globalThis.window;
  const nodes=Object.fromEntries(['tab-workspace','view-tabs','view-content','workbench-split'].map(id=>[id,new Element('div')]));
  const listeners={};
  globalThis.document={hidden:false,getElementById:id=>nodes[id],createElement:tag=>new Element(tag)};
  globalThis.window={innerWidth,addEventListener:(name,fn)=>{(listeners[name] ??= []).push(fn);},confirm:()=>true};
  const calls=[],channels=[],observes=[],terminals=[],resizes=[],tabTargets={};
  let generation=0;
  const invoke=(name,args)=>{calls.push({name,args});
    if(name==='remote_tab_reserve')return Promise.resolve(++generation);
    if(name==='remote_tab_input_mode')return Promise.resolve(7);
    if(name==='remote_tab_input_send'){if(args.draft && rejectDrafts)return Promise.resolve({status:'rejected',recoveryRequired:true});const pane=tabTargets[args.tabId];return Promise.resolve({status:'accepted',receipt:{requestId:'0'.repeat(32),paneId:pane.paneId,terminalId:pane.terminalId,acceptedBytes:args.bytes.length}});}
    if(name==='remote_tab_observe'){observes.push(args);channels.push(args.onEvent);return new Promise(()=>{});}
    return Promise.resolve();};
  const terminalFactory=options=>{const t={options,cols:options.cols,rows:options.rows,parser:{registerOscHandler(){}},textarea:new Element('textarea'),element:new Element('div'),
    open(){},write(_b,done){done();},reset(){},resize(cols,rows){resizes.push({cols,rows});},dispose(){},
    focus(){globalThis.document.activeElement=t.textarea;},onData(fn){t.onData=fn;}};
    terminals.push(t);return t;};
  const ui=initTabWorkspace({native:true,invoke,theme:{terminal:{}},hostName:id=>id.slice(0,4),
    hostInfo:id=>({target:{username:'u',host:id,port:22},hostFingerprint:'key',deviceFingerprint:'device'}),
    channelFactory:()=>({}),terminalFactory});
  const connectActive=async()=>{const review=nodes['view-content'].all().find(n=>n.tagName==='input');review.checked=true;review.onchange();
    nodes['view-content'].all().find(n=>n.tagName==='button'&&n.textContent==='连接').onclick();await flush();await flush();};
  const send=(tab,event)=>channels[observes.findIndex(o=>o.tabId===tab)].onmessage({generation:observes.find(o=>o.tabId===tab).generation,...event});
  const activate=async tab=>{send(tab,{kind:'observation',snapshot:{epoch:1,phase:'active'}});await flush();
    send(tab,{kind:'frame',epoch:1,frame:{seq:1,full:true,cols:80,rows:24,bytes:[65]}});
    send(tab,{kind:'input_ready',epoch:1,unknown:false,recovery_status:'none'});await flush();await flush();};
  const openTab=async id=>{const pane=target(id);const tab=ui.create(pane.hostId,pane);tabTargets[tab]=pane;await ui.select(tab);await connectActive();await activate(tab);return tab;};
  const settlePaused=async tab=>{send(tab,{kind:'observation',snapshot:{epoch:1,phase:'paused'}});await flush();};
  return {
    nodes,ui,calls,observes,terminals,resizes,splitButton:nodes['workbench-split'],
    // 单面板（未分屏）没有 section 包装层：#view-content 自身就是唯一面板（带同样的 data-role 标记）。
    panels:()=>{const wrapped=nodes['view-content'].all().filter(n=>n.dataset.role==='workbench-panel');return wrapped.length?wrapped:(nodes['view-content'].dataset.role==='workbench-panel'?[nodes['view-content']]:[]);},
    panelOf:id=>{const wrapped=nodes['view-content'].all().find(n=>n.dataset.role==='workbench-panel'&&n.dataset.tabId===id);return wrapped??(nodes['view-content'].dataset.role==='workbench-panel'&&nodes['view-content'].dataset.tabId===id?nodes['view-content']:undefined);},
    connectActive,send,openTab,settlePaused,flush:async()=>{await flush();await flush();},
    setWidth:width=>{globalThis.window.innerWidth=width;for(const fn of listeners.resize||[])fn();},
    restore:()=>{globalThis.document=oldDocument;globalThis.window=oldWindow;},
  };
}

test('split entry is declared in index.html and its grid only applies ≥900px in style.css', async () => {
  const html=await readFile(new URL('../index.html', import.meta.url),'utf8');
  const css=await readFile(new URL('../src/style.css', import.meta.url),'utf8');
  assert.ok(/<button id="workbench-split"[^>]*aria-pressed="false"/.test(html),'index.html 需声明分屏入口');
  assert.ok(css.includes('@media(max-width:899.98px){#workbench-split{display:none}}'),'≤899.98px 必须隐藏分屏入口（覆盖 899–900px 小数宽度，与 JS ≥900 判定闭合）');
  const desktop=css.slice(css.lastIndexOf('@media(min-width:900px){'));
  assert.ok(desktop.includes('#view-content[data-split="2"]'),'分屏网格必须位于 ≥900px 媒体查询内');
  assert.ok(desktop.includes('grid-template-columns:repeat(2,minmax(0,1fr))'),'分屏必须是两列等宽网格');
});

test('wide split mounts two panels and the partner keeps observing (visibility set, focus unique)', async () => {
  const s=setup({innerWidth:1280});
  try {
    const a=await s.openTab('direct-pane-a');
    const b=await s.openTab('mesh-pane-b');
    await s.settlePaused(a);  // 旧单面板语义：切走时暂停 a
    assert.ok(s.calls.some(c=>c.name==='remote_tab_control'&&c.args.tabId===a&&c.args.action==='pause'));
    assert.equal(s.splitButton.hidden,false,'宽屏且已有两个标签：分屏入口可用');
    s.splitButton.onclick();await s.flush();
    assert.equal(s.splitButton.getAttribute('aria-pressed'),'true');
    assert.equal(s.panels().length,2,'分屏后必须同时挂载两个面板');
    assert.ok(s.calls.some(c=>c.name==='remote_tab_visible'&&c.args.tabId===a),'开启分屏必须把副面板重新置为可见（集合语义）');
    assert.ok(s.calls.some(c=>c.name==='remote_tab_control'&&c.args.tabId===a&&c.args.action==='resume'),'副面板必须恢复观察而不是重建连接');
    assert.ok(s.panelOf(a).all().some(n=>n.className==='term-scroll'),'面板 A 挂载自己的终端视口');
    assert.ok(s.panelOf(b).all().some(n=>n.className==='term-scroll'),'面板 B 挂载自己的终端视口');
    assert.equal(s.panelOf(a).dataset.focus,'false');
    assert.equal(s.panelOf(b).dataset.focus,'true');
    assert.ok(s.nodes['view-content'].all().some(n=>n.dataset.role==='split-note'&&n.textContent.includes('未发送 PTY resize')),'分屏必须明示不 resize 远端');
    // 副面板（非活动标签）继续收帧并确认——多可见语义
    const ackBefore=s.calls.filter(c=>c.name==='remote_tab_ack'&&c.args.tabId===a).length;
    s.send(a,{kind:'frame',epoch:1,frame:{seq:2,full:false,cols:80,rows:24,bytes:[66]}});
    await s.flush();
    assert.equal(s.calls.filter(c=>c.name==='remote_tab_ack'&&c.args.tabId===a).length,ackBefore+1,'分屏副面板必须继续接收并确认帧');
    // 非焦点面板输入入口禁用，不得出现可点的静默 no-op
    assert.equal(s.panelOf(a).all().find(n=>n.tagName==='button'&&n.textContent==='逐键输入').disabled,true);
    assert.equal(s.panelOf(a).all().find(n=>n.tagName==='button'&&n.dataset.role==='panel-focus').disabled,false,'副面板的“设为输入焦点”必须可用');
  } finally { s.restore(); }
});

test('单面板无 section 包装：标题 <p> 是 #view-content 的直接子节点（android_gui.py 测量契约）', async () => {
  const s=setup({innerWidth:1280});
  try {
    const a=await s.openTab('direct-pane-a');
    const view=s.nodes['view-content'];
    assert.equal(view.all().filter(n=>n.dataset.role==='workbench-panel').length,0,'单面板不得创建 section 包装层');
    // 驱动测量按直接子节点取标题：const title=[...view.children].find(e=>e.tagName==='P')
    const title=[...view.children].find(e=>String(e.tagName).toUpperCase()==='P');
    assert.ok(title,'标题必须是 #view-content 的直接子节点');
    const parts=String(title.textContent).split(' · ');
    assert.equal(parts.at(-2),'w1:p1','测量必须能拆出 paneId');
    assert.equal(parts.at(-1),'term_a001','测量必须能拆出 terminalId');
    // 分屏打开后才有包装层，标题随之进入包装层内部
    await s.openTab('mesh-pane-b');
    await s.settlePaused(a);
    s.splitButton.onclick();await s.flush();
    assert.equal(view.all().filter(n=>n.dataset.role==='workbench-panel').length,2,'分屏时每个面板都有 section 包装层');
    assert.equal(view.children.filter(e=>String(e.tagName).toUpperCase()==='P').length,1,'分屏时 body 直接子节点里没有面板标题（只剩分屏说明）');
  } finally { s.restore(); }
});

test('panels keep independent target/draft/UI state across a focus swap', async () => {
  const s=setup({innerWidth:1280});
  try {
    const a=await s.openTab('direct-pane-a');
    const b=await s.openTab('mesh-pane-b');
    await s.settlePaused(a);
    s.splitButton.onclick();await s.flush();
    const mesh=target('mesh-pane-b');
    assert.ok(s.panelOf(a).all().some(n=>n.textContent&&n.textContent.includes('w1:p1')),'面板 A 显示自己的目标');
    assert.ok(s.panelOf(b).all().some(n=>n.textContent&&n.textContent.includes(mesh.paneId)),'面板 B 显示自己的目标');
    // B（焦点面板）启用草稿并写入
    s.panelOf(b).all().find(n=>n.tagName==='button'&&n.textContent==='启用草稿输入').onclick();await s.flush();
    const bDraft=()=>s.panelOf(b).all().find(n=>n.tagName==='textarea');
    bDraft().value='草稿B';bDraft().oninput();
    assert.equal(bDraft().disabled,false,'焦点面板草稿可编辑');
    // 焦点换到 A：swap——B 保持观察（不再 pause），但失去输入租约
    const pausesBefore=s.calls.filter(c=>c.name==='remote_tab_control'&&c.args.tabId===b&&c.args.action==='pause').length;
    await s.ui.select(a);
    assert.equal(s.calls.filter(c=>c.name==='remote_tab_control'&&c.args.tabId===b&&c.args.action==='pause').length,pausesBefore,'分屏换焦点不得暂停旧面板');
    assert.equal(s.panelOf(a).dataset.focus,'true');
    assert.equal(s.panelOf(b).dataset.focus,'false');
    assert.equal(bDraft().value,'草稿B','换焦点不丢 B 的草稿');
    assert.equal(bDraft().disabled,true,'非焦点面板草稿必须只读');
    // A 的草稿独立，不串到 B
    const aDraft=()=>s.panelOf(a).all().find(n=>n.tagName==='textarea');
    aDraft().value='草稿A';aDraft().oninput();
    assert.equal(bDraft().value,'草稿B','面板草稿互相独立');
    assert.equal(aDraft().value,'草稿A');
  } finally { s.restore(); }
});

test('input focus is unique: after a swap the old panel lease is released and its input is refused', async () => {
  const s=setup({innerWidth:1280});
  try {
    const a=await s.openTab('direct-pane-a');
    const b=await s.openTab('mesh-pane-b');
    await s.settlePaused(a);
    s.splitButton.onclick();await s.flush();
    s.panelOf(b).all().find(n=>n.tagName==='button'&&n.textContent==='逐键输入').onclick();await s.flush();
    assert.ok(s.calls.some(c=>c.name==='remote_tab_input_mode'&&c.args.tabId===b&&c.args.mode==='direct'),'焦点面板可取得逐键输入');
    const bTerm=s.terminals.find(t=>t.options.disableStdin===false);
    bTerm.onData('x');await s.flush();
    assert.ok(s.calls.some(c=>c.name==='remote_tab_input_send'&&c.args.tabId===b),'焦点面板输入应发送');
    await s.ui.select(a);  // 焦点换到 A
    assert.equal(bTerm.options.disableStdin,true,'旧面板 stdin 必须立即关闭');
    assert.ok(s.calls.some(c=>c.name==='remote_tab_input_mode'&&c.args.tabId===b&&c.args.mode==='observe'),'切换焦点必须显式释放旧面板输入租约');
    const sendsBefore=s.calls.filter(c=>c.name==='remote_tab_input_send'&&c.args.tabId===b).length;
    bTerm.onData('y');await s.flush();
    assert.equal(s.calls.filter(c=>c.name==='remote_tab_input_send'&&c.args.tabId===b).length,sendsBefore,'非焦点面板的输入必须被拒绝，不得发送（后端对应 input_stale）');
  } finally { s.restore(); }
});

test('toggling split never resizes terminals and never re-observes the canvas', async () => {
  const s=setup({innerWidth:1280});
  try {
    const a=await s.openTab('direct-pane-a');
    const b=await s.openTab('mesh-pane-b');
    await s.settlePaused(a);
    const observesBefore=s.observes.length;
    s.splitButton.onclick();await s.flush();          // 开
    s.send(a,{kind:'frame',epoch:1,frame:{seq:2,full:false,cols:80,rows:24,bytes:[66]}});
    await s.flush();
    s.splitButton.onclick();await s.flush();          // 关
    assert.equal(s.resizes.length,0,'分屏开关不得触发 terminal.resize');
    assert.equal(s.observes.length,observesBefore,'不得重新发起观察（画布保持连接时选定）');
    assert.ok(s.observes.every(o=>o.canvas.cols===80&&o.canvas.rows===24),'观察画布仍是连接时选定的 80×24');
    assert.ok(!s.calls.some(c=>c.name.includes('resize')),'不得出现任何 resize 类后端调用');
    assert.equal(s.panels().length,1,'关闭分屏后回到单面板');
    assert.equal(s.nodes['view-content'].all().filter(n=>n.dataset.role==='workbench-panel').length,0,'关闭分屏后不得残留 section 包装层');
    const firstTitle=[...s.nodes['view-content'].children].find(e=>String(e.tagName).toUpperCase()==='P');
    assert.ok(firstTitle&&firstTitle.textContent.includes(' · w1:p1 · '),'单面板的第一条 <p> 必须是标题（无重复、无残留）');
  } finally { s.restore(); }
});

test('closing either split panel ends split; the remaining panel becomes the single focus', async () => {
  const s=setup({innerWidth:1280});
  try {
    const a=await s.openTab('direct-pane-a');
    const b=await s.openTab('mesh-pane-b');
    await s.settlePaused(a);
    s.splitButton.onclick();await s.flush();
    assert.equal(s.panels().length,2);
    await s.ui.select(a);  // A 升为焦点（B 为副面板）
    s.panelOf(a).all().find(n=>n.tagName==='button'&&n.textContent==='关闭此标签').onclick();await s.flush();
    assert.equal(s.panels().length,1,'关闭分屏一侧后必须结束分屏');
    assert.equal(s.panels()[0].dataset.tabId,b,'剩余面板必须升为唯一焦点面板');
    assert.equal(s.panels()[0].dataset.focus,'true');
    assert.equal(s.splitButton.getAttribute('aria-pressed'),'false');
    // 剩余面板仍是活动标签：不会再有隐藏的无面板观察
    assert.equal(s.observes.filter(o=>o.tabId===a).length,1);
    assert.ok(s.calls.some(c=>c.name==='remote_tab_cancel'&&c.args.tabId===a));
  } finally { s.restore(); }
});

test('narrow windows never split: entry hidden, toggle refused, crossing 900px pauses the partner', async () => {
  const s=setup({innerWidth:800});
  try {
    const a=await s.openTab('direct-pane-a');
    const b=await s.openTab('mesh-pane-b');
    await s.settlePaused(a);
    assert.equal(s.splitButton.hidden,true,'窄窗必须隐藏分屏入口');
    s.splitButton.onclick();await s.flush();
    assert.equal(s.splitButton.getAttribute('aria-pressed'),'false','窄窗点击不得开启分屏');
    assert.equal(s.panels().length,1);
    assert.equal(s.nodes['view-content'].getAttribute('data-split'),'1');
    // 变宽：入口出现；开启分屏；再变窄：回落单面板并暂停副面板
    s.setWidth(1280);await s.flush();
    assert.equal(s.splitButton.hidden,false);
    s.splitButton.onclick();await s.flush();
    assert.equal(s.panels().length,2);
    s.setWidth(800);await s.flush();
    assert.equal(s.panels().length,1,'窄窗必须回落单面板');
    assert.equal(s.nodes['view-content'].all().filter(n=>n.dataset.role==='workbench-panel').length,0,'窄窗回落后不得残留 section 包装层');
    assert.ok(s.nodes['view-content'].children.some(e=>String(e.tagName).toUpperCase()==='P'&&e.textContent.includes(' · w1:p1 · ')),'窄窗回落后标题仍是 #view-content 的直接子节点');
    assert.ok(s.calls.some(c=>c.name==='remote_tab_control'&&c.args.tabId===a&&c.args.action==='pause'),'跨界变窄必须暂停分屏副面板');
    assert.equal(s.nodes['view-content'].getAttribute('data-split'),'1');
  } finally { s.restore(); }
});

test('标签切换进行中（switching 窗口）分屏入口禁用且 toggle 被拒，不产生 aria-pressed 脱节', async () => {
  const s=setup({innerWidth:1280});
  try {
    const a=await s.openTab('direct-pane-a');
    await s.openTab('mesh-pane-b');  // b 是焦点、a 已暂停
    const switching=s.ui.select(a);  // 不 await：同步段已置 switching=true 并 render（pause(b) 挂起中）
    assert.equal(s.splitButton.disabled,true,'切换进行中分屏入口必须禁用');
    assert.equal(s.splitButton.hidden,false,'宽屏双标签：入口可见，只是禁用');
    s.splitButton.onclick();await s.flush();await switching;
    assert.equal(s.splitButton.getAttribute('aria-pressed'),'false','切换窗口内的分屏点击必须被拒，aria-pressed 不得虚挂');
    assert.equal(s.panels().length,1);
    assert.ok(!s.calls.some(c=>c.name==='remote_tab_control'&&c.args.action==='resume'),'被拒的 toggle 不得恢复任何面板');
    assert.equal(s.splitButton.disabled,false,'切换完成后入口恢复可用');
  } finally { s.restore(); }
});

test('副面板 stage 事件不打断焦点面板的草稿输入：焦点、选区与草稿内容均保留', async () => {
  const s=setup({innerWidth:1280});
  try {
    const a=await s.openTab('direct-pane-a');
    const b=await s.openTab('mesh-pane-b');
    await s.settlePaused(a);
    s.splitButton.onclick();await s.flush();  // 分屏：b 焦点、a 副面板（已 resume）
    s.panelOf(b).all().find(n=>n.tagName==='button'&&n.textContent==='启用草稿输入').onclick();await s.flush();
    const draft=()=>s.panelOf(b).all().find(n=>n.tagName==='textarea'&&n.getAttribute('aria-label')==='当前标签草稿');
    const field=draft();
    field.focus();
    field.value='Pocket';field.oninput?.();field.setSelectionRange(2,4);
    s.send(a,{kind:'stage',stage:'connecting'});await s.flush();
    // 可观察契约：草稿内容、焦点与选区都不因副面板事件而丢失（节点可以重建）。
    const after=draft();
    assert.ok(after,'焦点面板的草稿输入框必须仍在');
    assert.equal(after.value,'Pocket','草稿内容不得因副面板事件丢失');
    assert.equal(globalThis.document.activeElement,after,'草稿输入焦点不得被副面板事件打断');
    assert.equal(after.selectionStart,2,'选区起点不得丢失');
    assert.equal(after.selectionEnd,4,'选区终点不得丢失');
    assert.ok(s.panelOf(a).all().some(n=>n.getAttribute('role')==='status'&&n.textContent.includes('正在连接 SSH')),'副面板自身状态文本仍更新');
  } finally { s.restore(); }
});

test('899.5px 小数宽度：分屏入口隐藏且禁用，toggle 被拒（CSS 899.98px 与 JS ≥900 判定闭合）', async () => {
  const s=setup({innerWidth:899.5});
  try {
    const a=await s.openTab('direct-pane-a');
    await s.openTab('mesh-pane-b');
    await s.settlePaused(a);
    assert.equal(s.splitButton.hidden,true,'899–900px 小数宽度必须隐藏分屏入口');
    assert.equal(s.splitButton.disabled,true,'隐藏入口同时禁用');
    s.splitButton.onclick();await s.flush();
    assert.equal(s.splitButton.getAttribute('aria-pressed'),'false');
    assert.equal(s.panels().length,1);
    assert.equal(s.nodes['view-content'].getAttribute('data-split'),'1');
  } finally { s.restore(); }
});

test('非焦点面板的「移除此找回原文」禁用：找回区只在焦点面板可操作', async () => {
  const s=setup({innerWidth:1280,rejectDrafts:true});
  try {
    const a=await s.openTab('direct-pane-a');
    const b=await s.openTab('mesh-pane-b');
    await s.settlePaused(a);
    s.splitButton.onclick();await s.flush();
    s.panelOf(b).all().find(n=>n.tagName==='button'&&n.textContent==='启用草稿输入').onclick();await s.flush();
    const bDraft=()=>s.panelOf(b).all().find(n=>n.tagName==='textarea'&&n.getAttribute('aria-label')==='当前标签草稿');
    bDraft().value='待拒草稿';bDraft().oninput();
    s.panelOf(b).all().find(n=>n.tagName==='button'&&n.textContent==='发送草稿').onclick();await s.flush();
    const dismissOf=()=>s.panelOf(b).all().find(n=>n.tagName==='button'&&n.textContent==='移除此找回原文');
    assert.ok(dismissOf(),'服务器拒绝后找回区渲染「移除此找回原文」');
    assert.equal(dismissOf().disabled,false,'焦点面板的找回按钮可用（对照）');
    await s.ui.select(a);  // 焦点换到 A：B 变非焦点面板
    assert.equal(dismissOf().disabled,true,'非焦点面板的找回按钮必须禁用（与其他输入入口同口径）');
  } finally { s.restore(); }
});
