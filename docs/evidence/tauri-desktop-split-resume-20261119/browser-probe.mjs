import assert from 'node:assert/strict';
const {chromium, webkit}=await import(process.env.HERDR_D2_PLAYWRIGHT_MODULE || 'playwright');
import {createServer} from 'node:http';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
const site = new URL('./site/', import.meta.url);
const sourceSHA=(await readFile(new URL('./SOURCE_COMMIT',import.meta.url),'utf8')).trim();
assert.match(sourceSHA,/^[0-9a-f]{40}$/);
const engine=process.env.HERDR_D2_BROWSER==='chromium'?'chromium':'webkit';
const tabKey=process.env.HERDR_D2_TAB || 'Tab';
const rapid=process.env.HERDR_D2_RAPID === '1';
const runDir=new URL('./'+engine+(tabKey==='Tab'?'':'-option-tab')+(rapid?'-rapid':'')+'/',import.meta.url);
const shots = new URL('./shots/',runDir).pathname;
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
        return acknowledged;
      };
      switch(cmd) {
        case 'config_document_platform':return 'macos';
        case 'host_list':return hosts;
        case 'network_list':return {profiles:[],preferences:{terminalFontSize:14}};
        case 'remote_tab_reserve':
          tabs.set(tabId,{generation:++nextGeneration,pane:paneOf[hostId],index:0,epoch:1,seq:0,resumes:0});
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
        case 'remote_tab_input_mode': return 1;
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
new Function('return ('+installBridge.toString()+')')();
const browser=await (engine==='chromium'?chromium:webkit).launch();
const context=await browser.newContext({viewport:{width:1440,height:1000},deviceScaleFactor:1});
const page=await context.newPage();
page.setDefaultTimeout(6500);
await page.addInitScript(installBridge,{hosts,paneOf,pauseDelay:rapid?500:80});
const log=[];
page.on('pageerror',error=>log.push(String(error)));
const out={sourceSHA, scope:'Tauri production frontend in an isolated Playwright browser; simulated Tauri IPC; no SSH, GTK, physical keyboard or remote input',engine,browser:browser.version(),tabKey};
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
  const idleCommand=async(cmd,tabId,extra='')=>await page.waitForFunction(
    ([cmd,id,extra])=>window.__commands.some(c=>c.cmd===cmd&&c.tabId===id&&(!extra||c.action===extra)),[cmd,tabId,extra],{timeout:5000});
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
  await page.setViewportSize({width:700,height:1000});
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
  await page.setViewportSize({width:1440,height:1000});
  await page.waitForFunction(()=>document.querySelector('#view-content').dataset.split==='2');
  await scrollToTerminal();
  await page.waitForFunction(()=>[...document.querySelectorAll('.xterm-rows')].some(x=>x.textContent.includes('ALPHA-D2-RESUME-2')));
  out.afterWiden=await snapshot('after-1440-return');
  assert.deepEqual(out.afterWiden.panels.map(p=>[p.id,p.focus,p.panel.x,p.panel.w]),out.afterSplit.panels.map(p=>[p.id,p.focus,p.panel.x,p.panel.w]));
  assert.equal(out.afterWiden.stashNote,null);
  assert.ok(!out.afterWiden.tabList.some(t=>t.label.includes('观察已暂停')));
  const onWiden=(await commandLog()).slice(beforeWiden);
  assert.deepEqual(onWiden.filter(c=>c.cmd==='remote_tab_control').map(c=>[c.tabId,c.action]),[[right.id,'resume']]);
  if(rapid) {
    const beforeRapid=(await commandLog()).length;
    const priorReplies=await page.evaluate(()=>window.__pauseReplies.length);
    await page.setViewportSize({width:700,height:1000});
    await page.waitForFunction(([start,id])=>document.querySelector('#view-content').dataset.split==='1' &&
      window.__commands.slice(start).some(c=>c.cmd==='remote_tab_control'&&c.action==='pause'&&c.tabId===id),[beforeRapid,right.id]);
    const beforeAcknowledgement=await read();
    assert.ok(!beforeAcknowledgement.tabList.some(t=>t.label.includes('观察已暂停')));
    assert.equal(await page.evaluate(()=>window.__pauseReplies.length),priorReplies);
    await page.setViewportSize({width:1440,height:1000});
    await page.waitForFunction(replyCount=>document.querySelector('#view-content').dataset.split==='2' && window.__pauseReplies.length===replyCount+1,priorReplies);
    const resumed=await page.waitForFunction(([start,id])=>window.__commands.slice(start).some(c=>c.cmd==='remote_tab_control'&&c.action==='resume'&&c.tabId===id),[beforeRapid,right.id],{timeout:1200})
      .then(()=>true,error=>{if(error.name==='TimeoutError')return false;throw error;});
    await scrollToTerminal();
    if(resumed) {
      await page.waitForFunction(()=>[...document.querySelectorAll('.xterm-rows')].some(x=>x.textContent.includes('ALPHA-D2-RESUME-3')));
      await page.waitForFunction(()=>document.querySelector('section[data-role=workbench-panel][data-focus=false] .tab-connection-actions').dataset.state==='active');
    }
    const returned=await snapshot('rapid-return-1440');
    const controls=(await commandLog()).slice(beforeRapid).filter(c=>c.cmd==='remote_tab_control');
    const partnerState=await page.locator('section[data-role=workbench-panel][data-focus=false] .tab-connection-actions').getAttribute('data-state');
    out.rapidReversal={pauseResponseDelayMs:500,beforeAcknowledgement,returned,controls,partnerState};
    assert.ok(resumed,'widening during a pending pause must resume the non-focus pane when pause is acknowledged');
    assert.deepEqual(controls.map(c=>[c.tabId,c.action]),[[right.id,'pause'],[right.id,'resume']]);
    assert.equal(partnerState,'active');
    assert.deepEqual(returned.panels.map(p=>[p.id,p.focus,p.panel.x,p.panel.w]),out.afterSplit.panels.map(p=>[p.id,p.focus,p.panel.x,p.panel.w]));
  } else {
  const beforeManual=(await commandLog()).length;
  await page.setViewportSize({width:700,height:1000});
  await page.waitForFunction(a=>[...document.querySelectorAll('#view-tabs button')].some(n=>n.textContent.includes(a)&&n.textContent.includes('观察已暂停')),aName);
  const focusByTab=async(label,seed,reverse=false)=>{
    if(seed) await page.locator(seed).focus();
    const stops=[];
    for(let i=0;i<45;i++){
      await page.keyboard.press((reverse?'Shift+':'')+tabKey);
      const hit=await page.evaluate(()=>{const e=document.activeElement;return {tag:e.tagName,label:e.textContent?.trim().slice(0,70)||'',id:e.id};});
      stops.push(hit);
      if(hit.label===label && hit.tag==='BUTTON') return stops;
    }
    throw Error('keyboard target not reached: '+label+' stops='+JSON.stringify(stops));
  };
  const keyboard={};
  out.keyboard=keyboard;
  keyboard.select=await focusByTab(aName+' · w1:p1 · 观察已暂停','#host-return-home');
  await page.keyboard.press('Enter');
  await page.waitForFunction(a=>document.querySelector('[data-role=workbench-panel] > p:not([data-role])')?.textContent.includes(a),aName);
  const beforeResume=(await commandLog()).slice(beforeManual);
  assert.ok(!beforeResume.some(c=>c.cmd==='remote_tab_control'&&c.action==='resume'));
  const resume=page.getByRole('button',{name:'恢复观察',exact:true});
  await resume.waitFor();
  keyboard.resume=await focusByTab('恢复观察','#host-return-home');
  await page.keyboard.press('Enter');
  await idleCommand('remote_tab_control',right.id,'resume');
  await scrollToTerminal();
  await page.waitForFunction(()=>[...document.querySelectorAll('.xterm-rows')].some(x=>x.textContent.includes('ALPHA-D2-RESUME-3')));
  out.manualRecovery=await snapshot('narrow-700-manual-recovery');
  assert.deepEqual(out.manualRecovery.panels.map(p=>[p.id,p.focus]),[[right.id,'true']]);
  const afterManual=(await commandLog()).slice(beforeManual);
  assert.deepEqual(afterManual.filter(c=>c.cmd==='remote_tab_control'&&c.action==='resume').map(c=>c.tabId),[right.id]);
  keyboard.returnHome=await focusByTab('返回主机看板','#view-tabs button:last-child',true);
  await page.keyboard.press('Enter');
  await page.locator('#host-home').waitFor();
  }
  const cmds=await commandLog();
  out.commands=cmds.filter(c=>c.cmd.startsWith('remote_tab_'));
  out.frames=await page.evaluate(()=>window.__frames);
  const renewed=out.frames.find(f=>f.label==='RESUME-3');
  assert.deepEqual([renewed.paneId,renewed.terminalId,renewed.full],['w1:p1','term_a001',true]);
  assert.ok(out.commands.some(c=>c.cmd==='remote_tab_ack'&&c.tabId===renewed.tabId&&c.epoch===renewed.epoch&&c.seq===renewed.seq));
  out.resizeCalls=cmds.filter(c=>[c.cmd,c.action].some(x=>/resize/i.test(x||'')));
  assert.deepEqual(out.resizeCalls,[]);
  assert.equal(cmds.filter(c=>c.cmd==='remote_tab_reserve').length,2);
  assert.deepEqual(cmds.filter(c=>c.cmd==='remote_tab_observe').map(c=>c.canvas),[{cols:80,rows:24},{cols:80,rows:24}]);
  assert.deepEqual(cmds.filter(c=>c.cmd==='remote_tab_select').map(c=>[c.paneId,c.terminalId]),[['w1:p1','term_a001'],['w1:p2','term_b002']]);
  assert.equal(cmds.filter(c=>c.cmd.startsWith('remote_tab_input_')).length,0);
  assert.deepEqual(log,[]);
  out.passed=true;
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
