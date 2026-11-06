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
