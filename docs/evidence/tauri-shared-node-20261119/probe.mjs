import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {resolve,sep} from 'node:path';
import {pathToFileURL} from 'node:url';

const [workspace,variant,engine='chromium',layout='narrow']=process.argv.slice(2);
assert.ok(workspace,'usage: node probe.mjs WORKSPACE main|pr13 [chromium|webkit] [narrow|wide]');
const workspaceURL=pathToFileURL(resolve(workspace)+sep);
const playwright=process.env.HERDR_M2_PLAYWRIGHT_MODULE;
const {chromium,webkit}=await import(playwright?pathToFileURL(resolve(playwright)).href:'playwright-core');
assert.match(layout,/^(narrow|wide)$/);
const wide=layout==='wide';
assert.match(variant,/^(main|pr13)$/);
assert.match(engine,/^(webkit|chromium)$/);
const sourceSHA=(await readFile(new URL('./'+variant+'/SOURCE_COMMIT',workspaceURL),'utf8')).trim();
const expectedSource={
  main:'0c3ef4817234f8519c4d9f8559cd0bd188ee89d5',
  pr13:'a1fe2517f56e15b7d169b34163d250e4759aee81',
};
assert.equal(sourceSHA,expectedSource[variant],'wrong source for variant');
const site=new URL('./'+variant+'/validation/tauri/dist/',workspaceURL);
const dir=new URL('./'+variant+'/'+engine+'-'+layout+'/',workspaceURL);
await mkdir(dir,{recursive:true});
const server=createServer(async(req,res)=>{
  try {
    const requested=new URL(req.url,'http://127.0.0.1').pathname.slice(1);
    const file=new URL(requested||'index.html',site);
    if(!file.href.startsWith(site.href))throw Error('outside fixture');
    const ext=file.pathname.split('.').at(-1);
    res.setHeader('content-type',({html:'text/html',js:'text/javascript',css:'text/css',json:'application/json',ttf:'font/ttf'})[ext]||'application/octet-stream');
    res.end(await readFile(file));
  } catch {res.statusCode=404;res.end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const profile={id:'c'.repeat(32),label:'QA Shared Guest',provider:'easytier',enabled:true,revision:7,settings:{networkName:'guest-fixture',peers:[]}};
const hosts=['A','B'].map((label,i)=>({id:['a','b'][i].repeat(32),name:'fixture-'+label,provider:'easytier',
  networkProfileId:profile.id,revision:1,enabled:true,deviceFingerprint:'SHA256:'+['C','D'][i].repeat(43),
  pairingStatus:'authorized',hostFingerprint:'SHA256:'+['E','F'][i].repeat(43),
  target:{username:'fixture',host:'203.0.113.'+(17+i),port:22,session:'fixture-'+label}}));
function installBridge({hosts,profile}) {
  const callbacks=new Map(), bindings=new Map();
  let callbackId=0,nextGeneration=0,nextConnection=0,nextInputEpoch=40;
  const nodeBinding={profileId:profile.id,profileRevision:profile.revision,networkName:profile.settings.networkName,identityRef:'fixture-node-identity'};
  const node={id:'guest-fixture-1',state:'engine-started',stops:0};
  const ledger=window.__ledger={calls:[],auth:[],closure:[],frames:[],inputs:[],errors:[],node};
  const targetFor=host=>{const suffix=host.name.at(-1);return {paneId:suffix==='A'?'w1:p1':'w1:p2',
    terminalId:suffix==='A'?'term_a001':'term_b002',agent:suffix,agentStatus:'idle',title:'fixture observation'};};
  const verify=(value,label)=>{if(!value){ledger.errors.push(label);throw Error(label);}};
  const send=(tab,event)=>callbacks.get(tab.channel)({index:tab.index++,message:{generation:tab.generation,...event}});
  const setPhase=(tab,phase)=>{tab.phase=phase;send(tab,{kind:'observation',snapshot:{epoch:tab.epoch,phase}});};
  const newFull=async(tab,marker)=>{
    const bytes=Array.from(new TextEncoder().encode(marker+'\r\n$ '));
    const seq=++tab.seq;
    const frameAck=new Promise(resolve=>{tab.frameAck={seq,resolve};});
    send(tab,{kind:'target_bound',epoch:tab.epoch,pane_id:tab.target.paneId,terminal_id:tab.target.terminalId});
    ledger.frames.push({host:tab.host.name,connection:tab.connection,generation:tab.generation,epoch:tab.epoch,seq,marker});
    send(tab,{kind:'frame',epoch:tab.epoch,frame:{seq,full:true,cols:tab.canvas.cols,rows:tab.canvas.rows,bytes}});
    await frameAck;
    setPhase(tab,'active');
    send(tab,{kind:'input_ready',epoch:tab.epoch,unknown:false,recovery_status:'ready'});
  };
  window.__emitOriginalBDelta=()=>{
    const tab=Array.from(bindings.values()).find(entry=>entry.host.name==='fixture-B');
    verify(tab&&tab.connection&&tab.phase==='active','cannot emit delta from closed or inactive B');
    const marker='fixture-B-after-close-delta';
    const bytes=Array.from(new TextEncoder().encode('\r\n'+marker+'\r\n'));
    const seq=++tab.seq;
    const frameAck=new Promise(resolve=>{tab.frameAck={seq,resolve};});
    ledger.frames.push({host:tab.host.name,connection:tab.connection,generation:tab.generation,epoch:tab.epoch,seq,marker,full:false});
    send(tab,{kind:'frame',epoch:tab.epoch,frame:{seq,full:false,cols:tab.canvas.cols,rows:tab.canvas.rows,bytes}});
    return frameAck;
  };
  window.isTauri=true;
  window.__TAURI_INTERNALS__={
    transformCallback(fn){callbacks.set(++callbackId,fn);return callbackId;},
    unregisterCallback(id){callbacks.delete(id);},
    async invoke(cmd,args={}){
      const {tabId,hostId,generation,clientGeneration,action,epoch,seq}=args;
      const tab=bindings.get(tabId);
      if(cmd.startsWith('remote_tab_')||cmd.startsWith('network_node_')){
        ledger.calls.push({cmd,host:tab?.host.name??hosts.find(x=>x.id===hostId)?.name??null,
          tabId,action,generation,clientGeneration,epoch,mode:args.mode});
      }
      if(tab&&cmd.startsWith('remote_tab_')&&cmd!=='remote_tab_reserve'){
        verify(tab.generation===generation&&tab.clientGeneration===clientGeneration,'native generation changed');
      }
      switch(cmd){
        case 'config_document_platform': return 'android';
        case 'host_list': return hosts;
        case 'network_list': return {revision:'fixture-catalog-1',profiles:[profile],
          bindings:hosts.map(host=>({hostId:host.id,profileId:profile.id})),preferences:{terminalFontSize:14}};
        case 'network_identity_status': return {supported:true,available:true,present:true,mode:'PRIVATE',handle:nodeBinding.identityRef};
        case 'network_node_status': return {state:node.state,binding:node.state==='stopped'?null:nodeBinding};
        case 'network_node_stop':
          verify(args.id===profile.id && args.expectedRevision===profile.revision &&
            args.expectedCatalog==='fixture-catalog-1' &&
            JSON.stringify(args.affected.slice().sort())===JSON.stringify(hosts.map(host=>host.id).sort()) &&
            JSON.stringify(args.binding)===JSON.stringify(nodeBinding),'explicit stop requires the exact shared binding');
          verify(node.state==='engine-started'&&Array.from(bindings.values()).every(entry=>!entry.connection),'node stop fixture expected after session release');
          node.stops++;node.state='stopped';return {};
        case 'remote_tab_reserve': {
          const host=hosts.find(x=>x.id===hostId);
          verify(host&&args.expectedDeviceFingerprint===host.deviceFingerprint &&
            JSON.stringify(args.expectedTarget)===JSON.stringify(host.target)&&args.expectedNetworkProfileId===profile.id&&
            args.expectedNetworkRevision===profile.revision,'tab reserve requires the exact reviewed host and shared profile');
          const generation=++nextGeneration;
          bindings.set(tabId,{host,target:targetFor(host),generation,clientGeneration,epoch:1,seq:0,index:0,
            phase:'reserved',connection:null,inputEpoch:null});
          return generation;
        }
        case 'remote_tab_visible': verify(tab&&node.state==='engine-started','visible stale');return {};
        case 'remote_tab_observe':
          verify(tab&&!tab.connection&&node.state==='engine-started','bad observe ownership');
          tab.connection=++nextConnection;
          tab.channel=args.onEvent.id;tab.canvas=args.canvas;
          ledger.auth.push({host:tab.host.name,connection:tab.connection,generation:tab.generation,
            clientGeneration:tab.clientGeneration,profile:profile.id,profileRevision:profile.revision,node:node.id});
          setTimeout(()=>{
            setPhase(tab,'starting');
            send(tab,{kind:'dashboard_watch',update:{epoch:tab.epoch,revision:1,phase:'fresh',reason:'isolated fixture',panes:[tab.target]}});
            send(tab,{kind:'selection_ready',epoch:tab.epoch});
          },25);
          return new Promise(resolve=>{tab.finish=resolve;});
        case 'remote_tab_select':
          verify(tab&&tab.connection&&args.paneId===tab.target.paneId&&args.terminalId===tab.target.terminalId,'wrong pane');
          void newFull(tab,tab.host.name+'-initial');return {};
        case 'remote_tab_ack':
          verify(tab&&tab.connection&&tab.epoch===epoch&&tab.frameAck?.seq===seq,'stale frame ACK');
          tab.frameAck.resolve();return {};
        case 'remote_tab_control':
          verify(tab&&tab.connection,'closed session control');
          tab.epoch++;tab.inputEpoch=null;tab.seq=0;
          if(action==='pause'){
            verify(tab.phase==='active','wrong pause phase');setPhase(tab,'pausing');setPhase(tab,'paused');
          } else if(action==='resume'){
            verify(tab.phase==='paused','wrong resume phase');setPhase(tab,'resuming');await newFull(tab,tab.host.name+'-same-session-new-frame');
          } else verify(false,'unknown control');
          return {};
        case 'remote_tab_input_mode':
          verify(tab&&tab.connection&&tab.phase==='active'&&tab.epoch===epoch,'mode stale');
          tab.inputEpoch=++nextInputEpoch;return tab.inputEpoch;
        case 'remote_tab_input_send': {
          verify(tab&&tab.connection&&tab.phase==='active'&&tab.epoch===epoch&&tab.inputEpoch===args.inputEpoch,'input was not authorized on this session');
          const marker=new TextDecoder().decode(Uint8Array.from(args.bytes));
          verify(tab.host.name==='fixture-B'&&marker==='B-after-A'&&args.draft===true,'unexpected target or draft bytes');
          ledger.inputs.push({host:tab.host.name,connection:tab.connection,generation:tab.generation,epoch:tab.epoch,inputEpoch:args.inputEpoch,marker});
          return {status:'accepted',receipt:{requestId:'a'.repeat(32),paneId:tab.target.paneId,terminalId:tab.target.terminalId,acceptedBytes:args.bytes.length}};
        }
        case 'remote_tab_cancel':
          if(tab?.connection){
            ledger.closure.push({host:tab.host.name,connection:tab.connection,generation:tab.generation,nodeState:node.state});
            tab.connection=null;tab.finish();
          }
          return {};
        default: return {};
      }
    },
  };
}
const executablePath=process.env.HERDR_M2_BROWSER_EXECUTABLE;
const browser=await (engine==='webkit'?webkit:chromium).launch(executablePath?{executablePath}:{});
const context=await browser.newContext({viewport:{width:wide?1440:390,height:wide?1200:851},deviceScaleFactor:1,isMobile:!wide,hasTouch:true});
const page=await context.newPage();
page.setDefaultTimeout(4500);
await page.addInitScript(installBridge,{hosts,profile});
const result={sourceSHA,variant,engine,layout,browser:browser.version(),scope:'Production Tauri page, real browser UI, isolated simulated IPC, no real SSH or overlay.',proof:{}};
const proof=result.proof;
const calls=()=>page.evaluate(()=>window.__ledger);
const ws=page.locator('#view-content');
const btn=name=>ws.getByRole('button',{name,exact:true});
const phase=()=>ws.locator('.tab-connection-actions').getAttribute('data-state');
const readWorkspace=async()=>page.evaluate(()=>({tabs:[...document.querySelectorAll('#view-tabs button')].map(tab=>({
  label:tab.textContent,active:tab.getAttribute('aria-pressed')==='true'})),
  children:document.querySelector('#view-content').childElementCount,
  phase:document.querySelector('#view-content .tab-connection-actions')?.dataset.state??null,
  title:document.querySelector('#view-content > p')?.textContent??null}));
const snapshot=async name=>{
  const image=await page.screenshot({path:new URL(name+'.png',dir).pathname});
  return {name,sha256:createHash('sha256').update(image).digest('hex')};
};
const waitPhase=state=>page.waitForFunction(state=>document.querySelector('#view-content .tab-connection-actions')?.dataset.state===state,state);
const tabBtn=host=>page.locator('#view-tabs button').filter({hasText:host});
const showBoard=()=>page.locator('#host-return-home').tap();
const assertOne=async locator=>{await locator.first().waitFor({state:'visible'});assert.equal(await locator.count(),1);};
const openHost=async(index,pane)=>{
  const card=page.locator('#host-list .saved-host-card').filter({hasText:hosts[index].name});
  await assertOne(card);await card.locator('summary').tap();
  await card.getByRole('button',{name:'新终端标签',exact:true}).tap();
  await ws.locator('input[type=checkbox]').check();
  await btn('连接').tap();
  const target=ws.locator('[data-pane-id="'+pane+'"]');
  await assertOne(target);await target.tap();
  await waitPhase('active');
  await page.waitForFunction(marker=>document.querySelector('#view-content .xterm-rows')?.textContent.includes(marker),hosts[index].name+'-initial');
};
try {
  await page.goto('http://127.0.0.1:'+server.address().port+'/');
  await openHost(1,'w1:p2');
  await showBoard();
  await page.waitForFunction(()=>window.__ledger.calls.some(o=>o.host==='fixture-B'&&o.action==='pause'));
  await openHost(0,'w1:p1');
  proof.opened=await readWorkspace();
  let separateStart=0;
  if(wide) {
    await page.locator('#workbench-split').tap();
    await page.waitForFunction(()=>Array.from(document.querySelectorAll('#view-content .tab-connection-actions')).map(e=>e.dataset.state).join(',')==='active,active');
    await ws.locator('.term-scroll').last().scrollIntoViewIfNeeded();
    await page.waitForFunction(()=>Array.from(document.querySelectorAll('#view-content .xterm-rows')).some(
      rows=>rows.textContent.includes('fixture-B-same-session-new-frame')));
    const panels=await page.locator('#view-content > section[data-role=workbench-panel]').evaluateAll(items=>items.map(panel=>{
      const r=panel.getBoundingClientRect();
      return {title:panel.querySelector(':scope > p')?.textContent, focused:panel.dataset.focus,
        x:r.x,y:r.y,width:r.width,height:r.height,frames:panel.querySelector('.xterm-rows')?.textContent};
    }));
    assert.equal(panels.length,2);
    assert.match(panels[0].title,/fixture-A/);assert.equal(panels[0].focused,'true');
    assert.match(panels[1].title,/fixture-B/);assert.equal(panels[1].focused,'false');
    assert.ok(panels.every(p=>p.width>0&&p.height>0));
    assert.match(panels[1].frames,/fixture-B-same-session-new-frame/);
    proof.splitBeforeClose=panels.map(({frames,...panel})=>({...panel,frameVisible:!!frames}));
    separateStart=(await calls()).calls.length;
  } else {
    await showBoard();
    await page.waitForFunction(()=>window.__ledger.calls.some(o=>o.host==='fixture-A'&&o.action==='pause'));
    proof.afterPausingA=await calls();
    assert.equal(proof.afterPausingA.auth.length,2);
    assert.equal(proof.afterPausingA.closure.length,0);
    assert.equal(proof.afterPausingA.node.stops,0);
    await page.locator('#nav-terminal').tap();
    await waitPhase('paused');
    assert.match((await readWorkspace()).title,/fixture-A/);
  }
  if(wide)await ws.locator('[data-focus=true]').getByRole('button',{name:'关闭此标签',exact:true}).tap();
  else await btn('关闭此标签').tap();
  await tabBtn('fixture-A').waitFor({state:'detached'});
  proof.afterClosingA=await readWorkspace();
  proof.closeImage=await snapshot('after-closing-A');
  const closed=await calls();
  assert.deepEqual(closed.closure.map(x=>x.host),['fixture-A']);
  assert.equal(closed.node.stops,0);
  assert.equal(closed.auth.length,2);
  assert.equal(closed.inputs.length,0);
  proof.remainingPanelVisible=proof.afterClosingA.children>0&&proof.afterClosingA.title?.includes('fixture-B')&&
    proof.afterClosingA.tabs.length===1&&proof.afterClosingA.tabs[0].active;
  const oldB=closed.auth.find(x=>x.host==='fixture-B');
  if(wide) {
    assert.equal(proof.remainingPanelVisible,true,'the already visible B remains mounted after active A closes');
    assert.equal(proof.afterClosingA.phase,'active','B remains in active read-only observation');
    assert.deepEqual(closed.calls.slice(separateStart).filter(o=>o.host==='fixture-B'),[]);
    await ws.locator('.term-scroll').scrollIntoViewIfNeeded();
    await page.evaluate(()=>Promise.race([
      window.__emitOriginalBDelta(),new Promise((_,rej)=>setTimeout(()=>rej(Error('B delta not rendered')),3200))
    ]));
    await page.waitForFunction(()=>document.querySelector('#view-content .xterm-rows')?.textContent.includes('fixture-B-after-close-delta'));
    const current=await calls();
    assert.deepEqual(current.calls.slice(separateStart).filter(o=>o.host==='fixture-B').map(o=>o.cmd),['remote_tab_ack']);
    const bFrames=current.frames.filter(x=>x.host==='fixture-B');
    assert.equal(bFrames.at(-1).full,false);
    assert.equal(bFrames.at(-1).epoch,bFrames.at(-2).epoch);
    assert.ok(bFrames.at(-1).seq>bFrames.at(-2).seq);
    assert.ok(bFrames.every(f=>f.connection===oldB.connection));
  } else {
    assert.equal(Boolean(proof.remainingPanelVisible),false,'a hidden B is not automatically selected');
    await tabBtn('fixture-B').tap();
    await waitPhase('paused');
    proof.beforeExplicitResume=await readWorkspace();
    assert.equal(await ws.locator('.xterm-rows').count(),1);
    assert.ok((await ws.locator('.xterm-rows').textContent()).includes('fixture-B-initial'));
    assert.equal((await calls()).frames.filter(x=>x.host==='fixture-B').length,1);
    await btn('恢复观察').tap();
    await waitPhase('active');
    await page.waitForFunction(()=>document.querySelector('#view-content .xterm-rows')?.textContent.includes('fixture-B-same-session-new-frame'));
  }
  await ws.locator('.terminal-host').scrollIntoViewIfNeeded();
  proof.newFrameImage=await snapshot('B-new-frame');
  await btn('启用草稿输入').waitFor();
  assert.equal(await ws.locator('.tab-mobile-controls').getAttribute('data-mode'),'observe');
  assert.notEqual(await ws.locator('.tab-send-button').getAttribute('disabled'),null);
  const readOnly=await calls();
  assert.equal(readOnly.inputs.length,0);
  assert.ok(readOnly.calls.filter(x=>x.cmd==='remote_tab_input_mode').every(x=>x.mode==='observe'));
  await btn('启用草稿输入').click();
  await ws.locator('.tab-mobile-controls[data-mode=draft]').waitFor();
  await ws.getByRole('textbox',{name:'当前标签草稿'}).fill('B-after-A');
  let inputConfirmation=false, stopConfirmation=false;
  page.on('dialog',async dialog=>{
    const m=dialog.message();
    if(dialog.type()==='confirm'&&m.includes('发送到 fixture-B · w1:p2 · term_b002')&&m.includes('9 字节')&&m.includes('B-after-A')){
      inputConfirmation=true;await dialog.accept();
    } else if(dialog.type()==='confirm'&&m.includes('停止 QA Shared Guest')&&m.includes('fixture-A')&&m.includes('fixture-B')){
      stopConfirmation=true;await dialog.accept();
    } else await dialog.dismiss();
  });
  await btn('发送草稿').click();
  await page.waitForFunction(()=>window.__ledger.inputs.length===1);
  assert.equal(inputConfirmation,true);
  const continued=await calls();
  const originalB=continued.auth.find(x=>x.host==='fixture-B');
  assert.deepEqual(continued.frames.filter(x=>x.host==='fixture-B').map(x=>x.connection),Array(wide?3:2).fill(originalB.connection));
  assert.equal(continued.inputs[0].connection,originalB.connection);
  assert.equal(continued.inputs[0].generation,originalB.generation);
  assert.deepEqual(continued.calls.filter(x=>x.cmd==='remote_tab_input_mode'&&x.mode!=='observe').map(x=>[x.host,x.mode]),[['fixture-B','draft']]);
  assert.equal(continued.auth.length,2);
  assert.equal(continued.node.stops,0);
  proof.continued=continued;
  await btn('关闭此标签').tap();
  await tabBtn('fixture-B').waitFor({state:'detached'});
  proof.afterClosingBoth=await calls();
  assert.deepEqual(proof.afterClosingBoth.closure.map(x=>x.host),['fixture-A','fixture-B']);
  assert.equal(proof.afterClosingBoth.node.stops,0);
  assert.equal(proof.afterClosingBoth.node.state,'engine-started');
  await page.locator('#nav-network').tap();
  const net=page.locator('#network-panel');
  const manage=net.getByText('管理网络',{exact:true});
  await assertOne(net.getByText('本机引擎已启动；入网及 SSH 尚未确认',{exact:true}));
  await assertOne(manage);await manage.tap();
  await net.getByRole('button',{name:'停止节点',exact:true}).tap();
  await page.waitForFunction(()=>window.__ledger.node.state==='stopped');
  assert.equal(stopConfirmation,true);
  await assertOne(net.getByText('节点已停止',{exact:true}));
  proof.afterExplicitNodeStop=await calls();
  assert.equal(proof.afterExplicitNodeStop.node.stops,1);
  assert.equal(proof.afterExplicitNodeStop.auth.length,2);
  assert.deepEqual(proof.afterExplicitNodeStop.errors,[]);
  result.checked=true;result.m2VisibleAfterClose=Boolean(proof.remainingPanelVisible);
} catch(error) {
  result.checked=false;result.error=String(error);
  result.diagnostic=await calls().catch(()=>null);
  await snapshot('failed').catch(()=>{});
} finally {
  await writeFile(new URL('report.json',dir),JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify({variant,engine,layout,checked:result.checked,m2VisibleAfterClose:result.m2VisibleAfterClose,error:result.error}));
  await browser.close();server.close();
}
if(!result.checked)process.exitCode=1;
