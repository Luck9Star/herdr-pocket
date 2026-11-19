import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createServer} from 'node:http';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {resolve, dirname, extname, sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {webkit} from 'playwright';
const root=dirname(fileURLToPath(import.meta.url));
const dist=resolve(process.env.FEEDBACK_PRODUCT_DIST || 'dist');
const output=resolve(process.env.FEEDBACK_EVIDENCE || 'auth-evidence');
const [algorithm,blob]=(await readFile(resolve(root,'fixture/host.pub'),'utf8')).trim().split(/\s+/);
const publicKey=`${algorithm} ${blob}`;
const fingerprint='SHA256:'+createHash('sha256').update(Buffer.from(blob,'base64')).digest('base64').replace(/=$/,'');
const key=await readFile(resolve(root,'fixture/client'),'utf8');
const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.ttf':'font/ttf','.json':'application/json'};
const server=createServer(async(req,res)=>{const path=resolve(dist,'.'+(req.url==='/'?'/index.html':req.url));
  if(!path.startsWith(dist+sep)) return res.writeHead(403).end();
  try {res.writeHead(200,{'content-type':mime[extname(path)]||'application/octet-stream'}).end(await readFile(path));} catch {res.writeHead(404).end();}
});
await new Promise(done=>server.listen(0,'127.0.0.1',done));
const base=`http://127.0.0.1:${server.address().port}/`;
const browser=await webkit.launch();
function fixture({host,publicKey,fingerprint,mode}) {
  const callbacks=new Map(), audit={events:[],unknown:[],reasons:[]}; let counter=0,openCount=0;
  window.isTauri=true; window.__AUTH_AUDIT__=audit;
  const check=(ok,reason)=>{if(!ok){audit.reasons.push(reason);throw Error(reason);}};
  window.__TAURI_INTERNALS__={transformCallback(fn){callbacks.set(++counter,fn);return counter;},unregisterCallback(id){callbacks.delete(id);},
    async invoke(command,args={}) {
      const event={command}; audit.events.push(event);
      if(command==='config_document_platform')return 'macos';
      if(command==='host_init')return;
      if(command==='host_list')return [];
      if(command==='network_list')return {revision:0,profiles:[],preferences:{terminalFontSize:14}};
      if(command==='ssh_host_key_probe') {check(args.host===host&&args.port===49821&&Object.keys(args).length===2,'probe-target');return {...args,publicKey,fingerprint};}
      if(command==='ssh_shell_open') {
        const c=args.config; check(c.host===host&&c.port===49821&&c.username==='fixture'&&c.reviewConfirmed&&c.expectedHostKey===publicKey,'open-target-and-pin');
        const usingKey=typeof c.privateKeyPem==='string'&&/^-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----/.test(c.privateKeyPem);
        check(mode.startsWith('key') ? usingKey&&!c.password : !!c.password&&!usingKey,'single-credential');
        event.auth=usingKey?'key':'password'; event.sessionId='fixture-'+(++openCount);
        const callback=callbacks.get(args.onEvent.id); check(!!callback,'channel');
        const send=(seq,kind,extra={})=>callback({index:seq-1,message:{sessionId:event.sessionId,seq,kind,...extra}});
        if(mode==='mismatch'&&openCount===1) {send(1,'host_key_change',{presentedFingerprint:'SHA256:fixtureChanged'});send(2,'error',{error:'host_key_mismatch'});}
        else {send(1,'ready');send(2,'data',{data:Array.from(new TextEncoder().encode('fixture ready\r\n$ '))});}
        return event.sessionId;
      }
      if(command==='ssh_shell_close') {event.sessionId=args.sessionId;if(mode==='close-failed')throw Error('fixture close failed');if(mode==='close-pending')await new Promise(resolve=>window.__finishClose=resolve);return null;}
      if(['ssh_shell_resize','ssh_shell_ack'].includes(command)) {event.sessionId=args.sessionId;return null;}
      audit.unknown.push(command); throw Error('unknown-fixture-command');
    }};
}
const selectors={back:'#ssh-step-back',host:'#ssh-host',username:'#ssh-user',port:'#ssh-port',probe:'#ssh-probe',target:'#ssh-reviewed-target',key:'#ssh-reviewed-key',fingerprint:'#ssh-reviewed-fingerprint',independent:'#ssh-independent-verification',confirm:'#ssh-trust-confirm',cancel:'#ssh-trust-cancel',passwordChoice:'#ssh-auth-password',keyChoice:'#ssh-auth-key',password:'#ssh-password',privateKey:'#ssh-key',paste:'#ssh-paste-key',passphrase:'#ssh-passphrase',connect:'#ssh-connect',sidebar:'.route-tabs',toggle:'#sidebar-toggle'};
async function run(width,height,mode='password') {
  const name=`${width}x${height}-${mode}`,folder=resolve(output,name);await mkdir(folder,{recursive:true});
  const context=await browser.newContext({viewport:{width,height},deviceScaleFactor:1,locale:'zh-CN'}),page=await context.newPage();
  const host=(mode==='key-long'||mode==='mismatch')?'very-long-hostname-for-terminal-acceptance.infrastructure-staging.example.test':'127.0.0.1';
  const result={viewport:[width,height],engine:'Playwright WebKit '+browser.version(),fixture:'loopback HTTP and synthetic IPC; no real SSH',mode,states:{},checks:{},errors:[]};
  page.on('pageerror',e=>result.errors.push(e.message));await context.route('**/*',r=>r.request().url().startsWith(base)?r.continue():r.abort());
  await page.addInitScript(fixture,{host,publicKey,fingerprint,mode});page.setDefaultTimeout(7000);
  const el=id=>page.locator('#'+id), audit=()=>page.evaluate(()=>window.__AUTH_AUDIT__);
  async function shot(state) {
    await page.evaluate(async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));});
    await page.screenshot({path:resolve(folder,state+'.png'),animations:'disabled',scale:'css'});
    result.states[state]=await page.evaluate(selectors=>Object.fromEntries(Object.entries(selectors).map(([name,selector])=>{
      const e=document.querySelector(selector),r=e.getBoundingClientRect(),c=getComputedStyle(e),x=r.x+r.width/2,y=r.y+r.height/2,p=document.elementFromPoint(x,y);
      return [name,{rect:[r.x,r.y,r.width,r.height],visible:!!r.width&&!!r.height&&c.visibility==='visible',hit:!!p&&(p===e||e.contains(p)),disabled:e.matches(':disabled')}];
    })),selectors);
  }
  const near=(got,want)=>assert(got.every((n,i)=>Math.abs(n-want[i])<=2),`${got} != ${want}`);
  try {
    await page.goto(base);if(width<600)await page.addStyleTag({content:`:root{--hp-system-top-inset:${width===390?47:24}px!important}`});
    await el('host-empty-add').click(); await el('add-ssh').click();
    await el('ssh-host').fill(host);await el('ssh-user').fill('fixture');await el('ssh-port').fill('49821');await shot('target');
    const x=width>=960?264:width>=600?104:width===390?24:16,span=width>=600?Math.min(560,width-x-40):width-2*x,top=width>=600?0:width===390?47:24;
    near(result.states.target.host.rect,[x,top+134,span,48]);near(result.states.target.port.rect,[x+span-84,top+218,84,48]);
    assert(await el('ssh-port').evaluate(e=>e.value==='49821'&&e.scrollWidth<=e.clientWidth),'five-digit port must fit');
    await el('ssh-probe').click();await el('ssh-trust-confirm').waitFor();await shot('trust');
    assert.equal((await el('ssh-reviewed-fingerprint').innerText()).replace(/\s/g,''),fingerprint);
    assert.equal(await el('ssh-reviewed-endpoint').innerText(),`fixture@${host}:49821`);
    const fragments=await el('ssh-reviewed-fingerprint').evaluate(e=>{const r=document.createRange();r.selectNodeContents(e);return [...r.getClientRects()].map(b=>{const p=document.elementFromPoint(b.x+b.width/2,b.y+b.height/2);return {rect:[b.x,b.y,b.width,b.height],visible:b.x>=0&&b.y>=0&&b.right<=innerWidth&&b.bottom<=innerHeight&&e.contains(p)};});});
    assert(fragments.length>0&&fragments.every(f=>f.visible),'complete fingerprint must remain visible');result.checks.fingerprintFragments=fragments;
    if(mode==='password') {near(result.states.trust.target.rect,[x,top+76,span,52]);near(result.states.trust.key.rect,[x,top+140,span,122]);}
    assert.equal((await audit()).events.filter(e=>e.command==='ssh_shell_open').length,0);
    await el('ssh-trust-confirm').click();await shot('auth');
    if(mode==='password') {const y=top+(width===320?296:304);near(result.states.auth.password.rect,[x,y,span,48]);near(result.states.auth.connect.rect,[x,y+62,span,48]);}

    if(mode.startsWith('key')) {
      await el('ssh-password').fill('temporary-discarded');await el('ssh-auth-key').click();
      assert.equal(await el('ssh-password').inputValue(),'');await shot('private-key');
      if(mode==='key') {const y=top+(width===320?296:304),h=width===320?68:84;near(result.states['private-key'].privateKey.rect,[x,y,span,h]);near(result.states['private-key'].paste.rect,[x,y+h+10,span,48]);near(result.states['private-key'].connect.rect,[x,y+h+154,span,48]);}
      await el('ssh-key').fill('invalid');assert(await el('ssh-connect').isDisabled());
      await el('ssh-key').fill(key);
    } else await el('ssh-password').fill('temporary-fixture-only');
    if(mode==='password'&&width===700) {
      await el('ssh-password').focus();await page.setViewportSize({width:390,height:844});
      assert(await el('ssh-password').evaluate(e=>document.activeElement===e));assert.equal(await el('ssh-password').inputValue(),'temporary-fixture-only');await shot('resize-mobile');
      await page.setViewportSize({width,height});assert(await el('ssh-password').evaluate(e=>document.activeElement===e));assert.equal(await el('ssh-password').inputValue(),'temporary-fixture-only');await shot('resize-restored');
      result.checks.resizePreservedActivePassword=true;
    }
    await el('ssh-connect').click();
    if(mode==='mismatch') {
      await el('ssh-key-change').waitFor();await shot('key-changed');await el('ssh-key-cancel').click();await shot('retained');
      assert.match(await el('ssh-prior-fingerprint').innerText(),new RegExp(fingerprint.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
      await el('ssh-probe').click();await el('ssh-trust-cancel').waitFor();
      assert.match(await el('ssh-trust-cancel').innerText(),/保留旧信任/);await shot('recheck');await el('ssh-trust-cancel').click();await shot('recheck-cancel');
      assert.match(await el('ssh-prior-fingerprint').innerText(),/保留的旧指纹/);
      assert.equal((await audit()).events.filter(e=>e.command==='ssh_shell_open').length,1);
      await el('ssh-probe').click();await el('ssh-trust-confirm').click();await el('ssh-password').fill('temporary-fixture-only');await el('ssh-connect').click();
    }
    await el('ssh-live').waitFor();await shot('connected');
    await el('ssh-disconnect').click();await el('ssh-return-home').waitFor();await shot('disconnected');
    const phase=mode==='close-failed'?'failed':mode==='close-pending'?'pending':'confirmed';
    await page.waitForFunction(phase=>document.getElementById('ssh-closed-feedback').dataset.phase===phase,phase);
    assert.equal(await el('ssh-closed-feedback').getAttribute('data-phase'),phase);
    const color=await el('ssh-closed-feedback').evaluate(e=>getComputedStyle(e).backgroundColor);
    assert.equal(color,phase==='failed'?'rgb(255, 241, 242)':phase==='pending'?'rgb(241, 245, 249)':'rgb(238, 242, 255)');
    assert(await page.locator('#ssh-password,#ssh-key,#ssh-passphrase').evaluateAll(es=>es.every(e=>!e.value)));
    await el('ssh-return-home').click();await el('host-ssh-disconnected').waitFor();await shot('returned');
    assert.equal(await el('host-ssh-disconnected').getAttribute('data-phase'),phase);
    if(phase==='pending') {await page.evaluate(()=>window.__finishClose());await page.waitForFunction(()=>document.getElementById('host-ssh-disconnected').dataset.phase==='confirmed');await shot('returned-confirmed');}
    const a=await audit();
    assert.equal(a.events.filter(e=>e.command==='ssh_shell_close').length,mode==='mismatch'?2:1);
assert.equal(a.events.filter(e=>e.command==='ssh_shell_open').length,mode==='mismatch'?2:1);
    assert.equal(a.events.filter(e=>e.command==='ssh_host_key_probe').length,mode==='mismatch'?3:1);
    assert.deepEqual(a.reasons,[]);assert.deepEqual(a.unknown,[]);assert.deepEqual(result.errors,[]);
    result.checks={...result.checks,fingerprintExact:true,opens:a.events.filter(e=>e.command==='ssh_shell_open'),probes:a.events.filter(e=>e.command==='ssh_host_key_probe').length,port:49821};result.ipc=a;result.passed=true;
  } catch(e) {result.failed=String(e.stack);await page.screenshot({path:resolve(folder,'failure.png')}).catch(()=>{});}
  result.ipc ??= await audit().catch(()=>null);
  await writeFile(resolve(folder,'geometry.json'),JSON.stringify(result,null,2)+'\n');console.log(name,result.passed?'PASS':result.failed);await context.close();return !!result.passed;
}
try {let ok=true;for(const [w,h] of [[1440,900],[980,780],[700,900],[390,844],[320,640]])if(!await run(w,h))ok=false;
  for(const [w,h] of [[1440,900],[980,780],[700,900],[390,844],[320,640]])if(!await run(w,h,'key'))ok=false;
  if(!await run(700,900,'key-long'))ok=false;
  if(!await run(700,900,'mismatch'))ok=false;
  if(!await run(700,900,'close-failed'))ok=false;
  if(!await run(700,900,'close-pending'))ok=false;if(!ok)process.exitCode=1;
} finally {await browser.close();await new Promise(done=>server.close(done));}
