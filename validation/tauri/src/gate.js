const encoder = new TextEncoder();
export const byteLength = value => encoder.encode(value).byteLength;

/** Per-view lifecycle. No transport retries, no shared PTY resize, no offline queue. */
export class ViewGate {
  constructor(target, maxQueuedBytes = 65536, maxInputBytes = 4096) {
    this.target = target;
    this.maxQueuedBytes = maxQueuedBytes;
    this.maxInputBytes = maxInputBytes;
    this.generation = 0;
    this.epoch = 0;
    this.focusRevision = 0;
    this.focused = false;
    this.visible = true;
    this.mode = 'observe';
    this.ready = false;
    this.pendingBytes = 0;
    this.pending = new Map();
    this.sequence = 0;
    this.reason = '等待全量画面';
    this.unknown = false;
  }
  token() { return { target: this.target, generation: this.generation, epoch: this.epoch, focusRevision: this.focusRevision }; }
  sameStream(token) { return token?.target === this.target && token.generation === this.generation && token.epoch === this.epoch; }
  sameInput(token) { return this.sameStream(token) && token.focusRevision === this.focusRevision; }
  focus(value) { if (this.focused !== value) this.focusRevision++; this.focused = value; }
  invalidate(reason) {
    this.epoch++;
    this.focusRevision++;
    this.pending.clear();
    this.pendingBytes = 0;
    this.ready = false;
    this.mode = 'observe';
    this.reason = reason;
  }
  hide() { this.visible = false; this.invalidate('观察暂停；恢复需新全量画面'); }
  reconnect() { this.visible = true; this.generation++; this.invalidate('恢复中；等待全量画面'); return this.token(); }
  setMode(mode) {
    if (!['observe','direct','draft'].includes(mode)) throw Error('invalid mode');
    if (mode !== this.mode) this.focusRevision++;
    this.mode = mode;
  }
  acknowledgeUnknown(token) {
    if (!this.ready || !this.focused || !this.sameInput(token)) return false;
    this.unknown = false; this.focusRevision++; return true;
  }
  unknownSend() { this.unknown = true; this.invalidate('发送结果未知；核实后主动恢复，不自动重放'); }
  receive(kind, data, token) {
    if (!this.visible || !this.sameStream(token)) return null;
    if (kind !== 'full' && !this.ready) return null;
    const bytes = byteLength(data);
    if (bytes > this.maxQueuedBytes || this.pendingBytes + bytes > this.maxQueuedBytes) {
      this.invalidate('缓冲达到上限；必须重建全量画面');
      return null;
    }
    const receipt = { id: ++this.sequence, token, bytes, kind };
    this.pending.set(receipt.id, receipt);
    this.pendingBytes += bytes;
    return receipt;
  }
  consumed(receipt) {
    if (!receipt || !this.sameStream(receipt.token) || !this.pending.delete(receipt.id)) return false;
    this.pendingBytes -= receipt.bytes;
    if (receipt.kind === 'full') { this.ready = true; this.reason = 'fixture 就绪；尚未连接 SSH'; }
    return true;
  }
  input(text, token, { draft = false } = {}) {
    if (this.unknown) return { accepted:false, reason:'发送结果未知，须先核实原目标并确认' };
    if (!this.visible || !this.focused || !this.ready || !this.sameInput(token)) return { accepted: false, reason: '目标、焦点或画面已变化' };
    if ((draft && this.mode !== 'draft') || (!draft && this.mode !== 'direct')) return { accepted: false, reason: '需显式进入对应输入模式' };
    if (!text || byteLength(text) > this.maxInputBytes) return { accepted: false, reason: '文本为空或超过输入字节上限' };
    return { accepted: true, target: this.target, generation: this.generation, epoch: this.epoch, bytes: encoder.encode(text) };
  }
}

/** Bind asynchronous clipboard reads before awaiting an OS permission/read. */
export async function readBoundClipboard(gate, read) {
  const token = gate.token();
  const text = await read();
  if (!gate.sameInput(token) || !gate.focused || !gate.visible || !gate.ready || gate.unknown) return null;
  return { token, text };
}

/** Every native callback wait is settled on cancel or deadline, even before a chunk arrives. */
export class WaitRegistry {
  constructor() { this.pending = new Set(); }
  create(timeoutMs = 5000) {
    let settle;
    const promise = new Promise(resolve => {
      const timer = setTimeout(() => settle(false), timeoutMs);
      settle = value => { clearTimeout(timer); this.pending.delete(settle); resolve(value); };
      this.pending.add(settle);
    });
    return { promise, settle };
  }
  cancel() { for (const settle of [...this.pending]) settle(false); }
}
