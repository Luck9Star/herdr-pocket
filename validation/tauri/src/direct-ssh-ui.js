import { createDirectSsh } from './direct-ssh.js';

export function initDirectSshUI({native, invoke, channelFactory, terminalFactory}) {
  const $ = id => document.getElementById(id);
  let terminal = null;
  let resizeWatch = null;
  let outputSubscription = null;
  let visibilityEpoch = 0;
  const helperKeys = {
    esc: '\u001b',
    tab: '\t',
    'ctrl-c': '\u0003',
  };
  const arrows = { up: 'A', down: 'B', left: 'D', right: 'C' };
  const eligible = (source, epoch) => source === terminal && epoch === visibilityEpoch &&
    !document.hidden && !$('home-ssh')?.hidden && !$('host-home')?.hidden && controller.isReady();
  function renderKeys(ready) {
    for (const button of $('ssh-helper-keys')?.querySelectorAll('button') || []) button.disabled = !ready;
  }
  function bindTerminal(source) {
    outputSubscription?.dispose();
    const epoch = visibilityEpoch;
    outputSubscription = source.onData(data => {
      if (eligible(source, epoch)) controller.write(new TextEncoder().encode(data), () => eligible(source, epoch));
    });
    const keys = $('ssh-helper-keys');
    if (keys) {
      keys.onpointerdown = event => {
        if (eligible(source, epoch) && document.activeElement === source.textarea) event.preventDefault();
      };
      keys.onclick = event => {
        const key = event.target.closest('button[data-ssh-key]')?.dataset.sshKey;
        const value = arrows[key] ? `\u001b${source.modes?.applicationCursorKeysMode ? 'O' : '['}${arrows[key]}` : helperKeys[key];
        if (value && eligible(source, epoch)) controller.write(new TextEncoder().encode(value), () => eligible(source, epoch));
      };
    }
  }
  const resizer = createDirectSshResizer({
    measure: () => measureDirectSshViewport($('ssh-terminal').parentElement, terminal),
    send: (cols, rows) => controller.resize(cols, rows),
    apply: (cols, rows) => terminal.resize(cols, rows),
  });
  const controller = createDirectSsh({invoke, channelFactory,
    onStatus: (message, ready, reason) => {
      $('ssh-status').textContent = message;
      $('ssh-focus').disabled = !ready;
      $('ssh-setup').hidden = ready;
      $('ssh-live').hidden = !ready;
      renderKeys(ready);
      if (reason === 'host_key_mismatch') $('ssh-review').checked = false;
      if (ready) { const t = target(); $('ssh-target').textContent = `${t.username}@${t.host}:${t.port} · SSH 已连接`; resizer.start(); requestAnimationFrame(resizer.request); }
      else resizer.stop();
    },
    onData: (bytes, acknowledge) => terminal?.write(bytes, acknowledge),
  });
  const target = () => ({host: $('ssh-host').value.trim(), port: Number($('ssh-port').value), username: $('ssh-user').value.trim()});
  function clearSecrets() { for (const id of ['ssh-password','ssh-key','ssh-passphrase']) $(id).value = ''; }
  $('ssh-auth-method').value = 'password';
  $('ssh-auth-method').addEventListener('change', () => {
    clearSecrets();
    const key = $('ssh-auth-method').value === 'key';
    $('ssh-password-fields').hidden = key;
    $('ssh-key-fields').hidden = !key;
  });
  for (const id of ['ssh-host','ssh-port']) $(id).addEventListener('input', () => {
    controller.invalidateReview(); void controller.close(); $('ssh-review').checked = false; $('ssh-fingerprint').textContent = '请先探测并独立核对主机指纹。';
  });
  $('ssh-user').addEventListener('input', () => { controller.invalidateReview(); void controller.close(); $('ssh-review').checked = false; });
  $('ssh-probe').disabled = !native;
  if (!native) $('ssh-status').textContent = '浏览器预览无法使用原生 SSH，请使用测试安装包。';
  $('ssh-probe').onclick = async () => {
    $('ssh-review').checked = false;
    const selected = target();
    try {
      const key = await controller.probe(selected);
      if (key) $('ssh-fingerprint').textContent = `主机 ${key.host}:${key.port} · ${key.fingerprint} · ${key.publicKey}`;
    } catch { $('ssh-fingerprint').textContent = '探测失败；请检查地址和端口后重试。'; }
  };
  $('ssh-form').onsubmit = async event => {
    event.preventDefault();
    if (!native) { $('ssh-status').textContent = '浏览器预览不支持原生 SSH。'; return; }
    const password = $('ssh-password').value, privateKeyPem = $('ssh-key').value, passphrase = $('ssh-passphrase').value;
    const credentials = $('ssh-auth-method').value === 'key'
      ? (privateKeyPem ? {privateKeyPem, ...(passphrase ? {privateKeyPassphrase:passphrase} : {})} : {})
      : (password ? {password} : {});
    // A fresh xterm per connection: reset() does not clear the WriteBuffer's
    // dangling partial UTF-8 sequence from the previous session, which would
    // corrupt the first characters of the next session. Disposing also drops
    // the old instance's subscriptions and renderer.
    outputSubscription?.dispose(); outputSubscription = null;
    terminal?.dispose();
    terminal = terminalFactory({cols:80, rows:24, fontSize:14, cursorBlink:true, theme:{background:'#0B0F17',foreground:'#E6EDF3'}});
    terminal.open($('ssh-terminal'));
    bindTerminal(terminal);
    // observe() returns void; keep the observer itself so reconnections don't
    // stack a new watcher on the same container.
    if (typeof ResizeObserver === 'function' && !resizeWatch) {
      resizeWatch = new ResizeObserver(resizer.request);
      resizeWatch.observe($('ssh-terminal').parentElement);
    }
    clearSecrets();
    try { await controller.open(target(), credentials, $('ssh-review').checked); }
    catch { $('ssh-status').textContent = '请先核对指纹并选择一种认证方式。'; }
  };
  const disconnect = () => { clearSecrets(); void controller.close(); };
  $('ssh-disconnect').onclick = disconnect;
  $('ssh-cancel').onclick = disconnect;
  $('ssh-focus').onclick = () => terminal?.focus();
  document.addEventListener('visibilitychange', () => { if (document.hidden) { clearSecrets(); void controller.close(); } });
  return {close: () => {clearSecrets(); void controller.close();}, isReady:controller.isReady, isActive:controller.isActive,
    hide: () => { visibilityEpoch++; }, show:()=>{ if(terminal) bindTerminal(terminal); if(controller.isReady()) requestAnimationFrame(resizer.request); }};
}

