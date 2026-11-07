import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const fixture=JSON.parse(readFileSync(new URL('../../shared/mobile-tabs-v1.json', import.meta.url)));
const target=id=>fixture.targets.find(t=>t.id===id);
import {initTabWorkspace} from '../src/tab-workspace.js';
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.attrs={};this.value='';this.disabled=false;this.hidden=false;this.textContent='';}
  append(...xs){for(const x of xs)this.children.push(x);}
  replaceChildren(...xs){this.replaceCount=(this.replaceCount || 0)+1;this.children=[];this.append(...xs);}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(name,fn){this['event_'+name]=fn;}
  focus(){globalThis.document.activeElement=this;}
  contains(node){return node===this || this.all().includes(node);}
  all(){return this.children.flatMap(x=>[x,...x.all()]);}
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
test('MT02 MT03 MT10: switching pauses old connection, explicit resume, stale frame cannot ACK',async()=>{
  const oldDocument=globalThis.document;
  const nodes=Object.fromEntries(['tab-workspace','view-tabs','view-content'].map(id=>[id,new Element('div')]));
  globalThis.document={hidden:false,getElementById:id=>nodes[id],createElement:tag=>new Element(tag)};
  const calls=[],channels=[],pending=[];
  const invoke=(name,args)=>{calls.push({name,args});if(name==='remote_tab_reserve')return Promise.resolve(calls.length);if(name==='remote_tab_observe'){pending.push(args);return new Promise(()=>{});}return Promise.resolve();};
  const fakeTerminal=()=>({parser:{registerOscHandler(){}},textarea:{setAttribute(){}},open(){},write(_b,done){done();},reset(){},dispose(){}});
  try {
    const ui=initTabWorkspace({native:true,invoke,theme:{terminal:{}},hostName:id=>id,hostInfo:id=>({target:{username:'u',host:id,port:22},hostFingerprint:'key',deviceFingerprint:'device'}),channelFactory:()=>{const c={};channels.push(c);return c;},terminalFactory:fakeTerminal});
    const direct=target('direct-pane-a'),mesh=target('mesh-pane-b');
    const a=ui.create(direct.hostId,direct);
    const button=label=>nodes['view-content'].all().find(n=>n.tagName==='button' && n.textContent===label);
    let review=nodes['view-content'].all().find(n=>n.tagName==='input');review.checked=true;review.onchange();
    button('连接').onclick();await flush();await flush();
    const first=pending[0];assert.ok(first);channels[0].onmessage({kind:'observation',generation:first.generation,snapshot:{epoch:1,phase:'active'}});
    const b=ui.create(mesh.hostId,mesh);
    await ui.select(b);
    assert.ok(calls.some(c=>c.name==='remote_tab_control' && c.args.tabId===a && c.args.action==='pause'));
    assert.ok(!calls.some(c=>c.name==='remote_tab_control' && c.args.tabId===b && c.args.action==='resume'));
    const before=calls.filter(c=>c.name==='remote_tab_ack').length;
    channels[0].onmessage({kind:'frame',generation:first.generation,epoch:1,frame:{seq:1,full:true,bytes:[65]}});
    await flush();assert.equal(calls.filter(c=>c.name==='remote_tab_ack').length,before);
    assert.equal(calls.filter(c=>c.name==='remote_tab_cancel').length,0);
  } finally {globalThis.document=oldDocument;}
});

test('MT07 MT10: background during reservation cancels late lease and never observes',async()=>{
  const oldDocument=globalThis.document;
  const nodes=Object.fromEntries(['tab-workspace','view-tabs','view-content'].map(id=>[id,new Element('div')]));
  globalThis.document={hidden:false,getElementById:id=>nodes[id],createElement:tag=>new Element(tag)};
  let resolveReserve;const calls=[];
  const invoke=(name,args)=>{calls.push({name,args});if(name==='remote_tab_reserve')return new Promise(resolve=>{resolveReserve=resolve;});return Promise.resolve();};
  try {
    const ui=initTabWorkspace({native:true,invoke,theme:{terminal:{}},hostName:id=>id,hostInfo:id=>({target:{username:'u',host:id,port:22},hostFingerprint:'key',deviceFingerprint:'device'}),channelFactory:()=>({}),terminalFactory:()=>{throw Error('unexpected terminal');}});
    const id=ui.create('host',{paneId:'w1:p1',terminalId:'term_a001'});
    let review=nodes['view-content'].all().find(n=>n.tagName==='input');review.checked=true;review.onchange();
    nodes['view-content'].all().find(n=>n.textContent==='连接').onclick();await flush();ui.background();resolveReserve(17);await flush();await flush();
    assert.equal(calls.filter(c=>c.name==='remote_tab_cancel' && c.args.tabId===id && c.args.generation===17).length,1);
    assert.equal(calls.filter(c=>c.name==='remote_tab_observe').length,0);
  } finally {globalThis.document=oldDocument;}
});

test('MT06 MT12: affected host must close and reopen; unrelated tab stays available',async()=>{
  const oldDocument=globalThis.document;
  const nodes=Object.fromEntries(['tab-workspace','view-tabs','view-content'].map(id=>[id,new Element('div')]));
  globalThis.document={hidden:false,getElementById:id=>nodes[id],createElement:tag=>new Element(tag)};
  const direct=target('direct-pane-a'),mesh=target('mesh-pane-b');
  const invoke=async()=>{};
  try {
    const ui=initTabWorkspace({native:true,invoke,theme:{terminal:{}},hostName:id=>id,hostInfo:id=>({target:{username:'u',host:id,port:22},hostFingerprint:'key',deviceFingerprint:'device'}),channelFactory:()=>({}),terminalFactory:()=>{}});
    ui.create(direct.hostId,direct);const b=ui.create(mesh.hostId,mesh);
    ui.affected([direct.hostId]);await flush();
    const review=nodes['view-content'].all().find(n=>n.tagName==='input');review.checked=true;review.onchange();
    assert.equal(nodes['view-content'].all().find(n=>n.textContent==='连接').disabled,true);
    await ui.select(b);const other=nodes['view-content'].all().find(n=>n.tagName==='input');other.checked=true;other.onchange();
    assert.equal(nodes['view-content'].all().find(n=>n.textContent==='连接').disabled,false);
  } finally {globalThis.document=oldDocument;}
});

