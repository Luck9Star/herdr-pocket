import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {readFile} from 'node:fs/promises';
const fixture=JSON.parse(readFileSync(new URL('../../shared/mobile-tabs-v1.json', import.meta.url)));
const target=id=>fixture.targets.find(t=>t.id===id);
import {initTabWorkspace} from '../src/tab-workspace.js';
import {HostDashboardSummary} from '../src/host-dashboard-summary.js';
import {initDesktopWorkbench} from '../src/desktop-workbench.js';

// 桌面工作台切片 4（D2，docs/08-ui-design-plan.md:69）：窄窗面板收纳/返回与分屏空间不足回退。
// 红线：窗口变化只改本地布局，绝不触发远端 PTY resize（docs/05:137）；窄窗口仍能完成核心流程（docs/05:143）。
class Element {
  constructor(tag){this.isConnected=true;this.tagName=tag;this.children=[];this.attrs={};this.dataset={};this.value='';this.disabled=false;this.hidden=false;this.textContent='';this.className='';this.title='';}
  append(...xs){for(const x of xs)this.children.push(x);}
  replaceChildren(...xs){this.children=[];this.append(...xs);}
  setAttribute(k,v){this.attrs[k]=v;}
  getAttribute(k){return this.attrs[k] ?? null;}
  addEventListener(name,fn){(this.events ??= {})[name] ??= []; this.events[name].push(fn);}
  dispatch(name,event={}){for(const fn of this.events?.[name] || [])fn({target:this,...event});}
  click(){this.onclick?.({target:this,preventDefault(){}});}
  focus(){globalThis.document.activeElement=this;}
  blur(){if(globalThis.document.activeElement===this){globalThis.document.activeElement=null;for(const fn of this.events?.blur || [])fn({relatedTarget:null});}}
  contains(node){return node===this || this.all().includes(node);}
  all(){return this.children.flatMap(x=>[x,...x.all()]);}
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));

function setup({innerWidth=1280}={}) {
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
    if(name==='remote_tab_input_send'){const pane=tabTargets[args.tabId];return Promise.resolve({status:'accepted',receipt:{requestId:'0'.repeat(32),paneId:pane.paneId,terminalId:pane.terminalId,acceptedBytes:args.bytes.length}});}
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
    panels:()=>nodes['view-content'].all().filter(n=>n.dataset.role==='workbench-panel'),
    panelOf:id=>nodes['view-content'].all().find(n=>n.dataset.role==='workbench-panel'&&n.dataset.tabId===id),
    openTab,settlePaused,send,flush:async()=>{await flush();await flush();},
    setWidth:width=>{globalThis.window.innerWidth=width;for(const fn of listeners.resize||[])fn();},
    restore:()=>{globalThis.document=oldDocument;globalThis.window=oldWindow;},
  };
}

