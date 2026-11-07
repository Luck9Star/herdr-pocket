import test from 'node:test';
import assert from 'node:assert/strict';
import {writePublicRequest,createPublicRequestClipboard} from '../src/public-request-clipboard.js';
function navigatorWith(value) {
 const descriptor=Object.getOwnPropertyDescriptor(globalThis,'navigator');Object.defineProperty(globalThis,'navigator',{value,configurable:true});
 return ()=>{if(descriptor)Object.defineProperty(globalThis,'navigator',descriptor);else delete globalThis.navigator;};
}
test('clipboard starts in the tap with exactly the original public text and performs no asynchronous discovery',async()=>{
 const copied=[],restore=navigatorWith({clipboard:{writeText:raw=>{copied.push(raw);return Promise.resolve();}}});
 try{const raw=' {"public":"request"}\n',work=writePublicRequest(raw);assert.deepEqual(copied,[raw]);await work;}finally{restore();}
});
test('unsupported or denied clipboard never substitutes another transport',async()=>{
 let restore=navigatorWith({});try{await assert.rejects(writePublicRequest('{}'),/clipboard_unavailable/);}finally{restore();}
 restore=navigatorWith({clipboard:{writeText:()=>Promise.reject(Error('denied'))}});try{await assert.rejects(writePublicRequest('{}'),/denied/);}finally{restore();}
});
test('empty and oversized public text never reaches the system clipboard',async()=>{
 const copied=[],restore=navigatorWith({clipboard:{writeText:raw=>copied.push(raw)}});try{for(const raw of ['',null,'中'.repeat(700)])await assert.rejects(writePublicRequest(raw),/invalid_public_request/);assert.deepEqual(copied,[]);}finally{restore();}
});

test('identified Android copies the original native request once by host and request ID, never browser text',async()=>{
 const calls=[],writes=[],identity={hostId:'a'.repeat(32),requestId:'b'.repeat(32)};
 const copy=createPublicRequestClipboard({shell:{current:()=> 'android'},callNative:async(name,args)=>{calls.push({name,args});return {...args,copied:true};},webClipboard:()=>({writeText:raw=>writes.push(raw)})});
 await copy('public source',identity);assert.deepEqual(calls,[{name:'pair_copy_request',args:identity}]);assert.deepEqual(writes,[]);
});
test('Android denial and malformed completion never trigger a second native or browser copy',async()=>{
 const identity={hostId:'a'.repeat(32),requestId:'b'.repeat(32)};
 for(const result of [null,true,{...identity,copied:false},{...identity,copied:true,extra:'unexpected'},{...identity,copied:true,requestId:'c'.repeat(32)},Error('denied')]) {
  let calls=0,writes=0;const copy=createPublicRequestClipboard({shell:{current:()=> 'android'},callNative:async()=>{calls++;if(result instanceof Error)throw result;return result;},webClipboard:()=>({writeText:()=>writes++})});
  await assert.rejects(copy('public source',identity));assert.equal(calls,1);assert.equal(writes,0);
 }
});
test('other platforms start navigator write in the same tap; unknown platform never probes then copies late',async()=>{
 let native=0,probes=0;const writes=[],shell={current:()=> 'ios',probe:()=>probes++};
 const copy=createPublicRequestClipboard({shell,callNative:()=>native++,webClipboard:()=>({writeText:raw=>{writes.push(raw);return Promise.resolve();}})});
 const work=copy('exact original');assert.deepEqual(writes,['exact original']);await work;assert.equal(native,0);
 const unknown=createPublicRequestClipboard({shell:{...shell,current:()=>null},callNative:()=>native++,webClipboard:()=>({writeText:raw=>writes.push(raw)})});
 await assert.rejects(unknown('public source'),/clipboard_unavailable/);assert.equal(probes,0);assert.equal(native,0);assert.equal(writes.length,1);
});
