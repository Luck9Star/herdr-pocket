import test from 'node:test';
import assert from 'node:assert/strict';
import { RemoteTabs } from '../src/remote-tabs.js';

test('tabs for one host retain distinct identities, target, draft and unknown result', () => {
  let n=0; const tabs=new RemoteTabs(()=>`tab-${++n}`);
  const a=tabs.create('host'), b=tabs.create('host');
  a.target={pane:'one',terminal:'term_1'}; b.target={pane:'two',terminal:'term_2'};
  a.draft='alpha'; a.unknown=true; b.draft='beta'; tabs.select(b.id);
  assert.notEqual(a.id,b.id); assert.equal(a.draft,'alpha'); assert.equal(b.unknown,false);
  assert.deepEqual(tabs.affected(['host']).map(t=>t.id),[a.id,b.id]);
  tabs.close(a.id); assert.equal(tabs.activeId,b.id); assert.equal(b.target.pane,'two');
});

test('late token is rejected after per-tab invalidation, close and background', () => {
  let n=0;const tabs=new RemoteTabs(()=>`tab-${++n}`);
  const a=tabs.create('a'),b=tabs.create('b'); const old=tabs.begin(a.id), other=tabs.begin(b.id);
  tabs.invalidate(a.id);assert.equal(tabs.accepts(old),false);assert.equal(tabs.accepts(other),true);
  const next=tabs.begin(a.id);tabs.close(a.id);assert.equal(tabs.accepts(next),false);
  tabs.background();assert.equal(tabs.accepts(other),false);
});

test('capacity and id collision fail closed', () => {
  let n=0;const tabs=new RemoteTabs(()=>String(++n));
  for(let i=0;i<8;i++)tabs.create('h');assert.throws(()=>tabs.create('h'),/tab_capacity/);
  const collision=new RemoteTabs(()=> 'same');collision.create('h');assert.throws(()=>collision.create('h'),/invalid_tab_id/);
});

test('reused id cannot accept a previous tab token', () => {
  const tabs=new RemoteTabs(()=> 'same'); const first=tabs.create('one');
  const old=tabs.begin(first.id);tabs.close(first.id);tabs.create('two');tabs.begin('same');
  assert.equal(tabs.accepts(old),false);
});

test('a newly created tab has no accepted unissued generation', () => {
  const tabs=new RemoteTabs(()=> 'tab'); tabs.create('host');
  assert.equal(tabs.accepts({id:'tab',generation:0}),false);
  assert.equal(tabs.accepts({id:'tab',generation:1}),false);
});

test('closing focused tab never activates a neighbour', () => {
  let n=0;const tabs=new RemoteTabs(()=>String(++n));const a=tabs.create('a'),b=tabs.create('b');
  tabs.select(a.id);tabs.close(a.id);assert.equal(tabs.activeId,null);assert.ok(tabs.get(b.id));
});
