import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {join, extname} from 'node:path';
const playwrightModule=process.env.PLAYWRIGHT_MODULE;
if(!playwrightModule) throw Error('usage: PLAYWRIGHT_MODULE=<playwright-module> R12_APP=<bundle-dir> R12_APP_SOURCE=<git-ref> R12_VARIANT=<baseline|current> node probe-behavior.mjs <output-dir>');
const {webkit}=await import(playwrightModule);
const app=process.env.R12_APP;
const appSourceRef=process.env.R12_APP_SOURCE;
const variant=process.env.R12_VARIANT;
const outDir=process.argv[2];
if(!app || !appSourceRef || !variant || !outDir) throw Error('usage: PLAYWRIGHT_MODULE=<playwright-module> R12_APP=<bundle-dir> R12_APP_SOURCE=<git-ref> R12_VARIANT=<baseline|current> node probe-behavior.mjs <output-dir>');
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
    target:{x:24,y:351,width:342,height:84},
    paste:{x:24,y:445,width:342,height:48},
    passphrase:{x:24,y:527,width:342,height:48},
    connect:{x:24,y:589,width:342,height:48},
  }},
  desktop:{viewport:{width:980,height:780},safeTop:0,safeBottom:0,anchors:{
    target:{x:264,y:304,width:560,height:84},
    paste:{x:264,y:398,width:560,height:48},
    passphrase:{x:264,y:480,width:560,height:48},
    connect:{x:264,y:542,width:560,height:48},
  }},
};

async function state(page){
  return await page.evaluate(()=>{
    const editor=document.querySelector('#ssh-key');
    const summary=document.querySelector('#ssh-key-summary');
    const paste=document.querySelector('#ssh-paste-key');
    const passphrase=document.querySelector('#ssh-passphrase');
    const connect=document.querySelector('#ssh-connect');
    const visible=element=>!!(element&&element.getClientRects().length&&getComputedStyle(element).visibility!=='hidden'&&getComputedStyle(element).display!=='none');
    return {
      activeElement:document.activeElement?.id??null,
      editorVisible:visible(editor),
      editorValue:editor?.value??null,
      summaryVisible:visible(summary),
      summaryText:summary?.textContent?.trim()??null,
      pasteVisible:visible(paste),
      passphraseVisible:visible(passphrase),
      connectDisabled:connect?.disabled??null,
      bodyContainsDraft:document.body.innerText.includes('PUBLIC-SYNTHETIC-DRAFT-R12'),
      bodyContainsClipboard:document.body.innerText.includes('PUBLIC-SYNTHETIC-CLIPBOARD-R12'),
    };
  });
}