test('MT09 MT10: direct input sends only current visible epoch and stops after switch',async()=>{
  const oldDocument=globalThis.document, oldWindow=globalThis.window;
  const nodes=Object.fromEntries(['tab-workspace','view-tabs','view-content'].map(id=>[id,new Element('div')]));
  globalThis.document={hidden:false,activeElement:null,getElementById:id=>nodes[id],createElement:tag=>new Element(tag)};
  globalThis.window={confirm:()=>true};
  const calls=[],channels=[],observers=[];let term;
  const invoke=(name,args)=>{calls.push({name,args});if(name==='remote_tab_reserve')return Promise.resolve(9);if(name==='remote_tab_observe'){observers.push(args);return new Promise(()=>{});}if(name==='remote_tab_input_mode')return Promise.resolve(5);if(name==='remote_tab_input_send')return Promise.resolve({status:'accepted',receipt:{requestId:'a'.repeat(32),paneId:'w1:p1',terminalId:'term_a001',acceptedBytes:args.bytes.length}});return Promise.resolve();};
  const fakeTerminal=()=>{term={options:{},parser:{registerOscHandler(){}},textarea:new Element('textarea'),open(){},write(_b,done){done();},reset(){},dispose(){},focus(){document.activeElement=this.textarea;},onData(fn){this.data=fn;}};return term;};
  try {
    const ui=initTabWorkspace({native:true,invoke,theme:{terminal:{}},hostName:id=>id,hostInfo:id=>({target:{username:'u',host:id,port:22},hostFingerprint:'key',deviceFingerprint:'device'}),channelFactory:()=>{const c={};channels.push(c);return c;},terminalFactory:fakeTerminal});
    const direct=target('direct-pane-a'),mesh=target('mesh-pane-b');ui.create(direct.hostId,direct);
    const find=label=>nodes['view-content'].all().find(n=>n.textContent===label);
    const review=nodes['view-content'].all().find(n=>n.tagName==='input');review.checked=true;review.onchange();find('连接').onclick();await flush();await flush();
    const g=observers[0].generation;channels[0].onmessage({kind:'observation',generation:g,snapshot:{epoch:1,phase:'starting'}});
    channels[0].onmessage({kind:'frame',generation:g,epoch:1,frame:{seq:1,full:true,bytes:[65]}});await flush();
    channels[0].onmessage({kind:'observation',generation:g,snapshot:{epoch:1,phase:'active'}});
    channels[0].onmessage({kind:'input_ready',generation:g,epoch:1,unknown:false,recovery_status:'ready'});
    find('逐键输入').onclick();await flush();await flush();term.data('a');await flush();
    assert.equal(calls.filter(c=>c.name==='remote_tab_input_send' && c.args.draft===false).length,1);
    const beforeRender=nodes['view-content'].replaceCount;const b=ui.create(mesh.hostId,mesh);
    assert.equal(nodes['view-content'].replaceCount,beforeRender,'another tab must not detach focused direct terminal');
    await ui.select(b);term.data('b');await flush();
    assert.equal(calls.filter(c=>c.name==='remote_tab_input_send').length,1);
  } finally {globalThis.document=oldDocument;globalThis.window=oldWindow;}
});

test('MT03 MT10: hiding while resume is pending supersedes it without cancelling SSH',async()=>{
  const oldDocument=globalThis.document;
  const nodes=Object.fromEntries(['tab-workspace','view-tabs','view-content'].map(id=>[id,new Element('div')]));
  globalThis.document={hidden:false,getElementById:id=>nodes[id],createElement:tag=>new Element(tag)};
  const calls=[],channels=[],observed=[];let rejectResume;
  const invoke=(name,args)=>{calls.push({name,args});if(name==='remote_tab_reserve')return Promise.resolve(9);if(name==='remote_tab_observe'){observed.push(args);return new Promise(()=>{});}if(name==='remote_tab_control' && args.action==='resume')return new Promise((_,reject)=>{rejectResume=reject;});return Promise.resolve();};
  try {
    const ui=initTabWorkspace({native:true,invoke,theme:{terminal:{}},hostName:id=>id,hostInfo:id=>({target:{username:'u',host:id,port:22},hostFingerprint:'key',deviceFingerprint:'device'}),channelFactory:()=>{const c={};channels.push(c);return c;},terminalFactory:()=>{}});
    const direct=target('direct-pane-a'),mesh=target('mesh-pane-b');const a=ui.create(direct.hostId,direct);
    const find=label=>nodes['view-content'].all().find(n=>n.textContent===label);
    const review=nodes['view-content'].all().find(n=>n.tagName==='input');review.checked=true;review.onchange();find('连接').onclick();await flush();await flush();
    const g=observed[0].generation;channels[0].onmessage({kind:'observation',generation:g,snapshot:{epoch:1,phase:'active'}});
    const b=ui.create(mesh.hostId,mesh);await ui.select(b);channels[0].onmessage({kind:'observation',generation:g,snapshot:{epoch:2,phase:'paused'}});
    await ui.select(a);find('恢复观察').onclick();await flush();await flush();assert.ok(rejectResume);
    channels[0].onmessage({kind:'observation',generation:g,snapshot:{epoch:3,phase:'resuming'}});
    const change=ui.select(b);await flush();rejectResume('control_superseded');await change;await flush();
    channels[0].onmessage({kind:'observation',generation:g,snapshot:{epoch:4,phase:'paused'}});
    channels[0].onmessage({kind:'observation',generation:g,snapshot:{epoch:3,phase:'active'}});
    await ui.select(a);assert.ok(find('恢复观察'));assert.equal(calls.filter(c=>c.name==='remote_tab_cancel').length,0);
  } finally {globalThis.document=oldDocument;}
});

test('MT07: background cancels every live tab, including a paused one',async()=>{
  const oldDocument=globalThis.document;
  const nodes=Object.fromEntries(['tab-workspace','view-tabs','view-content'].map(id=>[id,new Element('div')]));
  globalThis.document={hidden:false,getElementById:id=>nodes[id],createElement:tag=>new Element(tag)};
  const calls=[],channels=[],observed=[];let seq=0;
  const invoke=(name,args)=>{calls.push({name,args});if(name==='remote_tab_reserve')return Promise.resolve(++seq);if(name==='remote_tab_observe'){observed.push(args);return new Promise(()=>{});}return Promise.resolve();};
  try {
    const ui=initTabWorkspace({native:true,invoke,theme:{terminal:{}},hostName:id=>id,hostInfo:id=>({target:{username:'u',host:id,port:22},hostFingerprint:'key',deviceFingerprint:'device'}),channelFactory:()=>{const c={};channels.push(c);return c;},terminalFactory:()=>{}});
    const direct=target('direct-pane-a'),mesh=target('mesh-pane-b');const a=ui.create(direct.hostId,direct);
    const start=async()=>{const review=nodes['view-content'].all().find(n=>n.tagName==='input');review.checked=true;review.onchange();nodes['view-content'].all().find(n=>n.textContent==='连接').onclick();await flush();await flush();};
    await start();channels[0].onmessage({kind:'observation',generation:observed[0].generation,snapshot:{epoch:1,phase:'active'}});
    const b=ui.create(mesh.hostId,mesh);await ui.select(b);channels[0].onmessage({kind:'observation',generation:observed[0].generation,snapshot:{epoch:2,phase:'paused'}});
    await start();ui.background();await flush();
    assert.deepEqual(calls.filter(c=>c.name==='remote_tab_cancel').map(c=>c.args.tabId).sort(),[a,b].sort());
  } finally {globalThis.document=oldDocument;}
});