test('narrow-window return path: #host-return-home lives in #workbench-main and is never hidden by CSS', async () => {
  const html=await readFile(new URL('../index.html', import.meta.url),'utf8');
  const css=await readFile(new URL('../src/style.css', import.meta.url),'utf8');
  const main=html.indexOf('id="workbench-main"'), back=html.indexOf('id="host-return-home"');
  assert.ok(main>0 && back>main,'返回按钮必须位于 #workbench-main 内（窄窗侧栏隐藏时返回路径仍在）');
  // 窄窗只隐藏侧栏本体；返回按钮不得出现任何 display:none 规则（含媒体查询内）。
  assert.ok(!/#host-return-home[^{}]*\{[^}]*display:\s*none/.test(css),'#host-return-home 不得被任何规则隐藏');
  assert.ok(css.includes('@media(max-width:899px)') && css.includes('#workbench-sidebar{display:none}'),'窄窗隐藏的只是侧栏');
});

test('D2: crossing below 900px stashes only the non-focus panel and annotates the shortage', async () => {
  const s=setup({innerWidth:1280});
  try {
    const a=await s.openTab('direct-pane-a');
    const b=await s.openTab('mesh-pane-b');
    await s.settlePaused(a);
    s.splitButton.onclick();await s.flush();
    // 焦点面板 B 启用草稿并写入（窄窗回落前建立输入态）
    s.panelOf(b).all().find(n=>n.tagName==='button'&&n.textContent==='启用草稿输入').onclick();await s.flush();
    const bDraft=()=>s.panelOf(b).all().find(n=>n.tagName==='textarea');
    bDraft().value='窄窗草稿';bDraft().oninput();
    const resumeAt=s.calls.findIndex(c=>c.name==='remote_tab_control'&&c.args.tabId===a&&c.args.action==='resume');
    assert.ok(resumeAt>=0,'前置：分屏已恢复副面板 A');
    // 动态收窄
    s.setWidth(800);await s.flush();
    assert.equal(s.panels().length,1,'窄窗必须自动收纳第二面板、退回单面板');
    assert.equal(s.panels()[0].dataset.tabId,b,'输入焦点所在的面板继续在前台显示');
    assert.equal(s.nodes['view-content'].getAttribute('data-split'),'1');
    assert.ok(s.calls.slice(resumeAt).some(c=>c.name==='remote_tab_control'&&c.args.tabId===a&&c.args.action==='pause'),'被收纳的必须是非焦点面板（A 被暂停）');
    assert.equal(s.panelOf(a),undefined,'非焦点面板不得再挂载');
    assert.equal(bDraft().disabled,false,'焦点面板的草稿输入不因收窄失效');
    assert.equal(bDraft().value,'窄窗草稿','焦点面板草稿不因收窄丢失');
    const note=s.nodes['view-content'].all().find(n=>n.dataset.role==='split-stash-note');
    assert.ok(note,'收窄必须标注分屏空间不足');
    assert.ok(note.textContent.includes('分屏空间不足')&&note.textContent.includes('已保留另一面板状态'),'标注须说明空间不足且另一面板状态保留');
    assert.ok(!s.nodes['view-content'].all().some(n=>n.dataset.role==='split-note'),'双面板说明随分屏一起收起');
    assert.equal(s.splitButton.hidden,true,'窄窗分屏入口隐藏');
    await s.settlePaused(a);  // 后端确认暂停（真实链路中 pause 由 observation 快照落定）
    // resize 纪律（收窄方向）：窗口变化绝不触发远端/本地 resize
    assert.equal(s.resizes.length,0,'收窄不得触发 terminal.resize');
    assert.ok(!s.calls.some(c=>c.name.includes('resize')),'不得出现任何 resize 类后端调用');
  } finally { s.restore(); }
});

test('D2: widening back restores both panels without rebuilding observation or resizing anything', async () => {
  const s=setup({innerWidth:1280});
  try {
    const a=await s.openTab('direct-pane-a');
    const b=await s.openTab('mesh-pane-b');
    await s.settlePaused(a);
    s.splitButton.onclick();await s.flush();
    s.setWidth(800);await s.flush();
    await s.settlePaused(a);
    const observesBefore=s.observes.length;
    const resumesBefore=s.calls.filter(c=>c.name==='remote_tab_control'&&c.args.tabId===a&&c.args.action==='resume').length;
    // 重新变宽：分屏意图仍在，自动恢复双面板
    s.setWidth(1280);await s.flush();
    assert.equal(s.panels().length,2,'变宽必须平滑恢复双面板（状态不丢）');
    assert.equal(s.nodes['view-content'].getAttribute('data-split'),'2');
    assert.equal(s.calls.filter(c=>c.name==='remote_tab_control'&&c.args.tabId===a&&c.args.action==='resume').length,resumesBefore+1,'恢复走 resume 而非重建');
    assert.ok(s.calls.slice(-8).some(c=>c.name==='remote_tab_visible'&&c.args.tabId===a),'恢复必须把副面板重新置为可见');
    assert.equal(s.observes.length,observesBefore,'不得重新发起观察（画布保持连接时选定）');
    assert.ok(s.observes.every(o=>o.canvas.cols===80&&o.canvas.rows===24),'观察画布仍是连接时选定的 80×24');
    assert.ok(!s.nodes['view-content'].all().some(n=>n.dataset.role==='split-stash-note'),'收纳标注随恢复消失');
    assert.ok(s.nodes['view-content'].all().some(n=>n.dataset.role==='split-note'),'双面板说明回归');
    assert.equal(s.panelOf(a).dataset.focus,'false');
    assert.equal(s.panelOf(b).dataset.focus,'true');
    // 被收纳面板状态不丢：恢复后副面板继续收帧并确认（接着 activate 发送的 seq:1 继续发 seq:2）
    const ackBefore=s.calls.filter(c=>c.name==='remote_tab_ack'&&c.args.tabId===a).length;
    s.send(a,{kind:'frame',epoch:1,frame:{seq:2,full:false,cols:80,rows:24,bytes:[67]}});
    await s.flush();
    assert.equal(s.calls.filter(c=>c.name==='remote_tab_ack'&&c.args.tabId===a).length,ackBefore+1,'恢复后的副面板必须继续接收并确认帧');
    // resize 纪律（整个收窄/变宽来回）
    assert.equal(s.resizes.length,0,'窗口来回伸缩不得触发 terminal.resize');
    assert.ok(!s.calls.some(c=>c.name.includes('resize')),'全程不得出现任何 resize 类后端调用');
  } finally { s.restore(); }
});

// ---- 切片 1 审查遗留：零主机占位与「看板过滤为空 ≠ 侧栏不可达」的侧栏契约 ----
const sidebarIds=['workbench-host-list','workbench-host-error','workbench-host-retry','workbench-pending-list','workbench-host-count','workbench-pending-count'];
function sidebarHarness(){
  const nodes=Object.fromEntries(sidebarIds.map(id=>[id,new Element('div')]));
  const previous=globalThis.document;
  globalThis.document={activeElement:null,getElementById:id=>nodes[id] ?? null,createElement:tag=>new Element(tag)};
  return {nodes,restore:()=>{globalThis.document=previous;}};
}
const summaryHost=over=>({
  id:'host-a',name:'工作站',enabled:true,retired:false,keyDeletionPending:false,
  pairingStatus:null,deviceFingerprint:'device-fp',networkProfileId:null,networkRevision:null,
  target:{host:'fixture.invalid',port:22,username:'u',session:'work',expectedHostKey:'k',socketPath:'/s',herdrPath:'/h'},
  provider:'tailscale',...over,
});

test('D2/slice-1: reachable zero-host list renders the saved-host empty placeholder, not an error', () => {
  const h=sidebarHarness();
  try {
    let hosts=[];
    const workbench=initDesktopWorkbench({hosts:()=>hosts,activeHostId:()=>null,provider:()=>'',hostStatus:()=>'',
      store:new HostDashboardSummary(),isBusy:()=>false,onOpenHost:()=>{},onOpenBlocked:()=>{},onRetry:()=>{}});
    workbench.render();
    const children=h.nodes['workbench-host-list'].children;
    assert.equal(children.length,1,'可达但零主机：初始占位被替换为一行空态占位，而不是空白');
    assert.equal(children[0].className,'saved-host-empty');
    assert.equal(children[0].textContent,'还没有已存主机。');
    assert.equal(h.nodes['workbench-host-error'].hidden,true,'零主机是空态，不是资料不可达错误');
    assert.equal(h.nodes['workbench-host-retry'].hidden,true);
    assert.equal(h.nodes['workbench-host-count'].textContent,'0');
    hosts=[summaryHost()];  // 出现第一台主机后占位消失
    workbench.render();
    assert.equal(h.nodes['workbench-host-list'].children.length,1);
    assert.equal(h.nodes['workbench-host-list'].children[0].className,'host-card');
  } finally { h.restore(); }
});

test('D2/slice-1: a board filter yielding zero matches keeps the sidebar reachable with the full host list', () => {
  const h=sidebarHarness();
  try {
    // 装配契约（remote.js filterHostCards 只隐藏看板卡片）：hosts() 始终返回全量；
    // 侧栏的「不可达」只可能来自 setUnavailable，与看板过滤无关。
    const workbench=initDesktopWorkbench({hosts:()=>[summaryHost(),summaryHost({id:'host-b',name:'备份机'})],
      activeHostId:()=>null,provider:()=>'',hostStatus:()=>'',
      store:new HostDashboardSummary(),isBusy:()=>false,onOpenHost:()=>{},onOpenBlocked:()=>{},onRetry:()=>{}});
    workbench.render();  // 相当于过滤词变化后的一次侧栏重绘
    assert.equal(h.nodes['workbench-host-list'].children.length,2,'看板 0 结果时侧栏仍显示全部已存主机');
    assert.equal(h.nodes['workbench-host-error'].hidden,true,'看板过滤为空不等于侧栏不可达');
    assert.equal(h.nodes['workbench-host-retry'].hidden,true,'不得出现重试入口（那是资料不可达专属）');
    assert.equal(h.nodes['workbench-host-count'].textContent,'2');
  } finally { h.restore(); }
});
