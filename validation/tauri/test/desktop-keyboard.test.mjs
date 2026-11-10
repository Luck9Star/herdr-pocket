import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {initKeyRouter} from '../src/key-router.js';

// 桌面工作台切片 3：键盘导航与快捷键层。
// 依据 docs/08:68（D1 快捷键与焦点轮转）、docs/08:93（键位/焦点顺序/输入冲突处理由本层定义）、
// docs/05:143 红线：快捷键不改变目标、不意外发送——路由层只转焦点/点既有按钮，绝不 invoke。

class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.attrs={};this.dataset={};this.disabled=false;this.hidden=false;this.textContent='';this.onclick=null;}
  append(...xs){for(const x of xs)this.children.push(x);}
  replaceChildren(...xs){this.children=[];this.append(...xs);}
  setAttribute(k,v){this.attrs[k]=String(v);}
  getAttribute(k){return this.attrs[k] ?? null;}
  addEventListener(name,fn){this['event_'+name]=fn;}
  focus(){globalThis.document.activeElement=this;}
  contains(node){return node===this || this.all().includes(node);}
  all(){return this.children.flatMap(x=>[x,...x.all()]);}
}

function setupRouter({innerWidth=1280,split=false,bare=false,viewTabs=2,hostTabs=2,hosts=2,pending=1}={}) {
  const oldDocument=globalThis.document, oldWindow=globalThis.window;
  const clicks=[], listeners={};
  const nodes={};
  for(const id of ['remote-page','workbench-host-list','workbench-pending-list','host-tabs','view-tabs','view-content','workbench-split','host-return-home'])nodes[id]=new Element('div');
  nodes['remote-page'].hidden=false;
  const button=label=>{const b=new Element('button');b.textContent=label;b.onclick=()=>clicks.push(label);return b;};
  const hostCards=[];
  for(let i=1;i<=hosts;i++){const card=button(`host-${i}`);card.setAttribute('aria-pressed',String(i===1));hostCards.push(card);nodes['workbench-host-list'].append(card);}
  for(let i=1;i<=pending;i++)nodes['workbench-pending-list'].append(button(`pending-${i}`));
  const hostTabButtons=[];
  for(let i=1;i<=hostTabs;i++){const tab=button(`host-tab-${i}`);tab.setAttribute('aria-pressed',String(i===1));hostTabButtons.push(tab);nodes['host-tabs'].append(tab);}
  const viewTabButtons=[];
  for(let i=1;i<=viewTabs;i++){const tab=button(`view-tab-${i}`);tab.setAttribute('aria-pressed',String(i===1));viewTabButtons.push(tab);nodes['view-tabs'].append(tab);}
  const panels=[];
  const mkPanel=(id,focused)=>{
    // bare=true 模拟单面板的真实形态：没有 section 包装层，#view-content 自身就是唯一面板。
    const panel=bare?nodes['view-content']:new Element('section');
    if(!bare){panel.dataset.role='workbench-panel';panel.dataset.tabId=id;panel.dataset.focus=String(focused);}
    if(split){const head=new Element('div');const focus=button(`panel-focus-${id}`);focus.dataset.role='panel-focus';focus.setAttribute('aria-pressed',String(focused));focus.disabled=focused;head.append(focus);panel.append(head);}
    panel.append(button(`close-${id}`));
    const draft=new Element('textarea');draft.setAttribute('aria-label','当前标签草稿');draft.disabled=!focused;panel.append(draft);
    if(!bare)nodes['view-content'].append(panel);panels.push(panel);return panel;
  };
  mkPanel('a',true);
  if(split)mkPanel('b',false);
  if(bare){nodes['view-content'].dataset.role='workbench-panel';nodes['view-content'].dataset.focus='true';}
  nodes['workbench-split'].hidden=!(innerWidth>=900 && viewTabs>=2);
  nodes['workbench-split'].onclick=()=>clicks.push('workbench-split');
  nodes['host-return-home'].onclick=()=>clicks.push('host-return-home');
  globalThis.document={hidden:false,activeElement:null,getElementById:id=>nodes[id],createElement:tag=>new Element(tag),
    addEventListener:(name,fn)=>{(listeners[name] ??= []).push(fn);},removeEventListener:(name,fn)=>{listeners[name]=(listeners[name]||[]).filter(f=>f!==fn);}};
  globalThis.window={innerWidth};
  initKeyRouter();
  const key=over=>{const event={type:'keydown',key:'',ctrlKey:false,shiftKey:false,altKey:false,metaKey:false,repeat:false,isComposing:false,keyCode:0,
    preventDefault(){event.consumed=true;},stopPropagation(){},...over};for(const fn of [...listeners.keydown||[]])fn(event);return event;};
  return {nodes,clicks,panels,hostCards,hostTabButtons,viewTabButtons,
    draft:()=>panels[0].all().find(n=>n.tagName==='textarea'),
    partnerDraft:()=>panels[1]?.all().find(n=>n.tagName==='textarea'),
    active:()=>globalThis.document.activeElement,key,
    setWidth:width=>{globalThis.window.innerWidth=width;},
    restore:()=>{globalThis.document=oldDocument;globalThis.window=oldWindow;}};
}