test('MT08 MT10: late draft-mode and rejected-send replies cannot overwrite a new epoch',async()=>{
  const oldDocument=globalThis.document,oldWindow=globalThis.window;
  const nodes=Object.fromEntries(['tab-workspace','view-tabs','view-content'].map(id=>[id,new Element('div')]));
  globalThis.document={hidden:false,activeElement:null,getElementById:id=>nodes[id],createElement:tag=>new Element(tag)};globalThis.window={confirm:()=>true};
  const calls=[],channels=[],observed=[];let resolveMode,resolveSend,delayMode=true;
  const invoke=(name,args)=>{calls.push({name,args});if(name==='remote_tab_reserve')return Promise.resolve(3);if(name==='remote_tab_observe'){observed.push(args);return new Promise(()=>{});}if(name==='remote_tab_input_mode' && args.mode==='draft'){if(delayMode)return new Promise(resolve=>{resolveMode=resolve;});return Promise.resolve(10);}if(name==='remote_tab_input_send')return new Promise(resolve=>{resolveSend=resolve;});return Promise.resolve();};
  const fakeTerminal=()=>({options:{},parser:{registerOscHandler(){}},textarea:new Element('textarea'),open(){},write(_b,done){done();},reset(){},dispose(){},onData(){}});
  try {
    const ui=initTabWorkspace({native:true,invoke,theme:{terminal:{}},hostName:id=>id,hostInfo:id=>({target:{username:'u',host:id,port:22},hostFingerprint:'key',deviceFingerprint:'device'}),channelFactory:()=>{const c={};channels.push(c);return c;},terminalFactory:fakeTerminal});
    const direct=target('direct-pane-a');ui.create(direct.hostId,direct);
    const find=label=>nodes['view-content'].all().find(n=>n.textContent===label);
    const review=nodes['view-content'].all().find(n=>n.tagName==='input');review.checked=true;review.onchange();find('连接').onclick();await flush();await flush();
    const g=observed[0].generation;
    const frame=(epoch)=>{channels[0].onmessage({kind:'observation',generation:g,snapshot:{epoch,phase:'resuming'}});channels[0].onmessage({kind:'frame',generation:g,epoch,frame:{seq:1,full:true,bytes:[65]}});channels[0].onmessage({kind:'observation',generation:g,snapshot:{epoch,phase:'active'}});channels[0].onmessage({kind:'input_ready',generation:g,epoch,unknown:false,recovery_status:'ready'});};
    frame(1);find('启用草稿输入').onclick();await flush();frame(2);resolveMode(9);await flush();
    assert.equal(find('发送草稿').disabled,true);
    delayMode=false;find('启用草稿输入').onclick();await flush();let textarea=nodes['view-content'].all().find(n=>n.tagName==='textarea');textarea.value='old';textarea.oninput();find('发送草稿').onclick();await flush();
    frame(3);textarea=nodes['view-content'].all().find(n=>n.tagName==='textarea');textarea.value='new';textarea.oninput();resolveSend({status:'rejected'});await flush();
    assert.equal(nodes['view-content'].all().find(n=>n.tagName==='textarea').value,'new');assert.equal(find('发送草稿').disabled,true);
  } finally {globalThis.document=oldDocument;globalThis.window=oldWindow;}
});

test('MT12: changed network revision invalidates prior review before reserve',async()=>{
  const oldDocument=globalThis.document;
  const nodes=Object.fromEntries(['tab-workspace','view-tabs','view-content'].map(id=>[id,new Element('div')]));
  globalThis.document={hidden:false,getElementById:id=>nodes[id],createElement:tag=>new Element(tag)};
  const calls=[];let revision=1;
  try {
    const ui=initTabWorkspace({native:true,invoke:async(name,args)=>{calls.push({name,args});},theme:{terminal:{}},hostName:id=>id,hostInfo:id=>({target:{username:'u',host:id,port:22},hostFingerprint:'key',deviceFingerprint:'device',networkProfileId:'mesh',networkRevision:revision}),channelFactory:()=>({}),terminalFactory:()=>{}});
    const mesh=target('mesh-pane-b');ui.create(mesh.hostId,mesh);
    const review=nodes['view-content'].all().find(n=>n.tagName==='input');review.checked=true;review.onchange();revision=2;
    nodes['view-content'].all().find(n=>n.textContent==='连接').onclick();await flush();
    assert.equal(calls.filter(c=>c.name==='remote_tab_reserve').length,0);
    assert.ok(nodes['view-content'].all().some(n=>n.textContent.includes('重新核对')));
  } finally {globalThis.document=oldDocument;}
});

test('MT01 MT05: same-host panes are separate; closing the active view does not activate its neighbour',async()=>{
  const oldDocument=globalThis.document;
  const nodes=Object.fromEntries(['tab-workspace','view-tabs','view-content'].map(id=>[id,new Element('div')]));
  globalThis.document={hidden:false,getElementById:id=>nodes[id],createElement:tag=>new Element(tag)};
  const calls=[];
  try {
    const ui=initTabWorkspace({native:true,invoke:async(name,args)=>calls.push({name,args}),theme:{terminal:{}},hostName:id=>id,hostInfo:id=>({target:{username:'u',host:id,port:22},hostFingerprint:'key',deviceFingerprint:'device'}),channelFactory:()=>({}),terminalFactory:()=>{}});
    const a=target('direct-pane-a'),c=target('direct-pane-c');const one=ui.create(a.hostId,a),two=ui.create(c.hostId,c);
    assert.notEqual(one,two);assert.equal(nodes['view-tabs'].children.length,2);await ui.select(two);
    nodes['view-content'].all().find(n=>n.textContent==='关闭此标签').onclick();await flush();
    assert.equal(nodes['view-tabs'].children.length,1);assert.equal(nodes['view-content'].children.length,0);
    assert.ok(!calls.some(c=>c.name==='network_node_stop'));
  } finally {globalThis.document=oldDocument;}
});

test('MT02 MT08: blur during direct input pauses rather than disconnects and does not resend',async()=>{
  const oldDocument=globalThis.document;
  const nodes=Object.fromEntries(['tab-workspace','view-tabs','view-content'].map(id=>[id,new Element('div')]));
  globalThis.document={hidden:false,activeElement:null,getElementById:id=>nodes[id],createElement:tag=>new Element(tag)};
  const calls=[],channels=[],observed=[];let term;
  const invoke=(name,args)=>{calls.push({name,args});if(name==='remote_tab_reserve')return Promise.resolve(9);if(name==='remote_tab_observe'){observed.push(args);return new Promise(()=>{});}if(name==='remote_tab_input_mode')return Promise.resolve(5);if(name==='remote_tab_input_send')return new Promise(()=>{});return Promise.resolve();};
  const fakeTerminal=()=>{term={options:{},parser:{registerOscHandler(){}},textarea:new Element('textarea'),open(){},write(_b,done){done();},reset(){},dispose(){},focus(){document.activeElement=this.textarea;},onData(fn){this.data=fn;}};return term;};
  try {
    const ui=initTabWorkspace({native:true,invoke,theme:{terminal:{}},hostName:id=>id,hostInfo:id=>({target:{username:'u',host:id,port:22},hostFingerprint:'key',deviceFingerprint:'device'}),channelFactory:()=>{const c={};channels.push(c);return c;},terminalFactory:fakeTerminal});
    const direct=target('direct-pane-a');ui.create(direct.hostId,direct);
    const find=label=>nodes['view-content'].all().find(n=>n.textContent===label);const review=nodes['view-content'].all().find(n=>n.tagName==='input');review.checked=true;review.onchange();find('连接').onclick();await flush();await flush();
    const g=observed[0].generation;channels[0].onmessage({kind:'observation',generation:g,snapshot:{epoch:1,phase:'starting'}});channels[0].onmessage({kind:'frame',generation:g,epoch:1,frame:{seq:1,full:true,bytes:[65]}});await flush();channels[0].onmessage({kind:'observation',generation:g,snapshot:{epoch:1,phase:'active'}});channels[0].onmessage({kind:'input_ready',generation:g,epoch:1,unknown:false,recovery_status:'ready'});
    find('逐键输入').onclick();await flush();term.data('a');await flush();document.activeElement=null;term.textarea.event_blur();await flush();
    assert.equal(calls.filter(c=>c.name==='remote_tab_input_send').length,1);
    assert.equal(calls.filter(c=>c.name==='remote_tab_control' && c.args.action==='pause').length,1);
    assert.equal(calls.filter(c=>c.name==='remote_tab_cancel').length,0);
  } finally {globalThis.document=oldDocument;}
});

