import test from 'node:test';
import assert from 'node:assert/strict';
import {openZeroTierDeviceReview, validDeviceStatus} from '../src/zerotier-device-ui.js';
const h='11111111-1111-4111-8111-111111111111', i='22222222-2222-4222-8222-222222222222';
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.listeners={};this.attrs={};this.textContent='';}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,f){this.listeners[k]=f;}
  showModal(){this.open=true;}
  close(){this.open=false;this.listeners.close?.();}
  remove(){this.removed=true;}
  focus(){globalThis.document.activeElement=this;}
  contains(n){return this.all().includes(n);}
  querySelectorAll(tag){return this.all().filter(e=>e.tagName===tag);}
  querySelector(tag){return this.querySelectorAll(tag)[0] || null;}
  all(){return [this,...this.children.flatMap(n=>n.all())];}
}
const tick=()=>new Promise(r=>setImmediate(r));
async function fixture({device=null,pendingCreation=null,pendingDeletion=null,available=true,unknown=false,beforeForget,delayRead,invalidResult=false,writeResult,afterWrite,delayWrite,statusError=false,catalogError=false,hostError=false,delayHosts}={}) {
  const prev={document:globalThis.document,window:globalThis.window}; const docListeners={}, winListeners={};
  const body=new Element('body');globalThis.document={body,hidden:false,activeElement:new Element('button'),createElement:t=>new Element(t),addEventListener:(k,f)=>docListeners[k]=f,removeEventListener:k=>delete docListeners[k]};
  globalThis.window={addEventListener:(k,f)=>winListeners[k]=f,removeEventListener:k=>delete winListeners[k]};
  let catalog={revision:'r1',profiles:[{id:'p',label:'Network A',provider:'zerotier'},{id:'q',label:'Other',provider:'tailscale'}],bindings:[{profileId:'p',hostId:'host'}]};
  let status={available,device,pendingCreation,pendingDeletion}, calls=[], waiting=delayRead, hosts=[{id:'host',name:'Host A'}];
  const invoke=async(name,args)=>{calls.push([name,args]);if(name==='network_list'){if(catalogError)throw Error('catalog');if(waiting){const p=waiting;waiting=null;await p;}return structuredClone(catalog);}if(name==='host_list'){if(delayHosts)await delayHosts;if(hostError)throw Error('hosts');return structuredClone(hosts);}if(name==='zerotier_device_status'){if(statusError)throw Error('status');return structuredClone(status);}if(name==='zerotier_device_write'){if(delayWrite)await delayWrite;if(unknown)throw Error('unknown');if(afterWrite)status=afterWrite(status);if(invalidResult)return {};if(writeResult!==undefined)return writeResult;return ['create','recoverPendingCreation'].includes(args.action)?{handle:h,instanceId:i}:null;}throw Error(name);};
  const originalOpener=globalThis.document.activeElement;const ui=openZeroTierDeviceReview({invoke,getHosts:()=>hosts,beforeForget});await tick();
  const dialog=body.children[0]; const btn=s=>dialog.all().find(e=>e.tagName==='button'&&e.textContent===s); const text=()=>dialog.all().map(e=>e.textContent).join(' ');
  return {ui,dialog,btn,text,calls,docListeners,winListeners,invoke,originalOpener,getHosts:()=>hosts,setCatalog:v=>catalog=v,setHosts:v=>hosts=v,setHostError:v=>hostError=v,setStatus:v=>status=v,restore(){ui.close();globalThis.document=prev.document;globalThis.window=prev.window;}};
}
test('UUID validation fails closed',()=>{assert.equal(validDeviceStatus({available:true,device:{handle:h.toUpperCase().replace('1111','AAAA'),instanceId:i},pendingCreation:null,pendingDeletion:null}),false);assert.equal(validDeviceStatus({available:true,device:{handle:h,instanceId:i},pendingCreation:null,pendingDeletion:null}),true);});
test('shared review lists affected profiles and hosts, then writes reviewed catalog once',async()=>{const f=await fixture();try {assert.match(f.text(),/Network A/);assert.match(f.text(),/Host A/);f.btn('创建共享设备').onclick();f.btn('确认操作').onclick();await tick();await tick();const writes=f.calls.filter(c=>c[0]==='zerotier_device_write');assert.equal(writes.length,1);assert.deepEqual(writes[0][1],{action:'create',catalogRevision:'r1',profileIds:['p'],hostIds:['host'],handle:null,instanceId:null,expectedPhase:null});}finally{f.restore();}});
test('unavailable command or device cannot offer creation',async()=>{const f=await fixture({available:false});try{assert.match(f.text(),/不可用/);assert.equal(f.btn('创建共享设备'),undefined);}finally{f.restore();}});
test('missing native device capability retains verified impact without showing empty identity',async()=>{
 const f=await fixture({available:false});try{assert.match(f.text(),/Network A（p）/);assert.match(f.text(),/Host A（host）/);assert.match(f.text(),/设备状态未知|设备能力不可用/);assert.doesNotMatch(f.text(),/当前没有已确认的共享设备/);assert.equal(f.btn('创建共享设备'),undefined);assert.equal(f.btn('删除共享设备'),undefined);assert.ok(f.calls.some(c=>c[0]==='host_list'));}finally{f.restore();}
});
test('device status IPC rejection retains the independently verified impact',async()=>{
 const f=await fixture({statusError:true});try{assert.match(f.text(),/Network A（p）/);assert.match(f.text(),/Host A（host）/);assert.match(f.text(),/设备状态未知/);assert.equal(f.btn('确认操作'),undefined);assert.equal(f.calls.filter(c=>c[0]==='zerotier_device_write').length,0);}finally{f.restore();}
});
for(const failure of ['catalogError','hostError'])test(`${failure} keeps impact unknown and disables device actions`,async()=>{
 const f=await fixture({[failure]:true});try{assert.match(f.text(),/受影响范围未知/);assert.doesNotMatch(f.text(),/受影响网络：无|受影响主机：无/);assert.equal(f.btn('创建共享设备'),undefined);assert.equal(f.btn('确认操作'),undefined);}finally{f.restore();}
});
test('pending authoritative host list cannot be replaced by an empty home cache',async()=>{
 let release;const wait=new Promise(resolve=>release=resolve);const f=await fixture({delayHosts:wait});try{assert.match(f.text(),/正在读取/);assert.doesNotMatch(f.text(),/受影响主机：无/);assert.equal(f.btn('创建共享设备'),undefined);release();await tick();assert.match(f.text(),/Host A（host）/);assert.ok(f.btn('创建共享设备'));}finally{release();f.restore();}
});
test('authoritative host read failure before write revokes the confirmation without mutation',async()=>{
 const f=await fixture();try{f.btn('创建共享设备').onclick();f.setHostError(true);f.btn('确认操作').onclick();await tick();await tick();assert.equal(f.calls.filter(c=>c[0]==='zerotier_device_write').length,0);assert.match(f.text(),/受影响范围未知/);assert.equal(f.btn('创建共享设备'),undefined);}finally{f.restore();}
});
test('empty impact is stated only after both public lists successfully read as empty',async()=>{
 const f=await fixture({available:false});try{f.setCatalog({revision:'r2',profiles:[],bindings:[]});f.setHosts([]);f.btn('刷新状态').onclick();await tick();assert.match(f.text(),/受影响网络：无/);assert.match(f.text(),/受影响主机：无/);assert.equal(f.btn('创建共享设备'),undefined);}finally{f.restore();}
});
test('unknown write is never replayed and state is read back',async()=>{const f=await fixture({unknown:true});try{f.btn('创建共享设备').onclick();f.btn('确认操作').onclick();await tick();await tick();assert.equal(f.calls.filter(c=>c[0]==='zerotier_device_write').length,1);assert.ok(f.calls.filter(c=>c[0]==='zerotier_device_status').length>=3);assert.match(f.text(),/不会自动重试/);}finally{f.restore();}});
test('catalog change invalidates reviewed confirmation',async()=>{const f=await fixture();try{f.btn('创建共享设备').onclick();f.setCatalog({revision:'r2',profiles:[],bindings:[]});f.btn('确认操作').onclick();await tick();await tick();assert.equal(f.calls.filter(c=>c[0]==='zerotier_device_write').length,0);assert.match(f.text(),/审查已失效/);}finally{f.restore();}});
test('blur revokes confirmation and a late read cannot restore it',async()=>{let release;const wait=new Promise(r=>release=r);const f=await fixture({delayRead:wait});try{f.winListeners.blur();release();await tick();assert.match(f.text(),/审查已失效/);assert.equal(f.btn('创建共享设备'),undefined);}finally{f.restore();}});
test('delete requires confirmed native stop and passes original instance',async()=>{const a=await fixture({device:{handle:h,instanceId:i}});try{assert.equal(a.btn('删除共享设备').disabled,true);}finally{a.restore();}let stopped;const b=await fixture({device:{handle:h,instanceId:i},beforeForget:async args=>{stopped=args;return true;}});try{b.btn('删除共享设备').onclick();b.btn('确认操作').onclick();await tick();await tick();assert.equal(stopped.handle,h);assert.equal(stopped.instanceId,i);assert.equal(b.calls.filter(c=>c[0]==='zerotier_device_write').length,1);}finally{b.restore();}});
test('unconfirmed native stop does not delete',async()=>{const f=await fixture({device:{handle:h,instanceId:i},beforeForget:async()=>false});try{f.btn('删除共享设备').onclick();f.btn('确认操作').onclick();await tick();await tick();assert.equal(f.calls.filter(c=>c[0]==='zerotier_device_write').length,0);}finally{f.restore();}});
test('pending creation uses original handle and explicit recovery',async()=>{const f=await fixture({pendingCreation:{handle:h,phase:'record-present'}});try{f.btn('恢复待定创建').onclick();f.btn('确认操作').onclick();await tick();await tick();assert.equal(f.calls.find(c=>c[0]==='zerotier_device_write')[1].handle,h);assert.equal(f.calls.find(c=>c[0]==='zerotier_device_write')[1].expectedPhase,'record-present');}finally{f.restore();}});

