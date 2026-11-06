import test from 'node:test';
import assert from 'node:assert/strict';
import {nodePresentation} from '../src/network-node-state.js';
const profile={provider:'easytier',enabled:true};
const privateIdentity={supported:true,available:true,present:true,mode:'PRIVATE'};
test('only explicit enabled private identity with stopped node offers start',()=>{
  assert.equal(nodePresentation(profile,privateIdentity,{state:'stopped'}).canStart,true);
  for(const p of [{...profile,enabled:false},{...profile,provider:'tailscale'}])assert.equal(nodePresentation(p,privateIdentity,{state:'stopped'}).canStart,false);
  for(const i of [null,{supported:true,available:true,present:true,mode:'PUBLIC_NO_SECRET'},{supported:false,available:false,present:false}])assert.equal(nodePresentation(profile,i,{state:'stopped'}).canStart,false);
});
test('engine start never claims network or SSH connectivity; stop stays explicit',()=>{
  const view=nodePresentation(profile,privateIdentity,{state:'engine-started'});assert.equal(view.canStart,false);assert.equal(view.canStop,true);assert.match(view.text,/尚未确认/);
  for(const state of ['unknown','unavailable','unrecognized']){const stateView=nodePresentation(profile,privateIdentity,{state});assert.equal(stateView.canStart,false);assert.equal(stateView.canStop,false);}
});
test('public mode explains the fixed engine limitation without fallback',()=>{
  const view=nodePresentation(profile,{...privateIdentity,mode:'PUBLIC_NO_SECRET'},{state:'stopped'});assert.match(view.text,/暂不支持启动/);assert.equal(view.canStart,false);
});

test('a running or cleanup-pending node can still be stopped if identity is unavailable',()=>{for(const state of ['engine-started','starting','closing'])assert.equal(nodePresentation(profile,null,{state}).canStop,true);});
