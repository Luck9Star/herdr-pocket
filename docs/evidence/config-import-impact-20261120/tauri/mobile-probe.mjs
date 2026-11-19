import assert from 'node:assert/strict';
const {chromium, webkit}=await import(process.env.HERDR_D2_PLAYWRIGHT_MODULE || 'playwright');
import {createServer} from 'node:http';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
const site = new URL('./'+process.argv[2]+'/site/', import.meta.url);
const sourceSHA=process.argv[2];
assert.match(sourceSHA,/^(before|after)$/);
const engine=process.env.HERDR_D2_BROWSER==='chromium'?'chromium':'webkit';
const runDir=new URL('./'+sourceSHA+'-'+engine+'-390x844/',import.meta.url);
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
  target:{username:'fixture',host:'203.0.113.18',port:22,session:'beta'}},
 {id:'cccccccccccccccccccccccccccccccc',name:'fixture-gamma',provider:'system',revision:1,enabled:true,
  deviceFingerprint:'SHA256:'+'E'.repeat(43),pairingStatus:'authorized',hostFingerprint:'SHA256:'+'F'.repeat(43),
  target:{username:'fixture',host:'203.0.113.19',port:22,session:'gamma'}}];
const paneOf={aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:{paneId:'w1:p1',terminalId:'term_a001',agent:'alpha',agentStatus:'blocked',title:'alpha shell'},
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
        case 'config_document_open':return [1,2,3];
        case 'config_preview':return {
          ticket:'synthetic-ticket',
          activeHostId:hosts[0].id,
          activeHostIds:[hosts[0].id, hosts[2].id],
          plan:{entries:hosts.map((h,index)=>({
            index, host:{label:'synthetic-import-'+index,target:h.target,provider:h.provider},
            sameLabelIndices:[],conflicts:[{id:h.id,name:h.name,target:h.target,paired:true}],
          })),networks:[],preferences:null},
        };
        case 'network_list':return {profiles:[],preferences:{terminalFontSize:14}};
        case 'remote_tab_reserve':
          tabs.set(tabId,{generation:++nextGeneration,pane:paneOf[hostId],index:0,epoch:1,seq:0,resumes:0});
          return nextGeneration;
        case 'remote_tab_observe':
          tab.channel=args.onEvent.id;
          tab.canvas=canvas;
          window.__lateSnapshot ??= ()=>send({kind:'dashboard_watch', update:{epoch:1,revision:2,phase:'fresh',reason:'late old fixture',panes:[]}});
          setTimeout(()=>{
            observation('starting');
            send({kind:'dashboard_watch',update:{epoch:tab.epoch,revision:1,phase:'fresh',reason:'isolated fixture',panes:[tab.pane]}});
            send({kind:'selection_ready',epoch:tab.epoch});
          },40);
          return new Promise(resolve=>tab.finish=resolve);
        case 'remote_tab_select':
          assertTargetFixture(tab.pane,paneId,terminalId);
          setTimeout(async()=>{await frame('START');observation('active');
            send({kind:'input_ready',epoch:tab.epoch,unknown:false,recovery_status:'ready'});
          },40);
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
const context=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1,isMobile:true,hasTouch:true});
const page=await context.newPage();
page.setDefaultTimeout(7000);
await page.addInitScript(installBridge,{hosts,paneOf,pauseDelay:80});
const pageErrors=[];
page.on('pageerror',error=>pageErrors.push(String(error)));
const out={sourceSHA, engine, browser:browser.version(),
  scope:'Production Tauri frontend in a Playwright browser against simulated native IPC; synthetic file and saved hosts; no SSH or native picker.',
  viewport:{width:390,height:844},pageErrors,clicks:[],impactGeometry:{}};