test('main.js 装配点必须接线键盘路由层', async () => {
  const source=await readFile(new URL('../src/main.js', import.meta.url),'utf8');
  assert.ok(source.includes("from './key-router.js'"),'main.js 需要导入 initKeyRouter');
  assert.ok(source.includes('initKeyRouter();'),'main.js 需要在 initRemote 后初始化键盘路由层');
});

test('F6 焦点轮转按 侧栏主机→待处理→主机标签→终端标签→面板→输入区 顺序并首尾循环', () => {
  const s=setupRouter();
  try {
    const order=[s.hostCards[0],s.nodes['workbench-pending-list'].children[0],s.hostTabButtons[0],s.viewTabButtons[0],s.panels[0].children[0],s.draft()];
    for(const expected of order){const ev=s.key({key:'F6'});assert.ok(ev.consumed,'F6 应被消费');assert.equal(s.active(),expected);}
    assert.equal(s.active(),order[order.length-1],'已到输入区（最后一个区域）');
    const plain=s.key({key:'F6'});
    assert.equal(plain.consumed,undefined,'输入区是文本输入：纯 F6 必须放行，不得拦截（docs/05:143 冲突规则）');
    const wrap=s.key({key:'F6',ctrlKey:true,shiftKey:true});
    assert.ok(wrap.consumed,'Ctrl+Shift+F6 是离开输入区的唯一出口');
    assert.equal(s.active(),order[0],'离开输入区后回到侧栏主机列表（循环）');
    // Shift+F6 反向：非输入焦点下从侧栏主机列表退回应是输入区（尾区域）
    s.key({key:'F6',shiftKey:true});
    assert.equal(s.active(),order[order.length-1],'Shift+F6 反向轮转并循环');
    assert.equal(s.clicks.length,0,'焦点轮转只移动焦点，不触发任何按钮');
  } finally { s.restore(); }
});

test('F6 落在区域内的当前项（aria-pressed=true），不是第一项', () => {
  const s=setupRouter();
  try {
    s.hostCards[0].setAttribute('aria-pressed','false');
    s.hostCards[1].setAttribute('aria-pressed','true');
    s.key({key:'F6'});
    assert.equal(s.active(),s.hostCards[1]);
  } finally { s.restore(); }
});

test('窄窗（<900px）跳过侧栏区域，轮转从主机标签开始', () => {
  const s=setupRouter({innerWidth:800});
  try {
    s.key({key:'F6'});
    assert.equal(s.active(),s.hostTabButtons[0],'侧栏在窄窗被 CSS 隐藏，不得成为焦点目标');
    s.key({key:'F6'});
    assert.equal(s.active(),s.viewTabButtons[0]);
  } finally { s.restore(); }
});