async function run(kind){
  const config=expected[kind];
  const context=await browser.newContext({
    viewport:config.viewport,deviceScaleFactor:1,
    isMobile:kind==='mobile',hasTouch:kind==='mobile',locale:'zh-CN',
  });
  const page=await context.newPage();
  page.setDefaultTimeout(8000);
  page.on('pageerror',error=>console.error(variant,kind,'page error',error.message));
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
    const blockedShot=join(outDir,`pem-${variant}-${kind}-blocked-${config.viewport.width}.png`);
    await page.screenshot({path:blockedShot});
    await context.close();
    return {
      kind,viewport:config.viewport,variant,blocked:true,
      blockedReason:'visible entry and probe completed, but the visible fingerprint confirmation control did not appear',
      screenshot:blockedShot,
    };
  }
  await confirm.click();
  await page.evaluate(async()=>{await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));});
  await page.locator('#ssh-auth-key').click();
  await page.locator('#ssh-key').fill('PUBLIC-SYNTHETIC-DRAFT-R12');

  await page.locator('#ssh-passphrase').click();
  await page.evaluate(async()=>{await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));});
  const afterBlur=await state(page);
  const blurShot=join(outDir,variant==='current'?`pem-blur-current-${config.viewport.width}.png`:`pem-baseline-editor-visible-${config.viewport.width}.png`);
  await page.screenshot({path:blurShot});
  if(variant==='current'){
    assert.equal(afterBlur.editorVisible,false);
    assert.equal(afterBlur.editorValue,'');
    assert.equal(afterBlur.summaryVisible,true);
    assert.equal(afterBlur.summaryText,'已填写私钥 · 重新编辑');
    assert.equal(afterBlur.bodyContainsDraft,false);
  }else{
    assert.equal(afterBlur.editorVisible,true);
    assert.equal(afterBlur.editorValue,'PUBLIC-SYNTHETIC-DRAFT-R12');
    assert.equal(afterBlur.summaryVisible,false);
    assert.equal(afterBlur.bodyContainsDraft,false);
  }

  let afterReopen;
  const reopenShot=join(outDir,variant==='current'?`pem-reopen-current-${config.viewport.width}.png`:`pem-baseline-reopen-${config.viewport.width}.png`);
  if(variant==='current'){
    await page.locator('#ssh-key-summary').click();
    afterReopen=await state(page);
    await page.screenshot({path:reopenShot});
    assert.equal(afterReopen.editorVisible,true);
    assert.equal(afterReopen.editorValue,'PUBLIC-SYNTHETIC-DRAFT-R12');
    assert.equal(afterReopen.summaryVisible,false);
  }else{
    await page.locator('#ssh-key').click();
    afterReopen=await state(page);
    await page.screenshot({path:reopenShot});
    assert.equal(afterReopen.editorVisible,true);
    assert.equal(afterReopen.editorValue,'PUBLIC-SYNTHETIC-DRAFT-R12');
  }

  await page.locator('#ssh-paste-key').click();
  await page.evaluate(async()=>{await document.fonts.ready;await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));});
  const afterPaste=await state(page);
  const finalShot=join(outDir,variant==='current'?`pem-final-current-${config.viewport.width}.png`:`pem-baseline-paste-${config.viewport.width}.png`);
  await page.screenshot({path:finalShot});
  if(variant==='current'){
    assert.equal(afterPaste.editorVisible,false);
    assert.equal(afterPaste.editorValue,'');
    assert.equal(afterPaste.summaryVisible,true);
    assert.equal(afterPaste.activeElement,'ssh-paste-key');
    assert.equal(afterPaste.bodyContainsClipboard,false);
  }else{
    assert.equal(afterPaste.editorVisible,true);
    assert.equal(afterPaste.editorValue,'PUBLIC-SYNTHETIC-CLIPBOARD-R12');
    assert.equal(afterPaste.activeElement!==null,true);
  }
  await page.locator('#ssh-passphrase').fill('PUBLIC-SYNTHETIC-PASSPHRASE-R12');

  const targetSelector=variant==='current'?'#ssh-key-summary':'#ssh-key';
  const selectors={target:targetSelector,paste:'#ssh-paste-key',passphrase:'#ssh-passphrase',connect:'#ssh-connect'};
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
  measured.target.clickable=await page.locator(targetSelector).isEnabled();
  measured.paste.clickable=await page.locator('#ssh-paste-key').isEnabled();
  measured.passphrase.clickable=await page.locator('#ssh-passphrase').isEnabled();
  measured.connect.disabled=await page.locator('#ssh-connect').isDisabled();
  assert(measured.target.clickable&&measured.paste.clickable&&measured.passphrase.clickable);
  assert(measured.connect.disabled);
  await context.close();
  return {
    kind,viewport:config.viewport,safeArea:{top:config.safeTop,bottom:config.safeBottom},
    states:{afterBlur,afterReopen,afterPaste},anchors:measured,
    screenshots:{afterBlur:blurShot,afterReopen:reopenShot,final:finalShot},
  };
}

const results=[];
try{
  results.push(await run('mobile'));
  results.push(await run('desktop'));
  const report={
    variant,appSourceRef,
    engine:'playwright-webkit',engineVersion:browser.version(),
    mode:'CSS/DOM simulation in WebKit; safe-area insets substituted in CSS; no native iOS keyboard or simulator',
    designSource:{commit:'6fac813',boards:['private-key-collapsed-390','private-key-collapsed-980'],tolerance:2},
    syntheticMaterial:'PUBLIC-SYNTHETIC-DRAFT-R12 / PUBLIC-SYNTHETIC-CLIPBOARD-R12 / PUBLIC-SYNTHETIC-PASSPHRASE-R12; screenshots contain no real PEM body',
    results,
  };
  await writeFile(join(outDir,`behavior-geometry-${variant}.json`),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
}finally{
  await browser.close();
  await new Promise(resolve=>server.close(resolve));
}
