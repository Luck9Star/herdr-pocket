import test from 'node:test';
import assert from 'node:assert/strict';
import {initNetworkUI} from '../src/network-ui.js';

class Element {
  constructor(tag){this.tagName=tag;this.textContent='';this.children=[];this.value='';this.hidden=false;this.disabled=false;this.attrs={};}
  append(...nodes){for(const node of nodes){node.parent=this;this.children.push(node);}}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  setAttribute(key,value){this.attrs[key]=value;}
  descendants(){return this.children.flatMap(node=>[node,...node.descendants()]);}
  querySelectorAll(){return [];}
  querySelector(selector){return selector==='[role=status]'?this.descendants().find(node=>node.attrs.role==='status'):null;}
}
const flush=async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));};
function timers(){let id=0;const jobs=new Map();return {jobs,schedule:fn=>{jobs.set(++id,fn);return id;},cancel:id=>jobs.delete(id),async tick(){const [id,fn]=jobs.entries().next().value;jobs.delete(id);await fn();}};}
async function harness(run,{polling=false,bound=false,unknownWrite=false}={}) {
  const previous={document:globalThis.document,window:globalThis.window,confirm:globalThis.confirm};
  const panel=new Element('section'),open=new Element('button'),listeners={};panel.hidden=true;
  globalThis.document={hidden:false,getElementById:id=>id==='network-panel'?panel:open,createElement:tag=>new Element(tag),addEventListener:(name,fn)=>listeners[name]=fn};
  globalThis.window={addEventListener:(name,fn)=>listeners[name]=fn};
  const ts={id:'a'.repeat(32),label:'QA TS',provider:'tailscale',enabled:true,revision:1,settings:{controlUrl:'',hostname:''}};
  const et={id:'b'.repeat(32),label:'QA ET',provider:'easytier',enabled:true,revision:1,settings:{networkName:'fixture',peers:[]}};
  const hosts=['A','B'].map((name,index)=>({id:String(index+1).repeat(32),name,enabled:true,retired:false,
    target:{host:'192.0.2.'+(index+1),port:22,username:'fixture'},provider:'direct',deviceFingerprint:'synthetic-device-'+index,
    hostFingerprint:'synthetic-host-'+index,pairingStatus:'active',networkProfileId:null,requiresNetworkBinding:false,
    keyDeletionPending:false,keyCleanupMode:null}));
  if(bound)hosts[0].networkProfileId=ts.id;
  const catalog={revision:'r1',profiles:[ts,et],bindings:bound?[{hostId:hosts[0].id,profileId:ts.id}]:[],preferences:{}};
  const calls=[],confirmations=[],affected=[],timer=timers();let confirmAction=()=>true,readGate=null,release=null,readError=false;
  globalThis.confirm=message=>{confirmations.push(message);return confirmAction();};
  const invoke=async(name,args={})=>{
    calls.push({name,args:structuredClone(args)});
    if(name==='network_list'){if(readError)throw Error('fixture-read-failure');return structuredClone(catalog);}
    if(name==='network_identity_status'){if(readGate)await readGate;return {supported:true,available:true,present:false,mode:null,handle:null};}
    const binding={profileId:args.id,profileRevision:1,networkName:'fixture',identityRef:'synthetic'};
    if(name==='network_node_status' || name==='network_node_login_status')return {state:polling?'needs-login':'running',binding,authUrl:null,reviewToken:null};
    if(name==='network_bind'){
      if(unknownWrite)throw Error('fixture-result-unknown');
      assert.equal(args.expectedCatalog,catalog.revision);
      hosts.find(host=>host.id===args.hostId).networkProfileId=args.profileId;
      catalog.bindings=catalog.bindings.filter(binding=>binding.hostId!==args.hostId);
      if(args.profileId)catalog.bindings.push({hostId:args.hostId,profileId:args.profileId});
      catalog.revision='r2';return;
    }
    throw Error('unexpected fixture command '+name);
  };
  const ui=initNetworkUI({native:true,invoke,getHosts:()=>hosts,onAffected:async ids=>affected.push(ids),
    pollOptions:{delay:0,limit:20,timeout:60000,schedule:timer.schedule,cancel:timer.cancel}});
  const row=name=>panel.descendants().find(node=>node.className==='network-binding'&&node.children[0]?.textContent===name);
  const select=name=>row(name).children.find(node=>node.tagName==='select');
  const apply=name=>row(name).children.find(node=>node.tagName==='button');
  try {
    open.onclick();await flush();
    await run({ui,hosts,catalog,ts,et,timer,calls,confirmations,affected,listeners,panel,open,row,select,apply,
      status:()=>panel.querySelector('[role=status]')?.textContent,
      confirm:fn=>{confirmAction=fn;},failRead:value=>{readError=value;},
      holdRead:()=>{readGate=new Promise(resolve=>{release=resolve;});},releaseRead:()=>{readGate=null;release();}});
  } finally {if(release)release();ui.close();Object.assign(globalThis,previous);}
}
const writes=h=>h.calls.filter(call=>call.name==='network_bind');

