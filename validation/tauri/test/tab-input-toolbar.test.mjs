import test from 'node:test';
import assert from 'node:assert/strict';
import { createTabInputToolbar } from '../src/tab-input-toolbar.js';

class Element {
  constructor(tag) { this.tagName=tag; this.children=[]; this.attrs={}; this.dataset={}; this.events={}; this.textContent=''; }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute(key,value) { this.attrs[key]=value; }
  addEventListener(name,handler) { this.events[name]=handler; }
  all() { return this.children.flatMap(node=>[node,...node.all()]); }
}
function fixture() {
  const previous=globalThis.document;
  globalThis.document={createElement:tag=>new Element(tag)};
  let permission=true, cursorMode=false;
  const sent=[];
  const toolbar=createTabInputToolbar({canSend:()=>permission,send:bytes=>sent.push([...bytes]),applicationCursorMode:()=>cursorMode});
  const button=text=>toolbar.element.all().find(node=>node.tagName==='button' && node.textContent===text);
  const press=text=>button(text).onclick();
  return {toolbar,button,press,sent,setPermission:value=>permission=value,setCursorMode:value=>cursorMode=value,restore(){globalThis.document=previous;}};
}

test('navigation keys follow reported cursor mode and preserve focus on touch',()=>{
  const f=fixture();try {
    let prevented=false;f.button('↑').events.pointerdown({preventDefault(){prevented=true;}});assert.equal(prevented,true);
    f.press('↑');f.setCursorMode(true);f.press('↑');f.press('Enter');f.press('PgDn');
    assert.deepEqual(f.sent,[[27,91,65],[27,79,65],[13],[27,91,54,126]]);
    assert.equal(f.button('↑').attrs['aria-label'],'向上');
  } finally {f.restore();}
});
test('modifiers are one-shot, can combine, cancel, and never alter plain IME data',()=>{
  const f=fixture();try {
    f.press('Ctrl');f.press('Alt');assert.equal(f.button('Ctrl').attrs['aria-pressed'],'true');
    f.press('C');assert.deepEqual(f.sent,[[27,3]]);assert.equal(f.button('Ctrl').attrs['aria-pressed'],'false');
    f.press('Ctrl');f.press('取消组合键');assert.equal(f.button('Ctrl').attrs['aria-pressed'],'false');assert.equal(f.sent.length,1);
    assert.equal(f.toolbar.element.all().some(node=>Object.keys(node.events).some(name=>name.startsWith('composition'))),false);
  } finally {f.restore();}
});
test('stale rendered permission cannot send or retain modifiers',()=>{
  const f=fixture();try {
    f.press('Ctrl');f.setPermission(false);f.press('C');assert.deepEqual(f.sent,[]);
    assert.equal(f.button('Ctrl').attrs['aria-pressed'],'false');assert.equal(f.button('C').disabled,true);
    f.setPermission(true);f.toolbar.refresh();f.press('Esc');assert.deepEqual(f.sent,[[27]]);
  } finally {f.restore();}
});
test('refresh and reset retain nodes while disabling, clearing and re-enabling controls',()=>{
  const f=fixture();try {
    const ctrl=f.button('Ctrl'),up=f.button('↑');f.press('Alt');f.toolbar.reset();assert.equal(f.button('Alt').attrs['aria-pressed'],'false');
    f.setPermission(false);f.toolbar.refresh();assert.equal(up.disabled,true);assert.equal(ctrl.disabled,true);
    f.setPermission(true);f.toolbar.refresh();assert.equal(f.button('Ctrl'),ctrl);assert.equal(f.button('↑'),up);assert.equal(up.disabled,false);
  } finally {f.restore();}
});
test('unsupported combination clears modifiers without sending',()=>{
  const f=fixture();try {f.press('Ctrl');f.press('Tab');assert.equal(f.sent.length,0);assert.equal(f.button('Ctrl').attrs['aria-pressed'],'false');}
  finally {f.restore();}
});

test('unknown cursor mode fails closed and releases a held modifier',()=>{
  const previous=globalThis.document;globalThis.document={createElement:tag=>new Element(tag)};
  try {
    const sent=[];const toolbar=createTabInputToolbar({canSend:()=>true,send:bytes=>sent.push(bytes),applicationCursorMode:()=>{throw Error('unknown');}});
    const button=text=>toolbar.element.all().find(node=>node.tagName==='button' && node.textContent===text);
    button('Ctrl').onclick();button('↑').onclick();assert.equal(sent.length,0);assert.equal(button('Ctrl').attrs['aria-pressed'],'false');
  } finally {globalThis.document=previous;}
});