test('输入聚焦时除 Ctrl+Shift+F6 外全部放行：不消费、不点击、焦点不动', () => {
  const s=setupRouter();
  try {
    s.draft().focus();
    for(const over of [{key:'a'},{key:'F6'},{key:'F6',shiftKey:true},{key:'1',ctrlKey:true},{key:'c',ctrlKey:true},{key:'Tab',ctrlKey:true},{key:'\\',ctrlKey:true,shiftKey:true},{key:'Home',altKey:true},{key:'F6',ctrlKey:true}]) {
      const ev=s.key(over);
      assert.equal(ev.consumed,undefined,`输入聚焦时 ${JSON.stringify(over)} 不得被应用层消费`);
    }
    assert.equal(s.clicks.length,0,'输入聚焦时不得触发任何按钮（可打印字符与终端快捷键原样进入终端）');
    assert.equal(s.active(),s.draft());
    const ev=s.key({key:'F6',ctrlKey:true,shiftKey:true});
    assert.ok(ev.consumed,'Ctrl+Shift+F6 是输入焦点内唯一可用的应用快捷键');
    assert.equal(s.active(),s.hostCards[0],'离开输入区后落到第一区域');
  } finally { s.restore(); }
});

test('IME 组合期间（isComposing / keyCode 229）任何按键都不被应用层拦截', () => {
  const s=setupRouter();
  try {
    s.draft().focus();
    for(const over of [{key:'F6',ctrlKey:true,shiftKey:true,isComposing:true},{key:'F6',ctrlKey:true,shiftKey:true,keyCode:229},{key:'1',ctrlKey:true,isComposing:true}]) {
      const ev=s.key(over);
      assert.equal(ev.consumed,undefined,`组合期间 ${JSON.stringify(over)} 不得被消费`);
    }
    assert.equal(s.clicks.length,0);
    assert.equal(s.active(),s.draft());
  } finally { s.restore(); }
});

test('Ctrl+1..8 切换终端标签；越界与未映射数字无副作用', () => {
  const s=setupRouter();
  try {
    const ev2=s.key({key:'2',ctrlKey:true});
    assert.ok(ev2.consumed);assert.deepEqual(s.clicks,['view-tab-2']);
    s.key({key:'1',ctrlKey:true});
    assert.deepEqual(s.clicks,['view-tab-2','view-tab-1']);
    const ev3=s.key({key:'3',ctrlKey:true});  // 只有 2 个标签：越界
    assert.equal(ev3.consumed,undefined);assert.equal(s.clicks.length,2);
    const ev9=s.key({key:'9',ctrlKey:true});  // 超 8 上限：未映射
    assert.equal(ev9.consumed,undefined);assert.equal(s.clicks.length,2);
  } finally { s.restore(); }
});

test('Alt+1..8 切换主机标签；禁用主机标签不被触发', () => {
  const s=setupRouter();
  try {
    const ev=s.key({key:'2',altKey:true});
    assert.ok(ev.consumed);assert.deepEqual(s.clicks,['host-tab-2']);
    s.hostTabButtons[1].disabled=true;  // 配对忙碌等场景下主机标签禁用
    const ev2=s.key({key:'2',altKey:true});
    assert.equal(ev2.consumed,undefined,'禁用按钮不得被快捷键触发');
    assert.equal(s.clicks.length,1);
  } finally { s.restore(); }
});

test('Ctrl+Tab / Ctrl+Shift+Tab 相对当前标签循环切换；单标签时无操作', () => {
  const s=setupRouter();
  try {
    const ev=s.key({key:'Tab',ctrlKey:true});
    assert.ok(ev.consumed);assert.deepEqual(s.clicks,['view-tab-2']);
    s.viewTabButtons[0].setAttribute('aria-pressed','false');
    s.viewTabButtons[1].setAttribute('aria-pressed','true');
    s.key({key:'Tab',ctrlKey:true,shiftKey:true});
    assert.deepEqual(s.clicks,['view-tab-2','view-tab-1']);
  } finally { s.restore(); }
  const single=setupRouter({viewTabs:1});
  try {
    const ev=single.key({key:'Tab',ctrlKey:true});
    assert.equal(ev.consumed,undefined,'单标签循环切换无意义，不消费');
    assert.equal(single.clicks.length,0);
  } finally { single.restore(); }
});

