import test from 'node:test';
import assert from 'node:assert/strict';
import {NativeCameraReturn} from '../src/native-camera-return.js';
function lease(purpose,options={}) {return new NativeCameraReturn({purpose,snapshot:()=>purpose,allowed:()=>true,...options});}
test('a new scanner purpose destroys held bytes and pending callbacks from the other purpose',()=>{
 const profile=lease('connection-profile'),pair=lease('pairing-response');
 try {
  const first=profile.start();profile.background();assert.equal(profile.receive(first,'profile',true),'held');profile.foreground();
  const second=pair.start();assert.equal(profile.take(),null);assert.equal(profile.receive(first,'late-profile',false),false);
  assert.equal(pair.receive(second,'response',false,{hold:true}),'held');assert.equal(pair.take(),'response');
  assert.equal(pair.take(),null);assert.equal(profile.take(),null);
 }finally{profile.discard();pair.discard();}
});
test('native return deadline is monotonic, identity-bound, and remains bounded while hidden',()=>{
 let clock=100,key='target';const camera=lease('pairing-response',{now:()=>clock,snapshot:()=>key});
 try {
  const first=camera.start(50);camera.background();clock=151;
  assert.equal(camera.receive(first,'expired',true,{hold:true}),false);clock=100;camera.foreground();assert.equal(camera.take(),null);assert.equal(camera.receive(first,'revived',false),false);
  const second=camera.start();key='another-host';assert.equal(camera.receive(second,'foreign',false),false);assert.equal(camera.take(),null);
 }finally{camera.discard();}
});
test('purpose validator rejects cross-wire payload before any bytes become reviewable',()=>{
 const camera=lease('pairing-response',{validate:raw=>{if(raw!=='response')throw Error('wrong-purpose');}});
 try {const attempt=camera.start();assert.throws(()=>camera.receive(attempt,'profile',false,{hold:true}));assert.equal(camera.take(),null);}
 finally{camera.discard();}
});