try {
  await page.goto(base);
  const panel=page.locator('#view-content');
  const beginTab=async (name, resume=false)=>{
    const card=page.locator('#host-list .saved-host-card').filter({hasText:name});
    if (!(await card.locator('details.host-manage').evaluate(e=>e.open))) await card.locator('summary').click();
    await card.getByRole('button',{name:'新终端标签',exact:true}).click();
    await panel.getByRole('button',{name:'连接',exact:true}).waitFor();
    if (resume) {
      await panel.locator('input[type=checkbox]').check();
      await panel.getByRole('button',{name:'连接',exact:true}).click();
      await page.locator('[data-pane-id="w1:p1"]').click();
      await page.waitForFunction(()=>window.__commands.some(c=>c.cmd==='remote_tab_ack'));
      await panel.getByRole('button',{name:'启用草稿输入',exact:true}).click();
      await page.getByText('草稿输入已启用；仅在核对并确认后发送。',{exact:true}).waitFor();
    }
    await page.locator('#host-return-home').click();
  };
  await beginTab('fixture-alpha',true);
  await page.waitForFunction(()=>window.__pauseReplies.length===1);
  await beginTab('fixture-alpha');
  await beginTab('fixture-beta');
  await page.locator('#nav-settings').click();
  await page.locator('#config-transfer-open').click();
  await page.getByRole('button',{name:'选择加密文件',exact:true}).click();
  await page.getByLabel('导入口令',{exact:true}).fill('fixture-example-passphrase');
  await page.getByRole('button',{name:'解密并预览',exact:true}).click();
  const preview=page.locator('.config-preview');
  await preview.getByRole('heading',{name:'逐条审查并选择'}).waitFor();
  const impacts=preview.locator('.config-affected');
  const choice=(i,value)=>preview.locator('input[name=config-choice-'+i+'][value='+value+']');
  out.noSelection=await impacts.innerText();
  const choose=async (i,value)=>{
    const radio=choice(i,value);
    const option=radio.locator('..');
    const scrollBefore=await page.evaluate(()=>scrollY);
    await option.evaluate(node=>node.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'}));
    const metrics=await option.evaluate((label)=>{
      const radio=label.querySelector('input');
      const rect=radio.getBoundingClientRect(), row=label.getBoundingClientRect();
      const x=Math.floor(rect.left+rect.width/2),y=Math.floor(rect.top+rect.height/2);
      const hit=document.elementFromPoint(x,y);
      return {
        x,y,hitOwnRadio:hit===radio,hitOwnLabel:hit===label || label.contains(hit),
        hitTag:hit?.tagName,scrollY,viewport:innerWidth,viewportHeight:innerHeight,
        left:row.left,right:row.right,top:row.top,bottom:row.bottom,
        horizontalOverflow:Math.max(0,-row.left,row.right-innerWidth),
      };
    });
    const record={entry:i,choice:value,scrollBefore,...metrics};
    out.clicks.push(record);
    assert.equal(metrics.viewport,390);
    assert.equal(metrics.viewportHeight,844);
    assert.equal(metrics.hitOwnLabel,true);
    assert.ok(metrics.horizontalOverflow<=2);
    await page.touchscreen.tap(metrics.x,metrics.y);
    record.checked=await radio.isChecked();
    assert.ok(record.checked);
  };
  const mark=async name=>{
    await impacts.evaluate(node=>node.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'}));
    const geometry=await impacts.evaluate(node=>{
      const rect=node.getBoundingClientRect();
      const rails=[...node.querySelectorAll('p,li')];
      if (!rails.length) rails.push(node);
      const lines=rails.flatMap(item=>{
        const range=document.createRange();range.selectNodeContents(item);
        return [...range.getClientRects()].map(line=>{
          const hit=document.elementFromPoint(Math.floor((line.left+line.right)/2),Math.floor((line.top+line.bottom)/2));
          return {left:line.left,right:line.right,top:line.top,bottom:line.bottom,visible:node.contains(hit)};
        });
      });
      const preview=node.closest('.config-preview');
      return {
        visualWidth:visualViewport.width,visualHeight:visualViewport.height,
        scale:visualViewport.scale,scrollY,documentWidth:document.documentElement.scrollWidth,
        rootClientWidth:document.documentElement.clientWidth,previewScrollWidth:preview.scrollWidth,previewClientWidth:preview.clientWidth,
        left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom,
        width:rect.width,height:rect.height,clientWidth:node.clientWidth,scrollWidth:node.scrollWidth,lines,
      };
    });
    out.impactGeometry[name]=geometry;
    await page.screenshot({path:shots+name+'.png'});
    assert.ok(Math.abs(geometry.visualWidth-390)<=2);
    assert.ok(Math.abs(geometry.visualHeight-844)<=2);
    assert.ok(geometry.documentWidth-geometry.rootClientWidth<=2);
    assert.ok(geometry.previewScrollWidth-geometry.previewClientWidth<=2);
    assert.ok(geometry.scrollWidth-geometry.clientWidth<=2);
    assert.ok(geometry.lines.every(line=>line.visible && line.left>=geometry.left-2 && line.right<=geometry.right+2));
  };
  await choose(0,'replace');
  await choose(1,'add');
  out.alphaReplace=await impacts.innerText();
  out.alphaItems=await impacts.getByRole('listitem').allTextContents();
  out.includesOpaqueId=(await preview.innerText()).includes(hosts[0].id);
  out.passwordFieldsEmpty=await page.locator('#config-transfer input[type=password]').evaluateAll(items=>items.every(item=>!item.value));
  await mark('alpha-replace');
  await choose(0,'keep');
  await choose(1,'replace');
  out.betaReplace=await impacts.innerText();
  out.betaItems=await impacts.getByRole('listitem').allTextContents();
  await mark('beta-replace');
  await choose(0,'add');
  await choose(1,'keep');
  await choose(2,'replace');
  out.nativeOwnerOnly=await impacts.innerText();
  out.nativeOwnerItems=await impacts.getByRole('listitem').allTextContents();
  await mark('native-owner-only');
  await choose(2,'keep');
  out.noReplacement=await impacts.innerText();
  await mark('keep-and-add');
  assert.ok(out.clicks.some(click=>Math.abs(click.scrollY-click.scrollBefore)>2));
  out.counts=await page.evaluate(()=>Object.groupBy(window.__commands,c=>c.cmd));
  out.counts=Object.fromEntries(Object.entries(out.counts).map(([command, events])=>[command,events.length]));
  assert.equal(out.counts.remote_tab_observe,1);
  assert.equal(out.counts.remote_tab_control,1);
  assert.equal(out.counts.config_preview,1);
  assert.equal(out.counts.config_apply??0,0);
  assert.equal(out.counts.remote_tab_input_send??0,0);
  assert.ok(out.passwordFieldsEmpty);
  assert.deepEqual(pageErrors,[]);
  if(sourceSHA==='before') {
    assert.deepEqual(out.alphaItems,[]);
    assert.match(out.alphaReplace,/将关闭其标签与连接/);
    assert.match(out.nativeOwnerOnly,/将关闭其标签与连接/);
    assert.deepEqual(out.nativeOwnerItems,[]);
    assert.equal(out.includesOpaqueId,true);
  } else {
    assert.deepEqual(out.alphaItems,[
      'fixture-alpha',
      '标签 1 · fixture-alpha · w1:p1 · 观察已暂停 · 输入已关闭。',
      '标签 2 · fixture-alpha · 选择终端 · 未连接 · 输入已关闭。',
    ]);
    assert.deepEqual(out.betaItems,['标签 3 · fixture-beta · 选择终端 · 未连接 · 输入已关闭。']);
    assert.deepEqual(out.nativeOwnerItems,['fixture-gamma']);
    assert.match(out.nativeOwnerOnly,/停止.*连接[\s\S]*fixture-gamma[\s\S]*没有受影响的工作台标签/);
    assert.doesNotMatch(out.nativeOwnerOnly,/fixture-alpha|fixture-beta|输入已启用|c{32}/);
    assert.doesNotMatch(out.noReplacement,/fixture-alpha|fixture-beta|fixture-gamma/);
    assert.match(out.noSelection,/没有受影响的工作台标签/);
    assert.match(out.noReplacement,/没有受影响的工作台标签/);
    assert.equal(out.includesOpaqueId,false);
  }
  out.passed=true;
  console.log(JSON.stringify(out));
} catch(error) {
  out.error=String(error);out.passed=false;
  console.error(JSON.stringify(out));process.exitCode=1;
} finally {
  await writeFile(new URL('./report.json',runDir),JSON.stringify(out,null,2)+'\n');
  await browser.close();server.close();
}
