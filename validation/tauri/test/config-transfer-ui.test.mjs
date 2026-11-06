import test from 'node:test';
import assert from 'node:assert/strict';
import { buildImportChoices, previewIsCurrent, validExportPassword, exportIfCurrent } from '../src/config-transfer-ui.js';
const entries = [{ index: 0, conflicts: [{ id: 'a' }, { id: 'b' }] }, { index: 1, conflicts: [] }];
test('requires an explicit choice per entry and replaces every conflict', () => {
  assert.throws(() => buildImportChoices(entries, new Map([[0, 'replace']])));
  assert.deepEqual(buildImportChoices(entries, new Map([[0, 'replace'], [1, 'add']])), [
    { index: 0, action: 'replace', replaceIds: ['a', 'b'] }, { index: 1, action: 'add', replaceIds: [] }
  ]);
  assert.throws(() => buildImportChoices(entries, new Map([[0, 'keep'], [1, 'replace']])));
});
test('rejects replacing the same local record twice', () => {
  assert.throws(() => buildImportChoices([{ index: 0, conflicts: [{ id: 'a' }] }, { index: 1, conflicts: [{ id: 'a' }] }], new Map([[0, 'replace'], [1, 'replace']])));
});
test('a late picker or preview result cannot survive source change or leaving', () => {
  assert.equal(previewIsCurrent(4, 4), true);
  assert.equal(previewIsCurrent(4, 5), false);
});
test('export password counts Unicode scalars and UTF-8 bytes without trimming', () => {
  assert.equal(validExportPassword('😀'.repeat(12)), true);
  assert.equal(validExportPassword(' '.repeat(12)), true);
  assert.equal(validExportPassword('😀'.repeat(11)), false);
  assert.equal(validExportPassword('a'.repeat(1024)), true);
  assert.equal(validExportPassword('a'.repeat(1025)), false);
  assert.equal(validExportPassword('😀'.repeat(257)), false);
  assert.equal(validExportPassword('a'.repeat(12) + '\ud800'), false);
});
test('late export cannot open picker or start download after navigation', async () => {
  for (const departure of ['epoch', 'panel', 'background']) {
    let resolve; const encryption = new Promise(r => { resolve = r; });
    let epoch = 7, panelVisible = true, foreground = true, saves = 0;
    const pending = exportIfCurrent(() => encryption, () => epoch === 7 && panelVisible && foreground, () => { saves++; });
    if (departure === 'epoch') epoch++;
    if (departure === 'panel') panelVisible = false;
    if (departure === 'background') foreground = false;
    resolve([1, 2, 3]);
    assert.equal(await pending, false);
    assert.equal(saves, 0);
  }
  let saved;
  assert.equal(await exportIfCurrent(async () => [1, 2], () => true, bytes => { saved = bytes; }), true);
  assert.deepEqual(saved, [1, 2]);
});