test('refresh preserves a dirty host binding on the same row until one explicit confirmation',async()=>{
  await harness(async h=>{
    const select=h.select('A');select.value=h.ts.id;h.ui.refresh();await flush();
    assert.equal(h.select('A'),select);assert.equal(h.select('A').value,h.ts.id);assert.equal(h.select('B').value,'');
    assert.equal(writes(h).length,0);h.apply('A').onclick();await flush();
    assert.equal(h.confirmations.length,1);assert.equal(writes(h).length,1);
    assert.deepEqual(writes(h)[0].args,{hostId:h.hosts[0].id,profileId:h.ts.id,expectedCatalog:'r1',confirmedDirect:false});
    assert.equal(h.hosts[1].networkProfileId,null);
  });
});
test('real login poll preserves independent dirty bindings and keeps reading without writes',async()=>{
  await harness(async h=>{
    const a=h.select('A'),b=h.select('B');a.value=h.ts.id;b.value=h.et.id;
    const reads=h.calls.filter(call=>call.name==='network_node_status').length;
    await h.timer.tick();await flush();await h.timer.tick();await flush();
    assert.equal(h.select('A'),a);assert.equal(h.select('B'),b);assert.equal(a.value,h.ts.id);assert.equal(b.value,h.et.id);
    assert.ok(h.calls.filter(call=>call.name==='network_node_status').length>reads);
    assert.equal(writes(h).length,0);assert.equal(h.confirmations.length,0);
  },{polling:true});
});
test('explicit null unbinding draft survives refresh and still requires direct-route confirmation',async()=>{
  await harness(async h=>{
    const select=h.select('A');select.value='';h.ui.refresh();await flush();
    assert.equal(h.select('A'),select);assert.equal(select.value,'');h.apply('A').onclick();await flush();
    assert.match(h.confirmations[0],/解除 A/);assert.equal(writes(h)[0].args.profileId,null);assert.equal(writes(h)[0].args.confirmedDirect,true);
  },{bound:true});
});
test('host, permission, profile and catalog changes discard draft without invoking or reauthorizing it',async()=>{
  const mutations=[h=>h.hosts[0].target.port++,h=>h.hosts[0].hostFingerprint='changed',h=>h.hosts[0].deviceFingerprint='changed',
    h=>h.hosts[0].enabled=false,h=>h.hosts[0].retired=true,h=>h.hosts[0].pairingStatus='revoked',
    h=>{h.hosts[0].keyDeletionPending=true;h.hosts[0].keyCleanupMode='revoke';},h=>h.hosts.splice(0,1),
    h=>h.catalog.revision='r2',h=>h.ts.revision++,h=>h.ts.enabled=false,h=>h.ts.provider='easytier',
    h=>h.ts.settings.hostname='changed',h=>h.catalog.profiles.splice(0,1),
    h=>{h.hosts[0].networkProfileId=h.et.id;h.catalog.bindings.push({hostId:h.hosts[0].id,profileId:h.et.id});},
    h=>h.catalog.bindings.push({hostId:h.hosts[0].id,profileId:h.et.id})];
  for(const mutate of mutations)await harness(async h=>{
    h.select('A').value=h.ts.id;const old=h.apply('A');mutate(h);h.ui.refresh();await flush();
    assert.equal(writes(h).length,0);assert.equal(h.confirmations.length,0);assert.match(h.status(),/已变化.*已丢弃/);
    old.onclick();await flush();assert.equal(writes(h).length,0);
    if(h.row('A'))assert.notEqual(h.select('A').value,h.ts.id);
  });
});
test('cancel preserves a valid draft and a later explicit click asks once again',async()=>{
  await harness(async h=>{
    h.select('A').value=h.ts.id;h.confirm(()=>false);h.apply('A').onclick();await flush();h.ui.refresh();await flush();
    assert.equal(h.select('A').value,h.ts.id);assert.equal(writes(h).length,0);
    h.confirm(()=>true);h.apply('A').onclick();await flush();assert.equal(writes(h).length,1);assert.equal(h.confirmations.length,2);
  });
});
test('a target change during confirmation cannot commit the old review',async()=>{
  await harness(async h=>{
    h.select('A').value=h.ts.id;h.confirm(()=>{h.hosts[0].target.port++;return true;});h.apply('A').onclick();await flush();
    assert.equal(h.confirmations.length,1);assert.equal(writes(h).length,0);
  });
});
test('an identity read wait never upgrades a binding review changed before dispatch',async()=>{
  await harness(async h=>{
    h.select('A').value=h.ts.id;h.holdRead();h.ui.refresh();await flush();h.apply('A').onclick();await flush();
    assert.equal(writes(h).length,0);h.hosts[0].target.port++;h.releaseRead();await flush();
    assert.equal(writes(h).length,0);assert.equal(h.confirmations.length,1);
  });
});
test('a result-unknown write discards its draft and is never replayed by later refresh',async()=>{
  await harness(async h=>{
    h.select('A').value=h.ts.id;h.apply('A').onclick();await flush();h.ui.refresh();await flush();
    assert.equal(writes(h).length,1);assert.equal(h.select('A').value,'');assert.equal(h.confirmations.length,1);
  },{unknownWrite:true});
});
test('hiding, closing or losing read access retires stale binding controls without writes',async()=>{
  for(const action of [h=>h.ui.close(),h=>h.listeners.pagehide(),h=>{globalThis.document.hidden=true;h.listeners.visibilitychange();},
    async h=>{h.failRead(true);h.ui.refresh();await flush();}])await harness(async h=>{
    h.select('A').value=h.ts.id;const old=h.apply('A');await action(h);old.onclick();await flush();assert.equal(writes(h).length,0);
  });
});