for (const edited of ['new draft', '']) test(`MT08: same-epoch edit ${edited ? 'is kept' : 'cleared intentionally'} after rejected send`,async()=>{
  const oldDocument=globalThis.document,oldWindow=globalThis.window;
  const nodes=Object.fromEntries(['tab-workspace','view-tabs','view-content'].map(id=>[id,new Element('div')]));
  globalThis.document={hidden:false,activeElement:null,getElementById:id=>nodes[id],createElement:tag=>new Element(tag)};globalThis.window={confirm:()=>true};
  const channels=[],observed=[];let resolveSend,sends=0;
  const invoke=(name,args)=>{if(name==='remote_tab_reserve')return Promise.resolve(3);if(name==='remote_tab_observe'){observed.push(args);return new Promise(()=>{});}if(name==='remote_tab_input_mode')return Promise.resolve(10);if(name==='remote_tab_input_send'){sends++;return new Promise(resolve=>{resolveSend=resolve;});}return Promise.resolve();};
  const fakeTerminal=()=>({options:{},parser:{registerOscHandler(){}},textarea:new Element('textarea'),open(){},write(_b,done){done();},reset(){},dispose(){},onData(){}});
  try {
    const ui=initTabWorkspace({native:true,invoke,theme:{terminal:{}},hostName:id=>id,hostInfo:id=>({target:{username:'u',host:id,port:22},hostFingerprint:'key',deviceFingerprint:'device'}),channelFactory:()=>{const c={};channels.push(c);return c;},terminalFactory:fakeTerminal});
    const direct=target('direct-pane-a');ui.create(direct.hostId,direct);
    const find=label=>nodes['view-content'].all().find(n=>n.textContent===label);const review=nodes['view-content'].all().find(n=>n.tagName==='input');review.checked=true;review.onchange();find('连接').onclick();await flush();await flush();
    const g=observed[0].generation;channels[0].onmessage({kind:'observation',generation:g,snapshot:{epoch:1,phase:'starting'}});channels[0].onmessage({kind:'frame',generation:g,epoch:1,frame:{seq:1,full:true,bytes:[65]}});channels[0].onmessage({kind:'observation',generation:g,snapshot:{epoch:1,phase:'active'}});channels[0].onmessage({kind:'input_ready',generation:g,epoch:1,unknown:false,recovery_status:'ready'});
    find('启用草稿输入').onclick();await flush();let text=nodes['view-content'].all().find(n=>n.tagName==='textarea');text.value='original';text.oninput();find('发送草稿').onclick();await flush();
    text=nodes['view-content'].all().find(n=>n.tagName==='textarea');text.value='temporary';text.oninput();text.value=edited;text.oninput();resolveSend({status:'rejected'});await flush();
    const textareas=nodes['view-content'].all().filter(n=>n.tagName==='textarea');assert.equal(textareas[0].value,edited);assert.equal(textareas[1].value,'original');assert.equal(textareas[1].readOnly,true);assert.equal(sends,1);
  } finally {globalThis.document=oldDocument;globalThis.window=oldWindow;}
});

function watchWorkspace(fixedTarget=null,options={}) {
  const oldDocument=globalThis.document,oldWindow=globalThis.window;
  const nodes=Object.fromEntries(['tab-workspace','view-tabs','view-content'].map(id=>[id,new Element('div')]));
  globalThis.document={hidden:false,activeElement:null,getElementById:id=>nodes[id],createElement:tag=>new Element(tag)};
  globalThis.window={confirm:()=>true};const calls=[],channels=[],observed=[];let terminal;
  const invoke=(name,args)=>{
    calls.push({name,args});
    if(name==='remote_tab_reserve')return Promise.resolve(9);
    if(name==='remote_tab_observe'){
      observed.push(args);
      return options.observe?options.observe(args):new Promise(()=>{});
    }
    if(name==='remote_tab_select' && options.select)return options.select(args);
    if(name==='remote_tab_input_mode')return options.mode?options.mode(args):Promise.resolve(5);
    if(name==='remote_tab_input_send' && options.send)return options.send(args);
    return Promise.resolve();
  };
  const ui=initTabWorkspace({native:true,invoke,theme:{terminal:{}},hostName:id=>id,hostInfo:id=>({id,enabled:true,retired:false,target:{username:'u',host:id,port:22,session:'work'},hostFingerprint:'key',deviceFingerprint:'device'}),onDashboard:options.onDashboard,channelFactory:()=>{const c={};channels.push(c);return c;},terminalFactory:()=>{
    terminal={
      options:{},focusReadOnly:[],parser:{registerOscHandler(){}},textarea:new Element('textarea'),
      open(){},write(_b,done){done();},reset(){},dispose(){},
      focus(){this.focusReadOnly.push(this.textarea.readOnly);document.activeElement=this.textarea;},
      onData(fn){this.data=fn;},
    };
    Object.defineProperty(terminal.options,'disableStdin',{
      set(value){terminal.textarea.readOnly=value;},
      get(){return terminal.textarea.readOnly;},
    });
    terminal.options.disableStdin=true;
    return terminal;
  }});
  const id=ui.create('fixture',fixedTarget);
  const all=()=>nodes['view-content'].all(),find=label=>all().find(n=>n.textContent===label);
  const start=async()=>{const review=all().find(n=>n.tagName==='input');review.checked=true;review.onchange();find('连接').onclick();await flush();await flush();};
  const emit=event=>channels.at(-1).onmessage({generation:9,...event});
  const watch=(epoch,revision,phase='fresh',panes=[{paneId:'w1:p1',terminalId:'term_a001',agentStatus:'working'}])=>emit({kind:'dashboard_watch',update:{epoch,revision,phase,reason:'fixture',panes}});
  const observation=(epoch,phase)=>emit({kind:'observation',snapshot:{epoch,phase}});
  return {ui,id,calls,nodes,all,find,start,emit,watch,observation,terminal:()=>terminal,restore(){globalThis.document=oldDocument;globalThis.window=oldWindow;}};
}

test('SW01 SW09: watch selection awaits native receiver and freezes pane plus terminal and revision',async()=>{
  const h=watchWorkspace();try {
    await h.start();h.observation(1,'starting');h.watch(1,1);
    let row=h.all().find(n=>n.tagName==='button' && n.textContent.startsWith('选择 w1:p1'));
    assert.equal(row.disabled,true,'fresh publication must not race receiver installation');
    h.emit({kind:'selection_ready',epoch:1});row=h.all().find(n=>n.tagName==='button' && n.textContent.startsWith('选择 w1:p1'));
    assert.equal(row.disabled,false);const oldRow=row;
    h.watch(1,2,'stale',null);oldRow.onclick();await flush();assert.equal(h.calls.filter(c=>c.name==='remote_tab_select').length,0);
    h.watch(1,3,'fresh',[{paneId:'w1:p1',terminalId:'term_def'},{paneId:'w1:p2',terminalId:'term_123'}]);
    oldRow.onclick();await flush();assert.equal(h.calls.filter(c=>c.name==='remote_tab_select').length,0);
    row=h.all().find(n=>n.tagName==='button' && n.textContent.startsWith('选择 w1:p2'));row.onclick();await flush();
    const selected=h.calls.find(c=>c.name==='remote_tab_select').args;
    assert.deepEqual({pane:selected.paneId,terminal:selected.terminalId,epoch:selected.epoch,revision:selected.revision},{pane:'w1:p2',terminal:'term_123',epoch:1,revision:3});
    assert.equal(h.calls.filter(c=>c.name==='remote_tab_observe').length,1,'metadata refresh must not restart SSH or selector');
    assert.ok(!h.calls.some(c=>/input_send|resize/.test(c.name)));
  } finally {h.restore();}
});

