import test from 'node:test';
import assert from 'node:assert/strict';
import {initNetworkUI} from '../src/network-ui.js';
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve;return {promise:new Promise(r=>resolve=r),resolve:()=>resolve()};};
class Element {
  constructor(tag){this.tagName=tag;this.textContent='';this.children=[];this.value='';this.hidden=false;this.disabled=false;this.attrs={};}
  append(...nodes){for(const node of nodes){node.parent=this;this.children.push(node);}}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  setAttribute(key,value){this.attrs[key]=value;}
  descendants(){return this.children.flatMap(node=>[node,...node.descendants()]);}
  querySelectorAll(selector){return selector==='input[type=password]'?this.descendants().filter(node=>node.type==='password'):[];}
  querySelector(selector){return selector==='[role=status]'?this.descendants().find(node=>node.attrs.role==='status'):null;}
}
function timers(){let id=0;const jobs=new Map();return {jobs,schedule:fn=>{jobs.set(++id,fn);return id;},cancel:id=>jobs.delete(id),async tick(){const [id,fn]=jobs.entries().next().value;jobs.delete(id);await fn();}};}
async function harness(run,{state='needs-login',second=false}={}) {
  const previous={document:globalThis.document,window:globalThis.window,confirm:globalThis.confirm};
  const panel=new Element('section'),open=new Element('button'),listeners={};panel.hidden=true;
  globalThis.document={hidden:false,getElementById:id=>id==='network-panel'?panel:open,createElement:tag=>new Element(tag),addEventListener:(name,fn)=>listeners[name]=fn};
  globalThis.window={addEventListener:(name,fn)=>listeners[name]=fn};globalThis.confirm=()=>true;
  const id='a'.repeat(32),etId='b'.repeat(32),handle='11111111-1111-4111-8111-111111111111';
  const ts={id,label:'QA TS',provider:'tailscale',enabled:true,revision:1,settings:{controlUrl:'https://control.invalid',hostname:''}};
  const et={id:etId,label:'QA ET',provider:'easytier',enabled:true,revision:1,settings:{networkName:'fixture',peers:[]}};
  let profiles=second?[ts,et]:[ts],revision='r0',etPresent=false,lock=null,readGate=null,delivery=null,waitingDelivery=false;
  const timer=timers(),calls=[],counts={start:0,startSuccess:0,identityWrite:0,identitySuccess:0,save:0,busy:0,overlappingRead:0,stop:0,status:0};
  const binding={provider:'tailscale',profileId:id,profileRevision:1,networkName:'ts1:fixture',identityRef:handle};
  const acquire=()=>{if(lock){counts.busy++;throw 'network_identity_busy';}lock='write';};
  const invoke=async(name,args={})=>{
    calls.push({name,args});
    if(name==='network_list')return {revision,profiles:structuredClone(profiles),bindings:[]};
    if(name==='network_identity_status'){
      if(lock){counts.overlappingRead++;throw 'network_identity_busy';}
      lock='read';
      try {
        const gate=readGate;if(gate && (!gate.onlyDuringDelivery || waitingDelivery))await gate.promise;
        const present=args.id===id || etPresent;
        return {supported:true,available:true,present,mode:present?(args.id===id?'DEVICE_STATE':'PRIVATE'):null,handle:present?handle:null};
      } finally {lock=null;}
    }
    if(name==='network_node_status'){counts.status++;return args.id===id?{state,binding:state==='stopped'?null:binding}:{state:'stopped',binding:null};}
    if(name==='network_node_login_status')return {state,binding,authUrl:null,reviewToken:null};
    if(name==='network_node_start'){
      counts.start++;if(delivery){waitingDelivery=true;await delivery.promise;waitingDelivery=false;}
      acquire();try{state='needs-login';counts.startSuccess++;return;}finally{lock=null;}
    }
    if(name==='network_node_stop'){counts.stop++;assert.deepEqual(args.binding,binding);state='stopped';return;}
    if(name==='network_identity_write'){
      counts.identityWrite++;acquire();try{assert.equal(args.expectedCatalog,revision);etPresent=true;counts.identitySuccess++;return;}finally{lock=null;}
    }
    if(name==='network_save'){
      counts.save++;acquire();try{if(args.expectedCatalog!==revision)throw 'network_changed';profiles=[...profiles,{...args.profile,id:etId}];revision='r1';return;}finally{lock=null;}
    }
    throw Error(name);
  };
  const ui=initNetworkUI({native:true,invoke,getHosts:()=>[],onAffected:async()=>{},pollOptions:timer});
  const h={panel,ui,timer,calls,counts,binding,listeners,button:text=>panel.descendants().find(node=>node.tagName==='button'&&node.textContent===text),
    form:()=>panel.descendants().find(node=>node.tagName==='form'),texts:()=>panel.descendants().map(node=>node.textContent),
    holdRead(onlyDuringDelivery=false){readGate={...deferred(),onlyDuringDelivery};},releaseRead(){readGate?.resolve();readGate=null;},
    delayStart(){delivery=deferred();},releaseStart(){delivery?.resolve();},setRevision:value=>{revision=value;}};
  try{open.onclick();await flush();await run(h);}finally{h.releaseRead();h.releaseStart();ui.close();Object.assign(globalThis,previous);}
}
function publicDraft(h){
  h.button('新增网络配置').onclick();const form=h.form(),name=form.descendants().find(node=>node.tagName==='input'),provider=form.descendants().find(node=>node.tagName==='select');
  name.value='Unsubmitted ET';provider.value='easytier';provider.onchange();
  const settings=form.descendants().filter(node=>node.tagName==='input'&&node!==name),peers=form.descendants().find(node=>node.tagName==='textarea');
  settings[0].value='public-network';peers.value='tcp://peer.invalid:1234';return {form,name,provider,setting:settings[0],peers};
}
test('TS polling preserves the same public draft form and keeps reading without saving',async()=>{
  await harness(async h=>{
    const draft=publicDraft(h),reads=h.counts.status;await h.timer.tick();
    assert.equal(h.form(),draft.form);assert.equal(draft.provider.value,'easytier');assert.equal(draft.name.value,'Unsubmitted ET');assert.equal(draft.setting.value,'public-network');
    assert.ok(h.counts.status>reads);assert.equal(h.counts.save,0);
    draft.form.onsubmit({preventDefault(){}});await flush();await flush();
    const saved=h.calls.find(call=>call.name==='network_save').args;
    assert.equal(saved.profile.provider,'easytier');assert.equal(saved.profile.label,'Unsubmitted ET');assert.equal(saved.profile.settings.networkName,'public-network');assert.equal(h.counts.save,1);
  });
});
test('polling never replaces an old draft review with a newer catalog revision',async()=>{
  await harness(async h=>{
    const draft=publicDraft(h);h.setRevision('external-r1');await h.timer.tick();
    draft.form.onsubmit({preventDefault(){}});await flush();await flush();
    assert.equal(h.calls.find(call=>call.name==='network_save').args.expectedCatalog,'r0');
    assert.equal(h.form(),draft.form);assert.equal(draft.name.value,'Unsubmitted ET');assert.equal(h.counts.save,1);
    assert.ok(h.texts().some(text=>text.includes('操作结果未确认')));await flush();assert.equal(h.counts.save,1);
  });
});
test('identity secret remains only in its active input and is cleared on hiding the page',async()=>{
  await harness(async h=>{
    h.button('配置本机身份').onclick();const form=h.form(),secret=form.descendants().find(node=>node.type==='password');secret.value='synthetic-secret';
    await h.timer.tick();assert.equal(h.form(),form);assert.equal(secret.value,'synthetic-secret');assert.equal(h.counts.identityWrite,0);
    globalThis.document.hidden=true;h.listeners.visibilitychange();assert.equal(secret.value,'');assert.equal(h.counts.identityWrite,0);
    assert.equal(JSON.stringify(h.calls).includes('synthetic-secret'),false);
  },{second:true});
});
test('a user start wins over its own automatic identity refresh without any replay',async()=>{
  await harness(async h=>{
    h.delayStart();h.holdRead(true);h.button('启动节点').onclick();await flush();
    h.releaseStart();await flush();h.releaseRead();await flush();await flush();
    assert.equal(h.counts.start,1);assert.equal(h.counts.startSuccess,1);assert.equal(h.counts.busy,0);assert.equal(h.counts.overlappingRead,0);
    assert.ok(h.button('登录 Tailscale'));
  },{state:'stopped'});
});
test('a start waits for an already running identity read before its single dispatch',async()=>{
  await harness(async h=>{
    h.holdRead();h.ui.refresh();await flush();h.button('启动节点').onclick();await flush();assert.equal(h.counts.start,0);
    h.releaseRead();await flush();await flush();assert.equal(h.counts.start,1);assert.equal(h.counts.startSuccess,1);assert.equal(h.counts.busy,0);
  },{state:'stopped'});
});
test('revoking the visible review while waiting for a read prevents a late start dispatch',async()=>{
  await harness(async h=>{
    h.holdRead();h.ui.refresh();await flush();h.button('启动节点').onclick();await flush();
    globalThis.document.hidden=true;h.listeners.visibilitychange();h.releaseRead();await flush();await flush();assert.equal(h.counts.start,0);
  },{state:'stopped'});
});
test('ET identity creation waits for the TS identity read, clears its input and writes once',async()=>{
  await harness(async h=>{
    h.button('配置本机身份').onclick();const form=h.form(),secret=form.descendants().find(node=>node.type==='password');secret.value='synthetic-secret';
    h.holdRead();h.ui.refresh();await flush();form.onsubmit({preventDefault(){}});await flush();assert.equal(h.counts.identityWrite,0);assert.equal(secret.value,'');
    h.releaseRead();await flush();await flush();assert.equal(h.counts.identityWrite,1);assert.equal(h.counts.identitySuccess,1);assert.equal(h.counts.busy,0);
    const call=h.calls.find(call=>call.name==='network_identity_write');assert.equal(call.args.secret,'');
  },{second:true});
});
test('exact-binding stop remains independent of a pending identity read',async()=>{
  await harness(async h=>{
    h.holdRead();h.ui.refresh();await flush();h.button('停止节点').onclick();await flush();assert.equal(h.counts.stop,1);
    h.releaseRead();await flush();await flush();assert.equal(h.counts.start,0);
  },{state:'starting'});
});
