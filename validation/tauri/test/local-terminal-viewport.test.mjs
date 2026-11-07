import test from 'node:test';
import assert from 'node:assert/strict';
import {LocalTerminalViewport,terminalViewportIdentity} from '../src/local-terminal-viewport.js';
import {observationError} from '../src/observation-error.js';

function geometry(width=800,clientWidth=320) {
  const screen={getBoundingClientRect:()=>({width})};
  return {viewport:{scrollLeft:0,scrollTop:0,clientWidth,scrollWidth:width,clientHeight:200,scrollHeight:400},
    terminal:{cols:80,element:{querySelector:()=>screen}},setWidth:value=>width=value};
}
test('column anchor survives renderer replacement only after new full, geometry clamps locally',()=>{
  const state=new LocalTerminalViewport(),a=geometry();state.mount(a.viewport,a.terminal,'same',true);
  a.viewport.scrollLeft=250;a.viewport.scrollTop=40;state.detach();
  const b=geometry(960);state.mount(b.viewport,b.terminal,'same');assert.equal(b.viewport.scrollLeft,0);
  state.fullRendered();assert.equal(b.viewport.scrollLeft,300);assert.equal(b.viewport.scrollTop,40);
  b.setWidth(1200);b.viewport.scrollWidth=1200;state.restore();assert.equal(b.viewport.scrollLeft,375);
  b.viewport.clientWidth=1150;state.restore();assert.equal(b.viewport.scrollLeft,50);
  state.capture();b.viewport.clientWidth=320;state.restore();assert.equal(b.viewport.scrollLeft,375,'clamp-generated scroll must preserve the original column anchor');
  b.viewport.scrollWidth=200;b.viewport.scrollHeight=100;state.restore();assert.equal(b.viewport.scrollLeft,0);assert.equal(b.viewport.scrollTop,0);
});
test('hidden geometry never erases prior position and different targets never inherit it',()=>{
  const state=new LocalTerminalViewport(),a=geometry();state.mount(a.viewport,a.terminal,'first',true);
  a.viewport.scrollLeft=240;state.capture();a.viewport.clientWidth=0;a.viewport.scrollLeft=0;state.detach();
  const b=geometry();state.mount(b.viewport,b.terminal,'second');b.viewport.scrollLeft=240;state.fullRendered();assert.equal(b.viewport.scrollLeft,0);
  state.detach();state.mount(a.viewport,a.terminal,'first');a.viewport.clientWidth=320;state.fullRendered();assert.equal(a.viewport.scrollLeft,240);
});
test('viewport identity includes host pin, SSH endpoint, session, device, reviewed route and exact terminal',()=>{
  const host={target:{host:'a',port:22,username:'u',expectedHostKey:'pin',session:'s',socketPath:'sock',herdrPath:'herdr'},deviceFingerprint:'device',networkProfileId:'network-a',networkRevision:1};
  const pane={paneId:'w1:p1',terminalId:'term_abc'},identity=terminalViewportIdentity(host,pane);
  for(const key of Object.keys(host.target))assert.notEqual(terminalViewportIdentity({...host,target:{...host.target,[key]:'changed'}},pane),identity,key);
  assert.notEqual(terminalViewportIdentity({...host,deviceFingerprint:'new'},pane),identity);
  assert.notEqual(terminalViewportIdentity({...host,networkProfileId:'network-b'},pane),identity);
  assert.notEqual(terminalViewportIdentity({...host,networkRevision:2},pane),identity);
  assert.notEqual(terminalViewportIdentity({...host,networkProfileId:null,networkRevision:null},pane),identity);
  assert.notEqual(terminalViewportIdentity(host,{...pane,terminalId:'term_def'}),identity);
});
test('observation failures use exact public allowlist and never stringify raw exception content',()=>{
  assert.match(observationError('host_key_mismatch'),/认证未开始.*独立可信渠道.*不要直接替换/);
  assert.match(observationError('authentication_failed'),/认证失败/);
  assert.match(observationError('pane_missing'),/重新选择/);
  assert.match(observationError('resume_target_changed'),/终端身份已变化.*不会自动切换/);
  assert.match(observationError('observe_ended'),/观察通道已结束.*画面已陈旧/);
  for(const error of ['secret-host-key',Error('secret-host-key'),{toString(){throw Error('must not stringify');}},'constructor','toString'])assert.doesNotMatch(observationError(error),/secret-host-key|function|Object/);
});