// Exercise the real panel across asynchronous picker, preview and apply.
class FakeElement {
  constructor(tag, text='') { this.tagName=tag; this.textContent=text; this.children=[]; this.attrs={}; this.hidden=false; this.value=''; this.checked=false; this.disabled=false; }
  append(...nodes) { for(const node of nodes) {node.parent=this;this.children.push(node);} }
  replaceChildren(...nodes) { this.children=[];this.append(...nodes); }
  remove() { if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this); }
  setAttribute(name,value) {this.attrs[name]=value;}
  focus() {}
  descendants() {return this.children.flatMap(c=>[c,...c.descendants()]);}
  querySelectorAll(selector) {return this.descendants().filter(n=>selector==='input[type=password]' ? n.tagName==='input' && n.type==='password' : false);}
  querySelector(selector) {const nodes=this.descendants();if(selector==='[role=status]')return nodes.find(n=>n.attrs.role==='status');if(selector==='h2')return nodes.find(n=>n.tagName==='h2');if(selector==='.config-preview')return nodes.find(n=>n.className==='config-preview');if(selector==='.config-preview h3')return nodes.find(n=>n.className==='config-preview')?.descendants().find(n=>n.tagName==='h3');return undefined;}
}
async function runNetworkOnlyImport({applyFails=false, readFails=false}={}) {
  const {initConfigTransfer}=await import('../src/config-transfer-ui.js');
  const panel=new FakeElement('section'), opener=new FakeElement('button');panel.hidden=true;
  const previousDocument=globalThis.document, previousWindow=globalThis.window;
  globalThis.document={hidden:false,getElementById:id=>id==='config-transfer'?panel:opener,createElement:tag=>new FakeElement(tag),createTextNode:text=>new FakeElement('#text',text),addEventListener(){}};
  globalThis.window={addEventListener(){}};
  let profiles=[{id:'old',label:'已有网络',provider:'tailscale'}], reads=0, applies=0, applied=0;
  const invoke=async (name)=>{
    if(name==='config_document_platform')return 'macos';
    if(name==='network_list'){reads++;if(readFails && reads>1)throw Error('read_failed');return {profiles:[...profiles]};}
    if(name==='config_document_open')return [1,2,3];
    if(name==='config_preview')return {ticket:'single',activeHostId:null,plan:{entries:[],networks:[{network:{key:'n0',label:'新网络',provider:'tailscale',settings:{}},sameLabel:[]}],preferences:null}};
    if(name==='config_apply'){applies++;profiles.push({id:'new',label:'新网络',provider:'tailscale'});if(applyFails)throw Error('result_unknown');return {added:[],retired:[],removedIds:[]};}
    if(name==='config_discard')return;
    throw Error(name);
  };
  try {
    initConfigTransfer({native:true,invoke,getHosts:()=>[],refreshHosts:async()=>{},onApplied:async()=>{applied++;}});
    const button=label=>panel.descendants().find(n=>n.tagName==='button' && n.textContent===label);
    await opener.onclick();await button('选择加密文件').onclick();
    const passLabel=panel.descendants().find(n=>n.tagName==='label' && n.textContent==='导入口令');passLabel.children[0].value='fixture';
    await button('解密并预览').onclick();
    const selection=panel.descendants().find(n=>n.tagName==='#text' && n.textContent.includes('独立导入此网络')).parent.children[0];selection.checked=true;selection.onchange();
    await button('确认应用所选操作').onclick();
    return {texts:panel.descendants().map(n=>n.textContent),exportDisabled:button('加密并保存').disabled,reads,applies,applied};
  } finally {globalThis.document=previousDocument;globalThis.window=previousWindow;}
}
test('network-only import refreshes actual export choices and labels host counts', async()=>{
  const view=await runNetworkOnlyImport();
  assert.equal(view.applies,1);assert.equal(view.applied,1);assert.equal(view.reads,2);assert.equal(view.exportDisabled,false);
  assert.ok(view.texts.some(s=>s.includes('已有网络 · tailscale')));assert.ok(view.texts.some(s=>s.includes('新网络 · tailscale')));
  assert.ok(view.texts.some(s=>s.includes('主机新增 0')));
});
test('unknown save followed by failed catalog read discards old export options', async()=>{
  const view=await runNetworkOnlyImport({applyFails:true,readFails:true});
  assert.equal(view.applies,1);assert.equal(view.applied,0);assert.equal(view.reads,2);assert.equal(view.exportDisabled,true);
  assert.ok(!view.texts.some(s=>s.includes('已有网络 · tailscale')));
  assert.ok(view.texts.some(s=>s.includes('网络目录读取未确认')));assert.ok(view.texts.some(s=>s.includes('导入结果未确认')));
});
test('confirmed import with failed refresh blocks export without claiming stale options', async()=>{
  const view=await runNetworkOnlyImport({readFails:true});
  assert.equal(view.applies,1);assert.equal(view.applied,1);assert.equal(view.exportDisabled,true);
  assert.ok(!view.texts.some(s=>s.includes('已有网络 · tailscale')));assert.ok(view.texts.some(s=>s.includes('网络目录读取未确认')));
});
test('unknown save with successful refresh shows actual new catalog without replay', async()=>{
  const view=await runNetworkOnlyImport({applyFails:true});
  assert.equal(view.applies,1);assert.equal(view.applied,0);assert.equal(view.reads,2);assert.equal(view.exportDisabled,false);
  assert.ok(view.texts.some(s=>s.includes('新网络 · tailscale')));assert.ok(view.texts.some(s=>s.includes('导入结果未确认')));
});
