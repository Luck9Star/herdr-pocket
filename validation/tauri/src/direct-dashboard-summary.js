import {hostSummaryIdentity} from './host-dashboard-summary.js';
const fields=['host','port','username','expectedHostKey','socketPath','herdrPath','session'];
// A direct observer owns at most one authenticated host summary.
export class DirectDashboardSummary {
  constructor(emit){this.emit=emit;this.attempt=null;}
  begin({host,config,device,pairFingerprint,generation}) {
    this.finish();
    if(!device || !hostSummaryIdentity(host) || pairFingerprint!==host.deviceFingerprint || !Number.isSafeInteger(generation) || fields.some(k=>host.target[k]!==config[k]))return;
    const identity={...host,target:{...host.target}},source=Object.freeze({kind:'direct',generation});
    this.attempt={identity,source,generation,authenticated:false};
    this.emit({type:'starting',hostId:host.id,identity,source});
  }
  authenticated(generation) {if(this.attempt?.generation===generation)this.attempt.authenticated=true;}
  update(generation,board) {
    const a=this.attempt;if(!a || a.generation!==generation || !a.authenticated)return;
    if(!board?.selectable || !Array.isArray(board.panes) || !Number.isFinite(board.capturedAt)) {
      this.emit({type:'stale',hostId:a.identity.id,identity:a.identity,source:a.source});return;
    }
    this.emit({type:'snapshot',hostId:a.identity.id,identity:a.identity,source:a.source,board});
  }
  finish(generation) {
    const a=this.attempt;if(!a || (generation!==undefined && a.generation!==generation))return;
    this.attempt=null;this.emit({type:'stale',hostId:a.identity.id,identity:a.identity,source:a.source});
  }
}
