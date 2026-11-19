import test from 'node:test';
import assert from 'node:assert/strict';
import { buildImportChoices, reviewedImportLeases, previewIsCurrent, validExportPassword, exportIfCurrent, initConfigTransfer } from '../src/config-transfer-ui.js';
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

for (const [field, owners] of [
  ['activeHostIds', ['opaque-id-c','unrelated-native-owner']],
  ['activeHostId', 'opaque-id-c'],
]) test(`import preview lists only selected replacements and includes ${field} without a local tab`, async () => {
  const panel=new FakeElement('section'), opener=new FakeElement('button');
  const previousDocument=globalThis.document, previousWindow=globalThis.window;
  globalThis.document={hidden:false,getElementById:id=>id==='config-transfer'?panel:opener,createElement:tag=>new FakeElement(tag),createTextNode:text=>new FakeElement('#text',text),addEventListener(){}};
  globalThis.window={addEventListener(){}};
  const target={username:'fixture',host:'fixture.invalid',port:22,session:'demo'};
  const entry=(index, id)=>({index,host:{label:`导入主机 ${index+1}`,provider:'system',target},sameLabelIndices:[],conflicts:[{id,name:`本机主机 ${index+1}`,target}]});
  const impacts={
    'opaque-id-a': [
      {label:'标签 1 · 研发 · w1:p1',state:'观察已暂停',input:'输入已关闭。'},
      {label:'标签 3 · 研发 · w1:p2',state:'正在观察',input:'草稿输入已启用；仅在核对并确认后发送。'},
    ],
    'opaque-id-b': [{label:'标签 2 · 运维 · 选择终端',state:'未连接',input:'输入已关闭。'}],
  };
  const commands=[], stopped=[];
  let appliedChoices;
  async function invoke(name, args) {
    commands.push(name);
    if(name==='config_document_platform')return 'macos';
    if(name==='network_list')return {profiles:[]};
    if(name==='config_document_open')return [1,2,3];
    if(name==='config_preview')return {ticket:'single',[field]:owners,plan:{entries:[entry(0,'opaque-id-a'),entry(1,'opaque-id-b'),entry(2,'opaque-id-c')]}};
    if(name==='config_apply') {
      appliedChoices=args.choices;
      args.onRevoke.onmessage({hostIds:['opaque-id-b'],tabs:[],legacy:null});
      return {added:[],retired:[],removedIds:[]};
    }
    throw Error(name);
  }
  try {
    initConfigTransfer({native:true,invoke,getHosts:()=>[],refreshHosts:async()=>{},onApplied:async()=>{},
      getTabImpacts:ids=>ids.flatMap(id=>impacts[id] || []),onRevoked:event=>stopped.push(event.hostIds)});
    const button=label=>panel.descendants().find(n=>n.tagName==='button' && n.textContent===label);
    const choose=(index,value)=>panel.descendants().find(n=>n.name===`config-choice-${index}` && n.value===value).onchange();
    const impact=()=>panel.descendants().filter(n=>n.className==='config-affected').flatMap(n=>[n,...n.descendants()]).map(n=>n.textContent).join(' ');
    await opener.onclick();await button('选择加密文件').onclick();
    panel.descendants().find(n=>n.tagName==='input' && n.type==='password' && n.parent.textContent==='导入口令').value='synthetic-passphrase';
    await button('解密并预览').onclick();
    assert.doesNotMatch(panel.descendants().map(n=>n.textContent).join(' '),/opaque-id-|synthetic-passphrase|将关闭.*标签/);
    assert.doesNotMatch(impact(),/研发|运维|本机主机 3/);
    choose(0,'replace');choose(1,'add');
    assert.match(impact(),/旧标签.*保留.*最后画面.*手动关闭/);
    assert.match(impact(),/标签 1 · 研发 · w1:p1.*观察已暂停.*输入已关闭/);
    assert.match(impact(),/标签 3 · 研发 · w1:p2.*正在观察.*草稿输入已启用/);
    assert.doesNotMatch(impact(),/运维|本机主机 3/);
    choose(0,'keep');choose(1,'replace');
    assert.match(impact(),/标签 2 · 运维 · 选择终端.*未连接.*输入已关闭/);
    assert.doesNotMatch(impact(),/研发/);
    choose(1,'keep');choose(2,'replace');
    assert.match(impact(),/停止.*连接.*本机主机 3/);
    assert.doesNotMatch(impact(),/研发|运维|输入已启用|opaque-id-|unrelated-native-owner/);
    choose(2,'add');
    assert.doesNotMatch(impact(),/本机主机 3/);
    choose(2,'keep');choose(1,'replace');
    assert.deepEqual(stopped,[]);
    assert.equal(commands.includes('config_apply'),false);
    await button('确认应用所选操作').onclick();
    assert.equal(commands.filter(name=>name==='config_apply').length,1);
    assert.deepEqual(appliedChoices.map(choice=>choice.replaceIds),[[],['opaque-id-b'],[]]);
    assert.deepEqual(stopped,[['opaque-id-b']]);
  } finally {globalThis.document=previousDocument;globalThis.window=previousWindow;}
});

