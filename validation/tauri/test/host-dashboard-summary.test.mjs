import test from 'node:test';
import assert from 'node:assert/strict';
import {HostDashboardSummary,hostSummaryText} from '../src/host-dashboard-summary.js';
const host=(id,extra={})=>({id,enabled:true,retired:false,deviceFingerprint:`device-${id}`,target:{session:'work',host:`${id}.invalid`,expectedHostKey:`key-${id}`},networkProfileId:null,networkRevision:null,...extra});
const board=(statuses,phase='fresh',capturedAt=1000)=>({panes:statuses.map(agentStatus=>({agentStatus})),phase,capturedAt});
test('unknown, authoritative zero, and missing agent statuses remain distinct',()=>{
 const store=new HostDashboardSummary(),a=host('a'),token={};assert.match(hostSummaryText(store.get(a)),/未知/);
 store.begin(a,token);assert.equal(store.publish(a,token,board([])),true);assert.match(hostSummaryText(store.get(a)),/受阻 0/);
 store.publish(a,token,board([null]));assert.match(hostSummaryText(store.get(a)),/至少 0.*状态未知/);
 store.publish(a,token,board(['blocked',undefined]));assert.match(hostSummaryText(store.get(a)),/至少 1.*状态未知/);
});
test('latest source wins without adding duplicated pane snapshots; old source cannot stale newer',()=>{
 const store=new HostDashboardSummary(),a=host('a'),first={},second={};store.begin(a,first);store.publish(a,first,board(['blocked','blocked'], 'fresh',1000));store.begin(a,second);store.publish(a,second,board(['blocked'],'fresh',2000));assert.equal(store.publish(a,first,board(['blocked','blocked'],'fresh',3000)),false);assert.equal(store.get(a).count,1);assert.equal(store.invalidateSource(a.id,first),false);assert.equal(store.get(a).current,true);assert.equal(store.invalidateSource(a.id,second),true);assert.match(hostSummaryText(store.get(a)),/上次快照/);assert.equal(store.get(a).capturedAt,2000);
});
test('stable order prioritizes only latest currently valid blocked count',()=>{
 const store=new HostDashboardSummary(),a=host('a'),b=host('b'),c=host('c');const bs={},cs={};store.begin(b,bs);store.publish(b,bs,board(['blocked']));store.begin(c,cs);store.publish(c,cs,board([]));assert.deepEqual(store.order([a,b,c]).map(h=>h.id),['b','a','c']);store.invalidateHost('b');assert.deepEqual(store.order([a,b,c]).map(h=>h.id),['a','b','c']);
});
test('host identity changes, disabled or retired records cannot inherit old data',()=>{
 for(const changed of [host('a',{target:{session:'other'}}),host('a',{deviceFingerprint:'replacement'}),host('a',{networkProfileId:'network',networkRevision:1}),host('a',{enabled:false}),host('a',{retired:true})]){const store=new HostDashboardSummary(),a=host('a');const token={};store.begin(a,token);store.publish(a,token,board(['blocked']));assert.equal(store.get(changed),null);store.reconcile([changed]);assert.equal(store.get(a),null);}
});
test('network revision and missing network metadata fail closed; rename is retained',()=>{
 const store=new HostDashboardSummary(),a=host('a',{networkProfileId:'n',networkRevision:3,name:'old'});const token={};store.begin(a,token);store.publish(a,token,board(['blocked']));assert.ok(store.get({...a,name:'new'}));assert.equal(store.get({...a,networkRevision:4}),null);assert.equal(store.get({...a,networkRevision:undefined}),null);
});
test('one-time unavailable snapshot is explicitly labelled; staleness retains original time',()=>{
 const store=new HostDashboardSummary(),a=host('a');const token={};store.begin(a,token);store.publish(a,token,board(['idle'],'unavailable',1234));assert.match(hostSummaryText(store.get(a)),/持续更新不可用/);store.invalidateHost(a.id);assert.match(hostSummaryText(store.get(a)),/上次快照/);assert.equal(store.get(a).capturedAt,1234);
});
test('new source takes authority immediately; late old snapshots cannot revive old data',()=>{
 const store=new HostDashboardSummary(),a=host('a'),old={},next={};store.begin(a,old);store.publish(a,old,board(['blocked'],'fresh',1000));store.begin(a,next);assert.equal(store.get(a).current,false);assert.equal(store.publish(a,old,board(['blocked','blocked'],'fresh',3000)),false);assert.equal(store.get(a).capturedAt,1000);store.publish(a,next,board([],'fresh',4000));assert.equal(store.get(a).count,0);assert.equal(store.get(a).current,true);
});
test('unrelated record changes and rename preserve other host snapshots',()=>{
 const store=new HostDashboardSummary(),a=host('a',{name:'A'}),b=host('b'),aSource={},bSource={};store.begin(a,aSource);store.publish(a,aSource,board(['blocked']));store.begin(b,bSource);store.publish(b,bSource,board(['idle']));store.reconcile([{...a,name:'New A'},host('b',{deviceFingerprint:'new-key'})]);assert.equal(store.get({...a,name:'New A'}).count,1);assert.equal(store.get(b),null);
});

