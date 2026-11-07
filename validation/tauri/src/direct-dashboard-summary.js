import {hostSummaryIdentity} from './host-dashboard-summary.js';
const fields=['host','port','username','expectedHostKey','socketPath','herdrPath','session'];
// The legacy direct observer emits exactly one authoritative dashboard, not a watch.
export class DirectDashboardSummary {
  constructor(emit,now=()=>Date.now()){this.emit=emit;this.now=now;this.attempt=null;}
  begin({host,config,device,pairFingerprint,generation}) {
    this.finish();
    if(!device || !hostSummaryIdentity(host) || pairFingerprint!==host.deviceFingerprint || !Number.isSafeInteger(generation) || fields.some(k=>host.target[k]!==config[k]))return;
    const identity={...host,target:{...host.target}},source=Object.freeze({kind:'direct',generation});
    this.attempt={identity,source,generation,authenticated:false};
    this.emit({type:'starting',hostId:host.id,identity,source});
  }
  authenticated(generation) {if(this.attempt?.generation===generation)this.attempt.authenticated=true;}
  snapshot(generation,panes) {
    const a=this.attempt;if(!a || a.generation!==generation || !a.authenticated)return;
    this.emit({type:'snapshot',hostId:a.identity.id,identity:a.identity,source:a.source,board:{panes,capturedAt:this.now(),phase:'unavailable'}});
  }
  finish(generation) {
    const a=this.attempt;if(!a || (generation!==undefined && a.generation!==generation))return;
    this.attempt=null;this.emit({type:'stale',hostId:a.identity.id,identity:a.identity,source:a.source});
  }
}