test('stale native rejection does not revoke any tab or newly created lease', async()=>{
  const panel=new FakeElement('section'),opener=new FakeElement('button');
  const oldDocument=globalThis.document,oldWindow=globalThis.window;
  globalThis.document={hidden:false,getElementById:id=>id==='config-transfer'?panel:opener,createElement:tag=>new FakeElement(tag),createTextNode:text=>new FakeElement('#text',text),addEventListener(){}};
  globalThis.window={addEventListener(){}};
  const stopped=[];const target={username:'u',host:'fixture.invalid',port:22,session:'s'};
  const invoke=async(name)=>{if(name==='config_document_platform')return 'macos';if(name==='network_list')return {profiles:[]};if(name==='config_document_open')return [1];if(name==='config_preview')return {ticket:'t',activeHostIds:['a'],plan:{entries:[{index:0,host:{label:'new',provider:'system',target},sameLabelIndices:[],conflicts:[{id:'a',name:'old',target}]}]}};if(name==='config_apply')throw 'transfer_active_changed';};
  try {
    initConfigTransfer({native:true,invoke,getHosts:()=>[],refreshHosts:async()=>{},onApplied:async()=>{},onRevoked:event=>stopped.push(event.hostIds)});
    const button=text=>panel.descendants().find(n=>n.tagName==='button' && n.textContent===text);
    await opener.onclick();await button('选择加密文件').onclick();panel.descendants().find(n=>n.type==='password' && n.parent.textContent==='导入口令').value='fixture';await button('解密并预览').onclick();
    panel.descendants().find(n=>n.name==='config-choice-0' && n.value==='replace').onchange();
    await button('确认应用所选操作').onclick();assert.deepEqual(stopped,[]);
  } finally {globalThis.document=oldDocument;globalThis.window=oldWindow;}
});

test('native revoke matches only reviewed exact active leases and selected hosts',()=>{
  const snapshot=[{hostId:'a',tabId:'one',clientGeneration:3,nativeGeneration:7},{hostId:'a',tabId:'unconnected',clientGeneration:0,nativeGeneration:null},{hostId:'b',tabId:'other',clientGeneration:5,nativeGeneration:8}];
  const event={hostIds:['a','b'],tabs:[['one',3,7,'a'],['other',5,99,'b']]};
  assert.deepEqual(reviewedImportLeases(event,snapshot,['a']),snapshot.slice(0,2));
  assert.deepEqual(reviewedImportLeases(event,snapshot,['b']),[]);
});

test('revocation is retained when storage fails after native confirmation', async()=>{
  const panel=new FakeElement('section'),opener=new FakeElement('button');
  const oldDocument=globalThis.document,oldWindow=globalThis.window;
  globalThis.document={hidden:false,getElementById:id=>id==='config-transfer'?panel:opener,createElement:tag=>new FakeElement(tag),createTextNode:text=>new FakeElement('#text',text),addEventListener(){}};
  globalThis.window={addEventListener(){}};
  const revoked=[];const target={username:'u',host:'fixture.invalid',port:22,session:'s'};
  const invoke=async(name,args)=>{if(name==='config_document_platform')return 'macos';if(name==='network_list')return {profiles:[]};if(name==='config_document_open')return [1];if(name==='config_preview')return {ticket:'t',activeHostIds:['a'],plan:{entries:[{index:0,host:{label:'new',provider:'system',target},sameLabelIndices:[],conflicts:[{id:'a',name:'old',target}]}]}};if(name==='config_apply'){args.onRevoke.onmessage({hostIds:['a'],tabs:[['old',2,9,'a']],legacy:null});throw 'host_storage_unavailable';}};
  try {
    initConfigTransfer({native:true,invoke,getHosts:()=>[],refreshHosts:async()=>{},onApplied:async()=>{},captureLeases:()=>[{tabId:'old',clientGeneration:2}],onRevoked:(event,snapshot)=>revoked.push({event,snapshot})});
    const button=text=>panel.descendants().find(n=>n.tagName==='button' && n.textContent===text);
    await opener.onclick();await button('选择加密文件').onclick();panel.descendants().find(n=>n.type==='password' && n.parent.textContent==='导入口令').value='fixture';await button('解密并预览').onclick();
    panel.descendants().find(n=>n.name==='config-choice-0' && n.value==='replace').onchange();await button('确认应用所选操作').onclick();
    assert.equal(revoked.length,1);assert.deepEqual(revoked[0].snapshot,[{tabId:'old',clientGeneration:2}]);assert.ok(panel.descendants().some(n=>n.textContent.includes('重新预览并审查')));
  } finally {globalThis.document=oldDocument;globalThis.window=oldWindow;}
});
