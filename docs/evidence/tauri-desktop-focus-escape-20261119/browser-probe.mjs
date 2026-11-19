import assert from 'node:assert/strict';
const {chromium, webkit}=await import(process.env.HERDR_D2_PLAYWRIGHT_MODULE || 'playwright');
import {createServer} from 'node:http';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
const site = new URL('./site/', import.meta.url);
const sourceSHA=(await readFile(new URL('./SOURCE_COMMIT',import.meta.url),'utf8')).trim();
const routerSha256=createHash('sha256').update(await readFile(
  new URL('./validation/tauri/src/key-router.js',import.meta.url))).digest('hex');
assert.match(sourceSHA,/^[0-9a-f]{40}$/);
const engine=process.env.HERDR_D2_BROWSER==='chromium'?'chromium':'webkit';
const runDir=new URL('./'+engine+'/',import.meta.url);
await mkdir(runDir,{recursive:true});
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
  window.__TAURI_INTERNALS__={
    transformCallback(fn) {callbacks.set(++callbackId,fn);return callbackId;},
    unregisterCallback(id) {callbacks.delete(id);},
    async invoke(cmd,args={}) {
      const {tabId,hostId,action,mode,canvas,paneId,terminalId,generation,epoch,seq}=args;
      window.__commands.push({cmd,tabId,hostId,action,mode,canvas,paneId,terminalId,generation,epoch,seq});
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
            await new Promise(resolve=>setTimeout(resolve,80));
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
const browser=await (engine==='chromium'?chromium:webkit).launch(
  engine==='webkit'&&process.env.HERDR_WEBKIT_EXECUTABLE
    ? {executablePath:process.env.HERDR_WEBKIT_EXECUTABLE} : {});
const context=await browser.newContext({viewport:{width:1440,height:1200},deviceScaleFactor:1});
const page=await context.newPage();
page.setDefaultTimeout(6500);
await page.addInitScript(installBridge,{hosts,paneOf,pauseDelay:80});
const log=[];
page.on('pageerror',error=>log.push(String(error).includes('.filter')?'collection_filter_error':'page_error'));
const out={sourceSHA,routerSha256,engine,browser:browser.version(),
  scope:'Tauri production frontend and xterm, Playwright native browser keys, simulated IPC, no SSH'};
try{
  await page.goto(base);
  await page.locator('#host-list .saved-host-card').first().waitFor();
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
  await splitBtn.click();
  await page.waitForFunction(()=>document.querySelectorAll('section[data-role=workbench-panel] .xterm-rows').length===2);
  await page.waitForFunction(()=>window.__frames.some(f=>f.label==='RESUME-1')&&
    [...document.querySelectorAll('.tab-connection-actions')].every(n=>n.dataset.state==='active'));
  const identify=name=>page.locator('.workbench-panel').filter({hasText:name}).getAttribute('data-tab-id');
  const aId=await identify(aName), bId=await identify(bName);
  assert.ok(aId && bId && aId!==bId);
  const selected='.workbench-panel[data-focus=true]';
  const direct=page.locator(selected).getByRole('button',{name:'逐键输入',exact:true});
  await direct.click();
  await page.waitForFunction(()=>document.querySelector('.workbench-panel[data-focus=true] .tab-mobile-controls')?.dataset.mode==='direct');
  await page.evaluate(()=>{
    window.__originalEditor=document.activeElement;
    window.__kn=[];
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
    document.addEventListener('keydown',event=>{
      const record={key:event.key,ctrl:event.ctrlKey,shift:event.shiftKey,alt:event.altKey,trusted:event.isTrusted,
        before:describe(event.target)};
      window.__kn.push(record);
      queueMicrotask(()=>{record.consumed=event.defaultPrevented;record.after=describe(document.activeElement);});
    },true);
  });
  const keyState=()=>page.evaluate(()=>{
    return {viewport:innerWidth,focused:window.__describeFocus(document.activeElement),
      views:[...document.querySelectorAll('[data-role=workbench-panel]')].map(x=>({
        target:x.querySelector(':scope > p:not([data-role])')?.textContent.split(' · ').slice(-2),
        focused:x.dataset.focus==='true',phase:x.querySelector('.tab-connection-actions')?.dataset.state??null,
        mode:x.querySelector('.tab-mobile-controls')?.dataset.mode??null})),
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

  const inputCycleFrom=(await commandLog()).length;
  await page.setViewportSize({width:700,height:1200});
  await page.waitForFunction(a=>[...document.querySelectorAll('#view-tabs button')].some(n=>n.textContent.includes(a)&&n.textContent.includes('观察已暂停')),aName);
  await page.setViewportSize({width:1440,height:1200});
  await page.waitForFunction(id=>window.__frames.some(f=>f.tabId===id&&f.label==='RESUME-2')&&
    window.__commands.some(c=>c.cmd==='remote_tab_ack'&&c.tabId===id&&c.seq===window.__frames.find(f=>f.tabId===id&&f.label==='RESUME-2').seq),aId);
  keyboard.directWide=await keyState();
  keyboard.resizeControl=(await commandLog()).slice(inputCycleFrom)
    .filter(c=>c.cmd==='remote_tab_control').map(c=>[c.tabId===bId?'B':'A',c.action]);
  assert.equal(keyboard.directWide.focused.css,'xterm','original B xterm must still have DOM focus at wide return');
  assert.deepEqual(keyboard.directWide.focused.target,['w1:p2','term_b002']);
  const escapeFrom=(await commandLog()).length;
  await page.keyboard.press('Control+Shift+F6');
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  keyboard.escape=await keyState();
  if(process.env.HERDR_SCREENSHOT==='1') {
    const png=await page.screenshot({path:new URL('./after-chord.png',runDir).pathname});
    keyboard.screenshotSha256=createHash('sha256').update(png).digest('hex');
  }
  keyboard.escapeControl=(await commandLog()).slice(escapeFrom).filter(c=>c.cmd==='remote_tab_input_mode')
    .map(c=>[c.tabId===bId?'B':'A',c.mode]);
  const escaped=keyboard.escape.focused.css!=='xterm' && keyboard.escape.views.some(v=>v.target[1]==='term_b002'&&v.mode==='observe');
  if(escaped) {
    await page.keyboard.press('Tab');
    keyboard.tab=await keyState();
    await page.keyboard.press('Shift+Tab');
    keyboard.shiftTab=await keyState();
    const onChooseA=s=>s.focused?.kind==='BUTTON'&&s.focused?.role==='panel-focus'&&s.focused?.target?.[1]==='term_a001';
    if(!onChooseA(keyboard.shiftTab) && engine==='webkit') {
      keyboard.optionTab=[];
      for(let i=0;i<16 && !onChooseA(await keyState());i++) {
        await page.keyboard.press('Alt+Tab');
        keyboard.optionTab.push((await keyState()).focused);
      }
    }
    if(onChooseA(await keyState())) {
      await page.keyboard.press('Enter');
      await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      keyboard.enter=await keyState();
    }
  }
  keyboard.events=await page.evaluate(()=>window.__kn);
  keyboard.after=await keyState();
  keyboard.transport=(await commandLog()).filter(c=>c.cmd.includes('remote_tab_input') || c.cmd.includes('resize') || c.cmd==='remote_tab_reserve' || c.cmd==='remote_tab_observe')
    .map(c=>({cmd:c.cmd,side:c.tabId===bId?'B':c.tabId===aId?'A':'other',mode:c.mode,epoch:c.epoch}));
  out.passed=escaped && keyboard.after.input.length===1 && keyboard.after.sendCalls===1 &&
    keyboard.after.views.some(v=>v.target[1]==='term_a001' && v.focused) && log.length===0;
} catch {
  out.passed=false;
  out.probeError='test_operation_failed';
}
out.browserErrors=log;
await writeFile(new URL('./report.json',runDir),JSON.stringify(out,null,2)+'\n');
await browser.close();
server.close();
console.log(JSON.stringify({engine,browser:out.browser,passed:out.passed}));
process.exit(out.passed?0:1);
