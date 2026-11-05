const encoder = new TextEncoder();
const arrows = {up:'A',down:'B',right:'C',left:'D'};
export function auxiliaryKey(name, applicationCursorMode) {
  if (Object.hasOwn(arrows,name)) return `\x1b${applicationCursorMode?'O':'['}${arrows[name]}`;
  return ({esc:'\x1b',tab:'\t','ctrl-c':'\x03',enter:'\r'})[name] ?? null;
}
export function draftBytes(text, bracketed) {
  if (typeof text!=='string' || !text || (bracketed && text.includes('\x1b[201~'))) return null;
  const payload=bracketed ? `\x1b[200~${text}\x1b[201~` : text;
  const bytes=encoder.encode(payload);
  return bytes.length<=4096 ? bytes : null;
}
/** Make terminal control and bidi-format characters visible in confirmation. */
export function displayDraft(text) {
  return Array.from(text, ch => {
    if (ch==='\n') return '⏎\n';
    if (ch==='\r') return '\\r';
    if (ch==='\t') return '\\t';
    if (/^[\p{Cc}\p{Cf}]$/u.test(ch)) return `\\u{${ch.codePointAt(0).toString(16)}}`;
    return ch;
  }).join('');
}
