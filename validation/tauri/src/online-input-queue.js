/** Transient single-view FIFO. It never survives a lease or is replayed. */
export class OnlineInputQueue {
  constructor(maxItems=128,maxBytes=4096) { this.maxItems=maxItems; this.maxBytes=maxBytes; this.items=[]; this.bytes=0; }
  static same(a,b) { return !!a && !!b && a.generation===b.generation && a.epoch===b.epoch && a.revision===b.revision; }
  push(token,bytes) {
    if (!(bytes instanceof Uint8Array) || !bytes.length || bytes.length>4096 || this.items.length>=this.maxItems || this.bytes+bytes.length>this.maxBytes || (this.items.length && !OnlineInputQueue.same(this.items[0].token,token))) return false;
    this.items.push({token:{...token},bytes:bytes.slice()}); this.bytes+=bytes.length; return true;
  }
  take(token) {
    if (!this.items.length) return null;
    if (!OnlineInputQueue.same(this.items[0].token,token)) {this.clear();return null;}
    const item=this.items.shift(); this.bytes-=item.bytes.length; return item;
  }
  clear() {const discarded={count:this.items.length,bytes:this.bytes};this.items=[];this.bytes=0;return discarded;}
}
