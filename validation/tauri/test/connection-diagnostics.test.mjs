import test from 'node:test';
import assert from 'node:assert/strict';
import {ConnectionDiagnostics,connectionDiagnosticIdentity,connectionStageText} from '../src/connection-diagnostics.js';
const pair={paneId:'w1:p1',terminalId:'term_a001'};
const record=()=>new ConnectionDiagnostics({identity:'original',host:'fixture',session:'original',network:true,device:true,now:1234});
test('diagnostics record independent native facts without inferring missing checks',()=>{
 const r=record();assert.equal(r.rows.network.state,'pending');assert.equal(r.rows.hostKey.state,'unknown');
 r.stage('authenticated');assert.equal(r.rows.authentication.state,'verified');assert.equal(r.rows.hostKey.state,'unknown');assert.equal(r.rows.network.state,'pending');
 r.stage('host-key-verified');assert.equal(r.rows.network.state,'verified');assert.equal(r.rows.hostKey.state,'verified');assert.equal(r.stage('credentials=secret'),false);assert.equal(connectionStageText('credentials=secret'),null);
 assert.equal(r.dashboard({phase:'stale',selectable:false,panes:[]}),false);assert.equal(r.rows.dashboard.state,'unknown');r.dashboard({phase:'unavailable',selectable:true,panes:[]});assert.equal(r.rows.dashboard.state,'verified');assert.match(r.rows.dashboard.message,/持续更新不可用/);
 assert.equal(r.full(pair),false);r.bind(pair);assert.equal(r.full({...pair,terminalId:'term_a002'}),false);assert.equal(r.rows.terminal.state,'pending');assert.equal(r.full(pair),true);assert.equal(r.rows.terminal.state,'verified');r.bind(pair);assert.equal(r.rows.terminal.state,'verified');
});
test('failure preserves confirmed facts; unknown errors do not expose native detail or mark later stages passed',()=>{
 const r=record();r.stage('host-key-verified');r.finish('authentication_failed');assert.equal(r.rows.hostKey.state,'verified');assert.equal(r.rows.authentication.state,'failed');assert.equal(r.rows.dashboard.state,'unknown');assert.equal(r.rows.terminal.state,'unknown');assert.equal(r.stage('authenticated'),false);
 const failed=record();failed.finish('host_key_mismatch');assert.equal(failed.rows.hostKey.state,'failed');assert.equal(failed.rows.authentication.state,'unknown');assert.equal(failed.stage('authenticated'),false);
 const unknown=record();unknown.finish('privateKeyPem=do-not-print stderr contents');assert.ok(!JSON.stringify(unknown).includes('do-not-print'));assert.ok(!JSON.stringify(unknown).includes('stderr'));assert.equal(unknown.rows.network.state,'pending');
});
test('pause, cancel and target identity boundaries reject late evidence',()=>{
 const r=record();r.stage('host-key-verified');r.pause();assert.equal(r.stage('authenticated'),false);assert.equal(r.bind(pair),false);r.resume();assert.equal(r.stage('authenticated'),true);r.finish('cancelled');r.resume();assert.equal(r.active,false);assert.equal(r.full(pair),false);
 const base={hostId:'host-a',target:{host:'host.invalid',session:'s',expectedHostKey:'public'},deviceFingerprint:'device',networkProfileId:'n',networkRevision:1};
 const key=connectionDiagnosticIdentity(base);assert.equal(connectionDiagnosticIdentity({...base,target:{...base.target,privateKeyPem:'secret',password:'secret'}}),key);
 for(const v of [{...base,hostId:'host-b'},{...base,deviceFingerprint:'replacement'},{...base,networkRevision:2},{...base,target:{...base.target,session:'other'}},{...base,target:{...base.target,expectedHostKey:'new'}}])assert.notEqual(connectionDiagnosticIdentity(v),key);
});
