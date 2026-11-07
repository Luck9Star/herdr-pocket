import test from 'node:test';
import assert from 'node:assert/strict';
import {validThemePromptSamples,loadThemePromptSamples} from '../src/theme-prompt-samples.js';
const synthetic=()=>({schemaVersion:1,id:'theme-prompt-samples-v1',columns:40,rows:3,samples:[{id:'powerlevel10k',label:'合成验证 P10k',ansi:'\x1b[31m\ue0b0 中 é\x1b[m\r\n> ',cursorColumn:2,cursorRow:1},{id:'oh-my-posh',label:'合成验证 OMP',ansi:'\x1b[;1m❯\x1b[0m ',cursorColumn:2,cursorRow:0}]});
test('bounded theme schema permits printable PUA, combining text, SGR and paired CRLF',()=>{assert.equal(validThemePromptSamples(synthetic()),true);});
for(const [name,change] of [
 ['schema version',v=>v.schemaVersion=2],['extra top field',v=>v.remote='unused'],['missing field',v=>delete v.rows],['wrong columns',v=>v.columns=41],['wrong rows',v=>v.rows=4],['missing sample',v=>v.samples.pop()],['duplicate id',v=>v.samples[1].id='powerlevel10k'],['unknown id',v=>v.samples[0].id='other'],['extra sample field',v=>v.samples[0].command='never'],['long label',v=>v.samples[0].label='中'.repeat(54)],['empty label',v=>v.samples[0].label=' '],['surrogate label',v=>v.samples[0].label='\ud800'],['negative column',v=>v.samples[0].cursorColumn=-1],['column at edge',v=>v.samples[0].cursorColumn=40],['fraction row',v=>v.samples[0].cursorRow=0.5],['row at edge',v=>v.samples[0].cursorRow=3],['oversized ANSI',v=>v.samples[0].ansi='中'.repeat(1366)],
 ...['\x1b]52;c;Zm9v\x07','\x1b]8;;https://fixture.invalid\x1b\\','\x1b[2J','\x1b[1;1H','\x1b[?2004h','\x1bPdata\x1b\\','\x1b[38:2:1:2:3m','\x00','\t','\x7f','\x85','\u202e','\u2066','\u200f','\ud800','\udfff','\n','\r','\r\x1b[0m\n','x\r\x1b[31m\ny','x\r\ny\r\nz\r\nw'].map((text,i)=>['rejected sequence '+i,v=>v.samples[0].ansi=text]),
])test(`theme schema rejects ${name}`,()=>{const value=synthetic();change(value);assert.equal(validThemePromptSamples(value),false);});

test('local loader bounds raw JSON, rejects unknown fields and never returns malformed content',async()=>{
 const prior=globalThis.fetch,seen=[];
 try {
  globalThis.fetch=async url=>{seen.push(url);return {ok:true,text:async()=>JSON.stringify(synthetic())};};assert.equal(validThemePromptSamples(await loadThemePromptSamples()),true);assert.deepEqual(seen,['/shared/theme-prompt-samples-v1.json']);
  for(const text of [' '.repeat(16385),'{bad',JSON.stringify({...synthetic(),extra:true})]){globalThis.fetch=async()=>({ok:true,text:async()=>text});await assert.rejects(loadThemePromptSamples());}
  globalThis.fetch=async()=>({ok:false});await assert.rejects(loadThemePromptSamples());
 } finally {globalThis.fetch=prior;}
});

test('real theme fixtures match the normal xterm Unicode addon and declared zero-based cursors',async()=>{
 const {readFile}=await import('node:fs/promises');
 const fixture=JSON.parse(await readFile(new URL('../../shared/theme-prompt-samples-v1.json',import.meta.url),'utf8'));assert.equal(validThemePromptSamples(fixture),true);
 const {default:xterm}=await import('@xterm/xterm');
 const descriptor=Object.getOwnPropertyDescriptor(globalThis,'Buffer');let factory;
 try {Object.defineProperty(globalThis,'Buffer',{configurable:true,writable:true,value:undefined});factory=await import('../src/terminal-unicode.js');}
 finally {if(descriptor)Object.defineProperty(globalThis,'Buffer',descriptor);else delete globalThis.Buffer;}
 for(const sample of fixture.samples){
  const terminal=factory.createUnicodeTerminal(xterm.Terminal,{cols:40,rows:3,scrollback:0,disableStdin:true});
  try {
   assert.equal(terminal.unicode.activeVersion,'15-graphemes');await new Promise(resolve=>terminal.write(sample.ansi,resolve));const buffer=terminal.buffer.active;
   assert.equal(buffer.cursorX,sample.cursorColumn,sample.id);assert.equal(buffer.cursorY,sample.cursorRow,sample.id);assert.equal(buffer.length,3);
   const line=buffer.getLine(0),plain=line.translateToString(true);assert.match(plain,/ 中文/);assert.match(plain,//);assert.match(plain,/❯/);assert.ok(!plain.includes('\x1b'));
   let wide=false,color=false;for(let i=0;i<40;i++){const cell=line.getCell(i);if(cell.getChars()==='中')wide=cell.getWidth()===2;if(!cell.isFgDefault() || !cell.isBgDefault())color=true;}assert.equal(wide,true,sample.id);assert.equal(color,true,sample.id);
  } finally {terminal.dispose();}
 }
});
