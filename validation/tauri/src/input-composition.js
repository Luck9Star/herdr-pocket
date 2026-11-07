// A writable textarea can request the keyboard before the backend grants input.
// Keep composition events visible so a pre-grant composition retains its old lease.
export function blockPendingKeys(textarea, pending) {
  for (const kind of ['keydown', 'keypress', 'beforeinput', 'input']) {
    textarea.addEventListener(kind, event => {
      if (!pending()) return;
      event.preventDefault();
      event.stopImmediatePropagation();
    }, true);
  }
}

/** Bind IME output to the lease that began composition, including after blur. */
export class InputComposition {
  token = null;
  ended = false;
  begin(token) { this.token = token; this.ended = false; }
  end() { if (this.token) this.ended = true; }
  accepts(token) {
    if (!this.token) return true;
    const allowed = this.token.generation === token.generation && this.token.epoch === token.epoch &&
      this.token.revision === token.revision && token.epoch !== null;
    if (this.ended) { this.token = null; this.ended = false; }
    return allowed;
  }
}