test('Ctrl+Shift+\\ 开关分屏：宽窗触发既有按钮，窄窗拒绝', () => {
  const wide=setupRouter({innerWidth:1280});
  try {
    const ev=wide.key({key:'\\',ctrlKey:true,shiftKey:true});
    assert.ok(ev.consumed);assert.deepEqual(wide.clicks,['workbench-split']);
  } finally { wide.restore(); }
  const narrow=setupRouter({innerWidth:800});
  try {
    const ev=narrow.key({key:'\\',ctrlKey:true,shiftKey:true});
    assert.equal(ev.consumed,undefined,'窄窗分屏入口隐藏（切片 2 守卫），快捷键同样拒绝');
    assert.equal(narrow.clicks.length,0);
  } finally { narrow.restore(); }
});

test('Ctrl+F6 分屏面板焦点对调：点击非焦点面板的「设为输入焦点」；未分屏时无操作', () => {
  const split=setupRouter({split:true});
  try {
    const ev=split.key({key:'F6',ctrlKey:true});
    assert.ok(ev.consumed);assert.deepEqual(split.clicks,['panel-focus-b']);
  } finally { split.restore(); }
  const solo=setupRouter();
  try {
    const ev=solo.key({key:'F6',ctrlKey:true});
    assert.equal(ev.consumed,undefined,'未分屏没有可对调面板');
    assert.equal(solo.clicks.length,0);
  } finally { solo.restore(); }
});

test('Alt+Home 返回主机看板：触发既有返回按钮', () => {
  const s=setupRouter();
  try {
    const ev=s.key({key:'Home',altKey:true});
    assert.ok(ev.consumed);assert.deepEqual(s.clicks,['host-return-home']);
  } finally { s.restore(); }
});

test('工作台页隐藏（主机看板/离线实验室）、模态对话框、⌘ 修饰与 repeat 键都不触发快捷键', () => {
  const s=setupRouter();
  try {
    s.nodes['remote-page'].hidden=true;
    for(const over of [{key:'F6'},{key:'1',ctrlKey:true}])assert.equal(s.key(over).consumed,undefined,'非工作台页面不抢键');
    assert.equal(s.clicks.length,0);
    s.nodes['remote-page'].hidden=false;
    globalThis.document.querySelector=() => ({open:true});  // 模态（如字体诊断）打开
    assert.equal(s.key({key:'F6'}).consumed,undefined,'模态打开时不越过对话框');
    globalThis.document.querySelector=() => null;
    for(const over of [{key:'F6',metaKey:true},{key:'1',ctrlKey:true,metaKey:true},{key:'F6',repeat:true}])assert.equal(s.key(over).consumed,undefined);
    assert.equal(s.clicks.length,0);
  } finally { s.restore(); }
});

test('未映射按键与裸 Ctrl+\\（终端 SIGQUIT）不产生任何副作用', () => {
  const s=setupRouter();
  try {
    s.viewTabButtons[0].focus();
    for(const over of [{key:'x'},{key:'b',ctrlKey:true},{key:'\\',ctrlKey:true},{key:'Home'},{key:'F8'},{key:''}]) {
      const ev=s.key(over);
      assert.equal(ev.consumed,undefined,`未映射 ${JSON.stringify(over)} 不得被消费`);
    }
    assert.equal(s.clicks.length,0);
    assert.equal(s.active(),s.viewTabButtons[0],'焦点不被未映射按键移动');
  } finally { s.restore(); }
});

// ---- 与真实 initTabWorkspace 的集成：快捷键必须走既有按钮的同一条受守卫路径 ----
const fixture=JSON.parse(readFileSync(new URL('../../shared/mobile-tabs-v1.json', import.meta.url)));
const target=id=>fixture.targets.find(t=>t.id===id);
import {initTabWorkspace} from '../src/tab-workspace.js';

