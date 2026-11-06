import test from 'node:test';
import assert from 'node:assert/strict';
import {NetworkLoginPoll} from '../src/network-login-poll.js';
import {nodePresentation} from '../src/network-node-state.js';
import {initNetworkUI} from '../src/network-ui.js';
const flush=()=>new Promise(r=>setImmediate(r));
const deferred=()=>{let resolve;return {promise:new Promise(r=>resolve=r),resolve:(v)=>resolve(v)};};
function timers(){let next=0;const jobs=new Map();return {jobs,schedule:fn=>{jobs.set(++next,fn);return next;},cancel:id=>jobs.delete(id),async tick(){const [id,fn]=jobs.entries().next().value; jobs.delete(id);await fn();}};}
test('polling is serial and bounded; stopping an in-flight read cannot schedule another',async()=>{
  const timer=timers(), poll=new NetworkLoginPoll({...timer,limit:3}),read=deferred();let calls=0;
  poll.start(async()=>{calls++;return read.promise;});const first=timer.tick();await flush();assert.equal(calls,1);assert.equal(timer.jobs.size,0);
  poll.stop();read.resolve(true);await first;assert.equal(timer.jobs.size,0);
  poll.start(async()=>{calls++;return true;});for(let i=0;i<3;i++)await timer.tick();assert.equal(calls,4);assert.equal(timer.jobs.size,0);
});
test('provider state and identity mode never substitute for Running or valid device state',()=>{
  const p={provider:'tailscale',enabled:true},id={supported:true,available:true,present:true,mode:'DEVICE_STATE',handle:'a'},binding={identityRef:'a'};
  assert.equal(nodePresentation(p,id,{state:'stopped'}).canStart,true);
  assert.equal(nodePresentation(p,{...id,mode:'PRIVATE'},{state:'stopped'}).canStart,false);
  assert.equal(nodePresentation(p,id,{state:'engine-started',binding}).canLogin,false);
  assert.equal(nodePresentation(p,id,{state:'unexpected',binding}).canStart,false);
  assert.equal(nodePresentation(p,id,{state:'needs-login',binding}).canLogin,true);
  assert.equal(nodePresentation(p,{...id,handle:'b'},{state:'needs-login',binding}).canLogin,false);
  const running=nodePresentation(p,id,{state:'running',binding});assert.equal(running.canLogin,false);assert.equal(running.canStart,false);assert.equal(running.canStop,true);assert.match(running.text,/Running.*SSH 尚待核验/);
  assert.match(nodePresentation(p,id,{state:'needs-machine-auth',binding}).text,/管理员批准/);
});
class Element {
  constructor(tag){this.tagName=tag;this.textContent='';this.children=[];this.value='';this.hidden=false;this.disabled=false;this.attrs={};}
  append(...nodes){for(const n of nodes){n.parent=this;this.children.push(n);}}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  setAttribute(k,v){this.attrs[k]=v;}
  descendants(){return this.children.flatMap(c=>[c,...c.descendants()]);}
  querySelectorAll(s){return s==='input[type=password]'?this.descendants().filter(n=>n.type==='password'):[];}
  querySelector(s){return s==='[role=status]'?this.descendants().find(n=>n.attrs.role==='status'):null;}
}
async function harness(run,{present=true,state='needs-login'}={}) {
  const old={document:globalThis.document,window:globalThis.window,confirm:globalThis.confirm};const panel=new Element('section'),open=new Element('button');panel.hidden=true;
  const listeners={};globalThis.document={hidden:false,getElementById:id=>id==='network-panel'?panel:open,createElement:t=>new Element(t),addEventListener:(n,fn)=>listeners[n]=fn};globalThis.window={addEventListener:(n,fn)=>listeners[n]=fn};globalThis.confirm=()=>true;
  const profile={id:'a'.repeat(32),label:'TS',provider:'tailscale',enabled:true,revision:1,settings:{controlUrl:'',hostname:''}},handle='11111111-1111-4111-8111-111111111111';
  const binding={provider:'tailscale',profileId:profile.id,profileRevision:1,networkName:'ts1:hash',identityRef:handle};const timer=timers(),calls=[];let auth=null,token=null,loginWait=null,statusWait=null;
  const invoke=async(name,args)=>{calls.push({name,args});switch(name){
    case 'network_list':return {revision:'r',profiles:[profile],bindings:[{hostId:'h',profileId:profile.id}]};
    case 'network_identity_status':return {supported:true,available:true,present,mode:present?'DEVICE_STATE':null,handle:present?handle:null};
    case 'network_node_status':return {state,binding:state==='stopped'?null:binding};
    case 'network_node_login_status':if(statusWait)return statusWait.promise;return {state,binding,authUrl:auth,reviewToken:token};
    case 'network_node_login':if(loginWait)await loginWait.promise;return {state,binding,authUrl:auth,reviewToken:token};
    case 'network_node_stop':state='stopped';auth=null;token=null;return;
    case 'network_identity_write':present=true;return;
    case 'network_node_open_auth':return;
    default:throw Error(name);
  }};
  const ui=initNetworkUI({native:true,invoke,getHosts:()=>[{id:'h',name:'host'}],onAffected:async()=>{},pollOptions:timer});
  const h={ui,panel,open,profile,binding,calls,timer,listeners,button:text=>panel.descendants().find(n=>n.tagName==='button'&&n.textContent===text),texts:()=>panel.descendants().map(n=>n.textContent),setReview:(u,t)=>{auth=u;token=t;},waitLogin:()=>loginWait=deferred(),waitStatus:()=>statusWait=deferred(),allowStatus:()=>{statusWait=null;},setState:s=>state=s};
  try{open.onclick();await flush();await run(h);}finally{ui.close();Object.assign(globalThis,old);}
}
test('TS identity creation is fixed DEVICE_STATE with an empty secret and no password form',async()=>{
  await harness(async h=>{h.button('配置本机身份').onclick();await flush();await flush();const writes=h.calls.filter(c=>c.name==='network_identity_write');assert.equal(writes.length,1);assert.equal(writes[0].args.mode,'DEVICE_STATE');assert.equal(writes[0].args.secret,'');assert.equal(h.panel.querySelectorAll('input[type=password]').length,0);},{present:false,state:'stopped'});
});
test('explicit login does not open browser; stopping invalidates late login URL publication',async()=>{
  await harness(async h=>{const pending=h.waitLogin();h.button('登录 Tailscale').onclick();await flush();assert.equal(h.calls.filter(c=>c.name==='network_node_login').length,1);assert.equal(h.calls.filter(c=>c.name==='network_node_open_auth').length,0);
    assert.equal(h.button('停止节点').disabled,false);h.button('停止节点').onclick();await flush();await flush();h.setReview('https://login.test/old','review-old');pending.resolve();await flush();await flush();assert.equal(h.button('打开授权页面'),undefined);assert.ok(h.texts().includes('节点已停止'));assert.equal(h.calls.filter(c=>c.name==='network_node_login').length,1);
  });
});
test('same-binding new review rejects the retained old Open button; new explicit click freezes exact review',async()=>{
  await harness(async h=>{h.setReview('https://login.test/a','review-1');h.ui.refresh();await flush();const old=h.button('打开授权页面');assert.ok(old);
    h.setReview('https://login.test/a','review-2');h.ui.refresh();await flush();old.onclick();await flush();assert.equal(h.calls.filter(c=>c.name==='network_node_open_auth').length,0);
    h.button('打开授权页面').onclick();await flush();const opens=h.calls.filter(c=>c.name==='network_node_open_auth');assert.equal(opens.length,1);assert.equal(opens[0].args.reviewToken,'review-2');assert.equal(opens[0].args.expectedAuthUrl,'https://login.test/a');assert.deepEqual(opens[0].args.binding,h.binding);
  });
});
test('closing during a status read suppresses late auth URL and polling',async()=>{
  await harness(async h=>{const status=h.waitStatus();h.ui.refresh();await flush();h.ui.close();status.resolve({state:'needs-login',binding:h.binding,authUrl:'https://login.test/late',reviewToken:'late'});await flush();assert.equal(h.panel.hidden,true);assert.equal(h.timer.jobs.size,0);assert.equal(h.button('打开授权页面'),undefined);});
});
test('unpaired URL/token fields never produce an Open action',async()=>{await harness(async h=>{h.setReview('https://login.test/a',null);h.ui.refresh();await flush();assert.equal(h.button('打开授权页面'),undefined);});});
test('poll wall-clock deadline suppresses a late status publication capability',async()=>{
  const timer=timers();let now=0;const poll=new NetworkLoginPoll({...timer,now:()=>now,timeout:100}),pending=deferred();let published=false;
  poll.start(async current=>{await pending.promise;if(current())published=true;return true;});const tick=timer.tick();await flush();now=101;pending.resolve();await tick;assert.equal(published,false);assert.equal(timer.jobs.size,0);
});

