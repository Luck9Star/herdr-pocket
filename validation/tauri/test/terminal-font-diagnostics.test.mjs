import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createFontDiagnostics} from '../src/terminal-font-diagnostics.js';
const glyphs=JSON.parse(await readFile(new URL('../../shared/terminal-font-diagnostics-v1.json',import.meta.url),'utf8'));
const synthetic={schemaVersion:1,id:'theme-prompt-samples-v1',columns:40,rows:3,samples:[{id:'powerlevel10k',label:'合成 P10k',ansi:'p10k > ',cursorColumn:7,cursorRow:0},{id:'oh-my-posh',label:'合成 OMP',ansi:'omp > ',cursorColumn:6,cursorRow:0}]};
class Element {
 children=[];attrs={};dataset={};events={};isConnected=true;disabled=false;
 append(...items){this.children.push(...items);}replaceChildren(...items){this.children=[...items];}setAttribute(k,v){this.attrs[k]=v;}addEventListener(k,f){this.events[k]=f;}
 focus(){document.activeElement=this;}blur(){if(document.activeElement===this)document.activeElement=null;}showModal(){this.open=true;}close(){this.open=false;}remove(){this.removed=true;}
 all(){return this.children.flatMap(x=>[x,...x.all()]);}
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function setup({loadThemes=async()=>structuredClone(synthetic),delayWrite=false}={}){
 const prior=globalThis.document;globalThis.document={hidden:false,body:new Element(),createElement:()=>new Element()};const trigger=new Element(),terminals=[];let valid=true;
 const view=createFontDiagnostics({current:()=>valid,fontSize:14,theme:{foreground:'#fff'},returnFocus:trigger,loadFixture:async()=>glyphs,loadThemes,terminalFactory:options=>{const terminal={options,cols:options.cols,rows:options.rows,textarea:new Element(),writes:[],disposed:0,buffer:{active:{cursorX:7,cursorY:0}},parser:{registerOscHandler(){}},open(host){host.append(new Element());},write(text,done){this.writes.push(text);this.commit=done;if(!delayWrite)done();},dispose(){this.disposed++;}};terminals.push(terminal);return terminal;}});
 const all=()=>view.element.all(),choice=()=>all().find(e=>e.attrs['aria-label']==='诊断样例'),status=()=>all().find(e=>e.attrs.role==='status');
 return {view,trigger,terminals,choice,status,all,setCurrent:value=>valid=value,choose:kind=>{choice().focus();choice().value=kind;choice().onchange();},restore:()=>{view.close(false);globalThis.document=prior;}};
}
test('default grid stays 16×8 and switching uses independent readonly 40×3 with zero-based expected and actual cursor',async()=>{
 const h=setup();try{
  await flush();assert.equal(h.choice().value,'glyphs');const grid=h.terminals[0];assert.deepEqual([grid.options.cols,grid.options.rows],[16,8]);assert.deepEqual(grid.writes,[glyphs.write]);
  h.choose('powerlevel10k');await flush();assert.equal(grid.disposed,1);assert.equal(document.activeElement,h.choice());const prompt=h.terminals[1];assert.deepEqual([prompt.options.cols,prompt.options.rows],[40,3]);assert.equal(prompt.options.fontFamily,'ProbeNerd, monospace');assert.equal(prompt.options.disableStdin,true);assert.equal(prompt.textarea.disabled,true);assert.equal(prompt.textarea.attrs.tabindex,'-1');assert.equal(prompt.textarea.attrs.inputmode,'none');assert.equal(prompt.textarea.readOnly,true);assert.deepEqual(prompt.writes,[synthetic.samples[0].ansi]);
  assert.match(h.status().textContent,/实际光标：第 1 行、第 8 列；与预期一致/);assert.ok(h.all().some(e=>/预期光标：第 1 行、第 8 列/.test(e.textContent || '')));
  assert.equal(h.status().dataset.expectedCursorColumn,'7');assert.equal(h.status().dataset.actualCursorColumn,'7');assert.equal(h.status().dataset.expectedCursorRow,'0');assert.equal(h.status().dataset.sampleId,'powerlevel10k');assert.equal(h.status().dataset.columns,'40');assert.equal(h.status().dataset.rows,'3');
  h.choose('oh-my-posh');assert.equal(h.status().dataset.sampleId,undefined);assert.equal(h.status().dataset.columns,undefined);assert.equal(h.status().dataset.rows,undefined);await flush();assert.equal(h.status().dataset.sampleId,'oh-my-posh');assert.equal(prompt.disposed,1);assert.match(h.status().textContent,/与预期不同/);
  h.choose('glyphs');await flush();assert.deepEqual(h.terminals.at(-1).writes,[glyphs.write]);h.view.close();assert.equal(document.activeElement,h.trigger);assert.equal(h.terminals.at(-1).disposed,1);
 }finally{h.restore();}
});
test('a superseded theme read or render callback cannot replace the active sample or status',async()=>{
 const pending=[];const h=setup({loadThemes:()=>new Promise(resolve=>pending.push(resolve)),delayWrite:true});
 try {
  await flush();const grid=h.terminals[0];h.choose('powerlevel10k');h.choose('oh-my-posh');pending[1](synthetic);await flush();const current=h.terminals[1];current.buffer.active.cursorX=6;current.commit();const status=h.status().textContent,data={...h.status().dataset};
  pending[0](synthetic);await flush();grid.commit();assert.equal(h.terminals.length,2);assert.equal(h.status().textContent,status);assert.deepEqual(h.status().dataset,data);assert.equal(h.status().dataset.sampleId,'oh-my-posh');assert.deepEqual(current.writes,[synthetic.samples[1].ansi]);
  h.choose('powerlevel10k');assert.equal(h.status().dataset.sampleId,undefined);assert.equal(h.status().dataset.columns,undefined);h.view.close();pending[2](synthetic);current.commit();await flush();assert.equal(h.status().dataset.sampleId,undefined);assert.equal(h.status().dataset.columns,undefined);assert.equal(h.terminals.length,2);assert.equal(current.disposed,1);assert.equal(h.view.element.removed,true);
 }finally{h.restore();}
});
test('invalid theme data, failure and stale target never reach a diagnostic terminal',async()=>{
 let value={...synthetic,columns:41};const h=setup({loadThemes:async()=>{if(value instanceof Error)throw value;return value;}});
 try {await flush();h.choose('powerlevel10k');await flush();assert.equal(h.terminals.length,1);assert.match(h.status().textContent,/不可用/);value=Error('unavailable');h.choose('oh-my-posh');await flush();assert.equal(h.terminals.length,1);value=synthetic;h.setCurrent(false);h.choose('powerlevel10k');await flush();assert.equal(h.terminals.length,1);h.view.close();assert.notEqual(document.activeElement,h.trigger);}finally{h.restore();}
});

test('the Android theme capture expression reads production status after real xterm writes',async()=>{
 const prior=globalThis.document;globalThis.document={hidden:false,body:new Element(),createElement:()=>new Element()};let sample,view;
 try {
  const themes=JSON.parse(await readFile(new URL('../../shared/theme-prompt-samples-v1.json',import.meta.url),'utf8'));
  const capture=await readFile(new URL('../../remote-harness/theme-prompt-measurement.js',import.meta.url),'utf8');
  const {default:xterm}=await import('@xterm/xterm'),descriptor=Object.getOwnPropertyDescriptor(globalThis,'Buffer');let factory;
  try {Object.defineProperty(globalThis,'Buffer',{configurable:true,writable:true,value:undefined});factory=await import('../src/terminal-unicode.js');}
  finally {if(descriptor)Object.defineProperty(globalThis,'Buffer',descriptor);else delete globalThis.Buffer;}
  view=createFontDiagnostics({current:()=>true,fontSize:14,theme:{},loadFixture:async()=>glyphs,loadThemes:async()=>themes,terminalFactory:options=>{sample=factory.createUnicodeTerminal(xterm.Terminal,options);sample.open=()=>{};Object.defineProperty(sample,'textarea',{value:new Element()});sample.textarea.getAttribute=name=>sample.textarea.attrs[name];return sample;}});
  const all=()=>view.element.all(),choice=all().find(e=>e.attrs['aria-label']==='诊断样例'),status=all().find(e=>e.attrs.role==='status');
  view.element.querySelector=selector=>selector==='select[aria-label="诊断样例"]'?choice:selector==='[role=status]'?status:selector==='.xterm-helper-textarea'?sample.textarea:null;
  document.querySelector=selector=>selector==='.terminal-font-diagnostics[open]' && view.element.open?view.element:null;
  const measure=new Function(`return (${capture});`)();
  for(const theme of themes.samples){
   choice.value=theme.id;choice.onchange();
   assert.equal(measure(theme.id),null);
   for(let i=0;i<50 && status.dataset.sampleId!==theme.id;i++)await new Promise(resolve=>setTimeout(resolve,1));
   assert.deepEqual(measure(theme.id),{columns:40,rows:3,cursorColumn:theme.cursorColumn,cursorRow:theme.cursorRow});
   sample.textarea.disabled=false;
   assert.deepEqual(measure(theme.id),{columns:-1});
   sample.textarea.disabled=true;
  }
 }finally{view?.close(false);globalThis.document=prior;}
});