function setupWorkspace({innerWidth=1280}={}) {
  const oldDocument=globalThis.document, oldWindow=globalThis.window;
  const nodes=Object.fromEntries(['tab-workspace','view-tabs','view-content','workbench-split','remote-page','workbench-host-list','workbench-pending-list','host-tabs','host-return-home'].map(id=>[id,new Element('div')]));
  nodes['remote-page'].hidden=false;
  const listeners={};
  globalThis.document={hidden:false,activeElement:null,getElementById:id=>nodes[id],createElement:tag=>new Element(tag),
    addEventListener:(name,fn)=>{(listeners[name] ??= []).push(fn);},removeEventListener:()=>{}};
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
  initKeyRouter();
  const flush=async()=>{await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));};
  const connectActive=async()=>{const review=nodes['view-content'].all().find(n=>n.tagName==='input');review.checked=true;review.onchange();
    nodes['view-content'].all().find(n=>n.tagName==='button'&&n.textContent==='连接').onclick();await flush();};
  const send=(tab,event)=>channels[observes.findIndex(o=>o.tabId===tab)].onmessage({generation:observes.find(o=>o.tabId===tab).generation,...event});
  const activate=async tab=>{send(tab,{kind:'observation',snapshot:{epoch:1,phase:'active'}});await new Promise(r=>setImmediate(r));
    send(tab,{kind:'frame',epoch:1,frame:{seq:1,full:true,cols:80,rows:24,bytes:[65]}});
    send(tab,{kind:'input_ready',epoch:1,unknown:false,recovery_status:'none'});await flush();};
  const openTab=async id=>{const pane=target(id);const tab=ui.create(pane.hostId,pane);tabTargets[tab]=pane;await ui.select(tab);await connectActive();await activate(tab);return tab;};
  const key=over=>{const event={type:'keydown',key:'',ctrlKey:false,shiftKey:false,altKey:false,metaKey:false,repeat:false,isComposing:false,keyCode:0,
    preventDefault(){event.consumed=true;},stopPropagation(){},...over};for(const fn of [...listeners.keydown||[]])fn(event);return event;};
  return {nodes,ui,calls,observes,terminals,resizes,key,flush,openTab,
    // 单面板（未分屏）没有 section 包装层：#view-content 自身就是唯一面板（带同样的 data-role 标记）。
    panels:()=>{const wrapped=nodes['view-content'].all().filter(n=>n.dataset.role==='workbench-panel');return wrapped.length?wrapped:(nodes['view-content'].dataset.role==='workbench-panel'?[nodes['view-content']]:[]);},
    panelOf:id=>{const wrapped=nodes['view-content'].all().find(n=>n.dataset.role==='workbench-panel'&&n.dataset.tabId===id);return wrapped??(nodes['view-content'].dataset.role==='workbench-panel'&&nodes['view-content'].dataset.tabId===id?nodes['view-content']:undefined);},
    restore:()=>{globalThis.document=oldDocument;globalThis.window=oldWindow;}};
}

test('Ctrl+数字经真实工作台切标签：走既有 select 路径（旧标签暂停、面板焦点翻转）', async () => {
  const s=setupWorkspace();
  try {
    const a=await s.openTab('direct-pane-a');
    await s.openTab('mesh-pane-b');
    const ev=s.key({key:'1',ctrlKey:true});
    assert.ok(ev.consumed);
    await s.flush();
    assert.equal(s.panelOf(a).dataset.focus,'true','Ctrl+1 与点击标签走同一路径');
    assert.ok(s.calls.some(c=>c.name==='remote_tab_control'&&c.args.tabId!==a&&c.args.action==='pause'),'切走的活动标签被暂停（既有语义）');
    assert.equal(s.resizes.length,0,'切标签不触发任何终端 resize');
  } finally { s.restore(); }
});

test('单面板无包装层：#view-content 自身是唯一面板，F6 仍轮转到输入区，Ctrl+F6 无可对调面板', () => {
  const s=setupRouter({bare:true});
  try {
    assert.equal(s.nodes['view-content'].all().filter(n=>n.dataset.role==='workbench-panel').length,0,'单面板不得有 section 包装层');
    const order=[s.hostCards[0],s.nodes['workbench-pending-list'].children[0],s.hostTabButtons[0],s.viewTabButtons[0],s.nodes['view-content'].children[0],s.draft()];
    for(const expected of order){const ev=s.key({key:'F6'});assert.ok(ev.consumed,'F6 应被消费');assert.equal(s.active(),expected);}
    assert.equal(s.active(),s.draft(),'输入区（草稿编辑器）仍是轮转的最后一站');
    const wrap=s.key({key:'F6',ctrlKey:true,shiftKey:true});
    assert.ok(wrap.consumed,'Ctrl+Shift+F6 是离开输入区的唯一出口');
    assert.equal(s.active(),s.hostCards[0],'离开输入区后回到侧栏主机列表');
    const swap=s.key({key:'F6',ctrlKey:true});
    assert.equal(swap.consumed,undefined,'单面板没有可对调的副面板');
    assert.equal(s.clicks.length,0,'焦点轮转只移动焦点，不触发任何按钮');
  } finally { s.restore(); }
});

