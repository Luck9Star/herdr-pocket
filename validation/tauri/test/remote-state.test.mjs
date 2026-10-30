import test from 'node:test';
import assert from 'node:assert/strict';
import { RemoteViewGate } from '../src/remote-state.js';
test('remote read requires review; repeated starts cannot overlap',()=>{const g=new RemoteViewGate();assert.equal(g.begin(),null);g.reviewed=true;const old=g.begin();assert.ok(old);assert.equal(g.begin(),null);assert.ok(g.accepts(old,7));assert.equal(g.accepts(old,8),false);});
test('cancel invalidates late events and keeps cleanup busy until settled',()=>{const g=new RemoteViewGate();g.reviewed=true;const old=g.begin();g.invalidate();assert.equal(g.accepts(old,3),false);g.reviewed=true;assert.equal(g.begin(),null);assert.equal(g.finish(old),false);const next=g.begin();assert.ok(next>old);assert.equal(g.accepts(old,3),false);assert.ok(g.accepts(next,4));});
test('target edits clear review and invalidate completed frame callback',()=>{const g=new RemoteViewGate();g.reviewed=true;const old=g.begin();assert.ok(g.finish(old));g.invalidate();assert.equal(g.reviewed,false);assert.notEqual(g.generation,old);assert.equal(g.begin(),null);});
test('a repeated old completion cannot clear newer attempt ownership',()=>{const g=new RemoteViewGate();g.reviewed=true;const old=g.begin();g.finish(old);const fresh=g.begin();assert.equal(g.finish(old),false);assert.ok(g.accepts(fresh));assert.equal(g.pending,true);});
