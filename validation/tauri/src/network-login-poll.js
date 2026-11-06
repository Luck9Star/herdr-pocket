// One serial, bounded read loop per visible panel. Cancellation prevents publication
// even if a native status request itself cannot be interrupted.
export class NetworkLoginPoll {
  constructor({schedule=setTimeout,cancel=clearTimeout,limit=30,delay=2000,timeout=60000,now=Date.now}={}) {
    this.schedule=schedule;this.cancelTimer=cancel;this.limit=limit;this.delay=delay;this.timeout=timeout;this.now=now;this.epoch=0;this.timer=null;
  }
  stop(){this.epoch++;if(this.timer!==null)this.cancelTimer(this.timer);this.timer=null;}
  start(read){this.stop();const epoch=this.epoch,deadline=this.now()+this.timeout;let remaining=this.limit;const current=()=>epoch===this.epoch && this.now()<deadline;
    const tick=async()=>{this.timer=null;if(!current() || remaining--<=0)return;
      let again=false;try{again=await read(current);}catch{/* Unknown is not permission to retry a write. */}
      if(current() && again && remaining>0)this.timer=this.schedule(tick,this.delay);
    };
    this.timer=this.schedule(tick,this.delay);
  }
}