test('status rejects extra fields, contradictory records and unavailable records',()=>{
 const empty={available:true,device:null,pendingCreation:null,pendingDeletion:null};
 assert.equal(validDeviceStatus({...empty,extra:true}),false);
 assert.equal(validDeviceStatus({...empty,available:false,device:{handle:h,instanceId:i}}),false);
 assert.equal(validDeviceStatus({...empty,device:{handle:h,instanceId:i},pendingCreation:{handle:h,phase:'finishing'}}),false);
 assert.equal(validDeviceStatus({...empty,device:{handle:h,instanceId:i,extra:true}}),false);
});
test('legacy and archived bound hosts are included in review',async()=>{
 const {deviceReview}=await import('../src/zerotier-device-ui.js');
 const r=deviceReview({revision:'r',profiles:[{id:'p',label:'n',provider:'zerotier'}],bindings:[{profileId:'p',hostId:'archived'}]},[{id:'legacy',name:'Legacy',provider:'zerotier',retired:true},{id:'archived',name:'Archived',retired:true},{id:'bound',name:'Bound',networkProfileId:'p',retired:true}]);
 assert.deepEqual(r.hostIds,['archived','bound','legacy']);
});
test('malformed write result is unknown and re-read without replay',async()=>{
 const f=await fixture({invalidResult:true});try{f.btn('创建共享设备').onclick();f.btn('确认操作').onclick();await tick();await tick();assert.equal(f.calls.filter(c=>c[0]==='zerotier_device_write').length,1);assert.match(f.text(),/未确认/);}finally{f.restore();}
});

