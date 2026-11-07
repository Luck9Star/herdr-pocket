import { draftBytes } from './input-codec.js';

export { displayDraft as previewPaste } from './input-codec.js';

/** Return the reviewed local edit. Byte framing is checked again before send. */
export function applyPaste(original, pasted, choice) {
  if (typeof original !== 'string' || typeof pasted !== 'string' || !pasted || pasted.length > 4096) return null;
  if (choice !== 'append' && choice !== 'replace') return null;
  if (choice === 'append' && original.length + pasted.length > 4096) return null;
  const result = choice === 'append' ? original + pasted : pasted;
  return draftBytes(result, false) ? result : null;
}
