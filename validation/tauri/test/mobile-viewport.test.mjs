import test from 'node:test';
import assert from 'node:assert/strict';
import {observeAndroidSshHeader, observeAndroidSshIme, observeMobileViewport} from '../src/mobile-viewport.js';
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

test('the compact SSH terminal and settings use the shared top inset and the visual viewport',()=>{
  const css=readFileSync(new URL('../src/direct-ssh-live.css',import.meta.url),'utf8');
  assert.ok(css.includes('#host-home { padding:var(--hp-connection-top) 0 0; }'));
  assert.ok(css.includes('top:var(--hp-connection-top)'));
  assert.ok(css.includes('height:calc(var(--hp-ssh-ime-height,var(--hp-visual-height,100dvh)) - var(--hp-connection-top) - var(--ssh-tabs-space))'));
  assert.ok(css.includes('--ssh-tabs-space:calc(56px + env(safe-area-inset-bottom,0px))'));
  assert.match(css,/body:is\(\.ssh-ime-visible,\.keyboard-visible:not\(\.ssh-ime-known\)\)[^{]*\{\s*--ssh-tabs-space:0px;[\s\S]*?\.route-tabs \{ display:none; \}/);
});

function fixture() {
  const callbacks=new Map(),props=new Map(),classes=new Set();
  const viewport={height:800,offsetTop:0,addEventListener:(name,fn)=>callbacks.set('v:'+name,fn),removeEventListener:name=>callbacks.delete('v:'+name)};
  const view={innerWidth:390,innerHeight:800,devicePixelRatio:2.75,visualViewport:viewport,addEventListener:(name,fn)=>callbacks.set('w:'+name,fn),removeEventListener:name=>callbacks.delete('w:'+name)};
  const root={style:{setProperty:(key,value)=>props.set(key,value),removeProperty:key=>props.delete(key)}};
  const body={classList:{toggle:(key,on)=>on?classes.add(key):classes.delete(key),remove:(...keys)=>keys.forEach(key=>classes.delete(key))}};
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
test('iOS entry stores scoped CSS points and distinguishes measured zero from unavailable', async () => {
  const f = fixture();
  f.view.devicePixelRatio = 3;
  const outcomes = [
    {connectionEntry:true, overlapPx:141},
    {connectionEntry:true, overlapPx:0},
    {connectionEntry:true},
  ];
  const stop = observeMobileViewport(f.view,f.root,f.body,()=>outcomes.shift());
  const settle = () => new Promise(resolve => setImmediate(resolve));
  await settle();
  assert.equal(f.props.get('--hp-connection-native-top'), '47px');
  assert.equal(f.props.has('--hp-system-top-inset'), false);
  f.callbacks.get('w:orientationchange')();
  await settle();
  assert.equal(f.props.get('--hp-connection-native-top'), '0px');
  f.callbacks.get('w:resize')();
  await settle();
  assert.equal(f.props.has('--hp-connection-native-top'), false);
  stop();
});

test('Android overlap uses window bounds and WebView screen position',()=>{
  const source=readFileSync(new URL('../android/TerminalKeyboardPlugin.kt',import.meta.url),'utf8');
  assert.match(source, /currentWindowMetrics\.bounds/);
  assert.match(source, /windowTop \+ top/);
  assert.match(source, /\(safeTop - location\[1\]\)\.coerceAtLeast\(0\)/);
  const overlap=(root,top,view)=>Math.max(0,root+top-view);
  assert.equal(overlap(100,28,100),28);
  assert.equal(overlap(100,28,128),0);
});
test('native Android SSH IME covers unchanged and already reduced viewports, then clears on Back and exit', async t=>{
  const f = fixture(), timers = new Map(), nodes = ['host-home', 'home-ssh', 'ssh-live'].map(()=>({hidden:false}));
  const ids = Object.fromEntries(['host-home', 'home-ssh', 'ssh-live'].map((id,index)=>[id,nodes[index]]));
  let mutation, now = 0, focused = true, nextTimer = 0, reads = 0;
  let next = {imeVisible:false};
  const old = globalThis.MutationObserver;
  globalThis.MutationObserver = class {constructor(fn) {mutation=fn;} observe() {} disconnect() {}};
  t.after(()=> {globalThis.MutationObserver=old;});
  const doc = {documentElement:f.root, body:f.body, hidden:false, hasFocus:()=>focused,
    getElementById:id=>ids[id], addEventListener:(name,fn)=>f.callbacks.set('d:'+name,fn),
    removeEventListener:name=>f.callbacks.delete('d:'+name)};
  Object.assign(f.view, {innerWidth:393,innerHeight:851,devicePixelRatio:2,performance:{now:()=>now},
    setTimeout:fn=>{timers.set(++nextTimer,fn);return nextTimer;},clearTimeout:id=>timers.delete(id)});
  Object.assign(f.viewport, {height:851,offsetTop:0,scale:1});
  const settle = async()=>{await Promise.resolve(); await Promise.resolve();};
  const tick = async(delta=160)=>{
    now+=delta; const [id,fn] = timers.entries().next().value;
    timers.delete(id); fn(); await settle();
  };
  const stop = observeAndroidSshIme(f.view,doc,()=>{reads++;return next;});
  t.after(stop);
  await settle();
  assert.equal(f.classes.has('ssh-ime-known'),true);
  assert.equal(f.classes.has('ssh-ime-visible'),false);
  assert.equal(reads,1);
  await tick(2200);
  assert.equal(timers.size,0,'idle closed terminal stops requesting Insets');
  const hit = {target:{closest:()=>true}};
  next = {imeVisible:true,viewHeightPx:1702,imeOverlapPx:600};
  f.callbacks.get('d:pointerdown')(hit);
  await settle();
  assert.equal(f.classes.has('ssh-ime-visible'),true);
  assert.equal(f.props.get('--hp-ssh-ime-height'),'551px');
  assert.equal(f.props.get('--hp-ssh-ime-inset'),'300px');
  f.viewport.height=551;
  f.callbacks.get('v:resize')();
  assert.equal(f.props.get('--hp-ssh-ime-inset'),'300px','already reduced VisualViewport is not subtracted twice');
  next = {imeVisible:true,viewHeightPx:1102,imeOverlapPx:0};
  f.view.innerHeight=551;
  await tick();
  assert.equal(f.props.get('--hp-ssh-ime-height'),'551px');
  assert.equal(f.props.get('--hp-ssh-ime-inset'),'0px','already resized layout needs no padding');
  next = {imeVisible:true,viewHeightPx:1102,imeOverlapPx:1102};
  await tick();
  assert.equal(f.props.get('--hp-ssh-ime-height'),'0px','a fully covered WebView has no visible height');
  next = {imeVisible:false};
  await tick();
  assert.equal(f.classes.has('ssh-ime-known'),true);
  assert.equal(f.classes.has('ssh-ime-visible'),false);
  assert.equal(f.props.has('--hp-ssh-ime-height'),false);
  assert.equal(f.props.has('--hp-ssh-ime-inset'),false);

  let resolveOld;
  next = new Promise(resolve=>{resolveOld=resolve;});
  await tick();
  nodes[2].hidden=true;
  mutation();
  assert.equal(timers.size,0);
  assert.equal(f.classes.has('ssh-ime-known'),false);
  next={imeVisible:false};
  nodes[2].hidden=false;
  mutation(); await settle();
  resolveOld({imeVisible:true,viewHeightPx:1702,imeOverlapPx:740});
  await settle();
  assert.equal(f.classes.has('ssh-ime-visible'),false,'late result from prior terminal cannot override current');
  focused=false;
  f.callbacks.get('w:blur')();
  assert.equal(timers.size,0);
  assert.equal(f.classes.has('ssh-ime-known'),false);
  assert.equal(f.props.has('--hp-ssh-ime-inset'),false);
});

test('late Android IME confirmation after the wake window still updates the page', async t=>{
  // R5 second-open shape: tap wakes sampling, insets report imeVisible:false for
  // longer than the 2s window, then the IME becomes visible with no further
  // viewport event on a fixed WebView. The page must still adopt the state.
  const f = fixture(), timers = new Map(), nodes = ['host-home', 'home-ssh', 'ssh-live'].map(()=>({hidden:false}));
  const ids = Object.fromEntries(['host-home', 'home-ssh', 'ssh-live'].map((id,index)=>[id,nodes[index]]));
  let mutation, now = 0, focused = true, nextTimer = 0;
  let next = {imeVisible:false};
  const old = globalThis.MutationObserver;
  globalThis.MutationObserver = class {constructor(fn) {mutation=fn;} observe() {} disconnect() {}};
  t.after(()=> {globalThis.MutationObserver=old;});
  const editor = {isConnected:true};
  const doc = {documentElement:f.root, body:f.body, hidden:false, hasFocus:()=>focused, activeElement:editor,
    getElementById:id=>ids[id], addEventListener:(name,fn)=>f.callbacks.set('d:'+name,fn),
    removeEventListener:name=>f.callbacks.delete('d:'+name)};
  Object.assign(f.view, {innerWidth:393,innerHeight:851,devicePixelRatio:2,performance:{now:()=>now},
    setTimeout:fn=>{timers.set(++nextTimer,fn);return nextTimer;},clearTimeout:id=>timers.delete(id)});
  Object.assign(f.viewport, {height:851,offsetTop:0,scale:1});
  const settle = async()=>{await Promise.resolve(); await Promise.resolve();};
  const tick = async(delta=160)=>{
    now+=delta; const [id,fn] = timers.entries().next().value;
    timers.delete(id); fn(); await settle();
  };
  const stop = observeAndroidSshIme(f.view,doc,()=>next,{getEditor:()=>editor});
  t.after(stop);
  await settle();
  const hit = {target:{closest:()=>true}};
  f.callbacks.get('d:pointerdown')(hit);
  // 2s window expires with IME still closed; editor keeps focus
  await tick(2000);
  assert.equal(f.classes.has('ssh-ime-visible'),false,'window expired with IME still closed');
  next = {imeVisible:true,viewHeightPx:1702,imeOverlapPx:600};
  // late IME confirmation arrives with no further viewport event
  await tick(600);
  assert.equal(f.classes.has('ssh-ime-visible'),true,'late IME confirmation adopted');
  assert.equal(f.props.get('--hp-ssh-ime-height'),'551px');
  assert.equal(f.props.get('--hp-ssh-ime-inset'),'300px');
  // focus leaving the editor stops the slow watch
  doc.activeElement = null;
  next = {imeVisible:false};
  await tick(600);
  assert.equal(f.classes.has('ssh-ime-visible'),false);
  assert.equal(timers.size,0,'watch ends when the editor loses focus');
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
