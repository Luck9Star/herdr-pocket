import {validDashboard} from './remote-state.js';

/** Metadata freshness has no authority over terminal rendering or input leases. */
export class SessionDashboard {
  epoch=0;
  revision=0;
  phase='stale';
  reason='disconnected';
  panes=[];
  capturedAt=null;
  selectable=false;
  advance(epoch) {
    if(!Number.isSafeInteger(epoch) || epoch<1 || epoch<this.epoch)return false;
    if(epoch>this.epoch){this.epoch=epoch;this.revision=0;this.invalidate('epoch_changed');}
    return true;
  }
  invalidate(reason='paused') {this.phase='stale';this.reason=reason;this.selectable=false;}
  accept(update,currentEpoch) {
    if(!update || !Number.isSafeInteger(update.epoch) || update.epoch<1 || !Number.isSafeInteger(update.revision) || update.revision<1 ||
        !['stale','refreshing','fresh','unavailable'].includes(update.phase) || typeof update.reason!=='string' || update.reason.length>96 ||
        ![null,undefined].includes(update.panes) && !validDashboard(update.panes) ||
        update.phase==='fresh' && !Array.isArray(update.panes) ||
        ['stale','refreshing'].includes(update.phase) && ![null,undefined].includes(update.panes))return 'invalid';
    if(update.epoch!==currentEpoch || update.epoch<this.epoch || update.epoch===this.epoch && update.revision<=this.revision)return 'late';
    this.advance(update.epoch);this.revision=update.revision;this.phase=update.phase;this.reason=update.reason;
    this.selectable=update.phase==='fresh' || update.phase==='unavailable' && Array.isArray(update.panes);
    if(Array.isArray(update.panes)){this.panes=update.panes.map(p=>Object.freeze({...p}));this.capturedAt=Date.now();}
    return 'accepted';
  }
  reviewed(pane,epoch,revision) {
    return this.selectable && epoch===this.epoch && revision===this.revision &&
      this.panes.some(p=>p.paneId===pane.paneId && p.terminalId===pane.terminalId);
  }
  get label() {
    if(this.phase==='fresh')return '看板已同步 · 持续更新';
    if(this.phase==='refreshing')return '看板正在同步 · 旧状态仅供参考';
    if(this.phase==='unavailable')return this.selectable?'持续更新不可用 · 仅本次快照':'持续更新不可用 · 等待本次快照';
    return '看板状态陈旧 · 等待重新核验';
  }
}
