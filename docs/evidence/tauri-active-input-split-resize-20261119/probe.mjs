import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const {
  HERDR_D2_SITE, HERDR_D2_OUTPUT, HERDR_D2_SOURCE_SHA,
  HERDR_D2_BROWSER, HERDR_D2_PLAYWRIGHT_MODULE, HERDR_D2_EXECUTABLE,
}=process.env;
assert.ok(HERDR_D2_SITE && HERDR_D2_OUTPUT, 'Set HERDR_D2_SITE and HERDR_D2_OUTPUT');
assert.match(HERDR_D2_SOURCE_SHA ?? '', /^[0-9a-f]{40}$/);
const engine=HERDR_D2_BROWSER || 'webkit';
assert.ok(['chromium','webkit'].includes(engine));
const playwright=await import(HERDR_D2_PLAYWRIGHT_MODULE
  ? pathToFileURL(resolve(HERDR_D2_PLAYWRIGHT_MODULE)).href : 'playwright');
const directory=path=>pathToFileURL(resolve(path)+'/');
const site=directory(HERDR_D2_SITE), runDir=directory(HERDR_D2_OUTPUT);
const shots=new URL('./shots/',runDir).pathname;
await mkdir(shots,{recursive:true});
const mime = {html:'text/html', js:'text/javascript', css:'text/css', json:'application/json', ttf:'font/ttf'};
const server = createServer(async (req,res) => {
  try {
    const file = new URL(decodeURIComponent(req.url === '/' ? 'index.html' : req.url.slice(1)),site);
    if(!file.href.startsWith(site.href)) throw Error('outside fixture');
    res.setHeader('Content-Type', mime[file.pathname.split('.').at(-1)] || 'application/octet-stream');
    res.end(await readFile(file));
  } catch {
    res.statusCode=404;res.end();
  }
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const base='http://127.0.0.1:'+server.address().port+'/';
const hosts=[
 {id:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',name:'fixture-alpha',provider:'system',revision:1,enabled:true,
  deviceFingerprint:'SHA256:'+'A'.repeat(43),pairingStatus:'authorized',hostFingerprint:'SHA256:'+'C'.repeat(43),
  target:{username:'fixture',host:'203.0.113.17',port:22,session:'alpha'}},
 {id:'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',name:'fixture-beta',provider:'system',revision:1,enabled:true,
  deviceFingerprint:'SHA256:'+'B'.repeat(43),pairingStatus:'authorized',hostFingerprint:'SHA256:'+'D'.repeat(43),
  target:{username:'fixture',host:'203.0.113.18',port:22,session:'beta'}}];
const paneOf={aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:{paneId:'w1:p1',terminalId:'term_a001',agent:'alpha',agentStatus:'idle',title:'alpha shell'},
              bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb:{paneId:'w1:p2',terminalId:'term_b002',agent:'beta',agentStatus:'idle',title:'beta shell'}};
function installBridge({hosts, paneOf, pauseDelay}) {
  const callbacks=new Map(), tabs=new Map();
  let callbackId=0, nextGeneration=0;
  function assertTargetFixture(pane,paneId,terminalId){
    if(pane.paneId!==paneId || pane.terminalId!==terminalId)throw Error('mock target mismatch');
  }
  window.isTauri=true;
  window.__commands=[];
  window.__pauseReplies=[];
  window.__frames=[];
  window.__fixtureInput=[];
  window.__acceptedInput=[];
  window.__TAURI_INTERNALS__={
    transformCallback(fn) {callbacks.set(++callbackId,fn);return callbackId;},
    unregisterCallback(id) {callbacks.delete(id);},
    async invoke(cmd,args={}) {
      const {tabId,hostId,action,mode,canvas,paneId,terminalId,clientGeneration,generation,inputEpoch,epoch,seq}=args;
      window.__commands.push({cmd,tabId,hostId,action,mode,canvas,paneId,terminalId,clientGeneration,generation,inputEpoch,epoch,seq});
      const tab=tabs.get(tabId);
      const send=event=>callbacks.get(tab.channel)({index:tab.index++,message:{generation:tab.generation,...event}});
      const observation=phase=>send({kind:'observation',snapshot:{epoch:tab.epoch,phase}});
      const frame=label=>{
        const bytes=[...new TextEncoder().encode(tab.pane.agent.toUpperCase()+'-D2-'+label+'\r\n$ ')];
        const seq=++tab.seq;
        const acknowledged=new Promise(resolve=>tab.frameAck={seq,resolve});
        send({kind:'target_bound',epoch:tab.epoch,pane_id:tab.pane.paneId,terminal_id:tab.pane.terminalId});
        window.__frames.push({tabId,epoch:tab.epoch,seq,full:true,paneId:tab.pane.paneId,terminalId:tab.pane.terminalId,label});
        send({kind:'frame',epoch:tab.epoch,frame:{seq,full:true,cols:tab.canvas.cols,rows:tab.canvas.rows,bytes}});
        return acknowledged.then(()=>{
          send({kind:'input_ready',epoch:tab.epoch,unknown:false,recovery_status:'ready'});
        });
      };
      switch(cmd) {
        case 'config_document_platform':return 'macos';
        case 'host_list':return hosts;
        case 'network_list':return {profiles:[],preferences:{terminalFontSize:14}};
        case 'remote_tab_reserve':
          tabs.set(tabId,{generation:++nextGeneration,pane:paneOf[hostId],index:0,epoch:1,seq:0,resumes:0,mode:'observe',inputEpoch:0});
          return nextGeneration;
        case 'remote_tab_observe':
          tab.channel=args.onEvent.id;
          tab.canvas=canvas;
          setTimeout(()=>{
            observation('starting');
            send({kind:'dashboard_watch',update:{epoch:tab.epoch,revision:1,phase:'fresh',reason:'isolated fixture',panes:[tab.pane]}});
            send({kind:'selection_ready',epoch:tab.epoch});
          },40);
          return new Promise(resolve=>tab.finish=resolve);
        case 'remote_tab_select':
          assertTargetFixture(tab.pane,paneId,terminalId);
          setTimeout(async()=>{await frame('START');observation('active');},40);
          return {};
        case 'remote_tab_control':
          tab.epoch++;
          if(action==='pause') {
            observation('pausing');
            await new Promise(resolve=>setTimeout(resolve,pauseDelay));
            observation('paused');
            window.__pauseReplies.push({tabId,at:performance.now()});
          } else if(action==='resume') {
            observation('resuming');
            await new Promise(resolve=>setTimeout(resolve,450));
            await frame('RESUME-'+ ++tab.resumes);
            observation('active');
          }
          return {};
        case 'remote_tab_input_mode':
          if(!tab || tab.epoch!==epoch)throw Error('mode lease outside original epoch');
          tab.mode=mode;
          return ++tab.inputEpoch;
        case 'remote_tab_input_send':
          if(!tab || tab.epoch!==epoch || tab.mode!=='direct' || tab.inputEpoch!==args.inputEpoch || args.draft!==false)
            throw Error('send outside direct lease');
          window.__fixtureInput.push({side:tab.pane.agent,bytes:args.bytes});
          window.__acceptedInput.push({tabId,clientGeneration,generation,epoch,inputEpoch,paneId:tab.pane.paneId,terminalId:tab.pane.terminalId});
          return {status:'accepted',receipt:{requestId:'a'.repeat(32),paneId:tab.pane.paneId,
            terminalId:tab.pane.terminalId,acceptedBytes:args.bytes.length}};
        case 'remote_tab_cancel': tab?.finish?.();return {};
        case 'remote_tab_ack':
          if(tab.frameAck?.seq!==seq || tab.epoch!==epoch)throw Error('mock frame acknowledgment mismatch');
          tab.frameAck.resolve();
          return {};
        case 'remote_tab_visible':
          return {};
        default:
          return {};
      }
    }
  };
}
const browser=await playwright[engine].launch(HERDR_D2_EXECUTABLE ? {executablePath:HERDR_D2_EXECUTABLE} : {});
const context=await browser.newContext({viewport:{width:1440,height:1200},deviceScaleFactor:1});
const page=await context.newPage();
page.setDefaultTimeout(6500);
await page.addInitScript(installBridge,{hosts,paneOf,pauseDelay:80});
const log=[];
page.on('pageerror',error=>log.push(String(error)));
const out={sourceSHA:HERDR_D2_SOURCE_SHA,scope:'Tauri production frontend in an isolated Playwright browser; simulated Tauri IPC; no SSH, GTK, physical keyboard or remote input',engine,browser:browser.version()};
try{
  await page.goto(base);
  try{await page.locator('#host-list .saved-host-card').first().waitFor({timeout:8000});}
  catch(e){out.bootDiag=await page.evaluate(()=>({commands:(window.__commands||[]).map(c=>c.cmd),
    hasInternals:!!window.__TAURI_INTERNALS__,cards:document.querySelectorAll('#host-list .saved-host-card').length,
    hlChildren:document.getElementById('host-list')?.children.length,vis:document.getElementById('host-list')?.offsetParent!==null,
    bodySections:[...document.querySelectorAll('main>section')].filter(s=>!s.hidden).map(s=>s.id)})).catch(er=>String(er));throw e;}
  out.hostCards=await page.locator('#host-list .saved-host-card').count();
  const openHost=async(idx,pane)=>{
    const card=page.locator('#host-list .saved-host-card').filter({hasText:idx===0?'fixture-alpha':'fixture-beta'});
    await card.locator('summary').click();
    await card.getByRole('button',{name:'新终端标签',exact:true}).click();
    await page.locator('#tab-workspace:not([hidden])').waitFor();
    const review=page.locator('#view-content input[type=checkbox]').first();
    await review.waitFor();await review.check();
    await page.locator('#view-content').getByRole('button',{name:'连接',exact:true}).click();
    const paneBtn=page.locator(`[data-pane-id="${pane}"]`);
    await paneBtn.waitFor({timeout:8000});await paneBtn.click();
    await page.locator('.terminal-host .xterm').first().waitFor({timeout:8000});
    await page.waitForFunction(pane=>{const selection=window.__commands.find(c=>c.cmd==='remote_tab_select'&&c.paneId===pane);return selection&&window.__commands.some(c=>c.cmd==='remote_tab_ack'&&c.tabId===selection.tabId);},pane,{timeout:5000});
  };
  await openHost(0,'w1:p1');
  await page.locator('#host-return-home').click();
  await page.waitForFunction(()=>window.__pauseReplies.length===1);
  await openHost(1,'w1:p2');
  const splitBtn=page.locator('#workbench-split');
  const aName='fixture-alpha', bName='fixture-beta';
  const commandLog=()=>page.evaluate(()=>window.__commands);
  const scrollToTerminal=()=>page.evaluate(()=>{
    const terminal=[...document.querySelectorAll('#view-content .term-scroll')].at(-1);
    terminal?.scrollIntoView({block:'center'});
  });
  const read=()=>page.evaluate(()=>{
    const rect=e=>{if(!e)return null;const r=e.getBoundingClientRect();const round=x=>Math.round(x*100)/100;
      return {x:round(r.x+scrollX),y:round(r.y+scrollY),w:round(r.width),h:round(r.height),cssTop:round(r.top),cssBottom:round(r.bottom)};};
    const visible=e=>Boolean(e&&e.getClientRects().length&&getComputedStyle(e).visibility==='visible');
    const tabList=[...document.querySelectorAll('#view-tabs button')].map(e=>({label:e.textContent,pressed:e.getAttribute('aria-pressed')}));
    return {
      viewport:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio,scrollY},
      sidebar:visible(document.querySelector('#workbench-sidebar')),
      returnHome:visible(document.querySelector('#host-return-home')),
      dataSplit:document.querySelector('#view-content').getAttribute('data-split'),
      splitHidden:!visible(document.querySelector('#workbench-split')),
      stashNote:document.querySelector('[data-role=split-stash-note]')?.textContent??null,
      splitNote:document.querySelector('[data-role=split-note]')?.textContent??null,
      panels:[...document.querySelectorAll('[data-role=workbench-panel]')].map(n=>({
        id:n.dataset.tabId,focus:n.dataset.focus,
        title:n.querySelector(':scope > p:not([data-role])')?.textContent,
        panel:rect(n),terminal:rect(n.querySelector('.term-scroll')),
        terminalRows:n.querySelector('.xterm-rows')?.textContent.replace(/ +/g,' ').trim()??null
      })),
      tabList
    };
  });
  const snapshot=async name=>{
    const info=await read();
    const png=await page.screenshot({path:shots+name+'.png',fullPage:false});
    return {...info,png:{path:'shots/'+name+'.png',sha256:createHash('sha256').update(png).digest('hex')}};
  };
  assert.equal(await splitBtn.isHidden(),false,'two tabs expose split at 1440');
  await splitBtn.click();
  await page.waitForFunction(()=>document.querySelectorAll('section[data-role=workbench-panel] .xterm-rows').length===2);
  await scrollToTerminal();
  await page.waitForFunction(()=>[...document.querySelectorAll('.xterm-rows')].some(x=>x.textContent.includes('ALPHA-D2-RESUME-1')));
  out.afterSplit=await snapshot('wide-split-1440');
  const [left,right]=out.afterSplit.panels;
  assert.ok(left.title.includes(bName)&&left.title.includes('term_b002')&&left.terminalRows.includes('BETA-D2-START'));
  assert.ok(right.title.includes(aName)&&right.title.includes('term_a001')&&right.terminalRows.includes('ALPHA-D2-RESUME-1'));
  assert.notEqual(left.id,right.id);
  assert.deepEqual([left.focus,right.focus],['true','false']);
  assert.equal(left.panel.y,right.panel.y);
  assert.ok(left.panel.x+left.panel.w<=right.panel.x);
  const beforeNarrow=(await commandLog()).length;
  await page.setViewportSize({width:700,height:1200});
  await page.waitForFunction(a=>[...document.querySelectorAll('#view-tabs button')].some(n=>n.textContent.includes(a)&&n.textContent.includes('观察已暂停')),aName);
  await scrollToTerminal();
  out.narrow=await snapshot('narrow-700');
  assert.deepEqual(out.narrow.panels.map(p=>[p.id,p.focus]),[[left.id,'true']]);
  assert.equal(out.narrow.splitHidden,true);
  assert.equal(out.narrow.sidebar,false);
  assert.equal(out.narrow.returnHome,true);
  assert.ok(out.narrow.stashNote);
  assert.ok(out.narrow.panels[0].terminalRows.includes('BETA-D2-START'));
  const onNarrow=(await commandLog()).slice(beforeNarrow);
  assert.deepEqual(onNarrow.filter(c=>c.cmd==='remote_tab_control').map(c=>[c.tabId,c.action]),[[right.id,'pause']]);
  const beforeWiden=(await commandLog()).length;
  await page.setViewportSize({width:1440,height:1200});
  await page.waitForFunction(()=>document.querySelector('#view-content').dataset.split==='2');
  await scrollToTerminal();
  await page.waitForFunction(()=>[...document.querySelectorAll('.xterm-rows')].some(x=>x.textContent.includes('ALPHA-D2-RESUME-2')));
  out.afterWiden=await snapshot('after-1440-return');
  assert.deepEqual(out.afterWiden.panels.map(p=>[p.id,p.focus,p.panel.x,p.panel.w]),out.afterSplit.panels.map(p=>[p.id,p.focus,p.panel.x,p.panel.w]));
  assert.equal(out.afterWiden.stashNote,null);
  assert.ok(!out.afterWiden.tabList.some(t=>t.label.includes('观察已暂停')));
  const onWiden=(await commandLog()).slice(beforeWiden);
  assert.deepEqual(onWiden.filter(c=>c.cmd==='remote_tab_control').map(c=>[c.tabId,c.action]),[[right.id,'resume']]);
  const selected='.workbench-panel[data-focus=true]';
  const direct=page.locator(selected).getByRole('button',{name:'逐键输入',exact:true});
  await direct.click();
  await page.waitForFunction(()=>document.querySelector('.workbench-panel[data-focus=true] .tab-mobile-controls')?.dataset.mode==='direct');
  await page.evaluate(()=>{
    window.__originalEditor=document.activeElement;
    window.__blurEvents=[];
    window.__originalEditor.addEventListener('blur',()=>window.__blurEvents.push(performance.now()));
    const describe=(e)=>{
      if(!e)return null;
      const panel=e.closest('[data-role=workbench-panel]');
      const state=panel?.querySelector('.tab-connection-actions');
      return {kind:e.tagName,role:e.dataset.role||null,css:e.classList.contains('xterm-helper-textarea')?'xterm':null,
        target:panel?.querySelector(':scope > p:not([data-role])')?.textContent.split(' · ').slice(-2)??null,
        frame:state?.dataset.state??null,
        name:({BUTTON:e.textContent.trim(),SUMMARY:e.textContent.trim()})[e.tagName]||e.getAttribute('aria-label'),
        enabled:!e.disabled,readOnly:Boolean(e.readOnly),visible:!!e.getClientRects().length&&getComputedStyle(e).visibility==='visible',
        sameEditor:e===window.__originalEditor};
    };
    window.__describeFocus=describe;
  });
  const keyState=()=>page.evaluate(()=>{
    const root=document.getElementById('view-content');
    return {viewport:innerWidth,split:root.dataset.split,splitVisible:!document.getElementById('workbench-split').hidden,
      stash:!!root.querySelector('[data-role=split-stash-note]'),focused:window.__describeFocus(document.activeElement),
      views:[...document.querySelectorAll('[data-role=workbench-panel]')].map(x=>({
        target:x.querySelector(':scope > p:not([data-role])')?.textContent.split(' · ').slice(-2),
        focused:x.dataset.focus==='true',phase:x.querySelector('.tab-connection-actions')?.dataset.state??null,
        mode:x.querySelector('.tab-mobile-controls')?.dataset.mode??null,
        editable: x.querySelector('.xterm-helper-textarea')?.readOnly === false,
        terminalRows:x.querySelector('.xterm-rows')?.textContent.replace(/ +/g,' ').trim()??null,
        visible:!!x.getClientRects().length&&getComputedStyle(x).visibility==='visible',
        width:Math.round(x.getBoundingClientRect().width)})),
      input:window.__fixtureInput,sendCalls:window.__commands.filter(x=>x.cmd==='remote_tab_input_send').length};
  });
  const keyboard=out.keyboard={};
  keyboard.working=await keyState();
  assert.equal(keyboard.working.focused.css,'xterm');
  assert.deepEqual(keyboard.working.focused.target,['w1:p2','term_b002']);
  assert.equal(keyboard.working.focused.readOnly,false);
  await page.keyboard.press('x');
  await page.waitForFunction(()=>window.__fixtureInput.length===1);
  await page.getByText('主机已受理，命令结果请查看终端。',{exact:false}).waitFor({state:'attached'});
  keyboard.marker=await keyState();
  assert.deepEqual(keyboard.marker.input,[{side:'beta',bytes:[120]}]);

  const startCommands=(await commandLog()).length;
  const settled=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const overview=async name=>{
    await page.mouse.move(4,8);
    await page.mouse.wheel(0,-5000);
    await page.waitForFunction(()=>scrollY===0);
    return snapshot(name);
  };
  const frameAck=async (id,label)=>page.waitForFunction(([id,label])=>{
    const frame=window.__frames.find(f=>f.tabId===id&&f.label===label&&f.full);
    return frame && window.__commands.some(c=>c.cmd==='remote_tab_ack'&&c.tabId===id&&c.epoch===frame.epoch&&c.seq===frame.seq);
  },[id,label]);
  const isCurrentB=s=>s.focused?.css==='xterm' && s.focused.sameEditor &&
    s.focused.target?.[1]==='term_b002' && s.focused.visible && !s.focused.readOnly;
  const originalBMode=(await commandLog()).find(c=>c.cmd==='remote_tab_input_mode'&&c.tabId===left.id&&c.mode==='direct');
  const originalTyped=await page.evaluate(()=>window.__commands.find(c=>c.cmd==='remote_tab_input_send'));
  const scopeActions=(from,to)=>to.slice(from).filter(c=>c.cmd==='remote_tab_control').map(c=>[c.tabId===left.id?'B':'A',c.action,c.generation]);
  keyboard.directWideBefore=await snapshot('direct-wide-before');
  await page.setViewportSize({width:700,height:1200});
  await page.waitForFunction(a=>[...document.querySelectorAll('#view-tabs button')].some(n=>n.textContent.includes(a)&&n.textContent.includes('观察已暂停')),aName);
  await settled();
  keyboard.directNarrow=await keyState();
  keyboard.directNarrowImage=await snapshot('direct-narrow');
  keyboard.directNarrowOverview=await overview('direct-narrow-top');
  if(isCurrentB(keyboard.directNarrow)){
    await page.keyboard.press('y');
    await page.waitForFunction(()=>window.__fixtureInput.length===2);
  }
  await page.setViewportSize({width:1440,height:1200});
  await page.waitForFunction(([id,from])=>window.__commands.slice(from).some(c=>c.cmd==='remote_tab_control'&&c.tabId===id&&c.action==='resume'),[right.id,startCommands]);
  await settled();
  keyboard.directWidePending=await keyState();
  await frameAck(right.id,'RESUME-3');
  await settled();
  keyboard.directWide=await keyState();
  keyboard.directWideImage=await snapshot('direct-wide-after');
  keyboard.directWideOverview=await overview('direct-wide-top');
  const partnerViewport=page.locator('[data-role=workbench-panel][data-focus=false] .term-scroll');
  const wheelDistance=await partnerViewport.evaluate(node=>Math.round(node.getBoundingClientRect().top)-100);
  await page.mouse.move(4,8);
  await page.mouse.wheel(0,wheelDistance);
  await page.waitForFunction(()=>{
    const viewport=document.querySelector('[data-role=workbench-panel][data-focus=false] .term-scroll');
    return viewport && viewport.getBoundingClientRect().top<250 && viewport.getBoundingClientRect().bottom>0;
  });
  keyboard.directWideTerminals=await snapshot('direct-wide-terminals');

  if(isCurrentB(keyboard.directWide)){
    await page.keyboard.press('z');
    await page.waitForFunction(()=>window.__fixtureInput.length===3);
    await settled();
  }
  const mainCommands=await commandLog();
  keyboard.resizeControl=scopeActions(startCommands,mainCommands);
  keyboard.resizeTransport=mainCommands.slice(startCommands).filter(c=>c.cmd.includes('resize')||c.cmd==='remote_tab_reserve'||c.cmd==='remote_tab_observe'||c.cmd==='remote_tab_cancel');
  keyboard.inputModeChanges=mainCommands.slice(startCommands).filter(c=>c.cmd==='remote_tab_input_mode');
  keyboard.typed=mainCommands.filter(c=>c.cmd==='remote_tab_input_send');
  keyboard.originalBMode=originalBMode;
  keyboard.originalAReserves=mainCommands.filter(c=>c.cmd==='remote_tab_reserve'&&c.tabId===right.id).length;
  keyboard.acceptedInput=await page.evaluate(()=>window.__acceptedInput);
  keyboard.originalBSends=keyboard.acceptedInput.length===3&&keyboard.acceptedInput.every(c=>c.tabId===left.id&&c.clientGeneration===originalTyped.clientGeneration&&c.generation===originalTyped.generation&&c.epoch===originalTyped.epoch&&c.inputEpoch===originalTyped.inputEpoch&&c.paneId==='w1:p2'&&c.terminalId==='term_b002');
  keyboard.actualBytes=(await keyState()).input;
  keyboard.aNewFull=await page.evaluate(id=>window.__frames.find(f=>f.tabId===id&&f.label==='RESUME-3'),right.id);
  keyboard.blurEvents=await page.evaluate(()=>window.__blurEvents||[]);
  const panelColumns=snapshot=>snapshot.panels.map(({id,panel})=>[id,panel.x,panel.w]);
  keyboard.columnOrderPreserved=JSON.stringify(panelColumns(keyboard.directWideBefore))===JSON.stringify(panelColumns(keyboard.directWideImage));
  const mainGood=keyboard.columnOrderPreserved && keyboard.directNarrow.split==='1' && keyboard.directNarrow.stash && !keyboard.directNarrow.splitVisible &&
    keyboard.directNarrow.views.length===1 && isCurrentB(keyboard.directNarrow) &&
    keyboard.directWide.split==='2' && !keyboard.directWide.stash && keyboard.directWide.views.length===2 &&
    isCurrentB(keyboard.directWide) && keyboard.directWide.views.some(v=>v.target[1]==='term_a001'&&v.mode==='observe'&&!v.editable&&v.phase==='active'&&v.terminalRows.includes('ALPHA-D2-RESUME-3')) &&
    keyboard.directWidePending.views.some(v=>v.target[1]==='term_a001'&&v.phase==='resuming'&&!v.editable&&!v.terminalRows.includes('ALPHA-D2-RESUME-3')) &&
    keyboard.resizeControl.map(c=>c.slice(0,2)).map(c=>c.join(':')).join(',')==='A:pause,A:resume'&&
    keyboard.resizeControl[0][2]===keyboard.resizeControl[1][2] &&
    keyboard.resizeTransport.length===0 && keyboard.inputModeChanges.length===0 && keyboard.blurEvents.length===0 && keyboard.originalAReserves===1 &&
    keyboard.originalBSends && keyboard.actualBytes.map(c=>c.side+':'+String(c.bytes)).join(',')==='beta:120,beta:121,beta:122';

  // User-initiated pause independently of a width change: leave the workspace,
  // return to the existing tabs and explicitly resume only the focused B.
  const beforeHome=(await commandLog()).length;
  await page.evaluate(()=>{window.__homeAt=performance.now();});
  await page.locator('#host-return-home').click();
  await page.waitForFunction(([start,a,b])=>{
    const control=window.__commands.slice(start).filter(c=>c.cmd==='remote_tab_control'&&c.action==='pause');
    return [a,b].every(id=>control.some(c=>c.tabId===id)&&window.__pauseReplies.some(r=>r.tabId===id&&r.at>window.__homeAt));
  },[beforeHome,right.id,left.id]).catch(async()=>{throw Error('explicit navigation pause not confirmed');});
  await page.locator('#nav-terminal').click();
  await page.locator('#view-content .workbench-panel[data-focus=true]').getByRole('button',{name:'恢复观察',exact:true}).click();
  await frameAck(left.id,'RESUME-1');
  await settled();
  const focusedB=page.locator('#view-content .workbench-panel[data-focus=true]');
  await focusedB.getByRole('button',{name:'逐键输入',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.workbench-panel[data-focus=true] .tab-mobile-controls')?.dataset.mode==='direct');
  await page.evaluate(()=>{window.__originalEditor=document.activeElement;});
  const manualFrom=(await commandLog()).length;
  out.manual={before:await keyState()};
  await page.setViewportSize({width:700,height:1200});
  await settled();
  out.manual.narrow=await keyState();
  await page.setViewportSize({width:1440,height:1200});
  await settled();
  out.manual.wide=await keyState();
  out.manual.resizeControl=scopeActions(manualFrom,await commandLog());
  out.manual.frameCount=await page.evaluate(id=>window.__frames.filter(f=>f.tabId===id&&f.full).length,right.id);
  out.manual.image=await overview('manual-pause-wide');
  const manualGood=out.manual.narrow.split==='1'&&out.manual.narrow.views.length===1&&isCurrentB(out.manual.narrow)&&
    out.manual.wide.split==='2'&&isCurrentB(out.manual.wide)&&out.manual.wide.views.some(v=>v.target[1]==='term_a001'&&v.phase==='paused'&&['observe',null].includes(v.mode)&&!v.editable)&&
    out.manual.resizeControl.length===0&&out.manual.frameCount===4;
  await page.locator('#view-content .workbench-panel[data-focus=true]').getByRole('button',{name:'观察',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.workbench-panel[data-focus=true] .tab-mobile-controls')?.dataset.mode==='observe');
  await page.setViewportSize({width:700,height:1200});
  await settled();
  const ordinarySingle=await page.locator('#view-content').getAttribute('data-role')==='workbench-panel';
  await page.locator('#view-content').getByRole('button',{name:'逐键输入',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#view-content .tab-mobile-controls')?.dataset.mode==='direct');
  await page.evaluate(()=>{window.__originalEditor=document.activeElement;});
  const fromNarrow=(await commandLog()).length;
  out.enteredNarrow={ordinarySingle,narrow:await keyState()};
  await page.setViewportSize({width:1440,height:1200});
  await settled();
  out.enteredNarrow.wide=await keyState();
  out.enteredNarrow.resizeControl=scopeActions(fromNarrow,await commandLog());
  const enteredNarrowGood=ordinarySingle && out.enteredNarrow.narrow.views.length===1 && isCurrentB(out.enteredNarrow.narrow)&&
    out.enteredNarrow.wide.views.length===2 && isCurrentB(out.enteredNarrow.wide)&&out.enteredNarrow.resizeControl.length===0 &&
    out.enteredNarrow.wide.sendCalls===keyboard.typed.length;
  out.assertions={mainGood,manualGood,enteredNarrowGood};
  out.passed=mainGood&&manualGood&&enteredNarrowGood&&log.length===0;
}catch(e){out.diagnostic=await page.evaluate(()=>({
  commands:window.__commands?.slice(-24),
  panels:[...document.querySelectorAll('[data-role=workbench-panel]')].map(n=>({title:n.querySelector(':scope > p:not([data-role])')?.textContent,rows:n.querySelector('.xterm-rows')?.textContent,summary:n.querySelector('.tab-frame-status')?.textContent}))
})).catch(()=>null);out.passed=false;out.error=String(e&&e.message||e);out.stack=String(e&&e.stack||'').split('\n').slice(0,6).join('\n');}
out.browserErrors=log;
await writeFile(new URL('./report.json',runDir),JSON.stringify(out,null,2)+'\n');
await browser.close();
server.close();
console.log(JSON.stringify(out,null,1));
process.exit(out.passed?0:1);
