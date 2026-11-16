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
async function harness(run,{login=false}={}) {
  const previous={document:globalThis.document,window:globalThis.window,confirm:globalThis.confirm};
  const panel=new Element('section'),open=new Element('button');panel.hidden=true;
  globalThis.document={hidden:false,getElementById:id=>id==='network-panel'?panel:open,createElement:tag=>new Element(tag),addEventListener(){}};
  globalThis.window={addEventListener(){}};
  const confirmations=[],calls=[],jobs=new Map();let next=0;
  globalThis.confirm=message=>{confirmations.push(message);return true;};
  const ts={id:'a'.repeat(32),label:'QA TS',provider:'tailscale',enabled:true,revision:1,settings:{controlUrl:'',hostname:''}};
  const et={id:'b'.repeat(32),label:'QA ET',provider:'easytier',enabled:true,revision:1,settings:{networkName:'fixture',peers:[]}};
  const hosts=[{id:'h',name:'fixture',enabled:true,retired:false,networkProfileId:et.id,target:{host:'192.0.2.1',port:22}}];
  const catalog={revision:'r1',profiles:[ts,et],bindings:[{hostId:'h',profileId:et.id}]};
  const state={binding:1,identity:1,available:true,et:'engine-started',readError:false};
  const invoke=async(name,args={})=>{
    calls.push({name,args});
    if(name==='network_list'){if(state.readError)throw Error('fixture read failed');return structuredClone(catalog);}
    if(name==='network_identity_status')return {supported:true,available:state.available,present:true,mode:args.id===ts.id?'DEVICE_STATE':'PRIVATE',handle:'identity-'+state.identity};
    const binding={profileId:args.id,profileRevision:1,networkName:'fixture',identityRef:'identity-'+state.binding};
    if(name==='network_node_status'||name==='network_node_login_status')return {state:args.id===et.id?state.et:login?'needs-login':'running',binding,
      authUrl:login&&args.id===ts.id?'https://control.invalid/synthetic':null,reviewToken:login&&args.id===ts.id?'synthetic-review':null};
    if(name==='network_node_stop'){state.et='stopped';return;}
    if(name==='network_node_open_auth')return;
    throw Error('unexpected fixture command '+name);
  };
  const ui=initNetworkUI({native:true,invoke,getHosts:()=>hosts,onAffected:async()=>{},pollOptions:{delay:0,limit:20,timeout:60000,
    schedule:fn=>{jobs.set(++next,fn);return next;},cancel:id=>jobs.delete(id)}});
  const card=label=>panel.descendants().find(node=>node.tagName==='article'&&node.children[0]?.textContent===label);
  const button=(label,text)=>card(label)?.descendants().find(node=>node.tagName==='button'&&node.textContent===text);
  try {
    open.onclick();await flush();await run({ui,card,button,calls,confirmations,state,hosts,catalog,et,panel,
      stops:()=>calls.filter(call=>call.name==='network_node_stop'),
      async tick(){const [id,fn]=jobs.entries().next().value;jobs.delete(id);await fn();await flush();}});
  } finally {ui.close();Object.assign(globalThis,previous);}
}

test('identical reads preserve the pressed stop node and one confirmation stops only its reviewed binding',async()=>{
  await harness(async h=>{
    const stop=h.button('QA ET · EasyTier','停止节点');stop.onpointerdown();h.ui.refresh();await flush();
    assert.equal(h.button('QA ET · EasyTier','停止节点'),stop);
    stop.onclick({detail:1});await flush();assert.equal(h.confirmations.length,1);assert.equal(h.stops().length,1);
    assert.equal(h.stops()[0].args.binding.profileId,h.et.id);
  });
});
test('login polling preserves the same stop and authorization closures when all reviewed data is identical',async()=>{
  await harness(async h=>{
    const stop=h.button('QA ET · EasyTier','停止节点'),authorize=h.button('QA TS · Tailscale','打开授权页面');
    await h.tick();assert.equal(h.button('QA ET · EasyTier','停止节点'),stop);assert.equal(h.button('QA TS · Tailscale','打开授权页面'),authorize);
    authorize.onclick();await flush();assert.equal(h.calls.filter(call=>call.name==='network_node_open_auth').length,1);
    assert.equal(h.confirmations.length,1);assert.equal(h.stops().length,0);
  },{login:true});
});
test('changed host, catalog, identity, node binding or availability retires both the old gesture and retargeted click',async()=>{
  for(const change of [h=>h.hosts[0].target.port++,h=>h.hosts[0].enabled=false,h=>h.catalog.revision='r2',
    h=>h.state.identity++,h=>h.state.available=false,h=>h.state.binding++,h=>h.state.et='closing',h=>h.state.readError=true]) {
    await harness(async h=>{
      const old=h.button('QA ET · EasyTier','停止节点');old.onpointerdown();change(h);h.ui.refresh();await flush();
      const fresh=h.button('QA ET · EasyTier','停止节点');assert.notEqual(fresh,old);
      old.onclick({detail:1});fresh?.onclick({detail:1});await flush();
      assert.equal(h.confirmations.length,0);assert.equal(h.stops().length,0);
    });
  }
});
test('editing changes retire a held gesture while an explicit fresh keyboard activation remains supported',async()=>{
  await harness(async h=>{
    const old=h.button('QA ET · EasyTier','停止节点');old.onpointerdown();h.button('QA ET · EasyTier','编辑').onclick();
    const fresh=h.button('QA ET · EasyTier','停止节点');assert.notEqual(fresh,old);old.onclick({detail:1});
    assert.equal(h.confirmations.length,0);fresh.onclick({detail:0});await flush();
    assert.equal(h.confirmations.length,1);assert.equal(h.stops().length,1);
  });
});
test('an explicit status refresh updates its message without replacing identical action nodes',async()=>{
  await harness(async h=>{
    const stop=h.button('QA ET · EasyTier','停止节点');h.button('QA ET · EasyTier','刷新节点状态').onclick();await flush();
    assert.equal(h.button('QA ET · EasyTier','停止节点'),stop);assert.match(h.panel.querySelector('[role=status]').textContent,/已请求读取/);
    h.ui.refresh();await flush();assert.equal(h.button('QA ET · EasyTier','停止节点'),stop);assert.match(h.panel.querySelector('[role=status]').textContent,/已请求读取/);
  });
});