test('same revision with changed host metadata invalidates confirmation',async()=>{
 const f=await fixture();try{assert.match(f.text(),/Network A（p）/);assert.match(f.text(),/Host A（host）/);f.btn('创建共享设备').onclick();f.setHosts([{id:'host',name:'Renamed'}]);f.btn('确认操作').onclick();await tick();await tick();assert.equal(f.calls.filter(c=>c[0]==='zerotier_device_write').length,0);assert.match(f.text(),/审查已失效/);}finally{f.restore();}
});

test('recovery rejects a valid response for a different identity and reads actual pending state',async()=>{
 const f=await fixture({pendingCreation:{handle:h,phase:'record-present'},writeResult:{handle:i,instanceId:i}});try{f.btn('恢复待定创建').onclick();f.btn('确认操作').onclick();await tick();await tick();assert.equal(f.calls.filter(c=>c[0]==='zerotier_device_write').length,1);assert.match(f.text(),/未确认/);assert.match(f.text(),/待定创建/);}finally{f.restore();}
});
test('valid creation response does not confirm when readback has no matching device',async()=>{
 const f=await fixture();try{f.btn('创建共享设备').onclick();f.btn('确认操作').onclick();await tick();await tick();assert.equal(f.calls.filter(c=>c[0]==='zerotier_device_write').length,1);assert.match(f.text(),/未确认/);assert.match(f.text(),/当前没有已确认/);}finally{f.restore();}
});

