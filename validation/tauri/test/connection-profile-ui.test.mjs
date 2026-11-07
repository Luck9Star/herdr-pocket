import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {initConnectionProfileUI} from '../src/connection-profile-ui.js';
const corpus=JSON.parse(await readFile(new URL('../../shared/connection-profile-v1.json',import.meta.url),'utf8'));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
function setup(options={}) {
  const oldDocument=globalThis.document,oldWindow=globalThis.window,nodes={},documentEvents={},windowEvents={};
  for(const id of ['connection-profile-scan','connection-profile-preview','connection-profile-apply','connection-profile-details','connection-profile-fingerprint','connection-profile-status','connection-profile-raw','connection-profile-cancel','remote-form'])nodes[id]={id,value:'',textContent:'',hidden:false,events:{},addEventListener(event,fn){this.events[event]=fn;}};
  globalThis.document={hidden:false,getElementById:id=>nodes[id],addEventListener:(event,fn)=>documentEvents[event]=fn};
  globalThis.window={addEventListener:(event,fn)=>windowEvents[event]=fn};
  let state={available:true,navigation:1,target:'empty'},applied=[],calls=[];
  const controller=initConnectionProfileUI({native:options.native!==false,state:()=>state,apply:profile=>applied.push(profile),invoke:async command=>{calls.push(command);return options.scan?options.scan():corpus.valid[0].raw;},...options});
  return {nodes,applied,calls,controller,setState:next=>state=next,
    background:()=>{document.hidden=true;documentEvents.visibilitychange();},
    foreground:()=>{document.hidden=false;documentEvents.visibilitychange();},
    pagehide:()=>windowEvents.pagehide(),
    edit:()=>nodes['remote-form'].events.input({target:{id:'remote-host'}}),
    restore:()=>{controller.invalidate();globalThis.document=oldDocument;globalThis.window=oldWindow;}};
}
test('camera preview computes all public fields, requires explicit apply, and invokes only camera',async()=>{
 const h=setup();try {await h.nodes['connection-profile-scan'].onclick();assert.deepEqual(h.calls,['pair_scan_response']);assert.equal(h.applied.length,0);assert.ok(h.nodes['connection-profile-details'].textContent.includes(corpus.valid[0].fingerprint));assert.equal(h.nodes['connection-profile-apply'].disabled,false);assert.ok(h.nodes['connection-profile-fingerprint'].textContent.includes(corpus.valid[0].fingerprint));h.nodes['connection-profile-apply'].onclick();assert.equal(h.applied.length,1);h.nodes['connection-profile-apply'].onclick();assert.equal(h.applied.length,1);}finally{h.restore();}
});
for(const change of ['hidden','navigation','edit','identity','cancel'])test(`late camera result cannot modify source or form after ${change}`,async()=>{
 const pending=deferred(),h=setup({scan:()=>pending.promise});try {const work=h.nodes['connection-profile-scan'].onclick();
 if(change==='hidden')h.background();if(change==='navigation')h.setState({available:true,navigation:2,target:'new'});if(change==='edit')h.edit();if(change==='identity')h.setState({available:false,navigation:1,target:'saved-identity'});if(change==='cancel')h.nodes['connection-profile-cancel'].onclick();
 pending.resolve(corpus.valid[0].raw);await work;assert.equal(h.nodes['connection-profile-raw'].value,'');assert.equal(h.nodes['connection-profile-apply'].disabled,true);h.nodes['connection-profile-apply'].onclick();assert.equal(h.applied.length,0);
 }finally{h.restore();}
});
for(const change of ['edit','hidden','identity','cancel'])test(`late local fingerprint preview cannot restore authority after ${change}`,async()=>{
 const pending=deferred(),h=setup({preview:()=>pending.promise});try {h.nodes['connection-profile-raw'].value=corpus.valid[0].raw;const work=h.nodes['connection-profile-preview'].onclick();
 if(change==='edit')h.edit();if(change==='hidden')h.background();if(change==='identity')h.setState({available:false});if(change==='cancel')h.nodes['connection-profile-cancel'].onclick();
 pending.resolve({profile:JSON.parse(corpus.valid[0].raw),fingerprint:'late',text:'late preview'});await work;assert.equal(h.nodes['connection-profile-apply'].disabled,true);assert.notEqual(h.nodes['connection-profile-details'].textContent,'late preview');h.nodes['connection-profile-apply'].onclick();assert.equal(h.applied.length,0);
 }finally{h.restore();}
});
test('camera cancellation and permission denial keep manual paste fallback',async()=>{
 const h=setup({scan:()=>Promise.reject(Error('permission_denied'))});try {await h.nodes['connection-profile-scan'].onclick();assert.match(h.nodes['connection-profile-status'].textContent,/手动粘贴/);assert.equal(h.nodes['connection-profile-preview'].disabled,false);h.nodes['connection-profile-raw'].value=corpus.valid[0].raw;await h.nodes['connection-profile-preview'].onclick();assert.equal(h.nodes['connection-profile-apply'].disabled,false);}finally{h.restore();}
});
test('browser preview supports local paste and rejects invalid response / oversized camera text',async()=>{
 const h=setup({native:false});try {assert.equal(h.nodes['connection-profile-scan'].disabled,true);h.nodes['connection-profile-raw'].value=corpus.valid[0].raw;await h.nodes['connection-profile-preview'].onclick();assert.equal(h.nodes['connection-profile-apply'].disabled,false);h.nodes['connection-profile-raw'].value='{"status":"authorized"}';await h.nodes['connection-profile-preview'].onclick();assert.equal(h.nodes['connection-profile-apply'].disabled,true);assert.deepEqual(h.calls,[]);}finally{h.restore();}
 const large=setup({scan:()=> '中'.repeat(700)});try{await large.nodes['connection-profile-scan'].onclick();assert.equal(large.nodes['connection-profile-raw'].value,'');assert.equal(large.nodes['connection-profile-apply'].disabled,true);}finally{large.restore();}
});

