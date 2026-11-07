import test from 'node:test';
import assert from 'node:assert/strict';
import {blockedTargetList} from '../src/blocked-target-list.js';
import {HostDashboardSummary} from '../src/host-dashboard-summary.js';
class Element {children=[];dataset={};append(...x){this.children.push(...x);}setAttribute(){};}
const host={id:'h',enabled:true,target:{session:'original'},deviceFingerprint:'device'};
test('list distinguishes unknown, stale empty, verified empty, and rejects detached buttons',()=>{
 const old=globalThis.document;globalThis.document={createElement:()=>new Element()};
 try {
  const store=new HostDashboardSummary(),opened=[],source={};const render=()=>blockedTargetList({store,host,onOpen:t=>opened.push(t)});
  assert.match(render().children[0].textContent,/未知/);store.begin(host,source);
  store.publish(host,source,{panes:[{paneId:'w1:p1',terminalId:'term_a001',agentStatus:'blocked'}],capturedAt:1000,phase:'fresh'});
  const fresh=render().children[1];assert.match(fresh.textContent,/观察受阻目标/);store.invalidateHost(host.id);fresh.onclick();assert.equal(opened.length,0);
  const stale=render().children[1];assert.match(stale.textContent,/重新核查此目标/);stale.onclick();assert.equal(opened.length,1);
  store.publish(host,source,{panes:[],capturedAt:2000,phase:'fresh'});stale.onclick();assert.equal(opened.length,1);assert.match(render().children[0].textContent,/已核验受阻清单为空/);
  store.invalidateHost(host.id);assert.match(render().children[0].textContent,/陈旧.*未知/);
  store.publish(host,source,{panes:[{paneId:'w1:p1',terminalId:'term_a001',agentStatus:'blocked'}],capturedAt:3000,phase:'unavailable'});
  const snapshot=render();assert.match(snapshot.children[0].textContent,/持续更新不可用/);
  assert.match(snapshot.children[1].textContent,/重新核查此目标/);snapshot.children[1].onclick();assert.equal(opened.length,2);
 } finally {globalThis.document=old;}
});