test('creation is confirmed only when readback matches both identifiers',async()=>{
 const f=await fixture({afterWrite:s=>({...s,device:{handle:h,instanceId:i}})});try{f.btn('创建共享设备').onclick();f.btn('确认操作').onclick();await tick();await tick();assert.match(f.text(),/操作已确认/);}finally{f.restore();}
});
test('forget with pending deletion remains unconfirmed',async()=>{
 const f=await fixture({device:{handle:h,instanceId:i},beforeForget:async()=>true,afterWrite:s=>({...s,device:null,pendingDeletion:{handle:h,phase:'finishing'}})});try{f.btn('删除共享设备').onclick();f.btn('确认操作').onclick();await tick();await tick();assert.match(f.text(),/未确认/);assert.match(f.text(),/待定删除/);assert.equal(f.calls.filter(c=>c[0]==='zerotier_device_write').length,1);}finally{f.restore();}
});

test('dialog has a labelled modal and restores focus and listeners on close and escape',async()=>{
 const f=await fixture();try{const opener=new Element('button');globalThis.document.activeElement=opener;const second=openZeroTierDeviceReview({invoke:f.invoke,getHosts:f.getHosts});await tick();const d=globalThis.document.body.children.at(-1);assert.equal(f.dialog.removed,true);assert.equal(d.attrs['aria-labelledby'],'zerotier-device-title');assert.equal(globalThis.document.activeElement.tagName,'h2');let prevented=false;d.listeners.cancel({preventDefault(){prevented=true;}});assert.equal(prevented,true);assert.equal(d.removed,true);assert.equal(globalThis.document.activeElement,f.originalOpener);assert.equal(f.docListeners.visibilitychange,undefined);assert.equal(f.winListeners.blur,undefined);second.close();}finally{f.restore();}
});
test('backgrounding removes an existing confirmation and requires fresh review',async()=>{
 const f=await fixture();try{f.btn('创建共享设备').onclick();assert.ok(f.btn('确认操作'));globalThis.document.hidden=true;f.docListeners.visibilitychange();assert.equal(f.btn('确认操作'),undefined);globalThis.document.hidden=false;assert.equal(f.btn('创建共享设备'),undefined);f.btn('刷新状态').onclick();await tick();assert.ok(f.btn('创建共享设备'));}finally{f.restore();}
});
test('close restores the stable network entry when a settled catalog render replaced its opener',async()=>{
 const f=await fixture();try{const stable=new Element('button');f.originalOpener.isConnected=false;globalThis.document.getElementById=id=>id==='network-open'?stable:null;f.ui.close();assert.equal(globalThis.document.activeElement,stable);}finally{f.restore();}
});
test('reopening during a pending write cannot issue a second mutation',async()=>{
 let release;const delay=new Promise(r=>release=r);const f=await fixture({delayWrite:delay});let second;try{f.btn('创建共享设备').onclick();f.btn('确认操作').onclick();await tick();second=openZeroTierDeviceReview({invoke:f.invoke,getHosts:f.getHosts});await tick();const d=globalThis.document.body.children.at(-1);const create=d.all().find(e=>e.textContent==='创建共享设备');assert.equal(create.disabled,true);assert.equal(f.calls.filter(c=>c[0]==='zerotier_device_write').length,1);release();await tick();await tick();assert.equal(f.calls.filter(c=>c[0]==='zerotier_device_write').length,1);assert.equal(d.all().find(e=>e.textContent==='创建共享设备').disabled,false);}finally{release();second?.close();f.restore();}
});

