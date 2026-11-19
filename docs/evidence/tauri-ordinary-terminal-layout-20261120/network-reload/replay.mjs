import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createServer} from 'node:http';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {dirname,resolve,extname,sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {webkit} from 'playwright';

const here=dirname(fileURLToPath(import.meta.url));
const dist=resolve(process.env.PRODUCT_DIST || 'dist');
const output=resolve(process.env.OUTPUT_DIR || 'output');
const publicPath=process.env.FIXTURE_PUB || resolve(here,'../fixture/host.pub');
const [algorithm,blob]=(await readFile(publicPath,'utf8')).trim().split(/\s+/);
const publicKey=`${algorithm} ${blob}`;
const fingerprint='SHA256:'+createHash('sha256').update(Buffer.from(blob,'base64')).digest('base64').replace(/=$/,'');
const catalog={revision:'fixture-revision',profiles:[],bindings:[],preferences:{terminalFontSize:14}};
const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.ttf':'font/ttf','.json':'application/json'};
const server=createServer(async(req,res)=>{
  const path=resolve(dist,'.'+(req.url==='/'?'/index.html':req.url));
  if(!path.startsWith(dist+sep))return res.writeHead(403).end();
  try {const bytes=await readFile(path);res.writeHead(200,{'content-type':types[extname(path)]||'application/octet-stream'}).end(bytes);}
  catch {res.writeHead(404).end();}
});
await new Promise(done=>server.listen(0,'127.0.0.1',done));
const base=`http://127.0.0.1:${server.address().port}/`, browser=await webkit.launch();
function fixture({publicKey,fingerprint,catalog}) {
  let counter=0;const callbacks=new Map(),audit=[];
  window.isTauri=true;window.__reloadAudit=audit;window.__reloadQueue=[];window.__holdReload=false;
  window.__TAURI_INTERNALS__={
    transformCallback(fn){callbacks.set(++counter,fn);return counter;},unregisterCallback(id){callbacks.delete(id);},
    async invoke(command,args={}) {
      audit.push(command);
      if(command==='config_document_platform')return 'macos';
      if(command==='host_init')return;
      if(command==='host_list')return [];
      if(command==='network_list')return window.__holdReload ? await new Promise((resolve,reject)=>window.__reloadQueue.push({resolve,reject})) : catalog;
      if(command==='ssh_host_key_probe')return {...args,publicKey,fingerprint};
      if(command==='ssh_shell_open') {
        const c=args.config;
        if(c.host!=='127.0.0.1'||c.port!==49821||c.username!=='fixture'||!c.reviewConfirmed||c.expectedHostKey!==publicKey||!c.password||c.privateKeyPem)throw Error('unexpected authentication');
        callbacks.get(args.onEvent.id)({index:0,message:{sessionId:'fixture-session',seq:1,kind:'ready'}});
        return 'fixture-session';
      }
      if(command==='ssh_shell_resize'||command==='ssh_shell_ack'||command==='ssh_shell_close')return;
      throw Error('unexpected IPC: '+command);
    }
  };
}
await mkdir(output,{recursive:true});
const context=await browser.newContext({viewport:{width:980,height:780},deviceScaleFactor:1,locale:'zh-CN'}),page=await context.newPage();
const result={viewport:[980,780],engine:'Playwright WebKit '+browser.version(),fixture:'loopback HTTP and synthetic IPC; no real SSH or network catalog',states:{},checks:{},errors:[]};
page.on('pageerror',error=>result.errors.push(error.message));
await context.route('**/*',route=>route.request().url().startsWith(base)?route.continue():route.abort());
await page.addInitScript(fixture,{publicKey,fingerprint,catalog});page.setDefaultTimeout(7000);
const id=name=>page.locator('#'+name);
async function capture(name) {
  await page.evaluate(async()=>{await document.fonts.ready;await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));});
  const png=await page.screenshot({path:resolve(output,name+'.png'),animations:'disabled',scale:'css'});
  result.states[name]={sha256:createHash('sha256').update(png).digest('hex'),
    cardCount:await page.locator('#network-empty-card').count(),panelText:await id('network-panel').innerText()};
}
async function resizeAcrossBreakpoint() {
  await page.setViewportSize({width:590,height:780});await page.waitForTimeout(150);
  await page.setViewportSize({width:980,height:780});await page.waitForTimeout(150);
}
try {
  await page.goto(base);await id('host-empty-add').click();await id('add-ssh').click();
  await id('ssh-host').fill('127.0.0.1');await id('ssh-user').fill('fixture');await id('ssh-port').fill('49821');
  await id('ssh-probe').click();assert.equal((await id('ssh-reviewed-fingerprint').innerText()).replace(/\s/g,''),fingerprint);
  await id('ssh-trust-confirm').click();await id('ssh-password').fill('temporary-fixture');await id('ssh-connect').click();await id('ssh-live').waitFor();
  await id('nav-network').click();await page.locator('#network-empty-card').waitFor();
  await id('nav-terminal').click();await page.evaluate(()=>window.__holdReload=true);await id('nav-network').click();
  await page.waitForFunction(()=>document.querySelector('#network-panel').innerText.includes('正在读取网络配置'));
  await resizeAcrossBreakpoint();await capture('pending-resize');
  if(process.env.EXPECT_REPRO==='1') {
    assert.equal(result.states['pending-resize'].cardCount,1,'baseline must reproduce old empty card');
    result.checks.baselineReproduced=true;
  } else {
    assert.equal(result.states['pending-resize'].cardCount,0,'pending read must not publish old empty card');
    assert.equal(await page.getByRole('button',{name:'添加网络配置',exact:true}).count(),0);
    await page.evaluate(c=>window.__reloadQueue.shift().resolve(c),catalog);await page.locator('#network-empty-card').waitFor();await capture('fresh-empty');
    await id('nav-terminal').click();await id('nav-network').click();await page.waitForFunction(()=>window.__reloadQueue.length===1);
    await id('nav-terminal').click();await id('nav-network').click();await page.waitForFunction(()=>window.__reloadQueue.length===2);
    await page.evaluate(c=>window.__reloadQueue.shift().resolve({...c,revision:'retired'}),catalog);await page.waitForTimeout(150);
    assert.equal(await page.locator('#network-empty-card').count(),0,'retired response must not publish');
    await page.evaluate(()=>window.__reloadQueue.shift().reject(Error('fixture unavailable')));
    await page.waitForFunction(()=>document.querySelector('#network-panel').innerText.includes('网络配置读取失败'));
    await resizeAcrossBreakpoint();await capture('failed-resize');
    assert.equal(result.states['failed-resize'].cardCount,0,'failure must remain unknown');
    result.checks={pendingProtected:true,freshReadPublished:true,retiredReplyIgnored:true,failureRemainsUnknown:true};
  }
  const calls=await page.evaluate(()=>window.__reloadAudit);
  assert.equal(calls.filter(x=>x==='ssh_shell_open').length,1);
  assert.equal(calls.filter(x=>x==='ssh_shell_write'||x==='ssh_shell_close').length,0);
  assert.deepEqual(result.errors,[]);result.passed=true;
} catch(error) {result.failed=String(error.stack);await page.screenshot({path:resolve(output,'failure.png')}).catch(()=>{});process.exitCode=1;}
finally {await writeFile(resolve(output,'geometry.json'),JSON.stringify(result,null,2)+'\n');await context.close();await browser.close();await new Promise(done=>server.close(done));}
