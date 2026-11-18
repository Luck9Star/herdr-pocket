import test from 'node:test';
import assert from 'node:assert/strict';
import {observeAndroidSshHeader, observeMobileViewport} from '../src/mobile-viewport.js';
import {readFileSync} from 'node:fs';

test('header and SSH target union native and CSS safe-area insets without adding them',()=>{
  const css=readFileSync(new URL('../src/style.css',import.meta.url),'utf8');
  const union='max(var(--hp-system-top-inset,0px),env(safe-area-inset-top,0px))';
  assert.ok(css.includes(`padding-top:calc(20px + ${union})`));
  assert.ok(css.includes(`padding-top:calc(16px + ${union})`));
  assert.ok(css.includes(`top:var(--hp-ssh-sticky-top,${union})`));
  assert.doesNotMatch(css,/var\(--hp-system-top-inset,0px\)\s*\+\s*env\(safe-area-inset-top/);
});

test('S10 keeps its top safe area when the header is hidden',()=>{
  const css=readFileSync(new URL('../src/style.css',import.meta.url),'utf8');
  assert.match(css, /#host-home:has\(#home-ssh:not\(\[hidden\]\) #ssh-key-change:not\(\[hidden\]\)\)\s*\{\s*padding-top:calc\(12px \+ max\(var\(--hp-system-top-inset,0px\),env\(safe-area-inset-top,0px\),var\(--hp-ios-status-bar-fallback,0px\)\)\)/);
});

test('the active ordinary SSH header uses the shared status bar inset on compact portrait iOS',()=>{
  const css=readFileSync(new URL('../src/style.css',import.meta.url),'utf8');
  const activeHeader='.ios-edge-to-edge:has(#host-home:not([hidden]) #home-ssh:not([hidden]) #ssh-live:not([hidden])) .app-header';
  const inset='max(var(--hp-system-top-inset,0px),env(safe-area-inset-top,0px),var(--hp-ios-status-bar-fallback))';
  assert.ok(css.includes(`@media (max-width:599px) and (orientation:portrait) {
  /* A native iOS WebView can extend behind the status bar with a zero CSS top inset. */
  .ios-edge-to-edge { --hp-ios-status-bar-fallback:64px; }
  ${activeHeader} {
    position:sticky; top:0; z-index:10; background:var(--hp-canvas);
    padding-top:calc(16px + ${inset});
  }
}`));
});

function fixture() {
  const callbacks=new Map(),props=new Map(),classes=new Set();
  const viewport={height:800,offsetTop:0,addEventListener:(name,fn)=>callbacks.set('v:'+name,fn),removeEventListener:name=>callbacks.delete('v:'+name)};
  const view={innerWidth:390,innerHeight:800,devicePixelRatio:2.75,visualViewport:viewport,addEventListener:(name,fn)=>callbacks.set('w:'+name,fn),removeEventListener:name=>callbacks.delete('w:'+name)};
  const root={style:{setProperty:(key,value)=>props.set(key,value),removeProperty:key=>props.delete(key)}};
  const body={classList:{toggle:(key,on)=>on?classes.add(key):classes.delete(key),remove:key=>classes.delete(key)}};
  return {viewport,view,root,body,callbacks,props,classes};
}
test('fixed controls follow visual keyboard inset and reset after close',()=>{
  const f=fixture(),stop=observeMobileViewport(f.view,f.root,f.body);
  assert.equal(f.props.get('--hp-visual-inset'),'0px');assert.equal(f.classes.has('keyboard-visible'),false);
  f.viewport.height=480;f.viewport.offsetTop=20;f.callbacks.get('v:resize')();
  assert.equal(f.props.get('--hp-visual-inset'),'300px');assert.equal(f.props.get('--hp-visual-height'),'480px');assert.equal(f.classes.has('keyboard-visible'),true);
  f.viewport.height=800;f.viewport.offsetTop=0;f.callbacks.get('v:scroll')();
  assert.equal(f.props.get('--hp-visual-inset'),'0px');assert.equal(f.classes.has('keyboard-visible'),false);
  stop();assert.equal(f.callbacks.size,0);assert.equal(f.props.size,0);
});
test('desktop viewport never treats a height change as a mobile keyboard',()=>{
  const f=fixture();f.view.innerWidth=900;f.viewport.height=400;
  observeMobileViewport(f.view,f.root,f.body);assert.equal(f.classes.has('keyboard-visible'),false);assert.equal(f.props.get('--hp-visual-inset'),'0px');
});
test('native top inset follows the newest measurement and is removed on teardown', async()=>{
  const f=fixture(), pending=[];
  const stop=observeMobileViewport(f.view,f.root,f.body,()=>new Promise(resolve=>pending.push(resolve)));
  await Promise.resolve();
  f.viewport.height=480; f.viewport.offsetTop=20;
  f.callbacks.get('v:scroll')(); await Promise.resolve();
  assert.equal(pending.length,1);
  assert.equal(f.props.get('--hp-visual-inset'),'300px');
  f.callbacks.get('w:resize')(); await Promise.resolve();
  pending[1]({overlapPx:77,density:2}); await new Promise(resolve=>setImmediate(resolve));
  pending[0]({overlapPx:33}); await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.props.get('--hp-system-top-inset'),'28px');
  f.callbacks.get('w:focus')(); await Promise.resolve();
  f.callbacks.get('v:resize')(); await Promise.resolve();
  f.callbacks.get('w:orientationchange')(); await Promise.resolve();
  assert.equal(pending.length,5);
  stop(); pending[2]({overlapPx:42}); pending[3]({overlapPx:42}); pending[4]({overlapPx:42}); await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.props.has('--hp-system-top-inset'),false);
});
test('Android overlap uses window bounds and WebView screen position',()=>{
  const source=readFileSync(new URL('../android/TerminalKeyboardPlugin.kt',import.meta.url),'utf8');
  assert.match(source, /currentWindowMetrics\.bounds\.top/);
  assert.match(source, /windowTop \+ top/);
  assert.match(source, /\(safeTop - location\[1\]\)\.coerceAtLeast\(0\)/);
  const overlap=(root,top,view)=>Math.max(0,root+top-view);
  assert.equal(overlap(100,28,100),28);
  assert.equal(overlap(100,28,128),0);
});
test('Android SSH header scroll tracking stops during review and outside the route',()=>{
  const f=fixture(), nodes={'host-home':{hidden:false},'home-ssh':{hidden:false},'ssh-key-change':{hidden:true}};
  const previous={ResizeObserver:globalThis.ResizeObserver,MutationObserver:globalThis.MutationObserver};
  let mutation, resizeCallback, writes=0;
  globalThis.ResizeObserver=class {constructor(fn){resizeCallback=fn;} observe(){} disconnect(){}};
  globalThis.MutationObserver=class {constructor(fn){mutation=fn;} observe(){} disconnect(){}};
  const original=f.root.style.setProperty;
  f.root.style.setProperty=(...args)=>{writes++;original(...args);};
  const doc={documentElement:f.root,querySelector:()=>({getBoundingClientRect:()=>({bottom:94})}),getElementById:id=>nodes[id]};
  try {
    const stop=observeAndroidSshHeader(f.view,doc);
    assert.equal(f.props.get('--hp-ssh-sticky-top'),'94px');
    const oldScroll=f.callbacks.get('w:scroll');
    nodes['ssh-key-change'].hidden=false; mutation();
    assert.equal(f.callbacks.has('w:scroll'),false);
    const count=writes; oldScroll(); resizeCallback(); assert.equal(writes,count);
    nodes['ssh-key-change'].hidden=true; mutation(); assert.equal(f.callbacks.has('w:scroll'),true);
    nodes['home-ssh'].hidden=true; mutation(); assert.equal(f.callbacks.has('w:scroll'),false);
    stop();
  } finally { Object.assign(globalThis,previous); }
});
