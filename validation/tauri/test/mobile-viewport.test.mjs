import test from 'node:test';
import assert from 'node:assert/strict';
import {observeMobileViewport} from '../src/mobile-viewport.js';

function fixture() {
  const callbacks=new Map(),props=new Map(),classes=new Set();
  const viewport={height:800,offsetTop:0,addEventListener:(name,fn)=>callbacks.set('v:'+name,fn),removeEventListener:name=>callbacks.delete('v:'+name)};
  const view={innerWidth:390,innerHeight:800,visualViewport:viewport,addEventListener:(name,fn)=>callbacks.set('w:'+name,fn),removeEventListener:name=>callbacks.delete('w:'+name)};
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