test('one-shot blocked remains informative but does not outrank a live blocked host',()=>{
 const store=new HostDashboardSummary(),plain=host('plain'),once=host('once'),live=host('live'),onceToken={},liveToken={};store.begin(once,onceToken);store.publish(once,onceToken,board(['blocked'],'unavailable'));store.begin(live,liveToken);store.publish(live,liveToken,board(['blocked'],'fresh'));assert.deepEqual(store.order([plain,once,live]).map(h=>h.id),['live','plain','once']);assert.match(hostSummaryText(store.get(once)),/本次快照.*持续更新不可用.*受阻 1/);
});
test('catalog read failure preserves old snapshot but permanently revokes all old source owners',()=>{
 const store=new HostDashboardSummary(),a=host('a'),b=host('b'),sourceA={},sourceB={};store.begin(a,sourceA);store.publish(a,sourceA,board(['blocked'],'fresh',1234));store.begin(b,sourceB);store.publish(b,sourceB,board([],'fresh',5678));assert.equal(store.suspendAll(),true);assert.equal(store.get(a).current,false);assert.equal(store.get(a).capturedAt,1234);assert.equal(store.get(b).current,false);assert.equal(store.publish(a,sourceA,board(['blocked'],'fresh',9999)),false);store.reconcile([a,b]);assert.equal(store.get(a).capturedAt,1234);const fresh={};store.begin(a,fresh);assert.equal(store.publish(a,fresh,board([],'fresh',10000)),true);assert.equal(store.get(a).current,true);assert.equal(store.get(b).current,false);
});

test('blocked pair rows are immutable, host scoped, and superseded by a newer authoritative snapshot',()=>{
 const store=new HostDashboardSummary(),a=host('a'),token={};store.begin(a,token);
 const pane={paneId:'w1:p1',terminalId:'term_a001',agentStatus:'blocked',label:'same name'};
 store.publish(a,token,{panes:[pane,{paneId:'w1:p2',terminalId:'term_a002',agentStatus:'working'}],capturedAt:1000,phase:'fresh',epoch:1,revision:1});
 const target=store.get(a).blocked[0];assert.equal(store.get(a).blocked.length,1);assert.equal(Object.isFrozen(target),true);pane.terminalId='term_ffff';
 assert.equal(target.terminalId,'term_a001');assert.equal(store.blockedTarget(a,target),true);store.invalidateHost(a.id);assert.equal(store.blockedTarget(a,target),true);
 assert.equal(store.blockedTarget(host('b'),target),false);assert.equal(store.blockedTarget(host('a',{networkProfileId:'n',networkRevision:2}),target),false);
 assert.equal(store.publish(a,token,{panes:[],capturedAt:2000,phase:'fresh',epoch:1,revision:1}),false);
 assert.equal(store.publish(a,token,{panes:[],capturedAt:2000,phase:'fresh',epoch:1,revision:2}),true);assert.equal(store.blockedTarget(a,target),false);assert.equal(store.get(a).blocked.length,0);
});
