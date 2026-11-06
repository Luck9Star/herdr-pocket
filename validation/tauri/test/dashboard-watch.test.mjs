import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {SessionDashboard} from '../src/dashboard-watch.js';
const contract=JSON.parse(readFileSync(new URL('../../shared/session-watch-v1.json',import.meta.url)));
const pane=(paneId='w1:p1',terminalId='term_abc')=>({paneId,terminalId,agentStatus:'unknown'});
const update=(epoch,revision,phase='fresh',panes=[pane()])=>({epoch,revision,phase,reason:'fixture',panes});
test('SW01 SW07: dashboard revisions are independent and reject late epochs or updates',()=>{
  const board=new SessionDashboard();board.advance(1);
  assert.equal(board.accept(update(1,1),1),'accepted');const captured=board.capturedAt;
  assert.equal(board.accept(update(1,3,'stale',null),1),'accepted');
  assert.equal(board.accept(update(1,2),1),'late');assert.equal(board.phase,'stale');assert.equal(board.selectable,false);
  assert.equal(board.panes[0].terminalId,'term_abc');assert.equal(board.capturedAt,captured);
  board.advance(3);assert.equal(board.accept(update(1,99),3),'late');
  assert.equal(board.accept(update(4,1),3),'late');assert.equal(board.phase,'stale');
  assert.equal(board.accept(update(3,1),3),'accepted');assert.equal(board.phase,'fresh');
});
test('SW02 SW03: only snapshots update pane membership and state',()=>{
  const board=new SessionDashboard();board.advance(1);board.accept(update(1,1),1);
  const changed=[{...pane(),agentStatus:'blocked'},pane('w1:p2','term_def')];
  board.accept(update(1,2,'fresh',changed),1);assert.equal(board.panes.length,2);assert.equal(board.panes[0].agentStatus,'blocked');
  board.accept(update(1,3,'refreshing',null),1);assert.equal(board.panes.length,2);assert.equal(board.selectable,false);
  board.accept(update(1,4,'fresh',[]),1);assert.equal(board.panes.length,0);assert.equal(board.selectable,true);
  assert.equal(contract.limits.maxConcurrentSnapshotReads,1);
});
test('SW09: row identity and reviewed revision must still match after pane reuse',()=>{
  const board=new SessionDashboard();board.advance(1);board.accept(update(1,1),1);
  const old=board.panes[0];assert.equal(board.reviewed(old,1,1),true);
  board.accept(update(1,2,'fresh',[pane('w1:p1','term_def')]),1);
  assert.equal(board.reviewed(old,1,1),false);assert.equal(board.reviewed(old,1,2),false);
  assert.equal(board.reviewed(board.panes[0],1,2),true);
  board.invalidate('paused');assert.equal(board.reviewed(board.panes[0],1,2),false);
});
test('SW10: unsupported fallback labels one snapshot without inventing live freshness',()=>{
  const board=new SessionDashboard();board.advance(1);
  board.accept(update(1,1,'unavailable',null),1);assert.equal(board.selectable,false);
  board.accept(update(1,2,'unavailable',[pane()]),1);assert.equal(board.selectable,true);assert.match(board.label,/仅本次快照/);
  board.accept(update(1,3,'unavailable',null),1);assert.equal(board.selectable,false);assert.equal(board.panes.length,1);
});
test('SW07: malformed IPC cannot replace the current cache or enable row selection',()=>{
  const board=new SessionDashboard();board.advance(1);board.accept(update(1,1),1);
  for(const bad of [update(1,2,'fresh',null),update(1,2,'stale',[pane()]),update(1,2,'fresh',[pane(),pane()]),update(1,Number.MAX_SAFE_INTEGER+1),update(1,2,'invented')]){
    assert.equal(board.accept(bad,1),'invalid');assert.equal(board.revision,1);
  }
});