test('SW02 SW07: terminal full and stale or reordered metadata cannot rewrite dashboard freshness or unknown lock',async()=>{
  const h=watchWorkspace({paneId:'w1:p1',terminalId:'term_a001'});try {
    await h.start();h.observation(1,'starting');h.watch(1,1);h.emit({kind:'frame',epoch:1,frame:{seq:1,full:true,bytes:[65]}});
    h.observation(1,'active');h.emit({kind:'input_ready',epoch:1,unknown:true,recovery_status:'pending'});
    h.watch(1,3,'stale',null);h.watch(1,2);h.emit({kind:'frame',epoch:1,frame:{seq:2,full:true,bytes:[66]}});await flush();
    assert.ok(h.all().some(n=>n.attrs['data-dashboard-phase']==='stale'));
    assert.equal(h.find('逐键输入').disabled,true);
    h.watch(1,4,'fresh',[{paneId:'w1:p1',terminalId:'term_a001',agentStatus:'blocked'},{paneId:'w1:p2',terminalId:'term_def',agentStatus:'idle'}]);
    assert.ok(h.all().some(n=>n.textContent.includes('w1:p2') && n.textContent.includes('空闲')));
    assert.equal(h.find('逐键输入').disabled,true,'a fresh board must not resolve unknown input');
    h.watch(1,5,'fresh',[{paneId:'w1:p2',terminalId:'term_def',agentStatus:'idle'}]);
    assert.ok(h.all().some(n=>n.textContent==='fixture · w1:p1 · term_a001'),'target remains frozen when row exits');
    assert.ok(!h.calls.some(c=>/input_send|resize/.test(c.name)));
  } finally {h.restore();}
});

test('SW07: dashboard updates preserve focused direct input DOM while showing fresh and stale metadata',async()=>{
  const h=watchWorkspace({paneId:'w1:p1',terminalId:'term_a001'});try {
    await h.start();h.observation(1,'starting');h.watch(1,1);h.emit({kind:'frame',epoch:1,frame:{seq:1,full:true,bytes:[65]}});
    h.observation(1,'active');h.emit({kind:'input_ready',epoch:1,unknown:false,recovery_status:'ready'});
    h.find('逐键输入').onclick();await flush();await flush();const terminal=h.terminal(),before=h.nodes['view-content'].replaceCount;
    h.watch(1,2,'stale',null);assert.ok(h.all().some(n=>n.attrs['data-dashboard-phase']==='stale'));
    h.watch(1,3,'fresh',[{paneId:'w1:p1',terminalId:'term_a001',agentStatus:'blocked'}]);
    assert.equal(h.nodes['view-content'].replaceCount,before);assert.equal(document.activeElement,terminal.textarea);
    assert.ok(h.all().some(n=>n.textContent.includes('受阻')));
    assert.equal(h.calls.filter(c=>c.name==='remote_tab_input_send').length,0);
  } finally {h.restore();}
});

test('SW05 SW07 SW10: hidden watch epochs stay stale until explicit resume; unsupported snapshot remains explicit',async()=>{
  const h=watchWorkspace();try {
    await h.start();h.observation(1,'starting');h.watch(1,1);h.emit({kind:'selection_ready',epoch:1});
    await h.ui.hide();h.observation(2,'paused');h.watch(1,9);
    assert.ok(h.all().some(n=>n.attrs['data-dashboard-phase']==='stale'));assert.equal(h.calls.filter(c=>c.name==='remote_tab_cancel').length,0);
    h.find('恢复观察').onclick();await flush();await flush();
    assert.equal(h.calls.filter(c=>c.name==='remote_tab_control' && c.args.action==='resume').length,1);
    h.observation(3,'resuming');h.watch(1,99);h.watch(3,1,'unavailable',null);h.emit({kind:'selection_ready',epoch:1});
    assert.ok(!h.all().some(n=>n.tagName==='button' && n.textContent.startsWith('选择 ') && !n.disabled));
    h.watch(3,2,'unavailable',[{paneId:'w1:p1',terminalId:'term_a001'}]);h.emit({kind:'selection_ready',epoch:3});
    assert.ok(h.all().some(n=>n.textContent.includes('仅本次快照')));
    assert.ok(h.all().some(n=>n.tagName==='button' && n.textContent.startsWith('选择 ') && !n.disabled));
    h.ui.background();h.watch(3,3);await flush();assert.ok(h.all().some(n=>n.attrs['data-dashboard-phase']==='stale'));
    assert.equal(h.calls.filter(c=>c.name==='remote_tab_reserve').length,1);
  } finally {h.restore();}
});

test('SW09: first frame target proof and a late selection ACK cannot cross a restored epoch',async()=>{
  let resolveSelection;const h=watchWorkspace(null,{select:()=>new Promise(resolve=>{resolveSelection=resolve;})});try {
    await h.start();h.observation(1,'starting');h.watch(1,1);h.emit({kind:'selection_ready',epoch:1});
    h.all().find(n=>n.tagName==='button' && n.textContent.startsWith('选择 w1:p1')).onclick();await flush();
    h.emit({kind:'frame',epoch:1,frame:{seq:1,full:true,bytes:[65]}});h.observation(1,'active');h.emit({kind:'input_ready',epoch:1,unknown:false,recovery_status:'ready'});
    assert.equal(h.find('逐键输入').disabled,true,'an input-ready message cannot invent the selected target');
    h.emit({kind:'target_bound',epoch:1,pane_id:'w1:p1',terminal_id:'term_a001'});
    assert.ok(h.all().some(n=>n.textContent==='fixture · w1:p1 · term_a001'));
    await h.ui.hide();h.observation(2,'paused');h.find('恢复观察').onclick();await flush();await flush();h.observation(3,'resuming');h.watch(3,1);
    h.emit({kind:'target_bound',epoch:1,pane_id:'w1:p1',terminal_id:'term_def'});
    h.emit({kind:'target_bound',epoch:3,pane_id:'w1:p1',terminal_id:'term_a001'});
    h.emit({kind:'frame',epoch:3,frame:{seq:1,full:true,bytes:[66]}});h.observation(3,'active');h.emit({kind:'input_ready',epoch:3,unknown:true,recovery_status:'pending'});
    const resumedDraft=h.all().find(n=>n.tagName==='textarea');resumedDraft.value='恢复后的草稿';resumedDraft.oninput();document.activeElement=resumedDraft;
    resolveSelection();await flush();
    assert.equal(h.all().find(n=>n.tagName==='textarea'),resumedDraft);assert.equal(document.activeElement,resumedDraft);assert.equal(resumedDraft.value,'恢复后的草稿');
    assert.ok(h.all().some(n=>n.textContent==='fixture · w1:p1 · term_a001'));
    assert.equal(h.find('逐键输入').disabled,true);assert.equal(h.calls.filter(c=>c.name==='remote_tab_cancel').length,0);
    assert.equal(h.calls.filter(c=>c.name==='remote_tab_input_send').length,0);
  } finally {h.restore();}
});

test('SW08 SW09: native target proof cannot replace the pane terminal the user actually selected',async()=>{
  const h=watchWorkspace();try {
    await h.start();h.observation(1,'starting');h.watch(1,1);h.emit({kind:'selection_ready',epoch:1});
    h.all().find(n=>n.tagName==='button' && n.textContent.startsWith('选择 w1:p1')).onclick();await flush();
    h.emit({kind:'target_bound',epoch:1,pane_id:'w1:p1',terminal_id:'term_def'});await flush();
    assert.equal(h.calls.filter(c=>c.name==='remote_tab_cancel').length,1);
    assert.ok(h.all().some(n=>n.attrs['data-dashboard-phase']==='stale'));
    assert.equal(h.calls.filter(c=>c.name==='remote_tab_input_send').length,0);
  } finally {h.restore();}
});

