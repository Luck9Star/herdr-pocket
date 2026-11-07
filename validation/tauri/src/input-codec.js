const encoder = new TextEncoder();
const arrows = {up:'A',down:'B',right:'C',left:'D'};
export function auxiliaryKey(name, applicationCursorMode, {ctrl=false,alt=false}={}) {
  const modifier=1+(ctrl?4:0)+(alt?2:0);
  const functionKey = /^f(?:[1-9]|1[0-2])$/.test(name) ? Number(name.slice(1)) : 0;
  if(functionKey >= 1 && functionKey <= 4) {
    const suffix='PQRS'[functionKey-1];
    return modifier>1 ? `\x1b[1;${modifier}${suffix}` : `\x1bO${suffix}`;
  }
  const extendedKeys={f5:15,f6:17,f7:18,f8:19,f9:20,f10:21,f11:23,f12:24,insert:2,delete:3};
  const extended=Object.hasOwn(extendedKeys,name) ? extendedKeys[name] : null;
  if(extended) return `\x1b[${extended}${modifier>1?`;${modifier}`:''}~`;
  if(name==='backspace' || name==='shift-tab') return modifier>1 ? null : name==='backspace' ? '\x7f' : '\x1b[Z';
  const cursor=arrows[name] ?? ({home:'H',end:'F'})[name];
  if(cursor) return modifier>1 ? `\x1b[1;${modifier}${cursor}` : `\x1b${applicationCursorMode?'O':'['}${cursor}`;
  const page=({pgup:5,pgdn:6})[name];
  if(page) return `\x1b[${page}${modifier>1?`;${modifier}`:''}~`;
  const shortcuts={'ctrl-c':'\x03','ctrl-d':'\x04','ctrl-z':'\x1a','ctrl-a':'\x01','ctrl-e':'\x05','ctrl-l':'\x0c','ctrl-r':'\x12','ctrl-u':'\x15','ctrl-w':'\x17'};
  if(Object.hasOwn(shortcuts,name))return shortcuts[name];
  let value=({esc:'\x1b',tab:'\t',enter:'\r',space:' '})[name] ?? (/^[a-z]$/.test(name)?name:null);
  if(value===null)return null;
  if(ctrl) {
    if(/^[a-z]$/.test(value))value=String.fromCharCode(value.toUpperCase().charCodeAt(0)-64);
    else if(name==='space')value='\x00';
    else return null; // No guessed Ctrl+Tab/Enter/Esc encoding.
  }
  return (alt?'\x1b':'')+value;
}
/** One-shot toolbar state, never applied to terminal/IME onData. */
export class AuxiliaryModifiers {
  ctrl=false; alt=false;
  get held(){return this.ctrl || this.alt;}
  reset(){this.ctrl=false;this.alt=false;}
  toggle(name,allowed) {
    if(!allowed){this.reset();return false;}
    if(name!=='ctrl' && name!=='alt')return false;
    this[name]=!this[name];return true;
  }
  take(name,applicationCursorMode,allowed) {
    const selected={ctrl:this.ctrl,alt:this.alt}; this.reset();
    return allowed?auxiliaryKey(name,applicationCursorMode,selected):null;
  }
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
