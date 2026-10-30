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