test('visibilitychange clears original URL and discards late read; resume only rechecks current review',async()=>{
  await harness(async h=>{
    h.setReview('https://login.test/old','review-old');h.ui.refresh();await flush();
    const oldOpen=h.button('打开授权页面');assert.ok(oldOpen);const pending=h.waitStatus();h.ui.refresh();await flush();
    globalThis.document.hidden=true;h.listeners.visibilitychange();assert.equal(h.timer.jobs.size,0);
    oldOpen.onclick();await flush();assert.equal(h.calls.filter(c=>c.name==='network_node_open_auth').length,0);
    h.allowStatus();h.setReview('https://login.test/current','review-current');
    globalThis.document.hidden=false;h.listeners.visibilitychange();await flush();
    const freshOpen=h.button('打开授权页面');assert.ok(freshOpen);assert.notEqual(freshOpen,oldOpen);
    pending.resolve({state:'needs-login',binding:h.binding,authUrl:'https://login.test/old',reviewToken:'review-old'});await flush();
    oldOpen.onclick();await flush();assert.equal(h.calls.filter(c=>c.name==='network_node_open_auth').length,0);
    h.button('打开授权页面').onclick();await flush();
    const opened=h.calls.find(c=>c.name==='network_node_open_auth');assert.equal(opened.args.reviewToken,'review-current');assert.equal(opened.args.expectedAuthUrl,'https://login.test/current');
    assert.equal(h.calls.filter(c=>['network_node_login','network_node_start'].includes(c.name)).length,0);
    assert.ok(h.calls.filter(c=>c.name==='network_node_login_status').length>=3);assert.equal(h.timer.jobs.size,1);
  });
});
