import test from 'node:test';
import assert from 'node:assert/strict';
import { AuxiliaryModifiers, auxiliaryKey, draftBytes, displayDraft } from '../src/input-codec.js';
test('auxiliary cursor keys follow terminal cursor mode',()=>{
  assert.equal(auxiliaryKey('up',false),'\x1b[A'); assert.equal(auxiliaryKey('up',true),'\x1bOA');
  assert.equal(auxiliaryKey('ctrl-c',true),'\x03'); assert.equal(auxiliaryKey('invalid',false),null);
});
test('draft uses bounded bracketed paste and rejects embedded closing marker',()=>{
  assert.deepEqual([...draftBytes('文',false)],[230,150,135]);
  assert.equal(new TextDecoder().decode(draftBytes('abc',true)),'\x1b[200~abc\x1b[201~');
  assert.equal(draftBytes('x\x1b[201~bad',true),null);
  assert.equal(draftBytes('x'.repeat(4090),true),null);
});

test('preview exposes hidden control and bidi formatting characters',()=>{
  assert.equal(displayDraft('a\x1b\u202eb\nc'), 'a\\u{1b}\\u{202e}b⏎\nc');
});

test('explicit ASCII combinations have deterministic bytes and cursor modifiers preserve app mode',()=>{
  for(const key of 'abcdefghijklmnopqrstuvwxyz') {
    assert.equal(auxiliaryKey(key,false,{ctrl:true}).charCodeAt(0),key.charCodeAt(0)-96);
    assert.equal(auxiliaryKey(key,false,{alt:true}),'\x1b'+key);
    assert.equal(auxiliaryKey(key,false,{ctrl:true,alt:true}),'\x1b'+String.fromCharCode(key.charCodeAt(0)-96));
  }
  assert.equal(auxiliaryKey('space',false,{ctrl:true}),'\x00');
  for(const app of [false,true]) {
    assert.equal(auxiliaryKey('up',app,{ctrl:true}),'\x1b[1;5A');
    assert.equal(auxiliaryKey('left',app,{alt:true}),'\x1b[1;3D');
    assert.equal(auxiliaryKey('down',app,{ctrl:true,alt:true}),'\x1b[1;7B');
    assert.equal(auxiliaryKey('home',app,{alt:true}),'\x1b[1;3H');
    assert.equal(auxiliaryKey('pgdn',app,{ctrl:true}),'\x1b[6;5~');
    assert.equal(auxiliaryKey('ctrl-c',app,{ctrl:true,alt:true}),'\x03');
  }
  assert.equal(auxiliaryKey('enter',false),'\r');
  assert.equal(auxiliaryKey('tab',false,{ctrl:true}),null);
  assert.equal(auxiliaryKey('中文',false,{alt:true}),null);
});

test('toolbar holds both modifiers, toggles/cancels without writes, and always releases on a base attempt',()=>{
  const keys=new AuxiliaryModifiers();
  assert.equal(keys.toggle('ctrl',true),true);assert.equal(keys.ctrl,true);
  keys.toggle('alt',true);assert.equal(keys.alt,true);
  assert.equal(keys.take('c',false,true),'\x1b\x03');assert.equal(keys.held,false);
  assert.equal(keys.take('c',false,true),'c'); // No lingering modifier.
  keys.toggle('ctrl',true);keys.toggle('ctrl',true);assert.equal(keys.held,false);
  keys.toggle('alt',true);keys.reset();assert.equal(keys.held,false);
  keys.toggle('ctrl',true);assert.equal(keys.take('c',false,false),null);assert.equal(keys.held,false);
  assert.equal(keys.toggle('alt',false),false);assert.equal(keys.held,false);
  keys.toggle('ctrl',true);assert.equal(keys.take('tab',false,true),null);assert.equal(keys.held,false);
});
