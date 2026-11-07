import test from 'node:test';
import assert from 'node:assert/strict';
import {visibleCellBounds,visibleTerminalText,createTerminalSelection} from '../src/terminal-selection.js';
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.value='';this.selectionStart=0;this.selectionEnd=0;}
  append(...items){this.children.push(...items);}
  setAttribute(){} focus(){} remove(){this.removed=true;}
}
const line=(chars,wrapped=false)=>({isWrapped:wrapped,length:chars.length,getCell:i=>({getChars:()=>chars[i],getWidth:()=>1}),translateToString:(_trim,_start,end)=>chars.slice(0,end).map(x=>x || ' ').join('')});
const bounds=(rows,cols)=>({startRow:0,endRow:rows,startCol:0,endCol:cols,visible:()=>true});
const term=lines=>({cols:6,rows:lines.length,buffer:{active:{viewportY:0,getLine:i=>lines[i]}}});
test('viewport snapshot keeps CJK, combining characters, emoji, meaningful spaces and soft wraps',()=>{
  assert.equal(visibleTerminalText(term([line(['中','e\u0301',' ','','','']),line(['😀',' ','','', '', ''],true),line(['x',' ','','', '', ''])]),bounds(3,6)), '中e\u0301 😀 \nx ');
});
test('selection requires explicit range, preserves it and reports clipboard failure',async()=>{
  const oldDoc=globalThis.document, oldNavigator=globalThis.navigator, oldStyle=globalThis.getComputedStyle;
  const body=new Element('body'),root={contains:()=>true},screen={parentElement:null,getBoundingClientRect:()=>({left:0,top:0,width:60,height:10})};root.querySelector=()=>screen;globalThis.document={body,querySelectorAll:()=>[],documentElement:{clientWidth:100,clientHeight:100},elementsFromPoint:()=>[root],createElement:t=>new Element(t)};globalThis.getComputedStyle=()=>({});
  let copied=[];Object.defineProperty(globalThis,'navigator',{configurable:true,value:{clipboard:{writeText:async x=>copied.push(x)}}});
  try {
    let current=true;const ui=createTerminalSelection({current:()=>current,terminal:{...term([line(['中','e\u0301','😀',' ','',''])]),element:root},label:'pane · term'});
    const field=ui.element.children[2], status=ui.element.children[3], copy=ui.element.children[4].children[0];
    await copy.onclick();assert.deepEqual(copied,[]);assert.match(status.textContent,/先/);
    field.selectionStart=1;field.selectionEnd=3;await copy.onclick();assert.deepEqual(copied,['e\u0301']);
    globalThis.navigator.clipboard.writeText=async()=>{throw Error('denied');};await copy.onclick();assert.match(status.textContent,/失败/);
    current=false;await copy.onclick();assert.equal(ui.element.removed,true);assert.equal(field.value,'');assert.deepEqual(copied,['e\u0301']);
  } finally {globalThis.document=oldDoc;globalThis.getComputedStyle=oldStyle;Object.defineProperty(globalThis,'navigator',{configurable:true,value:oldNavigator});}
});

test('snapshot rejects over 64 KiB rather than truncating',()=>{const l=line(['😀'.repeat(33000)]);assert.throws(()=>visibleTerminalText({...term([l]),cols:1},bounds(1,1)),/snapshot_too_large/);});

test('64 KiB counts interior gaps and explicit spaces but omits unwritten row padding', () => {
  const text = 'é'.repeat(32768);
  const snapshot = chars => visibleTerminalText({...term([line(chars)]), cols:chars.length}, bounds(1, chars.length));
  assert.equal(snapshot([text, '', '']), text);
  assert.equal(snapshot([text.slice(1), '', '!']), text.slice(1) + ' !');
  assert.throws(() => snapshot([text, '', '!']), /snapshot_too_large/);
  assert.throws(() => snapshot([text, ' ']), /snapshot_too_large/);
});


test('shared selection cases clip cells and preserve hard and soft wraps',async()=>{
  const {readFile}=await import('node:fs/promises');const fixture=JSON.parse(await readFile(new URL('../../shared/terminal-selection-v1.json',import.meta.url),'utf8'));
  const {default:pkg}=await import('@xterm/xterm');
  const {createUnicodeTerminal}=await import('../src/terminal-unicode.js');
  const t=createUnicodeTerminal(pkg.Terminal,{cols:fixture.columns,rows:fixture.rows});
  assert.equal(t.unicode.activeVersion,'15-graphemes');
  await new Promise(resolve=>t.write(fixture.write,resolve));
  assert.equal(t.buffer.active.getLine(2).getCell(0).getWidth(),2);
  assert.equal(t.buffer.active.getLine(2).getCell(2).getChars(),'!');
  for(const c of fixture.cases)assert.equal(visibleTerminalText(t,{startRow:c.top,endRow:c.bottom,startCol:c.left,endCol:c.right,visible:()=>true}),c.text,c.name);
});


test('layout clips to scroll ancestors and excludes occluded and half cells',()=>{
  const oldDoc=globalThis.document,oldStyle=globalThis.getComputedStyle;
  const root={contains:node=>node==='terminal'};
  const clip={parentElement:null,clientLeft:0,clientTop:0,clientWidth:35,clientHeight:20,getBoundingClientRect:()=>({left:15,top:0})};
  const screen={parentElement:clip,getBoundingClientRect:()=>({left:0,top:0,width:60,height:20})};root.querySelector=()=>screen;
  globalThis.document={querySelectorAll:()=>[],documentElement:{clientWidth:60,clientHeight:20},elementsFromPoint:(x,y)=>[x>=30&&x<40&&y<10?'overlay':'terminal']};globalThis.getComputedStyle=()=>({display:'block',visibility:'visible',overflowX:'hidden',overflowY:'hidden'});
  try {const b=visibleCellBounds({element:root,cols:6,rows:2});assert.deepEqual([b.startCol,b.endCol,b.startRow,b.endRow],[2,5,0,2]);assert.equal(b.visible(0,3),false);assert.equal(b.visible(1,3),true);}
  finally {globalThis.document=oldDoc;globalThis.getComputedStyle=oldStyle;}
});


test('real terminal groups emoji sequences without shifting common terminal cells',async()=>{
  const {default:pkg}=await import('@xterm/xterm');
  const {createUnicodeTerminal}=await import('../src/terminal-unicode.js');
  for(const [text,width] of [['👩‍💻',2],['👨‍👩‍👧‍👦',2],['🇨🇳',2],['❤️',2],['\ue0b0',1],['·',1],['e\u0301',1],['中',2]]) {
    const t=createUnicodeTerminal(pkg.Terminal,{cols:80,rows:24});
    await new Promise(resolve=>t.write(text+'!',resolve));
    const line=t.buffer.active.getLine(0);
    assert.equal(line.getCell(width).getChars(),'!',text);
    assert.equal(line.getCell(0).getChars(),text,text);
    assert.equal(line.getCell(0).getWidth(),width,text);
    t.dispose();
  }
});
