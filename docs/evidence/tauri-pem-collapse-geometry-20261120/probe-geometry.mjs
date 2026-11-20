import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {join, extname} from 'node:path';
const playwrightModule=process.env.PLAYWRIGHT_MODULE;
if(!playwrightModule) throw Error('usage: PLAYWRIGHT_MODULE=<playwright-module> R12_APP=<bundle-dir> R12_APP_SOURCE=<git-ref> node probe-geometry.mjs <output-dir>');
const {webkit}=await import(playwrightModule);
const app=process.env.R12_APP;
const appSourceRef=process.env.R12_APP_SOURCE;
const outDir=process.argv[2];
if(!app || !appSourceRef || !outDir) throw Error('usage: PLAYWRIGHT_MODULE=<playwright-module> R12_APP=<bundle-dir> R12_APP_SOURCE=<git-ref> node probe-geometry.mjs <output-dir>');
await mkdir(outDir,{recursive:true});
const mime={'.html':'text/html','.css':'text/css','.js':'text/javascript','.json':'application/json','.ttf':'font/ttf','.svg':'image/svg+xml','.woff2':'font/woff2'};
const server=createServer(async(req,res)=>{
  try{
    const path=new URL(req.url,'http://localhost').pathname;
    const relative=path==='/'?'index.html':path.slice(1);
    const body=await readFile(join(app,relative));
    res.setHeader('Content-Type',mime[extname(relative)]||'application/octet-stream');
    res.end(body);
  }catch{res.statusCode=404;res.end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const base='http://127.0.0.1:'+server.address().port;
const browser=await webkit.launch();
const expected={
  mobile:{viewport:{width:390,height:844},safeTop:47,safeBottom:34,anchors:{
    summary:{x:24,y:351,width:342,height:84},
    paste:{x:24,y:445,width:342,height:48},
    passphrase:{x:24,y:527,width:342,height:48},
    connect:{x:24,y:589,width:342,height:48},
  }},
  desktop:{viewport:{width:980,height:780},safeTop:0,safeBottom:0,anchors:{
    summary:{x:264,y:304,width:560,height:84},
    paste:{x:264,y:398,width:560,height:48},
    passphrase:{x:264,y:480,width:560,height:48},
    connect:{x:264,y:542,width:560,height:48},
  }},
};
const selectors={summary:'#ssh-key-summary',paste:'#ssh-paste-key',passphrase:'#ssh-passphrase',connect:'#ssh-connect'};

async function run(kind){
  const config=expected[kind];
  const context=await browser.newContext({
    viewport:config.viewport,deviceScaleFactor:1,
    isMobile:kind==='mobile',hasTouch:kind==='mobile',locale:'zh-CN',
  });
  const page=await context.newPage();
  page.setDefaultTimeout(8000);
  page.on('pageerror',error=>console.error(kind,'page error',error.message));
  await context.route('**/*',async route=>{
    const url=route.request().url();
    if(!url.startsWith(base+'/'))return route.abort();
    if(!url.endsWith('.css'))return route.continue();
    const response=await route.fetch();
    const body=(await response.text()).replace(/env\(safe-area-inset-(top|bottom)(?:,\s*0px)?\)/g,(_,side)=>String(side==='top'?config.safeTop:config.safeBottom)+'px');
    return route.fulfill({response,body});
  });
  await page.addInitScript(({platform,safeTop})=>{
    window.isTauri=true;
    window.__TAURI_INTERNALS__={
      async invoke(command,args={}){
        switch(command){
          case 'config_document_platform':return platform;
          case 'mobile_system_top_inset':return {overlapPx:safeTop};
          case 'network_list':return {profiles:[],bindings:[],revision:0,preferences:{terminalFontSize:14}};
          case 'host_list':return [];
          case 'ssh_host_key_probe':return {...args,publicKey:'ssh-ed25519 PUBLIC-SYNTHETIC-R12',fingerprint:'SHA256:PUBLIC-SYNTHETIC-R12'};
          default:return [];
        }
      },
    };
    Object.defineProperty(navigator.clipboard,'readText',{value:async()=>'PUBLIC-SYNTHETIC-CLIPBOARD-R12'});
  },{platform:kind==='mobile'?'ios':'macos',safeTop:config.safeTop});
  await page.goto(base,{waitUntil:'domcontentloaded'});
  await page.locator('#host-empty').waitFor();
  await page.locator('#home-open-ssh').click();
  await page.locator('#ssh-host').fill('ssh.example.test');
  await page.locator('#ssh-user').fill('demo');
  await page.locator('#ssh-port').fill('22');
  await page.locator('#ssh-probe').click();
  const confirm=page.locator('#ssh-trust-confirm');
  if(!(await confirm.isVisible())){
    const screenshot=join(outDir,`pem-current-${kind}-blocked-${config.viewport.width}.png`);
    await page.screenshot({path:screenshot});
    await context.close();
    return {
      kind,viewport:config.viewport,blocked:true,
      blockedReason:'visible entry and probe completed, but the visible fingerprint confirmation control did not appear',
      screenshot,
    };
  }
  await confirm.click();
  console.log(kind,'state',await page.evaluate(()=>({
    width:innerWidth,platform:document.documentElement.className,
    homeHidden:document.querySelector('#host-home')?.hidden,
    setupHidden:document.querySelector('#ssh-setup')?.hidden,
    credentialsHidden:document.querySelector('#ssh-credentials')?.hidden,
    step:document.querySelector('#home-ssh')?.dataset.sshStep,
    reviewChecked:document.querySelector('#ssh-review')?.checked,
    reviewDisabled:document.querySelector('#ssh-review')?.disabled,
    authHidden:document.querySelector('#ssh-auth-key')?.hidden,
    authDisabled:document.querySelector('#ssh-auth-key')?.disabled,
    authMethodDisplay:getComputedStyle(document.querySelector('#ssh-auth-method')).display,
    credentialsDisplay:getComputedStyle(document.querySelector('#ssh-credentials')).display,
    keyFieldsHidden:document.querySelector('#ssh-key-fields')?.hidden,
  })));
  await page.locator('#ssh-auth-key').click();
  await page.locator('#ssh-key').fill('PUBLIC-SYNTHETIC-DRAFT-R12');
  await page.locator('#ssh-passphrase').click();
  await page.locator(selectors.summary).waitFor({state:'visible'});
  assert.equal(await page.locator('#ssh-key').isHidden(),true);
  assert.equal(await page.locator('#ssh-key').inputValue(), '');
  assert.equal(await page.locator(selectors.summary).innerText(),'已填写私钥 · 重新编辑');
  await page.locator(selectors.summary).click();
  assert.equal(await page.locator('#ssh-key').isVisible(),true);
  assert.equal(await page.locator('#ssh-key').inputValue(),'PUBLIC-SYNTHETIC-DRAFT-R12');
  await page.locator(selectors.paste).click();
  await page.locator(selectors.summary).waitFor({state:'visible'});
  assert.equal(await page.locator('#ssh-key').isHidden(),true);
  assert.equal(await page.locator('#ssh-key').inputValue(), '');
  assert.equal(await page.evaluate(()=>document.activeElement?.id),'ssh-paste-key');
  await page.locator(selectors.passphrase).fill('PUBLIC-SYNTHETIC-PASSPHRASE-R12');
  await page.locator(selectors.paste).click();
  await page.evaluate(async()=>{await document.fonts.ready;await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));});
  console.log(kind,'layout',await page.evaluate(()=>{
    const pick=id=>{const el=document.querySelector(id);if(!el)return null;const r=el.getBoundingClientRect();return{x:r.left+scrollX,y:r.top+scrollY,w:r.width,h:r.height,hidden:el.hidden,display:getComputedStyle(el).display};};
    return {scrollY,home:pick('#host-home'),ssh:pick('#home-ssh'),setup:pick('#ssh-setup'),form:pick('#ssh-form'),credentials:pick('#ssh-credentials'),target:pick('#ssh-target-fields'),approved:pick('#ssh-approved-note'),auth:pick('#ssh-auth-options'),fields:pick('#ssh-key-fields'),summary:pick('#ssh-key-summary')};
  }));
  const measured={};
  for(const [name,selector] of Object.entries(selectors)){
    const box=await page.evaluate(selector=>{
      const rect=document.querySelector(selector).getBoundingClientRect();
      return {x:rect.left+window.scrollX,y:rect.top+window.scrollY,width:rect.width,height:rect.height};
    },selector);
    assert(box,name+' has no box');
    const want=config.anchors[name];
    measured[name]={...box,expected:{...want},delta:{
      x:Math.round((box.x-want.x)*10)/10,
      y:Math.round((box.y-want.y)*10)/10,
      width:Math.round((box.width-want.width)*10)/10,
      height:Math.round((box.height-want.height)*10)/10,
    }};
    measured[name].withinTolerance=Object.values(measured[name].delta).every(value=>Math.abs(value)<=2);
  }
  measured.summaryStyle=await page.evaluate(()=>{
    const element=document.querySelector('#ssh-key-summary');
    const styles=getComputedStyle(element);
    const range=document.createRange();
    range.selectNodeContents(element);
    const text=range.getBoundingClientRect();
    const box=element.getBoundingClientRect();
    return {
      borderRadius:styles.borderTopLeftRadius,
      color:styles.color,
      textAlign:styles.textAlign,
      textCenterX:Math.round((text.left+text.width/2+window.scrollX)*10)/10,
      summaryCenterX:Math.round((box.left+box.width/2+window.scrollX)*10)/10,
      expected:{borderRadius:'42px',color:'rgb(79, 70, 229)',textAlign:'center'},
    };
  });
  measured.summary.clickable=await page.locator(selectors.summary).isEnabled();
  measured.paste.clickable=await page.locator(selectors.paste).isEnabled();
  measured.passphrase.clickable=await page.locator(selectors.passphrase).isEnabled();
  measured.connect.disabled=await page.locator(selectors.connect).isDisabled();
  assert(measured.summary.clickable&&measured.paste.clickable&&measured.passphrase.clickable);
  assert(measured.connect.disabled);
  const screenshot=join(outDir,`pem-collapsed-${config.viewport.width}.png`);
  await page.screenshot({path:screenshot});
  await context.close();
  return {kind,viewport:config.viewport,safeArea:{top:config.safeTop,bottom:config.safeBottom},anchors:measured,screenshot};
}

const results=[];
try{
  results.push(await run('mobile'));
  results.push(await run('desktop'));
  const report={
    appSourceRef,
    engine:'playwright-webkit',
    engineVersion:browser.version(),
    mode:'CSS/DOM simulation in WebKit; safe-area insets substituted in CSS; no native iOS keyboard or simulator',
    designSource:{commit:'6fac813',boards:['private-key-collapsed-390','private-key-collapsed-980'],tolerance:2},
    syntheticMaterial:'PUBLIC-SYNTHETIC-DRAFT-R12 / PUBLIC-SYNTHETIC-CLIPBOARD-R12 / PUBLIC-SYNTHETIC-PASSPHRASE-R12; screenshots contain no PEM body',
    results,
  };
  await writeFile(join(outDir,'geometry.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
}finally{
  await browser.close();
  await new Promise(resolve=>server.close(resolve));
}