test('SW07: live board refresh preserves draft textarea, focus, composition and exact text',async()=>{
  const h=watchWorkspace({paneId:'w1:p1',terminalId:'term_a001'});try {
    await h.start();h.observation(1,'starting');h.watch(1,1);h.emit({kind:'frame',epoch:1,frame:{seq:1,full:true,bytes:[65]}});
    h.observation(1,'active');h.emit({kind:'input_ready',epoch:1,unknown:false,recovery_status:'ready'});
    const draft=h.all().find(n=>n.tagName==='textarea');document.activeElement=draft;
    let composing=false;draft.addEventListener('compositionstart',()=>{composing=true;});draft.addEventListener('compositionend',()=>{composing=false;});
    draft.event_compositionstart();draft.value='草稿 ni';draft.oninput();const before=h.nodes['view-content'].replaceCount;
    const oldRow=h.all().find(n=>n.tagName==='button' && n.textContent.startsWith('新标签：'));
    h.watch(1,2,'stale',null);
    assert.equal(h.all().find(n=>n.tagName==='textarea'),draft);assert.equal(document.activeElement,draft);assert.equal(composing,true);assert.equal(draft.value,'草稿 ni');
    assert.ok(h.all().filter(n=>n.tagName==='button' && n.textContent.startsWith('新标签：')).every(n=>n.disabled));
    h.watch(1,3,'fresh',[{paneId:'w1:p1',terminalId:'term_a001',agentStatus:'blocked'},{paneId:'w1:p2',terminalId:'term_def',agentStatus:'idle'}]);
    h.emit({kind:'target_bound',epoch:1,pane_id:'w1:p1',terminal_id:'term_a001'});
    h.emit({kind:'frame',epoch:1,frame:{seq:2,full:true,bytes:[66]}});
    assert.equal(h.nodes['view-content'].replaceCount,before);assert.equal(h.all().find(n=>n.tagName==='textarea'),draft);assert.equal(document.activeElement,draft);assert.equal(composing,true);
    assert.ok(h.all().some(n=>n.textContent.includes('w1:p2') && !n.disabled));
    // A retained old row still cannot use its obsolete review revision.
    oldRow.onclick();await flush();assert.equal(h.nodes['view-tabs'].children.length,1);
    draft.value='草稿你';draft.event_compositionend();draft.oninput();
    assert.equal(composing,false);assert.equal(draft.value,'草稿你');assert.equal(h.calls.filter(c=>c.name==='remote_tab_input_send').length,0);
  } finally {h.restore();}
});

test('SW07: an explicit new SSH attempt accepts epoch one after the prior attempt reached epoch three',async()=>{
  let endObserve;const h=watchWorkspace({paneId:'w1:p1',terminalId:'term_a001'},{observe:()=>new Promise(resolve=>{endObserve=resolve;})});try {
    await h.start();h.observation(3,'resuming');h.watch(3,1);h.observation(3,'active');
    h.ui.background();endObserve();await flush();await flush();
    assert.equal(h.calls.filter(c=>c.name==='remote_tab_reserve').length,1);
    await h.start();h.observation(1,'starting');h.watch(1,1);
    assert.ok(h.all().some(n=>n.attrs['data-dashboard-phase']==='fresh'));
    h.emit({kind:'frame',epoch:1,frame:{seq:1,full:true,bytes:[65]}});await flush();
    assert.ok(h.calls.some(c=>c.name==='remote_tab_ack' && c.args.epoch===1));
    assert.equal(h.calls.filter(c=>c.name==='remote_tab_reserve').length,2);
    assert.equal(h.calls.filter(c=>c.name==='remote_tab_input_send').length,0);
  } finally {h.restore();}
});

test('IJ04 IJ12: recovery confirmation alone requests observe review focus with the captured input epoch',async()=>{
  const h=watchWorkspace({paneId:'w1:p1',terminalId:'term_a001'});try {
    await h.start();h.observation(1,'starting');h.emit({kind:'frame',epoch:1,frame:{seq:1,full:true,bytes:[65]}});h.observation(1,'active');
    h.emit({kind:'input_ready',epoch:1,unknown:true,recovery_status:'pending'});
    window.confirm=()=>false;h.find('已核实原目标结果，恢复输入').onclick();await flush();
    assert.equal(h.calls.filter(c=>c.name==='remote_tab_input_mode').length,0);
    window.confirm=()=>true;h.find('已核实原目标结果，恢复输入').onclick();await flush();await flush();
    const mode=h.calls.find(c=>c.name==='remote_tab_input_mode').args,recover=h.calls.find(c=>c.name==='remote_tab_input_recover').args;
    assert.equal(mode.mode,'observe');assert.equal(mode.review,true);assert.equal(mode.epoch,1);assert.equal(mode.generation,9);
    assert.equal(recover.epoch,mode.epoch);assert.equal(recover.generation,mode.generation);assert.equal(recover.inputEpoch,5);
    assert.equal(h.find('发送草稿').disabled,true,'review does not enable direct or draft input');
    assert.equal(h.calls.filter(c=>c.name==='remote_tab_input_send').length,0);
    h.find('逐键输入').onclick();await flush();await flush();document.activeElement=null;h.terminal().textarea.event_blur();await flush();
    const blur=h.calls.filter(c=>c.name==='remote_tab_input_mode' && c.args.mode==='observe').at(-1).args;
    assert.equal(blur.review,undefined,'ordinary blur must remain unfocused observe');
  } finally {h.restore();}
});

test('IJ03 IJ12: a delayed review-mode result cannot resolve the next observation epoch',async()=>{
  let reviewResult;const h=watchWorkspace({paneId:'w1:p1',terminalId:'term_a001'},{mode:args=>args.review?new Promise(resolve=>{reviewResult=resolve;}):Promise.resolve(5)});try {
    await h.start();h.observation(1,'starting');h.emit({kind:'frame',epoch:1,frame:{seq:1,full:true,bytes:[65]}});h.observation(1,'active');h.emit({kind:'input_ready',epoch:1,unknown:true,recovery_status:'pending'});
    h.find('已核实原目标结果，恢复输入').onclick();await flush();assert.ok(reviewResult);
    h.observation(3,'resuming');h.emit({kind:'frame',epoch:3,frame:{seq:1,full:true,bytes:[66]}});h.observation(3,'active');h.emit({kind:'input_ready',epoch:3,unknown:true,recovery_status:'pending'});
    reviewResult(8);await flush();await flush();assert.equal(h.calls.filter(c=>c.name==='remote_tab_input_recover').length,0);
    assert.equal(h.find('逐键输入').disabled,true);assert.equal(h.calls.filter(c=>c.name==='remote_tab_input_send').length,0);
  } finally {h.restore();}
});