for(const timing of ['before-visible','after-visible'])test(`native Activity return ${timing} requires an explicit foreground re-view`,async()=>{
 const pending=deferred(),h=setup({scan:()=>pending.promise});try{
  const work=h.nodes['connection-profile-scan'].onclick();h.background();
  if(timing==='after-visible')h.foreground();
  pending.resolve(corpus.valid[0].raw);await work;
  assert.equal(h.nodes['connection-profile-raw'].value,'');assert.equal(h.nodes['connection-profile-details'].hidden,true);
  assert.equal(h.nodes['connection-profile-apply'].disabled,true);assert.equal(h.applied.length,0);
  if(timing==='before-visible'){assert.equal(h.nodes['connection-profile-preview'].disabled,true);h.foreground();}
  assert.equal(h.nodes['connection-profile-preview'].disabled,false);assert.equal(h.nodes['connection-profile-scan'].disabled,false);
  assert.equal(h.nodes['connection-profile-preview'].textContent,'重新查看本次扫描结果');
  await h.nodes['connection-profile-preview'].onclick();
  assert.equal(h.nodes['connection-profile-raw'].value,corpus.valid[0].raw);assert.equal(h.nodes['connection-profile-apply'].disabled,false);
  assert.equal(h.applied.length,0);assert.deepEqual(h.calls,['pair_scan_response']);
  h.nodes['connection-profile-apply'].onclick();assert.equal(h.applied.length,1);
 }finally{h.restore();}
});
for(const event of ['edit','navigation','expired','pagehide','second-background','cancel'])test(`native camera continuation is discarded on ${event}`,async()=>{
 let clock=1000;const pending=deferred(),h=setup({scan:()=>pending.promise,now:()=>clock});try{
  const work=h.nodes['connection-profile-scan'].onclick();h.background();
  if(event==='edit')h.edit();if(event==='navigation')h.setState({available:true,navigation:2,target:'empty'});
  if(event==='expired')clock+=60001;if(event==='pagehide')h.pagehide();
  if(event==='second-background'){h.foreground();h.background();}if(event==='cancel')h.nodes['connection-profile-cancel'].onclick();
  pending.resolve(corpus.valid[0].raw);await work;h.foreground();
  assert.equal(h.nodes['connection-profile-preview'].textContent,'预览连接资料与指纹');
  await h.nodes['connection-profile-preview'].onclick();assert.equal(h.nodes['connection-profile-raw'].value,'');
  assert.equal(h.nodes['connection-profile-apply'].disabled,true);assert.equal(h.applied.length,0);
 }finally{h.restore();}
});
test('held native result expires before a later explicit view and cannot be restored by a new scan',async()=>{
 let clock=1000,finish;const pending=new Promise(resolve=>finish=resolve);let count=0;
 const h=setup({scan:()=>++count===1?pending:Promise.resolve(corpus.valid[1].raw),now:()=>clock});try{
  const work=h.nodes['connection-profile-scan'].onclick();h.background();finish(corpus.valid[0].raw);await work;h.foreground();
  clock+=60001;h.controller.render();assert.equal(h.nodes['connection-profile-preview'].textContent,'预览连接资料与指纹');
  await h.nodes['connection-profile-preview'].onclick();assert.equal(h.nodes['connection-profile-raw'].value,'');assert.equal(h.nodes['connection-profile-apply'].disabled,true);
  await h.nodes['connection-profile-scan'].onclick();assert.equal(h.nodes['connection-profile-raw'].value,corpus.valid[1].raw);
 }finally{h.restore();}
});
test('a held return is discarded when another scan starts, even if the second scan is cancelled',async()=>{
 let finish,count=0;const pending=new Promise(resolve=>finish=resolve);
 const h=setup({scan:()=>++count===1?pending:Promise.reject(Error('scan_cancelled'))});try{
  const work=h.nodes['connection-profile-scan'].onclick();h.background();finish(corpus.valid[0].raw);await work;h.foreground();
  await h.nodes['connection-profile-scan'].onclick();await h.nodes['connection-profile-preview'].onclick();
  assert.equal(h.nodes['connection-profile-raw'].value,'');assert.equal(h.nodes['connection-profile-apply'].disabled,true);
 }finally{h.restore();}
});
test('cancelled Activity return while hidden restores manual controls on foreground',async()=>{
 const pending=deferred(),h=setup({scan:()=>pending.promise});try{
  const work=h.nodes['connection-profile-scan'].onclick();h.background();pending.reject(Error('scan_cancelled'));await work;
  assert.equal(h.nodes['connection-profile-scan'].disabled,true);h.foreground();
  assert.equal(h.nodes['connection-profile-scan'].disabled,false);assert.equal(h.nodes['connection-profile-preview'].disabled,false);
  assert.match(h.nodes['connection-profile-status'].textContent,/手动粘贴/);
 }finally{h.restore();}
});
