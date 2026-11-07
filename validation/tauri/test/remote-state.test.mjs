import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import { RemoteViewGate } from '../src/remote-state.js';
test('remote read requires review; repeated starts cannot overlap',()=>{const g=new RemoteViewGate();assert.equal(g.begin(),null);g.reviewed=true;const old=g.begin();assert.ok(old);assert.equal(g.begin(),null);assert.ok(g.accepts(old,7));assert.equal(g.accepts(old,8),false);});
test('cancel invalidates late events and keeps cleanup busy until settled',()=>{const g=new RemoteViewGate();g.reviewed=true;const old=g.begin();g.invalidate();assert.equal(g.accepts(old,3),false);g.reviewed=true;assert.equal(g.begin(),null);assert.equal(g.finish(old),false);const next=g.begin();assert.ok(next>old);assert.equal(g.accepts(old,3),false);assert.ok(g.accepts(next,4));});
test('target edits clear review and invalidate completed frame callback',()=>{const g=new RemoteViewGate();g.reviewed=true;const old=g.begin();assert.ok(g.finish(old));g.invalidate();assert.equal(g.reviewed,false);assert.notEqual(g.generation,old);assert.equal(g.begin(),null);});
test('a repeated old completion cannot clear newer attempt ownership',()=>{const g=new RemoteViewGate();g.reviewed=true;const old=g.begin();g.finish(old);const fresh=g.begin();assert.equal(g.finish(old),false);assert.ok(g.accepts(fresh));assert.equal(g.pending,true);});

test('dashboard only accepts unique pane and terminal bindings from the snapshot', async () => {
  const {validDashboard}=await import('../src/remote-state.js');
  const panes=[{paneId:'w1:p1',terminalId:'term_ab'},{paneId:'w1:p2',terminalId:'term_cd'}];
  assert.equal(validDashboard(panes),true);
  assert.equal(validDashboard([...panes,{paneId:'w1:p1',terminalId:'term_ef'}]),false);
  assert.equal(validDashboard([...panes,{paneId:'w1:p3',terminalId:'term_ab'}]),false);
});
test('one frame in flight; a gap, malformed full or oversized frame cannot advance', async () => {
  const {RemoteFrameQueue}=await import('../src/remote-state.js');
  const q=new RemoteFrameQueue(), full={seq:1,full:true,cols:80,rows:24,bytes:[65]}, delta={seq:2,full:false,cols:80,rows:24,bytes:[66]};
  assert.equal(q.accept({...full,full:false}),false);
  assert.equal(q.accept(full),true); assert.equal(q.accept(delta),false);
  assert.equal(q.acknowledge(0),false); assert.equal(q.acknowledge(1),true);
  assert.equal(q.accept({...delta,seq:3}),false);
  assert.equal(q.accept({...delta,bytes:Array(65537).fill(1)}),false);
  assert.equal(q.accept(delta),true); assert.equal(q.acknowledge(2),true);
});

test('geometry is bounded, required and cannot change on a delta', async () => {
  const {RemoteFrameQueue}=await import('../src/remote-state.js');
  const q=new RemoteFrameQueue(), full={seq:1,full:true,cols:119,rows:40,bytes:[65]};
  for (const invalid of [{cols:undefined},{rows:0},{cols:1},{cols:513},{rows:1.5},{cols:'119'},{cols:512,rows:129}])
    assert.equal(q.accept({...full,...invalid}),false);
  assert.equal(q.accept(full),true);assert.equal(q.acknowledge(1),true);
  assert.equal(q.accept({seq:2,full:false,cols:80,rows:24,bytes:[66]}),false);
  assert.equal(q.accept({seq:2,full:false,cols:119,rows:40,bytes:[66]}),true);
  assert.equal(q.acknowledge(2),true);
  assert.equal(q.accept({seq:3,full:true,cols:100,rows:30,bytes:[67]}),true);
  assert.equal(q.acknowledge(3),true);
  assert.equal(q.accept({seq:4,full:false,cols:100,rows:30,bytes:[]}),true);
});


test('shared observer geometry fixture matches the IPC contract',async()=>{
  const fixture=JSON.parse(readFileSync(new URL('../../shared/remote-frame-geometry-v1.json',import.meta.url)));
  assert.equal(fixture.schemaVersion,1);
  const {RemoteFrameQueue}=await import('../src/remote-state.js');
  for(const sample of fixture.cases){const queue=new RemoteFrameQueue();
    sample.frames.forEach((frame,index)=>{const accepted=queue.accept({seq:frame.seq,full:frame.full,cols:frame.width,rows:frame.height,bytes:[]});
      assert.equal(accepted,sample.accepted[index],`${sample.id} frame ${index}`);if(accepted)assert.equal(queue.acknowledge(frame.seq),true);
    });
  }
});