test('Ctrl+Shift+\\ 经真实工作台开关分屏：双面板挂载，全程无 resize/重观察', async () => {
  const s=setupWorkspace();
  try {
    await s.openTab('direct-pane-a');
    await s.openTab('mesh-pane-b');
    const observesBefore=s.observes.length;
    s.key({key:'\\',ctrlKey:true,shiftKey:true});await s.flush();
    assert.equal(s.panels().length,2,'快捷键开分屏挂载双面板');
    s.key({key:'\\',ctrlKey:true,shiftKey:true});await s.flush();
    assert.equal(s.panels().length,1,'再按关闭分屏');
    assert.equal(s.resizes.length,0,'开关分屏不得触发 terminal.resize（docs/05:137）');
    assert.equal(s.observes.length,observesBefore,'不得重新发起观察');
    assert.ok(!s.calls.some(c=>c.name.includes('resize')),'不得出现任何 resize 类后端调用');
  } finally { s.restore(); }
});

test('逐键输入聚焦终端时，路由层对任何按键零副作用：无 invoke、无标签切换', async () => {
  const s=setupWorkspace();
  try {
    await s.openTab('direct-pane-a');
    const b=await s.openTab('mesh-pane-b');
    s.panelOf(b).all().find(n=>n.tagName==='button'&&n.textContent==='逐键输入').onclick();await s.flush();
    const bTerm=s.terminals.find(t=>t.options.disableStdin===false);
    assert.equal(globalThis.document.activeElement,bTerm.textarea,'逐键输入后焦点在终端 textarea');
    const callsBefore=s.calls.length;
    for(const over of [{key:'x'},{key:'1',ctrlKey:true},{key:'c',ctrlKey:true},{key:'Tab',ctrlKey:true},{key:'\\',ctrlKey:true,shiftKey:true}]) {
      const ev=s.key(over);
      assert.equal(ev.consumed,undefined,`终端聚焦时 ${JSON.stringify(over)} 必须原样放行`);
    }
    assert.equal(s.calls.length,callsBefore,'路由层不得产生任何 invoke/发送（docs/05:143 红线）');
    assert.equal(s.panelOf(b).dataset.focus,'true','焦点面板不被快捷键切换');
    const ev=s.key({key:'F6',ctrlKey:true,shiftKey:true});
    assert.ok(ev.consumed,'Ctrl+Shift+F6 可从终端聚焦状态离开输入区');
    assert.equal(globalThis.document.activeElement,s.nodes['view-tabs'].children.find(n=>n.getAttribute('aria-pressed')==='true'),'焦点落到当前终端标签');
  } finally { s.restore(); }
});

test('窄窗集成：分屏快捷键拒绝，标签切换仍可用', async () => {
  const s=setupWorkspace({innerWidth:800});
  try {
    const a=await s.openTab('direct-pane-a');
    await s.openTab('mesh-pane-b');
    const ev=s.key({key:'\\',ctrlKey:true,shiftKey:true});await s.flush();
    assert.equal(ev.consumed,undefined,'窄窗拒绝分屏快捷键（与切片 2 守卫一致）');
    assert.equal(s.panels().length,1);
    const ev2=s.key({key:'1',ctrlKey:true});await s.flush();
    assert.ok(ev2.consumed,'窄窗下非分屏快捷键仍可用（docs/05:143：窄窗口仍能完成核心流程）');
    assert.equal(s.panelOf(a).dataset.focus,'true');
  } finally { s.restore(); }
});