async function readyPaste(h) {
 await h.start();h.observation(1,'starting');h.watch(1,1);h.emit({kind:'frame',epoch:1,frame:{seq:1,full:true,bytes:[65]}});h.observation(1,'active');h.emit({kind:'input_ready',epoch:1,unknown:false,recovery_status:'ready'});
 const draft=h.all().find(n=>n.tagName==='textarea');draft.value='原草稿';draft.oninput();h.find('逐键输入').onclick();await flush();await flush();
}
function paste(terminal,value){let prevented=false,stopped=false;terminal.textarea.event_paste({preventDefault(){prevented=true;},stopImmediatePropagation(){stopped=true;},clipboardData:{getData:()=>value}});assert.equal(prevented,true);assert.equal(stopped,true);}
for(const [label,expected] of [['追加到草稿','原草稿新\n文本'],['替换草稿','新\n文本'],['取消粘贴','原草稿']]) test(`粘贴预览 ${label} preserves draft until explicit action`,async()=>{
 const h=watchWorkspace({paneId:'w1:p1',terminalId:'term_a001'});try{await readyPaste(h);paste(h.terminal(),'新\n文本');await flush();await flush();assert.ok(h.all().some(n=>n.tagName==='pre' && n.textContent==='新\n文本'));assert.equal(h.all().find(n=>n.tagName==='textarea').value,'原草稿');h.find(label).onclick();assert.equal(h.all().find(n=>n.tagName==='textarea').value,expected);assert.equal(h.calls.filter(c=>c.name==='remote_tab_input_send').length,0);}finally{h.restore();}
});
test('paste review is revoked on focus escape and cannot apply a retained button',async()=>{
 const h=watchWorkspace({paneId:'w1:p1',terminalId:'term_a001'});try{await readyPaste(h);paste(h.terminal(),'新');await flush();const apply=h.find('替换草稿');const group=h.all().find(n=>n.attrs['aria-label']==='粘贴内容审查');group.onfocusout({relatedTarget:new Element('button')});apply.onclick();assert.equal(h.all().find(n=>n.tagName==='textarea').value,'原草稿');assert.equal(h.calls.filter(c=>c.name==='remote_tab_input_send').length,0);}finally{h.restore();}
});
test('clipboard loses authority when focus leaves and returns while observe mode is pending',async()=>{
 let release;const h=watchWorkspace({paneId:'w1:p1',terminalId:'term_a001'},{mode:a=>a.mode==='observe'?new Promise(r=>release=r):Promise.resolve(5)});try{await readyPaste(h);const term=h.terminal();paste(term,'新');await flush();term.textarea.event_blur();document.activeElement=term.textarea;release(6);await flush();assert.equal(h.find('追加到草稿'),undefined);assert.equal(h.all().find(n=>n.tagName==='textarea').value,'原草稿');}finally{h.restore();}
});
test('composition in progress is not converted into a clipboard review',async()=>{
 const h=watchWorkspace({paneId:'w1:p1',terminalId:'term_a001'});try{await readyPaste(h);const term=h.terminal();term.textarea.event_compositionstart();paste(term,'新');await flush();assert.equal(h.find('追加到草稿'),undefined);assert.equal(h.all().find(n=>n.tagName==='textarea').value,'原草稿');term.textarea.event_compositionend();}finally{h.restore();}
});
test('blocked rows lead the snapshot and selection retains exact identities',async()=>{
 const h=watchWorkspace();try{await h.start();h.observation(1,'starting');h.watch(1,1,'fresh',[{paneId:'w1:p1',terminalId:'term_ab01',agentStatus:'working'},{paneId:'w1:p2',terminalId:'term_ab02',agentStatus:'blocked'},{paneId:'w1:p3',terminalId:'term_ab03',agentStatus:'future'}]);h.emit({kind:'selection_ready',epoch:1});const rows=h.all().filter(n=>n.tagName==='button'&&n.textContent.startsWith('选择 '));assert.match(rows[0].textContent,/w1:p2.*term_ab02.*受阻/);assert.match(rows[1].textContent,/工作中/);assert.match(rows[2].textContent,/状态未知/);assert.ok(h.all().some(n=>n.textContent.includes('1 个受阻窗格')));rows[0].onclick();await flush();const sent=h.calls.find(c=>c.name==='remote_tab_select').args;assert.equal(sent.paneId,'w1:p2');assert.equal(sent.terminalId,'term_ab02');}finally{h.restore();}
});
test('new connection keeps old snapshot stale until authority replaces it',async()=>{
 let finish;let attempt=0;const h=watchWorkspace(null,{observe:()=>{attempt++;return attempt===1?new Promise(r=>finish=r):new Promise(()=>{});}});try{await h.start();h.observation(3,'starting');h.watch(3,1,'fresh',[{paneId:'w1:p1',terminalId:'term_cd01',agentStatus:'blocked'}]);h.emit({kind:'selection_ready',epoch:3});h.ui.background();finish();await flush();await flush();await h.start();assert.ok(h.all().some(n=>n.textContent.includes('term_cd01')));assert.ok(h.all().some(n=>n.textContent.includes('上次快照')));assert.ok(h.all().filter(n=>n.tagName==='button' && n.textContent.startsWith('选择 ')).every(n=>n.disabled));h.observation(1,'starting');assert.ok(h.all().some(n=>n.textContent.includes('term_cd01')));h.watch(1,1,'fresh',[{paneId:'w1:p2',terminalId:'term_cd02',agentStatus:'idle'}]);h.emit({kind:'selection_ready',epoch:1});assert.ok(h.all().some(n=>n.textContent.includes('term_cd02')));assert.ok(!h.all().some(n=>n.textContent.includes('term_cd01')));assert.equal(h.calls.filter(c=>c.name==='remote_tab_reserve').length,2);}finally{h.restore();}
});

test('clipboard review from old epoch cannot modify the retained draft',async()=>{
 const h=watchWorkspace({paneId:'w1:p1',terminalId:'term_a001'});try{await readyPaste(h);paste(h.terminal(),'新');await flush();const stale=h.find('替换草稿');h.observation(2,'resuming');stale.onclick();h.emit({kind:'frame',epoch:2,frame:{seq:1,full:true,bytes:[65]}});h.observation(2,'active');h.emit({kind:'input_ready',epoch:2,unknown:false,recovery_status:'ready'});assert.equal(h.all().find(n=>n.tagName==='textarea').value,'原草稿');assert.equal(h.calls.filter(c=>c.name==='remote_tab_input_send').length,0);}finally{h.restore();}
});
test('old row cannot regain authority after a new connection reuses epoch and revision',async()=>{
 let end,attempt=0;const h=watchWorkspace(null,{observe:()=>{attempt++;return attempt===1?new Promise(r=>end=r):new Promise(()=>{});}});try{await h.start();h.observation(1,'starting');h.watch(1,1);h.emit({kind:'selection_ready',epoch:1});const old=h.all().find(n=>n.tagName==='button'&&n.textContent.startsWith('选择 '));h.ui.background();end();await flush();await flush();await h.start();h.observation(1,'starting');h.watch(1,1);h.emit({kind:'selection_ready',epoch:1});old.onclick();await flush();assert.equal(h.calls.filter(c=>c.name==='remote_tab_select').length,0);const fresh=h.all().find(n=>n.tagName==='button'&&n.textContent.startsWith('选择 '));fresh.onclick();await flush();assert.equal(h.calls.filter(c=>c.name==='remote_tab_select').length,1);}finally{h.restore();}
});
test('failed reconnect keeps last snapshot stale without automatic retry',async()=>{
 let finish,attempt=0;const h=watchWorkspace(null,{observe:()=>{attempt++;return attempt===1?new Promise(r=>finish=r):Promise.reject(Error('offline'));}});try{await h.start();h.observation(1,'starting');h.watch(1,1);h.ui.background();finish();await flush();await flush();await h.start();await flush();assert.ok(h.all().some(n=>n.textContent.includes('term_a001')));assert.ok(h.all().some(n=>n.attrs['data-dashboard-phase']==='stale'));assert.ok(h.all().filter(n=>n.tagName==='button'&&n.textContent.startsWith('选择 ')).every(n=>n.disabled));assert.equal(h.calls.filter(c=>c.name==='remote_tab_reserve').length,2);assert.equal(h.calls.filter(c=>c.name==='remote_tab_input_send').length,0);}finally{h.restore();}
});

