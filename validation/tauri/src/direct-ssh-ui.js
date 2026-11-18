import { createDirectSsh } from './direct-ssh.js';

export function initDirectSshUI({native, invoke, channelFactory, terminalFactory}) {
  const $ = id => document.getElementById(id);
  const hideKeyboard = $('ssh-hide-keyboard');
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
  function revealFocusedTerminal() {
    if (!document.documentElement.classList.contains('android-edge-to-edge') || !controller.isReady() || document.activeElement !== terminal?.textarea) return;
    requestAnimationFrame(() => {
      if (document.activeElement !== terminal?.textarea || !controller.isReady()) return;
      const targetBox = $('ssh-target').getBoundingClientRect();
      const terminalBox = $('ssh-terminal').parentElement.getBoundingClientRect();
      const obscured = targetBox.bottom - terminalBox.top;
      if (obscured > 0) { window.scrollBy(0, -obscured); return; }
      const headerBottom = document.querySelector('.app-header')?.getBoundingClientRect().bottom || 0;
      const nav = document.querySelector('.route-tabs');
      const visibleBottom = nav && !nav.hidden ? nav.getBoundingClientRect().top : window.innerHeight;
      const needed = $('ssh-helper-keys').getBoundingClientRect().bottom - visibleBottom;
      const room = terminalBox.top - headerBottom - targetBox.height;
      if (needed > 0 && room > 0) window.scrollBy(0, Math.min(needed, room));
    });
  }
  const resizer = createDirectSshResizer({
    measure: () => measureDirectSshViewport($('ssh-terminal').parentElement, terminal),
    send: (cols, rows) => controller.resize(cols, rows),
    apply: (cols, rows) => terminal.resize(cols, rows),
  });
  const controller = createDirectSsh({invoke, channelFactory,
    onStatus: (message, ready, reason, details) => {
      $('ssh-status').textContent = message;
      $('ssh-focus').disabled = !ready;
      if (hideKeyboard) hideKeyboard.disabled = !ready;
      renderKeys(ready);
      const freshRefusal = reason === 'host_key_mismatch' || details?.blocked === true;
      if (freshRefusal) { $('ssh-review').checked = false; renderKeyChange(details); }
      else renderKeyChange(null);
      applyView(ready, freshRefusal);
      applyLock(ready, freshRefusal);
      if (ready) {
        const t = details.target;
        const host = t.host.includes(':') && !t.host.startsWith('[') ? `[${t.host}]` : t.host;
        $('ssh-target').textContent = `${t.username}@${host}:${t.port} · SSH 已连接`;
        globalThis.window?.visualViewport?.addEventListener('resize', revealFocusedTerminal);
        resizer.start(); requestAnimationFrame(resizer.request);
        alignHeadingBelowHeader();
      } else { globalThis.window?.visualViewport?.removeEventListener('resize', revealFocusedTerminal); $('ssh-target').textContent = ''; resizer.stop(); }
    },
    onData: (bytes, acknowledge) => terminal?.write(bytes, acknowledge),
  });
  const target = () => ({host: $('ssh-host').value.trim(), port: Number($('ssh-port').value), username: $('ssh-user').value.trim()});
  function clearSecrets() { for (const id of ['ssh-password','ssh-key','ssh-passphrase']) $(id).value = ''; }
  // After the form→live swap or a keyboard collapse, the retained form scroll can
  // park the page heading under the sticky header (iOS). One event-point
  // realignment to the top; manual scrolling afterwards is never corrected.
  function alignHeadingBelowHeader() {
    if (!document.documentElement?.classList?.contains('ios-edge-to-edge')) return;
    const header = document.querySelector && document.querySelector('.app-header');
    const heading = $('ssh-page-heading');
    if (!header || !heading || heading.hidden) return;
    requestAnimationFrame(() => {
      if (!controller.isReady() || heading.hidden || $('home-ssh')?.hidden || $('host-home')?.hidden) return;
      const headingBox = heading.getBoundingClientRect();
      const headerBox = header.getBoundingClientRect();
      // A hidden parent or a switched view has zero geometry; never scroll another page.
      if (!headingBox.height || !headerBox.height) return;
      if (headerBox.bottom > headingBox.top) globalThis.window?.scrollTo?.(0, 0);
    });
  }
  // One place decides what the user sees: the terminal, the blocked review or the setup form.
  function applyView(ready, blocked) {
    const setup = $('ssh-setup');
    const focused = document.activeElement;
    if (blocked && focused && setup.contains(focused)) focused.blur();
    setup.hidden = ready || blocked;
    $('ssh-live').hidden = !ready;
    $('ssh-key-change').hidden = !blocked;
    // While the change review is open, its own heading is the first heading and the
    // generic status line would repeat the same failure.
    $('ssh-page-heading').hidden = blocked;
    $('ssh-status').hidden = blocked;
    // The change review has exactly two visible ways forward; while it is open
    // the header and the route tabs are removed entirely (mouse, keyboard and
    // assistive tech) instead of layering a disabled state over their own.
    // Narrow hosts that lack the groups are left alone.
    const header = document.querySelector && document.querySelector('.app-header');
    const routeTabs = document.querySelector && document.querySelector('.route-tabs');
    if (header) header.hidden = blocked;
    if (routeTabs) routeTabs.hidden = blocked;
  }
  // While a refused handshake is unresolved every credential entry stays locked.
  // After the same target is probed again, the user's own confirmation of the
  // probed fingerprint releases them; nothing else does.
  function applyLock(ready, blockedView) {
    setEntryLock(ready || blockedView || controller.isBlocked() || !$('ssh-review').checked);
    $('ssh-review').disabled = ready || controller.isBlocked();
  }
  function setEntryLock(locked) {
    for (const id of ['ssh-password','ssh-key','ssh-passphrase','ssh-auth-method']) $(id).disabled = locked;
    $('ssh-form').querySelectorAll('button[type=submit]').forEach(button => { button.disabled = locked; });
  }
  function revealAuthField() {
    const view = globalThis.window;
    const field = $($('ssh-auth-method').value === 'key' ? 'ssh-key' : 'ssh-password');
    if (!view?.scrollBy || field.disabled || !$('ssh-review').checked || $('ssh-setup').hidden) return;
    const box = field.getBoundingClientRect();
    if (!box.height) return;
    const top = view.visualViewport?.offsetTop ?? 0;
    let bottom = top + (view.visualViewport?.height ?? view.innerHeight);
    const nav = document.querySelector('.route-tabs');
    if (nav && !nav.hidden && view.getComputedStyle(nav).position === 'fixed') {
      const navBox = nav.getBoundingClientRect();
      if (navBox.height > 0 && navBox.bottom > top) bottom = Math.min(bottom, navBox.top);
    }
    if (bottom > top && (box.top < top || box.bottom > bottom)) {
      // Reveal the control without moving focus or opening the keyboard.
      view.scrollBy(0, (box.top + box.bottom - top - bottom) / 2);
    }
  }
  // The review checkbox is the user's own confirmation of the probed fingerprint;
  // only then may the credential entries be used again.
  $('ssh-review').addEventListener('change', () => {
    if (controller.isReady() || controller.isBlocked()) return;
    setEntryLock(!$('ssh-review').checked);
    revealAuthField();
  });
  // The blocked view keeps the pin that was in effect and, only when the refused handshake
  // carried one, the public key fingerprint that handshake actually presented.
  function renderKeyChange(details) {
    if (!details) return;
    const t = target();
    $('ssh-key-change-old').textContent = `旧：${details.pinnedFingerprint || '见上方指纹显示'}`;
    $('ssh-key-change-new').textContent = details.presentedFingerprint
      ? `新：${details.presentedFingerprint}`
      : '新：待重新探测';
    $('ssh-key-change-target').textContent = `目标：${t.username}@${t.host}:${t.port}`;
  }
  $('ssh-auth-method').value = 'password';
  $('ssh-auth-method').addEventListener('change', () => {
    clearSecrets();
    const key = $('ssh-auth-method').value === 'key';
    $('ssh-password-fields').hidden = key;
    $('ssh-key-fields').hidden = !key;
    revealAuthField();
  });
  for (const id of ['ssh-host','ssh-port']) $(id).addEventListener('input', () => {
    controller.resetTargetBlock(); void controller.close(); $('ssh-review').checked = false; $('ssh-fingerprint').textContent = '请先探测并独立核对主机指纹。';
  });
  $('ssh-user').addEventListener('input', () => { controller.invalidateReview(); void controller.close(); $('ssh-review').checked = false; });
  $('ssh-probe').disabled = !native;
  if (!native) $('ssh-status').textContent = '浏览器预览无法使用原生 SSH，请使用测试安装包。';
  $('ssh-probe').onclick = async () => {
    $('ssh-review').checked = false;
    renderKeyChange(null);
    applyView(controller.isReady(), false);
    const selected = target();
    try {
      const key = await controller.probe(selected);
      if (key) $('ssh-fingerprint').textContent = `主机 ${key.host}:${key.port} · ${key.fingerprint} · ${key.publicKey}`;
    } catch { $('ssh-fingerprint').textContent = '探测失败；请检查地址和端口后重试。'; }
    // The same target was probed again; the user must confirm the fingerprint
    // before any credential entry is usable again.
    applyLock(false, controller.isBlocked());
  };
  $('ssh-form').onsubmit = async event => {
    event.preventDefault();
    if (!native) { $('ssh-status').textContent = '浏览器预览不支持原生 SSH。'; return; }
    if (controller.isBlocked()) { $('ssh-status').textContent = '主机指纹变化尚未重新核对；请先探测并独立核对本目标的主机指纹。'; return; }
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
    terminal.textarea?.addEventListener('focus', revealFocusedTerminal);
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
  // Cancelling keeps the pin that was in effect and leaves the target blocked:
  // the same target must be probed and confirmed again before anything is used.
  const disconnect = () => { clearSecrets(); void controller.close(); };
  $('ssh-disconnect').onclick = disconnect;
  $('ssh-cancel').onclick = disconnect;
  $('ssh-key-recheck').onclick = () => { $('ssh-probe').onclick(); };
  $('ssh-key-cancel').onclick = () => {
    clearSecrets();
    const pinned = controller.pinnedFingerprint();
    if (pinned) $('ssh-fingerprint').textContent = `主机 ${target().host}:${target().port} · ${pinned} · 已保留的旧信任`;
    renderKeyChange(null);
    // Back to the setup form for the same target with the old trust on display;
    // review, authentication and connect stay locked until the next re-probe and
    // the user's own confirmation of that fingerprint.
    applyView(false, false);
    applyLock(false, false);
    $('ssh-status').hidden = false;
    $('ssh-status').textContent = '已保留旧信任；请重新探测并独立核对本目标的主机指纹后再连接。';
  };
  $('ssh-focus').onclick = () => terminal?.focus();
  if (hideKeyboard) hideKeyboard.onclick = () => {
    if (controller.isReady()) { terminal?.textarea?.blur(); alignHeadingBelowHeader(); }
  };
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