test('pending creation actions follow reviewed phase including finishing',async()=>{
 for(const [phase,recover,discard] of [['record-present',true,false],['record-pending',false,true],['finishing',true,true]]){const f=await fixture({pendingCreation:{handle:h,phase}});try{assert.equal(!!f.btn('恢复待定创建'),recover);assert.equal(!!f.btn('放弃待定创建'),discard);}finally{f.restore();}}
});
test('pending delete requires explicit review and sends original phase and handle',async()=>{
 for(const phase of ['record-present','record-removed','finishing']){const f=await fixture({pendingDeletion:{handle:h,phase},afterWrite:s=>({...s,pendingDeletion:null})});try{assert.match(f.text(),/Network A（p）/);assert.match(f.text(),/Host A（host）/);f.btn('恢复待定删除').onclick();assert.ok(f.btn('确认操作'));f.btn('确认操作').onclick();await tick();await tick();const writes=f.calls.filter(c=>c[0]==='zerotier_device_write');assert.equal(writes.length,1);assert.equal(writes[0][1].action,'recoverPendingDeletion');assert.equal(writes[0][1].handle,h);assert.equal(writes[0][1].instanceId,null);assert.equal(writes[0][1].expectedPhase,phase);assert.match(f.text(),/操作已确认/);}finally{f.restore();}}
});
test('changed pending phase invalidates old review without writing',async()=>{
 const f=await fixture({pendingDeletion:{handle:h,phase:'record-present'}});try{f.btn('恢复待定删除').onclick();f.setStatus({available:true,device:null,pendingCreation:null,pendingDeletion:{handle:h,phase:'record-removed'}});f.btn('确认操作').onclick();await tick();await tick();assert.equal(f.calls.filter(c=>c[0]==='zerotier_device_write').length,0);assert.match(f.text(),/未确认|失效/);}finally{f.restore();}
});
test('unknown pending recovery is read only and never replayed',async()=>{
 const f=await fixture({unknown:true,pendingDeletion:{handle:h,phase:'finishing'}});try{f.btn('恢复待定删除').onclick();f.btn('确认操作').onclick();await tick();await tick();assert.equal(f.calls.filter(c=>c[0]==='zerotier_device_write').length,1);assert.match(f.text(),/不会自动重试/);assert.match(f.text(),/待定删除/);}finally{f.restore();}
});
test('discard finishing does not confirm an already present device',async()=>{
 const f=await fixture({pendingCreation:{handle:h,phase:'finishing'},afterWrite:s=>({...s,pendingCreation:null,device:{handle:h,instanceId:i}})});try{assert.match(f.text(),/恢复只接纳已安装记录/);assert.match(f.text(),/放弃仅清理未安装记录/);f.btn('放弃待定创建').onclick();f.btn('确认操作').onclick();await tick();await tick();assert.match(f.text(),/未确认/);}finally{f.restore();}
});

test('discard finishing cannot confirm a different device identity',async()=>{
 const f=await fixture({pendingCreation:{handle:h,phase:'finishing'},afterWrite:s=>({...s,pendingCreation:null,device:{handle:i,instanceId:h}})});try{f.btn('放弃待定创建').onclick();f.btn('确认操作').onclick();await tick();await tick();assert.match(f.text(),/未确认/);}finally{f.restore();}
});

test('pending delete cannot confirm while readback remains pending',async()=>{
 const f=await fixture({pendingDeletion:{handle:h,phase:'record-removed'}});try{f.btn('恢复待定删除').onclick();f.btn('确认操作').onclick();await tick();await tick();assert.equal(f.calls.filter(c=>c[0]==='zerotier_device_write').length,1);assert.match(f.text(),/未确认/);assert.match(f.text(),/待定删除/);}finally{f.restore();}
});

test('discard finishing confirms only when all device records are absent',async()=>{
 const f=await fixture({pendingCreation:{handle:h,phase:'finishing'},afterWrite:s=>({...s,pendingCreation:null})});try{f.btn('放弃待定创建').onclick();f.btn('确认操作').onclick();await tick();await tick();assert.match(f.text(),/操作已确认/);}finally{f.restore();}
});