test('workspace publishes only accepted authoritative watch snapshots and retires them on background',async()=>{
 const {HostDashboardSummary}=await import('../src/host-dashboard-summary.js');const store=new HostDashboardSummary(),events=[];
 const h=watchWorkspace(null,{onDashboard:event=>{events.push(event.type);if(event.type==='starting')store.begin(event.identity,event.source);else if(event.type==='snapshot')store.publish(event.identity,event.source,event.board);else store.invalidateSource(event.hostId,event.source);}});
 try{await h.start();h.observation(1,'starting');h.watch(1,1,'fresh',[{paneId:'w1:p1',terminalId:'term_a001',agentStatus:'blocked'}]);const identity={id:'fixture',enabled:true,retired:false,target:{username:'u',host:'fixture',port:22,session:'work'},deviceFingerprint:'device'};assert.equal(store.get(identity).count,1);assert.equal(store.get(identity).current,true);const seen=events.filter(x=>x==='snapshot').length;h.watch(1,1,'fresh',[{paneId:'w1:p1',terminalId:'term_a001',agentStatus:'idle'}]);assert.equal(events.filter(x=>x==='snapshot').length,seen);h.ui.background();h.watch(1,2,'fresh',[]);await flush();assert.equal(store.get(identity).current,false);assert.equal(store.get(identity).count,1);assert.equal(events.filter(x=>x==='snapshot').length,seen);assert.equal(h.calls.filter(c=>c.name==='remote_tab_reserve').length,1);}finally{h.restore();}
});

async function readyKeyboard(h) {
  await h.start();
  h.observation(1, 'starting');
  h.watch(1, 1);
  h.emit({ kind: 'frame', epoch: 1, frame: { seq: 1, full: true, bytes: [65] } });
  h.observation(1, 'active');
  h.emit({ kind: 'input_ready', epoch: 1, unknown: false, recovery_status: 'ready' });
}

const acceptedInput = args => Promise.resolve({
  status: 'accepted',
  receipt: {
    requestId: 'a'.repeat(32), paneId: 'w1:p1', terminalId: 'term_a001',
    acceptedBytes: args.bytes.length,
  },
});

test('mobile direct gesture focuses an editable terminal but sends nothing before native permission', async () => {
  let grant;
  const h = watchWorkspace({ paneId: 'w1:p1', terminalId: 'term_a001' }, {
    mode: args => args.mode === 'direct' ? new Promise(resolve => grant = resolve) : Promise.resolve(5),
    send: acceptedInput,
  });
  try {
    await readyKeyboard(h);
    const term = h.terminal();
    h.find('逐键输入').onclick();
    assert.deepEqual(term.focusReadOnly, [false]);
    assert.equal(term.textarea.readOnly, false);
    term.data('x');
    assert.equal(h.calls.filter(call => call.name === 'remote_tab_input_send').length, 0);

    await flush();
    grant(7);
    await flush();
    term.data('y');
    await flush();
    const sent = h.calls.filter(call => call.name === 'remote_tab_input_send');
    assert.equal(sent.length, 1);
    assert.deepEqual(sent[0].args.bytes, [121]);
  } finally { h.restore(); }
});

test('blur while native direct permission is pending locks input and revokes late permission', async () => {
  let grant;
  const h = watchWorkspace({ paneId: 'w1:p1', terminalId: 'term_a001' }, {
    mode: args => args.mode === 'direct' ? new Promise(resolve => grant = resolve) : Promise.resolve(5),
    send: acceptedInput,
  });
  try {
    await readyKeyboard(h);
    const term = h.terminal();
    h.find('逐键输入').onclick();
    await flush();
    document.activeElement = new Element('button');
    term.textarea.event_blur();
    assert.equal(term.textarea.readOnly, true);
    grant(7);
    await flush(); await flush();
    document.activeElement = term.textarea;
    term.data('x');
    await flush();
    assert.equal(h.calls.filter(call => call.name === 'remote_tab_input_send').length, 0);
    assert.ok(h.calls.some(call => call.name === 'remote_tab_input_mode' && call.args.mode === 'observe'));
    assert.equal(term.textarea.readOnly, true);
  } finally { h.restore(); }
});

test('IME composition begun before permission cannot submit after the late grant', async () => {
  let grant;
  const h = watchWorkspace({ paneId: 'w1:p1', terminalId: 'term_a001' }, {
    mode: args => args.mode === 'direct' ? new Promise(resolve => grant = resolve) : Promise.resolve(5),
    send: acceptedInput,
  });
  try {
    await readyKeyboard(h);
    const term = h.terminal();
    h.find('逐键输入').onclick();
    await flush();
    term.textarea.event_compositionstart();
    term.data('中');
    grant(7);
    await flush();
    term.textarea.event_compositionend();
    term.data('中文');
    await flush();
    assert.equal(h.calls.filter(call => call.name === 'remote_tab_input_send').length, 0);
    term.data('字');
    await flush();
    const sent = h.calls.filter(call => call.name === 'remote_tab_input_send');
    assert.equal(sent.length, 1);
    assert.deepEqual(sent[0].args.bytes, [...new TextEncoder().encode('字')]);
  } finally { h.restore(); }
});

test('switch during pending permission prevents old reply from sending to the new tab', async () => {
  let grant;
  const h = watchWorkspace({ paneId: 'w1:p1', terminalId: 'term_a001' }, {
    mode: args => args.mode === 'direct' ? new Promise(resolve => grant = resolve) : Promise.resolve(5),
    send: acceptedInput,
  });
  try {
    await readyKeyboard(h);
    const term = h.terminal();
    h.find('逐键输入').onclick();
    await flush();
    const second = h.ui.create('other', { paneId: 'w2:p1', terminalId: 'term_a002' });
    await h.ui.select(second);
    grant(7);
    await flush();
    term.data('x');
    await flush();
    assert.equal(h.calls.filter(call => call.name === 'remote_tab_input_send').length, 0);
    assert.equal(term.textarea.readOnly, true);
  } finally { h.restore(); }
});

test('unknown direct-mode failure locks input and waits for observe reset before another attempt', async () => {
  let rejectMode, finishReset;
  const h = watchWorkspace({ paneId: 'w1:p1', terminalId: 'term_a001' }, {
    mode: args => args.mode === 'direct'
      ? new Promise((_, reject) => rejectMode = reject)
      : new Promise(resolve => finishReset = resolve),
    send: acceptedInput,
  });
  try {
    await readyKeyboard(h);
    const term = h.terminal();
    h.find('逐键输入').onclick();
    await flush();
    rejectMode(Error('unknown'));
    await flush();
    assert.equal(term.textarea.readOnly, true);
    term.data('x');
    h.find('逐键输入').onclick();
    assert.equal(h.calls.filter(call => call.name === 'remote_tab_input_mode' && call.args.mode === 'direct').length, 1);
    assert.equal(h.calls.filter(call => call.name === 'remote_tab_input_send').length, 0);
    finishReset(6);
    await flush();
  } finally { h.restore(); }
});

test('keyboard and paste events are blocked while direct permission is pending', async () => {
  let grant;
  const h = watchWorkspace({ paneId: 'w1:p1', terminalId: 'term_a001' }, {
    mode: args => args.mode === 'direct' ? new Promise(resolve => grant = resolve) : Promise.resolve(5),
    send: acceptedInput,
  });
  try {
    await readyKeyboard(h);
    const term = h.terminal();
    h.find('逐键输入').onclick();
    await flush();
    for (const name of ['keydown', 'keypress', 'beforeinput', 'input', 'paste']) {
      let prevented = false, stopped = false;
      term.textarea[`event_${name}`]({
        preventDefault() { prevented = true; },
        stopImmediatePropagation() { stopped = true; },
        clipboardData: { getData: () => 'not authorized' },
      });
      assert.equal(prevented, true, name);
      assert.equal(stopped, true, name);
    }
    assert.equal(h.calls.filter(call => call.name === 'remote_tab_input_send').length, 0);
    grant(7);
    await flush();
    term.data('z');
    await flush();
    assert.equal(h.calls.filter(call => call.name === 'remote_tab_input_send').length, 1);
  } finally { h.restore(); }
});
