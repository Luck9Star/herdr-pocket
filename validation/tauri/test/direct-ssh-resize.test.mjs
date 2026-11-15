import test from 'node:test';
import assert from 'node:assert/strict';
import {createDirectSshResizer, measureDirectSshViewport} from '../src/direct-ssh-ui.js';

const flush=()=>new Promise(resolve=>setImmediate(resolve));
test('viewport measures both cell dimensions and ignores a hidden terminal',()=>{
  const previous=globalThis.getComputedStyle;
  globalThis.getComputedStyle=()=>({paddingLeft:'8px',paddingRight:'8px',paddingTop:'12px',paddingBottom:'12px'});
  let visible=true;
  const container={clientWidth:816,clientHeight:408,getClientRects:()=>visible?[{}]:[]};
  const terminal={cols:80,rows:24,element:{querySelector:()=>({getBoundingClientRect:()=>({width:800,height:384})})}};
  try {
    assert.deepEqual(measureDirectSshViewport(container,terminal),{cols:80,rows:24});
    container.clientHeight=280;
    assert.deepEqual(measureDirectSshViewport(container,terminal),{cols:80,rows:16});
    visible=false;assert.equal(measureDirectSshViewport(container,terminal),null);
  } finally {globalThis.getComputedStyle=previous;}
});

test('coalesces in-flight changes and applies final measured height',async()=>{
  let size={cols:80,rows:24},finish;const sent=[],applied=[];
  const resizer=createDirectSshResizer({measure:()=>size,send:(cols,rows)=>{sent.push([cols,rows]);return sent.length===1?new Promise(resolve=>finish=resolve):Promise.resolve(true);},apply:(...v)=>applied.push(v)});
  resizer.start();resizer.request();size={cols:80,rows:18};resizer.request();size={cols:80,rows:14};resizer.request();
  assert.deepEqual(sent,[[80,24]]);finish(true);await flush();
  assert.deepEqual(sent,[[80,24],[80,14]]);assert.deepEqual(applied,[[80,24],[80,14]]);
});

test('late resize from old session cannot apply or block new session',async()=>{
  let finish;const applied=[],sent=[];
  const resizer=createDirectSshResizer({measure:()=>({cols:70,rows:15}),send:(...v)=>{sent.push(v);return sent.length===1?new Promise(resolve=>finish=resolve):Promise.resolve(true);},apply:(...v)=>applied.push(v)});
  resizer.start();resizer.request();resizer.stop();resizer.start();resizer.request();await flush();finish(true);await flush();
  assert.deepEqual(sent,[[70,15],[70,15]]);assert.deepEqual(applied,[[70,15]]);
});