// Serialize PTY updates and remeasure after each completion. A new session gets
// its own generation so late replies cannot resize or block the new terminal.
export function createDirectSshResizer({measure, send, apply}) {
  let generation=0, active=false, busy=false, dirty=false, synced=null;
  async function drain(current) {
    if (!active || busy || current!==generation) return;
    busy=true;
    try {
      while (active && current===generation && dirty) {
        dirty=false;
        const size=measure();
        if (!size || (synced && size.cols===synced.cols && size.rows===synced.rows)) continue;
        const accepted=await send(size.cols,size.rows);
        if (!active || current!==generation) return;
        if (!accepted) return;
        apply(size.cols,size.rows);
        synced=size;
      }
    } finally { if (current===generation) busy=false; }
  }
  function request() { if (!active) return; dirty=true; void drain(generation); }
  return {
    start() { generation++; active=true; busy=false; dirty=false; synced=null; },
    stop() { generation++; active=false; busy=false; dirty=false; synced=null; },
    request,
  };
}

export function measureDirectSshViewport(container, terminal) {
  const screen=terminal?.element?.querySelector('.xterm-screen');
  if (!screen || !terminal.cols || !terminal.rows || !container.getClientRects().length) return null;
  const rect=screen.getBoundingClientRect(), style=getComputedStyle(container);
  const width=container.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight);
  const height=container.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom);
  const cellWidth=rect.width/terminal.cols, cellHeight=rect.height/terminal.rows;
  if (![width,height,cellWidth,cellHeight].every(value=>Number.isFinite(value) && value>0)) return null;
  return {cols:Math.max(2,Math.min(240,Math.floor(width/cellWidth))),
          rows:Math.max(1,Math.min(200,Math.floor(height/cellHeight)))};
}
