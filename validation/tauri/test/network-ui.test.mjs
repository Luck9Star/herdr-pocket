import test from 'node:test';
import assert from 'node:assert/strict';
import { settleNetworkOperation } from '../src/network-ui.js';

test('unknown write invalidates affected host and waits for refresh before catalog reload', async () => {
  const calls=[]; let release;
  const refreshing=new Promise(resolve=>{release=resolve;});
  const pending=settleNetworkOperation(async()=>{calls.push('write');throw Error('sync_result_unknown');},['host-a'],async ids=>{calls.push(['invalidate',ids]);await refreshing;calls.push('hosts-refreshed');},async message=>{calls.push(['catalog-reload',message]);});
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls,['write',['invalidate',['host-a']]]);
  release();assert.equal(await pending,false);
  assert.equal(calls[2],'hosts-refreshed');assert.equal(calls[3][0],'catalog-reload');
  assert.match(calls[3][1],/结果未确认/);assert.doesNotMatch(calls[3][1],/重试|未更改/);
});

test('successful write also invalidates before catalog reload', async () => {
  const calls=[];
  assert.equal(await settleNetworkOperation(async()=>{calls.push('write');},[],async()=>{calls.push('refresh');},async()=>{calls.push('catalog');}),true);
  assert.deepEqual(calls,['write','refresh','catalog']);
});

class Element {
  constructor(tag,text=''){this.tagName=tag;this.textContent=text;this.children=[];this.value='';this.hidden=false;this.disabled=false;this.attrs={};}
  append(...nodes){for(const n of nodes){n.parent=this;this.children.push(n);}}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  setAttribute(k,v){this.attrs[k]=v;}
  descendants(){return this.children.flatMap(c=>[c,...c.descendants()]);}
  querySelectorAll(selector){return selector==='input[type=password]'?this.descendants().filter(n=>n.tagName==='input'&&n.type==='password'):[];}
}
async function identityUI({supported=true,unknownWrite=false,readError=false,publicMode=false,existing=false,replaceBeforeDelete=false,deferredSerialization=false}={}) {
  const {initNetworkUI}=await import('../src/network-ui.js');const previous={document:globalThis.document,window:globalThis.window,confirm:globalThis.confirm};
  const panel=new Element('section'),open=new Element('button');panel.hidden=true;
  globalThis.document={hidden:false,getElementById:id=>id==='network-panel'?panel:open,createElement:tag=>new Element(tag),addEventListener(){}};globalThis.window={addEventListener(){}};globalThis.confirm=()=>true;
  let mode=existing?'PRIVATE':null,writes=0,reads=0,sent=null,affectedCalls=0;let handle='11111111-1111-4111-8111-111111111111',argsReference=null;
  const profile={id:'a'.repeat(32),label:'Team',provider:'easytier',enabled:true,revision:1,settings:{networkName:'team',peers:['tcp://host:12']}};
  const invoke=async(name,args)=>{if(name==='network_list')return {revision:'r',profiles:[profile],bindings:[{hostId:'h1',profileId:profile.id}]};if(name==='network_identity_status'){reads++;if(readError)throw Error('locked');return {supported,available:supported,present:!!mode,mode,handle:mode?handle:null};}if(name==='network_identity_write'){writes++;argsReference=args;if(deferredSerialization)await new Promise(resolve=>setImmediate(resolve));sent={...args};if(args.action==='delete' && replaceBeforeDelete){handle='22222222-2222-4222-8222-222222222222';if(args.expectedHandle!==handle)throw Error('stale_handle');}mode=args.action==='delete'?null:args.mode;if(unknownWrite)throw Error('unknown');return;}throw Error(name);};
  try {initNetworkUI({native:true,invoke,getHosts:()=>[{id:'h1',name:'host',retired:false}],onAffected:async()=>{affectedCalls++;}});open.onclick();await new Promise(resolve=>setImmediate(resolve));
    const btn=text=>panel.descendants().find(n=>n.tagName==='button'&&n.textContent===text);const texts=()=>panel.descendants().map(n=>n.textContent);
    if(!supported||readError)return {texts:texts(),create:!!btn('配置本机身份')};
    if(existing){btn('删除本机身份').onclick();await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));return {texts:texts(),writes,reads,sent,affectedCalls};}
    btn('配置本机身份').onclick();const secret=panel.descendants().find(n=>n.tagName==='input'&&n.type==='password');secret.value='fixture-secret';const form=secret.parent.parent;if(publicMode){const select=form.descendants().find(n=>n.tagName==='select');select.value='PUBLIC_NO_SECRET';select.onchange();}form.onsubmit({preventDefault(){}});const cleared=secret.value;await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));
    return {texts:texts(),writes,reads,sent,cleared,affectedCalls,argsReference};
  } finally {globalThis.document=previous.document;globalThis.window=previous.window;globalThis.confirm=previous.confirm;}
}
test('private identity creation clears input, writes once and refreshes public status',async()=>{
  const v=await identityUI();assert.equal(v.cleared,'');assert.equal(v.writes,1);assert.equal(v.sent.mode,'PRIVATE');assert.equal(v.sent.secret,'fixture-secret');assert.equal(v.affectedCalls,1);assert.ok(v.reads>=2);assert.ok(v.texts.some(s=>s.includes('本机身份已保存')));
});
test('unknown identity write is not replayed and re-reads current status',async()=>{
  const v=await identityUI({unknownWrite:true});assert.equal(v.writes,1);assert.equal(v.cleared,'');assert.equal(v.affectedCalls,1);assert.ok(v.reads>=2);assert.ok(v.texts.some(s=>s.includes('操作结果未确认')));
});
test('unsupported platform and unknown vault status never present create as available',async()=>{
  const a=await identityUI({supported:false});assert.equal(a.create,false);assert.ok(a.texts.some(s=>s.includes('本平台本机身份待接入')));
  const b=await identityUI({readError:true});assert.equal(b.create,false);assert.ok(b.texts.some(s=>s.includes('本机身份状态未知')));
});

test('public mode sends an explicit empty secret and clears private input',async()=>{const v=await identityUI({publicMode:true});assert.equal(v.writes,1);assert.equal(v.sent.mode,'PUBLIC_NO_SECRET');assert.equal(v.sent.secret,'');assert.equal(v.cleared,'');});
test('explicit identity deletion rechecks status without deleting SSH keys',async()=>{const v=await identityUI({existing:true});assert.equal(v.writes,1);assert.equal(v.sent.action,'delete');assert.equal(v.sent.expectedHandle,'11111111-1111-4111-8111-111111111111');assert.equal(v.sent.secret,'');assert.equal(v.affectedCalls,1);assert.ok(v.reads>=2);assert.ok(v.texts.some(s=>s.includes('本机身份尚未创建')));});

test('delayed delete retains reviewed identity A when identity B has replaced it',async()=>{const v=await identityUI({existing:true,replaceBeforeDelete:true});assert.equal(v.writes,1);assert.equal(v.sent.expectedHandle,'11111111-1111-4111-8111-111111111111');assert.ok(v.reads>=2);assert.ok(v.texts.some(s=>s.includes('操作结果未确认')));assert.ok(v.texts.some(s=>s.includes('本机身份已保存')));});

test('deferred invoke sees the secret until serialization and clears it after settlement',async()=>{const v=await identityUI({deferredSerialization:true});assert.equal(v.cleared,'');assert.equal(v.sent.secret,'fixture-secret');assert.equal(v.argsReference.secret,'');assert.equal(v.writes,1);});
