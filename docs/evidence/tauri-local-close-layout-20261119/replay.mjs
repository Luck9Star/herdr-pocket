import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createServer} from 'node:http';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {dirname, extname, resolve, sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {webkit} from 'playwright';

const root = dirname(fileURLToPath(import.meta.url));
const dist = process.env.FEEDBACK_PRODUCT_DIST || resolve(root, 'validation/tauri/dist');
const sourceSha = process.env.FEEDBACK_PRODUCT_SHA || '887dbb16a225d2327dfc47eb492f56cdade00bed+working-diff';
const viewports = [[1440, 900], [980, 780], [700, 900]];
const [algorithm, blob] = (await readFile(resolve(root, 'fixture/host.pub'), 'utf8')).trim().split(/\s+/);
const fingerprint = 'SHA256:' + createHash('sha256').update(Buffer.from(blob, 'base64')).digest('base64').replace(/=$/, '');
const publicKey = algorithm + ' ' + blob;
const privateKeyPem = await readFile(resolve(root, 'fixture/client'), 'utf8');
const temporaryPassword = 'temporary-desktop-fixture';
const shortTarget = {host:'127.0.0.1', username:'desktopfixture', port:49821};
const longTarget = {host:'pt-long-hostname-for-terminal-acceptance.infra-staging.very-long-test-environment.example.test', username:'desktopfixture', port:49821};
const marker = 'desktop-before-marker';
const evidence = resolve(root, process.env.FEEDBACK_EVIDENCE || 'evidence');
const mime = {'.html':'text/html; charset=utf-8', '.js':'text/javascript', '.css':'text/css', '.json':'application/json', '.ttf':'font/ttf'};
const server = createServer(async (request, response) => {
  const path = resolve(dist, '.' + (request.url === '/' ? '/index.html' : request.url));
  if (!path.startsWith(dist + sep)) return response.writeHead(403).end();
  try {
    const bytes = await readFile(path);
    response.writeHead(200, {'content-type': mime[extname(path)] || 'application/octet-stream'}).end(bytes);
  } catch { response.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const base = 'http://127.0.0.1:' + server.address().port + '/';
const browser = await webkit.launch();
const application = {
  'app-header': '.app-header', 'app-sidebar': '#workbench-sidebar',
  'nav-container': '.route-tabs', 'nav-board':'#show-remote', 'nav-terminal':'#nav-terminal',
  'nav-network':'#nav-network', 'nav-settings':'#nav-settings',
};
const home = {'home-empty-card':'#host-empty','home-add':'#host-empty-add','top-add':'#host-open-remote','home-direct-ssh':'#home-open-ssh','closed-feedback':'#host-ssh-disconnected'};
const choose = {'page-header':'.connection-choice-header','choice-container':'#home-add','back':'#add-back','choice-heading':'.connection-choice-desktop','choose-ssh':'#add-ssh','choose-herdr':'#add-herdr'};
const form = {
  'page-header':'#ssh-page-heading','back':'#ssh-step-back','form':'#ssh-form','host':'#ssh-host','username':'#ssh-user',
  'port':'#ssh-port','probe':'#ssh-probe','target-card':'#ssh-reviewed-target','key-evidence':'#ssh-reviewed-key',
  'key-fingerprint':'#ssh-fingerprint','key-fingerprint-mobile':'#ssh-reviewed-fingerprint',
  'independent-verification':'#ssh-independent-verification','trust-confirm':'#ssh-review','trust-confirm-mobile':'#ssh-trust-confirm',
  'trust-confirm-label':'label.review-check','trust-cancel':'#ssh-trust-cancel','auth-method':'#ssh-auth-method',
  'auth-password':'#ssh-auth-password','auth-key':'#ssh-auth-key','password':'#ssh-password','key-pem':'#ssh-key',
  'paste-key':'#ssh-paste-key','passphrase':'#ssh-passphrase','connect':'#ssh-connect','cancel-connection':'#ssh-cancel',
  'status':'#ssh-status','closed-feedback':'#ssh-closed-feedback','return-home':'#ssh-return-home',
};
const terminal = {
  'page-header':'#ssh-page-heading','live-header':'.ssh-live-header','live-title':'#ssh-active-title','disconnect':'#ssh-disconnect',
  'terminal-status':'.ssh-live-status','terminal-target':'#ssh-target','terminal-panel':'#ssh-terminal-output',
  'terminal-screen':'#ssh-terminal .xterm-screen','terminal-scrollbar':'#ssh-terminal .xterm-viewport',
  'focus-terminal':'#ssh-focus','hide-keyboard':'#ssh-hide-keyboard','keyboard-helpers':'#ssh-helper-keys',
};
const settings = {
  'page-header':'#home-settings h2','active-ssh':'#ssh-settings-active','target-card':'#ssh-settings-target',
  'font-size':'#terminal-font-size','save-font-size':'#terminal-font-save','transfer-settings':'#config-transfer-open',
};
const network = {'page-header':'#home-network h2','active-ssh':'#ssh-settings-active','network-panel':'#network-panel'};

function initIpc({target, fingerprint, publicKey, auth, marker, closeOutcome}) {
  const callbacks = new Map();
  const audit = {events:[], sentLines:0, unknown:[], reasons:[]};
  let counter = 0;
  let current;
  let probed = false;
  window.isTauri = true;
  window.__DESKTOP_BEFORE_AUDIT__ = audit;
  const assert = (value, reason) => {
    if (value) return;
    audit.reasons.push(reason);
    throw Error(reason);
  };
  const deliver = (kind, payload = {}) => {
    const seq = ++current.seq;
    const callback = callbacks.get(current.callback);
    callback({index:seq-1, message:{kind, seq, sessionId:current.id, ...payload}});
  };
  const ascii = value => Array.from(new TextEncoder().encode(value));
  let inputBuffer = '';
  window.__TAURI_INTERNALS__ = {
    transformCallback(callback) { callbacks.set(++counter, callback); return counter; },
    unregisterCallback(id) { callbacks.delete(id); },
    async invoke(command, args = {}) {
      const event = {command};
      audit.events.push(event);
      switch (command) {
        case 'config_document_platform': return 'macos';
        case 'host_init': return;
        case 'host_list': return [];
        case 'network_list': return {revision:0, profiles:[], preferences:{terminalFontSize:14}};
        case 'ssh_host_key_probe':
          assert(!current && args.host === target.host && args.port === target.port, 'probe-target');
          assert(Object.keys(args).length === 2, 'probe-must-contain-only-endpoint');
          probed = true;
          return {host:target.host, port:target.port, publicKey, fingerprint};
        case 'ssh_shell_open': {
          const c = args.config;
          assert(!current && probed && c.host === target.host && c.port === target.port && c.username === target.username, 'open-target');
          assert(c.reviewConfirmed && c.expectedHostKey === publicKey, 'open-pin-and-review');
          const password = typeof c.password === 'string' && c.password.length > 0;
          const key = /^-----BEGIN OPENSSH PRIVATE KEY-----\n/.test(c.privateKeyPem || '');
          assert(auth === 'password' ? password && !key : key && !password, 'open-selected-auth');
          assert(!c.privateKeyPassphrase, 'no-passphrase-needed-for-fixture');
          assert(callbacks.has(args.onEvent.id), 'missing-channel');
          const id = 'desktop-fixture-' + auth;
          event.sessionId = id;
          event.auth = auth;
          event.grid = [c.cols, c.rows];
          current = {id, callback:args.onEvent.id, seq:0};
          deliver('ready');
          deliver('data', {data:ascii('IPC fixture shell ready\r\n$ ')});
          return id;
        }
        case 'ssh_shell_resize':
          assert(current?.id === args.sessionId, 'resize-session');
          event.sessionId = args.sessionId;
          event.grid = [args.cols,args.rows];
          return;
        case 'ssh_shell_ack':
          assert(current?.id === args.sessionId && args.seq <= current.seq, 'ack-session');
          event.sessionId = args.sessionId;
          event.sequence = args.seq;
          return;
        case 'ssh_shell_write': {
          assert(current?.id === args.sessionId, 'write-session');
          event.sessionId = args.sessionId;
          event.byteLength = args.bytes.length;
          const text = new TextDecoder().decode(new Uint8Array(args.bytes));
          inputBuffer += text;
          if (/\r|\n/.test(inputBuffer)) {
            assert(inputBuffer === marker + '\r' || inputBuffer === marker + '\n', 'unexpected-fixture-input');
            audit.sentLines++;
            deliver('data', {data:ascii('FIXTURE ECHO: ' + marker + '\r\n$ ')});
            inputBuffer = '';
          }
          return;
        }
        case 'ssh_shell_close':
          assert(current?.id === args.sessionId, 'close-session');
          event.sessionId = args.sessionId;
          if (closeOutcome === 'rejected') {
            event.result = closeOutcome;
            throw Error('fixture_close_unconfirmed');
          }
          if (closeOutcome === 'false') {
            event.result = closeOutcome;
            return false;
          }
          event.result = 'confirmed';
          current = undefined;
          return null;
        default:
          audit.unknown.push(command);
          throw Error('unhandled-audit-ipc-' + command);
      }
    },
  };
}

function measure(selectors) {
  const scrollRoot = document.scrollingElement;
  const rect = a => [a.x,a.y,a.width,a.height];
  function describe(el) {
    if (!el) return null;
    return {tag:el.localName,id:el.id || null,classes:el.getAttribute('class'),role:el.getAttribute('role')};
  }
  const elements = {};
  for (const [name,selector] of Object.entries(selectors)) {
    const e = document.querySelector(selector);
    if (!e) { elements[name] = {selector, missing:true}; continue; }
    const r = e.getBoundingClientRect();
    const px = r.x+r.width/2;
    const py = r.y+r.height/2;
    const point = document.elementFromPoint(px,py);
    const css = getComputedStyle(e);
    const label = e.closest('label');
    const parent = e.parentElement;
    elements[name] = {
      selector, element:describe(e), rect:rect(r), visible:r.width > 0 && r.height > 0 && css.visibility === 'visible',
      fullyInViewport:r.width > 0 && r.height > 0 && r.x >= 0 && r.y >= 0 && r.right <= innerWidth && r.bottom <= innerHeight,
      center:[px,py], centerElement:describe(point), ownCenterHit:!!point && (e === point || e.contains(point)),
      labelCenterHit:!!point && !!label && label.contains(point), label:describe(label), labelRect:label ? rect(label.getBoundingClientRect()) : null,
      enclosing:describe(parent), enclosingRect:parent ? rect(parent.getBoundingClientRect()):null,
      disabled:e.matches(':disabled'), focused:e === document.activeElement, pressed:e.getAttribute('aria-pressed'),
      checked:e.type === 'checkbox' ? e.checked : undefined,
      empty:['ssh-password','ssh-key','ssh-passphrase'].includes(e.id) ? !e.value : undefined,
      styles:{display:css.display,position:css.position,overflowX:css.overflowX,overflowY:css.overflowY,borderWidth:css.borderTopWidth,
        borderStyle:css.borderTopStyle,borderColor:css.borderTopColor,font:css.fontFamily,pointerEvents:css.pointerEvents,color:css.color,background:css.backgroundColor,phase:e.dataset.phase || null},
      scroll:{client:[e.clientWidth,e.clientHeight],total:[e.scrollWidth,e.scrollHeight],offset:[e.scrollLeft,e.scrollTop]},
    };
  }
  return {viewport:[innerWidth,innerHeight],dpr:devicePixelRatio,visualViewport:[visualViewport.width,visualViewport.height],
    scroll:[scrollX,scrollY],scrollExtent:[scrollRoot.scrollWidth,scrollRoot.scrollHeight],
    activeElement:describe(document.activeElement),elements};
}

function fingerprintRead(expected) {
  const element = document.getElementById('ssh-fingerprint');
  const index = element.textContent.indexOf(expected);
  if (index < 0 || element.childNodes.length !== 1) return {exact:false};
  const range = document.createRange();
  range.setStart(element.firstChild,index);
  range.setEnd(element.firstChild,index+expected.length);
  const fragments = [...range.getClientRects()].map(r => {
    const p = [r.x+r.width/2,r.y+r.height/2];
    return {rect:[r.x,r.y,r.width,r.height],
      inViewport:r.x>=0&&r.y>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,
      ownCenterHit:element.contains(document.elementFromPoint(...p))};
  });
  return {exact:range.toString()===expected, fingerprint:range.toString(), algorithm:element.textContent.includes('ssh-rsa'),
    fragments, allVisible:fragments.length>0&&fragments.every(f=>f.inViewport&&f.ownCenterHit)};
}

async function run(width,height,auth,{closeOutcome = 'confirmed', entry = 'choose', checkCompact = false} = {}) {
  const target = auth === 'private-key' && width === 700 ? longTarget : shortTarget;
  const context = await browser.newContext({viewport:{width,height},deviceScaleFactor:1,locale:'zh-CN',colorScheme:'light'});
  const page = await context.newPage();
  const name = width + 'x' + height + '-' + auth + '-' + entry + '-close-' + closeOutcome;
  const folder = resolve(evidence,name);
  await mkdir(folder,{recursive:true});
  const result = {sourceSha,fixture:'bounded loopback HTTP and JS Tauri IPC; no native material or SSH connection',
    engine:'Playwright WebKit '+browser.version(),viewport:[width,height],auth,entry,closeOutcome,expected:{algorithm,fingerprint,target},states:{},clicks:{},checks:{},errors:[]};
  page.on('pageerror', error=>result.errors.push(error.message));
  await context.route('**/*', route=>route.request().url().startsWith(base)?route.continue():route.abort());
  await page.addInitScript(initIpc,{target,fingerprint,publicKey,auth,marker,closeOutcome});
  page.setDefaultTimeout(5000);
  const id = name => page.locator('#'+name);
  const eventSummary = () => page.evaluate(() => window.__DESKTOP_BEFORE_AUDIT__);
  const settle = () => page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)));
  });
  const inspect = (name, selectors) => page.evaluate(measure,{...application,...selectors});
  async function capture(state, selectors) {
    await settle();
    const screen = await page.screenshot({path:resolve(folder,state+'.png'),animations:'disabled',scale:'css'});
    result.states[state] = {...await inspect(state,selectors),
      png:state+'.png',sha256:createHash('sha256').update(screen).digest('hex')};
    assert.deepEqual([screen.readUInt32BE(16),screen.readUInt32BE(20)],result.states[state].viewport);
    return result.states[state];
  }
  async function click(action, selector) {
    const element = page.locator(selector);
    await element.waitFor({state:'visible'});
    const initial = (await page.evaluate(measure,{action:selector})).elements.action;
    if (!initial.ownCenterHit || !initial.fullyInViewport) await element.scrollIntoViewIfNeeded();
    const after = (await page.evaluate(measure,{action:selector})).elements.action;
    result.clicks[action] = {initial,after,scroll:await page.evaluate(()=>[scrollX,scrollY]), clicked:false};
    assert(after.ownCenterHit, 'center could not be reached: ' + action);
    assert(!after.disabled, 'disabled action: '+action);
    await page.mouse.click(...after.center);
    result.clicks[action].clicked = true;
  }
  const count = (stats,command) => stats.events.filter(event=>event.command===command).length;
  async function waitTerminal(receipt) {
    await id('ssh-live').waitFor();
    await page.waitForFunction(text=>document.querySelector('#ssh-terminal .xterm-rows').textContent.includes(text),receipt);
    return id('ssh-live-endpoint').innerText();
  }
  try {
    await page.goto(base);
    if (width < 600) await page.addStyleTag({content: ':root { --hp-system-top-inset: ' + (width === 390 ? 47 : 24) + 'px !important; }'});
    await id('host-empty').waitFor();
    await page.waitForFunction(()=>!document.getElementById('host-open-remote').disabled);
    await capture('home', home);
    if (entry === 'choose') {
      await click('add-host', '#host-empty-add');
      await id('home-add').waitFor();
      await capture('choose', choose);
      await click('choose-ordinary', '#add-ssh');
    } else {
      await click('ordinary-direct', '#home-open-ssh');
    }
    await id('ssh-host').waitFor();
    await id('ssh-host').fill(target.host);
    await id('ssh-port').fill(String(target.port));
    await id('ssh-user').fill(target.username);
    await click('focus-host', '#ssh-host');
    await capture('target-focused', form);
    await page.keyboard.press('Tab');
    await capture('target', form);
    await click('probe', '#ssh-probe');
    if (width < 600) {
      await id('ssh-trust-confirm').waitFor();
      await click('confirm-trust', '#ssh-trust-confirm');
      await id('ssh-password').fill(temporaryPassword);
    } else {
    await page.waitForFunction(f=>document.getElementById('ssh-fingerprint').textContent.includes(f), fingerprint);
    assert(await id('ssh-password').isDisabled());
    assert(await id('ssh-connect').isDisabled());
    assert.equal(count(await eventSummary(),'ssh_shell_open'),0);
    await capture('trust', form);
    result.checks.fingerprintFirstView = await page.evaluate(fingerprintRead,fingerprint);
    if (!result.checks.fingerprintFirstView.allVisible) {
      await id('ssh-fingerprint').scrollIntoViewIfNeeded();
      await capture('trust-scrolled',form);
    }
    result.checks.fingerprintReachable = await page.evaluate(fingerprintRead,fingerprint);
    assert(result.checks.fingerprintReachable.exact && result.checks.fingerprintReachable.algorithm &&
      result.checks.fingerprintReachable.allVisible,'complete fingerprint is not visible');
    await click('confirm-trust', '#ssh-review');
    assert(await id('ssh-review').isChecked());
    assert(!(await id('ssh-password').isDisabled()));
    await capture('confirmed-password-empty',form);
    await id('ssh-auth-method').selectOption('key');
    assert(!(await id('ssh-key').isDisabled()));
    assert(await id('ssh-connect').isDisabled());
    await capture('private-key', form);
    if (auth === 'password') {
      await id('ssh-auth-method').selectOption('password');
      await id('ssh-password').fill(temporaryPassword);
      await capture('password',form);
    } else {
      await id('ssh-key').fill(privateKeyPem);
    }
    }
    await click('connect', '#ssh-connect');
    const endpoint = await waitTerminal('IPC fixture shell ready');
    assert.equal(endpoint,target.username+'@'+target.host+':'+target.port);
    await capture('terminal', terminal);
    const dom = await id('ssh-terminal .xterm').elementHandle();
    assert(dom);
    const first = await eventSummary();
    assert.equal(count(first,'ssh_shell_open'),1);
    assert.equal(count(first,'ssh_shell_close'),0);
    assert.equal(count(first,'ssh_shell_write'),0);
    if (width >= 600) {
    for (const [route, selectors, routeTab] of [
      ['board',home,'#show-remote'],
      ['network',network,'#nav-network'],
      ['settings',settings,'#nav-settings'],
    ]) {
      await click('leave-for-'+route,routeTab);
      await id('ssh-live').waitFor({state:'hidden'});
      assert.equal(await page.locator(routeTab).getAttribute('aria-pressed'),'true');
      await capture(route+'-active',selectors);
      const away = await eventSummary();
      assert.equal(count(away,'ssh_shell_close'),0);
      assert.equal(count(away,'ssh_shell_write'),0);
      await click('return-from-'+route,'#nav-terminal');
      assert.equal(await waitTerminal('IPC fixture shell ready'),endpoint);
      assert(await page.evaluate(handle=>document.querySelector('#ssh-terminal .xterm')===handle,dom));
      assert.equal(await id('nav-terminal').getAttribute('aria-pressed'),'true');
    }
    result.checks.retainedSameXtermAcrossRoutes = true;
    await capture('terminal-returned',terminal);
    await click('focus-terminal','#ssh-focus');
    assert(await page.locator('#ssh-terminal textarea').evaluate(e=>e===document.activeElement));
    await page.keyboard.type(marker);
    await page.keyboard.press('Enter');
    await page.waitForFunction(text=>document.querySelector('#ssh-terminal .xterm-rows').textContent.includes('FIXTURE ECHO: '+text),marker);
    await capture('terminal-echo',terminal);
    }
    await click('disconnect','#ssh-disconnect');
    await id('ssh-setup').waitFor();
    const cleared = await page.locator('#ssh-password,#ssh-key,#ssh-passphrase').evaluateAll(list=>list.every(e=>e.value===''));
    assert(cleared);
    assert(await id('ssh-connect').isDisabled());
    result.checks.credentialsCleared = true;
    const ended = await capture('disconnected',form);
    assert.equal(ended.elements['closed-feedback'].styles.phase,closeOutcome === 'confirmed' ? 'confirmed' : 'failed');
    assert.equal(ended.elements['closed-feedback'].styles.background,closeOutcome === 'confirmed' ? 'rgb(238, 242, 255)' : 'rgb(255, 241, 242)');
    result.checks.closeStatusText = await id('ssh-status').innerText();
    assert(await id('ssh-closed-feedback').isVisible());
    assert(ended.elements['closed-feedback'].fullyInViewport && ended.elements['closed-feedback'].ownCenterHit,'close result outside client viewport');
    assert(ended.elements['return-home'].fullyInViewport && ended.elements['return-home'].ownCenterHit,'return button outside client viewport');
    assert(ended.elements.port.fullyInViewport);
    result.checks.disconnectedTarget = {
      host:await id('ssh-host').inputValue(),
      username:await id('ssh-user').inputValue(),
      port:Number(await id('ssh-port').inputValue()),
    };
    assert.deepEqual(result.checks.disconnectedTarget,target);
    result.checks.portAppearance = await id('ssh-port').evaluate(port=>getComputedStyle(port).appearance);
    assert.equal(result.checks.portAppearance,'textfield');
    assert(!await id('ssh-review').isChecked());
    assert.equal(ended.scroll[1],0);
    if (checkCompact) {
      await page.setViewportSize({width:390,height:844});
      await page.waitForFunction(()=>document.getElementById('home-ssh').dataset.sshStep==='target');
      await capture('compact-disconnected',form);
      assert.equal(await id('ssh-closed-feedback').isVisible(),true);
      assert.equal(await id('ssh-return-home').isVisible(),true);
      if (closeOutcome !== 'confirmed') assert.match(await id('ssh-closed-feedback').innerText(),/失败/);
      await page.setViewportSize({width,height});
      await page.waitForFunction(()=>!document.getElementById('home-ssh').dataset.sshStep);
      await capture('desktop-returned-width',form);
      assert.equal(await id('ssh-status').innerText(),result.checks.closeStatusText);
    }
    await click('return-home','#ssh-return-home');
    await id('host-empty').waitFor();
    await capture('returned',home);
    assert.equal(await id('host-ssh-disconnected').evaluate(e=>!e.hidden),true);
    if (checkCompact) {
      await page.setViewportSize({width:390,height:844});
      await capture('compact-returned-home',home);
      assert.equal(await id('host-ssh-disconnected').isVisible(),true);
    }
    const end = await eventSummary();
    const opens = end.events.filter(e=>e.command==='ssh_shell_open');
    const closes = end.events.filter(e=>e.command==='ssh_shell_close');
    const writes = end.events.filter(e=>e.command==='ssh_shell_write');
    assert.equal(count(end,'ssh_host_key_probe'),1);
    assert.equal(opens.length,1);
    assert.equal(closes.length,1);
    assert.equal(closes[0].sessionId,opens[0].sessionId);
    assert.equal(closes[0].result,closeOutcome);
    assert.equal(end.sentLines,width < 600 ? 0 : 1);
    assert(writes.every(e=>e.sessionId===opens[0].sessionId));
    assert.equal(writes.reduce((n,e)=>n+e.byteLength,0),width < 600 ? 0 : marker.length+1);
    assert.deepEqual(end.reasons,[]);
    assert.deepEqual(end.unknown,[]);
    assert.deepEqual(result.errors,[]);
    result.checks.oneProbeOpenInputAndCloseCallSameSession = true;
    result.passed = true;
  } catch (error) {
    result.failed = String(error.stack);
    try { await page.screenshot({path:resolve(folder,'failure.png'),animations:'disabled',scale:'css'}); } catch {}
  } finally {
    result.ipc = await eventSummary().catch(()=>null);
    await writeFile(resolve(folder,'geometry.json'),JSON.stringify(result,null,2)+'\n');
    console.log(name, result.passed ? 'PASS' : result.failed, result.ipc?.unknown, result.errors);
    await context.close();
  }
  return !!result.passed;
}

try {
  let passed = true;
  for (const [width,height] of [[1440,900],[980,780],[700,900],[390,844],[320,640]]) {
    if (!await run(width,height,'password')) passed = false;
    if (!await run(width,height,'password',{closeOutcome:'rejected'})) passed = false;
  }
  if (!passed) process.exitCode=1;
} finally {
  await browser.close();
  await new Promise(resolve=>server.close(resolve));
}
