/** UI generation is independent of native generation; neither comes from imported configuration. */
export class RemoteViewGate {
  generation = 0;
  pending = false;
  reviewed = false;
  nativeGeneration = null;
  pendingGeneration = null;
  begin() {
    if (this.pending || !this.reviewed) return null;
    this.pending = true; this.nativeGeneration = null;
    this.pendingGeneration = ++this.generation;
    return this.pendingGeneration;
  }
  accepts(generation, nativeGeneration = null) {
    if (!this.pending || generation !== this.generation) return false;
    if (nativeGeneration !== null) {
      if (!Number.isSafeInteger(nativeGeneration) || nativeGeneration < 1) return false;
      if (this.nativeGeneration === null) this.nativeGeneration = nativeGeneration;
      return nativeGeneration === this.nativeGeneration;
    }
    return true;
  }
  invalidate() { this.reviewed = false; this.generation++; }
  finish(generation) {
    if (this.pendingGeneration !== generation) return false;
    const current = this.accepts(generation); this.pending = false; this.pendingGeneration = null;
    return current;
  }
}

/** Fail closed on malformed IPC or out-of-order data; one frame stays in flight until rendered. */
export class RemoteFrameQueue {
  lastSeq = null;
  inFlight = false;
  accept(frame) {
    if (this.inFlight || !frame || !Number.isSafeInteger(frame.seq) || frame.seq < 0 || typeof frame.full !== 'boolean' ||
        (this.lastSeq === null ? !frame.full : frame.seq !== this.lastSeq + 1) ||
        !Array.isArray(frame.bytes) || frame.bytes.length > 65536 ||
        !frame.bytes.every(b => Number.isInteger(b) && b >= 0 && b <= 255)) return false;
    this.lastSeq = frame.seq; this.inFlight = true; return true;
  }
  acknowledge(seq) {
    if (!this.inFlight || seq !== this.lastSeq) return false;
    this.inFlight = false; return true;
  }
}
export function validDashboard(panes) {
  if (!Array.isArray(panes) || panes.length > 256) return false;
  const ids = new Set(), terminals = new Set();
  for (const p of panes) {
    if (!p || typeof p.paneId !== 'string' || !/^[A-Za-z0-9:_-]{1,128}$/.test(p.paneId) ||
        typeof p.terminalId !== 'string' || !/^term_[0-9a-f]{1,123}$/.test(p.terminalId) || ids.has(p.paneId) || terminals.has(p.terminalId)) return false;
    ids.add(p.paneId); terminals.add(p.terminalId);
  }
  return true;
}
