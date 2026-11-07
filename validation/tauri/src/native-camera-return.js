// Only one native scanner bridge may own public return bytes at a time. Each
// owner binds its own purpose, target snapshot and validator; no trust survives.
let owner=null;
export class NativeCameraReturn {
  constructor({purpose,snapshot,allowed,validate=()=>{},now=()=>performance.now(),ttl=60000,onExpire=()=>{}}) {
    Object.assign(this,{purpose,snapshot,allowed,validate,now,ttl,onExpire});this.attempt=null;
  }
  discard() {
    if(this.attempt?.timer)clearTimeout(this.attempt.timer);
    this.attempt=null;if(owner===this)owner=null;
  }
  current(attempt=this.attempt) {
    const valid=!!attempt && this.attempt===attempt && owner===this && attempt.purpose===this.purpose &&
      this.now()<attempt.expires && this.allowed() && attempt.identity===this.snapshot();
    // Once an expiry, edit or identity change is observed, returning to an old
    // value (including a wall-clock correction) cannot revive the attempt.
    if(!valid && attempt && this.attempt===attempt)this.discard();
    return valid;
  }
  start(ttl=this.ttl) {
    owner?.discard();this.discard();
    if(!this.allowed())return null;
    const attempt={purpose:this.purpose,identity:this.snapshot(),expires:this.now()+Math.min(ttl,this.ttl),phase:'scanning',sawHidden:false,sawVisible:false,raw:null,timer:null};
    this.attempt=attempt;owner=this;
    attempt.timer=setTimeout(()=>{if(this.attempt===attempt){this.discard();this.onExpire();}},Math.min(ttl,this.ttl));attempt.timer.unref?.();
    return attempt;
  }
  receive(attempt,raw,hidden,{hold=false}={}) {
    if(!this.current(attempt))return false;
    if(typeof raw!=='string' || new TextEncoder().encode(raw).length>2048)throw Error('invalid_scan');
    this.validate(raw);
    if(hidden || attempt.sawHidden || hold) {
      attempt.sawHidden ||= hidden;attempt.phase='held';attempt.raw=raw;return 'held';
    }
    this.discard();return 'visible';
  }
  get held() {return this.current() && this.attempt.phase==='held';}
  take(hidden=false) {
    if(hidden || !this.held)return null;
    const raw=this.attempt.raw;this.discard();return raw;
  }
  background() {
    const attempt=this.attempt;
    if(this.current(attempt) && !attempt.sawVisible && (attempt.phase==='scanning' || attempt.sawHidden)) {
      attempt.sawHidden=true;return true;
    }
    this.discard();return false;
  }
  foreground() {if(this.current() && this.attempt.sawHidden)this.attempt.sawVisible=true;}
}
