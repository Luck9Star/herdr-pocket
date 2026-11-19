import { createDirectSsh, directSshCloseFeedback } from './direct-ssh.js';

export function initDirectSshUI({native, invoke, channelFactory, terminalFactory, terminalCursor, clipboardRead, keyboardRequest, onBack, onCloseUpdate}) {
  const $ = id => document.getElementById(id);
  const hideKeyboard = $('ssh-hide-keyboard');
  const compactLayout = globalThis.window?.matchMedia?.('(max-width:599px)');
  const compact = () => compactLayout?.matches === true;
  const setup = $('ssh-setup');
  const mobileSection = $('home-ssh');
  let evidence = null;
  let probeRevision = 0;
  let probing = false;
  let submitting = false;
  let pasteRevision = 0;
  let retainedTrust = false;
  let closeResult = null;

  let terminal = null;
  let resizeWatch = null;
  let outputSubscription = null;
  let visibilityEpoch = 0;
  const terminalAppearance = () => ({
    lineHeight: compact() ? 1.25 : 1,
    theme: {background:'#0B0F17', foreground:'#E6EDF3', cursor:compact() ? terminalCursor : undefined},
  });
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
    if (compact() || !document.documentElement.classList.contains('android-edge-to-edge') || !controller.isReady() || document.activeElement !== terminal?.textarea) return;
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
      const outcome = details?.close;
      if (outcome) {
        if (outcome.phase === 'pending') {
          closeResult = outcome;
          clearSecrets();
          resetReview();
        } else if (closeResult !== outcome) {
          onCloseUpdate?.(outcome);
          return;
        }
      }
      $('ssh-status').textContent = message;
      $('ssh-disconnect').disabled = !ready;
      $('ssh-focus').disabled = !ready;
      if (hideKeyboard) hideKeyboard.disabled = !ready;
      renderKeys(ready);
      const freshRefusal = reason === 'host_key_mismatch' || details?.blocked === true;
      if (freshRefusal) {
        renderKeyChange(details, evidence);
        resetReview();
        retainedTrust = true;
      }
      showSetupNotice(!ready && !!reason && !outcome);
      applyView(ready, freshRefusal);
      if (freshRefusal) scrollToStep();
      if (outcome?.phase === 'pending' && !document.hidden && !mobileSection.hidden && !$('host-home').hidden) {
        globalThis.window?.scrollTo?.(0, 0);
      }
      applyLock(ready, freshRefusal);
      if (ready) {
        retainedTrust = false;
        closeResult = null;
        const endpoint = targetText(details.target);
        $('ssh-live-endpoint').textContent = endpoint;
        $('ssh-settings-endpoint').textContent = endpoint;
        if (!mobileSection.hidden && !$('host-home').hidden) scrollToStep();
        globalThis.window?.visualViewport?.addEventListener('resize', revealFocusedTerminal);
        resizer.start(); requestAnimationFrame(resizer.request);
        alignHeadingBelowHeader();
      } else {
        globalThis.window?.visualViewport?.removeEventListener('resize', revealFocusedTerminal);
        $('ssh-live-endpoint').textContent = '';
        $('ssh-settings-endpoint').textContent = '';
        resizer.stop();
      }
    },
    onData: (bytes, acknowledge) => terminal?.write(bytes, acknowledge),
  });
  const target = () => ({host: $('ssh-host').value.trim(), port: Number($('ssh-port').value), username: $('ssh-user').value.trim()});
  function targetText(t) {
    const host = t.host.includes(':') && !t.host.startsWith('[') ? `[${t.host}]` : t.host;
    return `${t.username}@${host}:${t.port}`;
  }
  function clearSecrets() {
    pasteRevision++;
    for (const id of ['ssh-password','ssh-key','ssh-passphrase']) $(id).value = '';
  }
  function resetReview() {
    probeRevision++;
    probing = false;
    evidence = null;
    controller.invalidateReview();
    $('ssh-review').checked = false;
    if ($('ssh-public-key-details')) $('ssh-public-key-details').open = false;
  }
  function showSetupNotice(visible) {
    $('ssh-status').toggleAttribute?.('data-setup-notice', visible);
  }
  function refreshStep() {
    if (!mobileSection?.dataset) return;
    delete mobileSection.dataset.sshClose;
    $('ssh-closed-feedback').hidden = !closeResult;
    if (closeResult) $('ssh-closed-feedback').dataset.phase = closeResult.phase;
    else delete $('ssh-closed-feedback').dataset.phase;
    $('ssh-return-home').hidden = !closeResult;
    if (closeResult) {
      const {title, detail} = directSshCloseFeedback(closeResult);
      $('ssh-closed-feedback').setAttribute('aria-label', title);
      $('ssh-closed-title').textContent = title;
      $('ssh-closed-detail').textContent = detail;
      $('ssh-closed-detail').hidden = !detail;
    }
    if (!compact()) {
      delete mobileSection.dataset.sshStep;
      if (closeResult) mobileSection.dataset.sshClose = closeResult.phase;
      $('ssh-credentials').hidden = false;
      $('ssh-reviewed-target').hidden = true;
      $('ssh-trust-review').hidden = true;
      $('ssh-probe').textContent = '探测主机指纹';
      $('ssh-connect').textContent = '连接 / 重新连接';
      return;
    }
    const confirmed = evidence && $('ssh-review').checked;
    const step = confirmed ? 'auth' : evidence ? 'trust' : 'target';
    mobileSection.dataset.sshStep = step;
    $('ssh-step-title').textContent = confirmed ? 'SSH 账号认证' : evidence ? '核对主机密钥' : '普通 SSH';
    $('ssh-target-fields').hidden = step !== 'target';
    $('ssh-credentials').hidden = step !== 'auth';
    $('ssh-reviewed-target').hidden = step === 'target';
    $('ssh-trust-review').hidden = step !== 'trust';
    $('ssh-probe').textContent = probing ? '正在探测…' : '探测并核对主机密钥';
    $('ssh-connect').textContent = '连接 SSH';
    $('ssh-trust-cancel').textContent = evidence?.rechecking ? '取消核对，保留旧信任' : '取消核对';
    const pinned = retainedTrust ? controller.pinnedFingerprint() : null;
    $('ssh-prior-trust').hidden = !pinned;
    $('ssh-prior-fingerprint').hidden = !pinned;
    $('ssh-prior-fingerprint').textContent = pinned ? `保留的旧指纹：${pinned}` : '';
  }
  function scrollToStep() {
    if (compact()) globalThis.window?.scrollTo?.(0,0);
  }
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
    const focused = document.activeElement;
    if (blocked && focused && setup.contains(focused)) focused.blur();
    setup.hidden = ready || blocked;
    $('ssh-live').hidden = !ready;
    $('ssh-settings-active').hidden = !ready;
    $('ssh-settings-target').hidden = !ready;
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
    refreshStep();
  }
  // A probe and an explicit confirmation must still belong to the same target.
  function reviewMatches() {
    const now = target();
    return evidence && now.host === evidence.target.host && now.port === evidence.target.port &&
      now.username === evidence.target.username;
  }
  function usableCredentials() {
    if ($('ssh-auth-method').value !== 'key') return !!$('ssh-password').value;
    const pem = $('ssh-key').value.trim();
    return compact() ? privateKeyReady(pem, $('ssh-passphrase').value) : !!pem;
  }
  function applyLock(ready = controller.isReady(), blockedView = !$('ssh-key-change').hidden) {
    const unavailable = !native || ready || blockedView || controller.isActive() || submitting || closeResult?.phase === 'pending';
    const locked = unavailable || probing || controller.isBlocked() || !reviewMatches() || !$('ssh-review').checked;
    for (const id of ['ssh-password','ssh-key','ssh-passphrase','ssh-auth-method','ssh-auth-password','ssh-auth-key','ssh-paste-key']) {
      const field = $(id);
      if (field) field.disabled = locked;
    }
    $('ssh-review').disabled = unavailable || controller.isBlocked() || !reviewMatches();
    $('ssh-probe').disabled = unavailable || probing;
    $('ssh-form').querySelectorAll('button[type=submit]').forEach(button => { button.disabled = locked || !usableCredentials(); });
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
  $('ssh-review').addEventListener('change', () => {
    applyLock();
    revealAuthField();
  });
  if (compactLayout) {
    compactLayout.addEventListener('change', () => {
      if (terminal) Object.assign(terminal.options, terminalAppearance());
      refreshStep();
      applyLock();
    });
    $('ssh-trust-confirm').onclick = () => {
      if (!reviewMatches() || controller.isBlocked() || probing || submitting) return;
      $('ssh-review').checked = true;
      refreshStep();
      applyLock();
      scrollToStep();
    };
    const cancelTrust = () => {
      clearSecrets();
      resetReview();
      refreshStep();
      applyLock();
      scrollToStep();
    };
    $('ssh-trust-cancel').onclick = cancelTrust;
    const leaveTarget = (returnToDashboard = false) => {
      onBack?.(closeResult?.phase ?? null, returnToDashboard);
      clearSecrets();
      resetReview();
      closeResult = null;
      showSetupNotice(false);
      refreshStep();
    };
    $('ssh-return-home').onclick = () => {
      if (closeResult) leaveTarget(true);
    };
    $('ssh-step-back').onclick = () => {
      if (controller.isActive() || submitting) {
        resetReview();
        disconnect();
      } else if (evidence && $('ssh-review').checked) {
        clearSecrets();
        $('ssh-review').checked = false;
        refreshStep();
        applyLock();
      } else if (evidence || probing) {
        cancelTrust();
      } else {
        leaveTarget();
      }
      scrollToStep();
    };
  }
  // The blocked view keeps the pin that was in effect and, only when the refused handshake
  // carried one, the public key fingerprint that handshake actually presented.
  function renderKeyChange(details, reviewed) {
    const endpoint = targetText(reviewed?.target ?? target());
    $('ssh-key-change-old').textContent = `旧：${details.pinnedFingerprint || '见上方指纹显示'}`;
    $('ssh-key-change-new').textContent = details.presentedFingerprint
      ? `新：${details.presentedFingerprint}`
      : '新：待重新探测';
    $('ssh-key-change-target').textContent = `目标：${endpoint}`;
    $('ssh-key-change-endpoint').textContent = endpoint;
    $('ssh-key-change-algorithms').textContent = reviewed?.algorithm
      ? `旧密钥算法 · ${reviewed.algorithm}` : '密钥算法待重新探测';
  }
  function changeMethod(key) {
    clearSecrets();
    $('ssh-auth-method').value = key ? 'key' : 'password';
    $('ssh-password-fields').hidden = key;
    $('ssh-key-fields').hidden = !key;
    $('ssh-auth-password')?.setAttribute('aria-pressed', String(!key));
    $('ssh-auth-key')?.setAttribute('aria-pressed', String(key));
    if ($('ssh-credential-note')) $('ssh-credential-note').textContent = key
      ? '填写完整私钥后才能连接。' : '断开或取消后，本次密码会清空。';
    applyLock();
    if (!compact()) revealAuthField();
  }
  $('ssh-auth-method').addEventListener('change', () => changeMethod($('ssh-auth-method').value === 'key'));
  if ($('ssh-auth-password')) $('ssh-auth-password').onclick = () => {
    if ($('ssh-auth-method').value !== 'password') changeMethod(false);
  };
  if ($('ssh-auth-key')) $('ssh-auth-key').onclick = () => {
    if ($('ssh-auth-method').value !== 'key') changeMethod(true);
  };
  for (const id of ['ssh-password','ssh-key','ssh-passphrase']) $(id).addEventListener('input', () => {
    pasteRevision++;
    applyLock();
  });
  if ($('ssh-paste-key')) $('ssh-paste-key').onclick = async () => {
    if ($('ssh-paste-key').disabled || !clipboardRead) return;
    const revision = ++pasteRevision;
    const current = () => revision === pasteRevision && !document.hidden && !mobileSection.hidden &&
      !$('host-home').hidden && compact() && !$('ssh-key-fields').hidden && !$('ssh-paste-key').disabled;
    try {
      const text = await clipboardRead();
      if (!current()) return;
      $('ssh-key').value = text;
      $('ssh-credential-note').textContent = '填写完整私钥后才能连接。';
      applyLock();
    } catch {
      if (current()) $('ssh-credential-note').textContent = '无法读取剪贴板，可在私钥框用系统粘贴。';
    }
  };
  for (const id of ['ssh-host','ssh-port','ssh-user']) $(id).addEventListener('input', () => {
    closeResult = null;
    clearSecrets();
    resetReview();
    if (id !== 'ssh-user') {
      controller.resetTargetBlock();
      retainedTrust = false;
      $('ssh-fingerprint').textContent = '请先探测并独立核对主机指纹。';
    }
    void controller.close();
    applyLock();
  });
  applyView(false, false);
  changeMethod(false);
  if (!native) {
    $('ssh-status').textContent = '浏览器预览无法使用原生 SSH，请使用测试安装包。';
    showSetupNotice(true);
  }
  $('ssh-probe').onclick = async () => {
    if (!native || probing || controller.isActive() || submitting || closeResult?.phase === 'pending') return;
    const selected = target();
    if (!selected.host || !selected.username || !Number.isInteger(selected.port) || selected.port < 1 || selected.port > 65535) {
      $('ssh-status').textContent = '请输入主机地址、用户名和有效端口（1–65535）。';
      showSetupNotice(true);
      return;
    }
    const rechecking = retainedTrust || controller.isBlocked();
    closeResult = null;
    clearSecrets();
    resetReview();
    const revision = probeRevision;
    probing = true;
    showSetupNotice(false);
    applyView(false, false);
    applyLock(false, false);
    try {
      const key = await controller.probe(selected);
      if (revision !== probeRevision) return;
      if (typeof key?.publicKey !== 'string' || typeof key?.fingerprint !== 'string') throw Error('probe_unavailable');
      const algorithm = key.publicKey.trim().split(/\s+/,1)[0];
      evidence = {target:selected, rechecking, algorithm};
      $('ssh-fingerprint').textContent = `主机 ${key.host}:${key.port} · ${key.fingerprint} · ${key.publicKey}`;
      if ($('ssh-reviewed-endpoint')) {
        $('ssh-reviewed-endpoint').textContent = targetText(selected);
        $('ssh-reviewed-algorithm').textContent = algorithm;
        $('ssh-reviewed-fingerprint').textContent = key.fingerprint;
        $('ssh-reviewed-public-key').textContent = key.publicKey;
      }
      if (compact()) changeMethod(false);
      scrollToStep();
    } catch {
      if (revision !== probeRevision) return;
      $('ssh-fingerprint').textContent = '探测失败；请检查地址和端口后重试。';
      $('ssh-status').textContent = $('ssh-fingerprint').textContent;
      showSetupNotice(true);
    } finally {
      if (revision === probeRevision) {
        probing = false;
        refreshStep();
        applyLock(false, false);
      }
    }
  };
  $('ssh-form').onsubmit = async event => {
    event.preventDefault();
    if (!native) { $('ssh-status').textContent = '浏览器预览不支持原生 SSH。'; return; }
    if (controller.isBlocked()) {
      $('ssh-status').textContent = '主机指纹变化尚未重新核对；请先探测并独立核对本目标的主机指纹。';
      showSetupNotice(true);
      return;
    }
    if (submitting || controller.isActive()) return;
    if (!reviewMatches() || !$('ssh-review').checked || !usableCredentials()) {
      $('ssh-status').textContent = '请先核对指纹并选择一种认证方式。';
      showSetupNotice(true);
      return;
    }
    submitting = true;
    closeResult = null;
    applyLock();
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
    terminal = terminalFactory({cols:80, rows:24, fontSize:14, cursorBlink:true, ...terminalAppearance()});
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
    catch {
      $('ssh-status').textContent = '请先核对指纹并选择一种认证方式。';
      showSetupNotice(true);
    } finally {
      submitting = false;
      applyLock();
    }
  };
  // Cancelling keeps the pin that was in effect and leaves the target blocked:
  // the same target must be probed and confirmed again before anything is used.
  const disconnect = (requested = false) => {
    clearSecrets();
    if (closeResult?.phase === 'pending' || (requested && !controller.isReady())) return;
    $('ssh-disconnect').disabled = true;
    if (!requested && compact()) resetReview();
    void controller.close({showOutcome:requested});
    if (!requested) scrollToStep();
  };
  $('ssh-disconnect').onclick = () => disconnect(true);
  $('ssh-cancel').onclick = () => disconnect();
  $('ssh-key-recheck').onclick = () => { $('ssh-probe').onclick(); };
  $('ssh-key-cancel').onclick = () => {
    clearSecrets();
    resetReview();
    retainedTrust = true;
    const pinned = controller.pinnedFingerprint();
    if (pinned) $('ssh-fingerprint').textContent = `主机 ${target().host}:${target().port} · ${pinned} · 已保留的旧信任`;
    // Back to the setup form for the same target with the old trust on display;
    // review, authentication and connect stay locked until the next re-probe and
    // the user's own confirmation of that fingerprint.
    applyView(false, false);
    applyLock(false, false);
    $('ssh-status').hidden = false;
    $('ssh-status').textContent = '已保留旧信任；请重新探测并独立核对本目标的主机指纹后再连接。';
    showSetupNotice(!compact());
    scrollToStep();
  };
  function requestAndroidKeyboard(action) {
    if (!compact() || !document.documentElement?.classList?.contains('android-edge-to-edge')) return;
    const source = terminal, epoch = visibilityEpoch;
    if (source && eligible(source, epoch)) keyboardRequest?.(action, source.textarea, () => eligible(source, epoch));
  }
  $('ssh-focus').onclick = () => {
    terminal?.focus();
    requestAndroidKeyboard('show');
  };
  if (hideKeyboard) hideKeyboard.onclick = () => {
    if (controller.isReady()) {
      terminal?.textarea?.blur();
      requestAndroidKeyboard('hide');
      if (compact()) scrollToStep();
      alignHeadingBelowHeader();
    }
  };
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      clearSecrets();
      if (compact()) resetReview();
      // An explicit close already retired the local session and owns its status.
      if (!closeResult) void controller.close();
    }
  });
  return {close:disconnect, isReady:controller.isReady, isActive:controller.isActive,
    hide: () => {
      visibilityEpoch++;
      if (document.activeElement === terminal?.textarea) terminal?.textarea?.blur();
      clearSecrets();
      const outcome = closeResult;
      closeResult = null;
      if (outcome) {
        $('ssh-status').textContent = '尚未连接。';
        showSetupNotice(false);
      }
      if (compact() && !controller.isActive()) resetReview();
      refreshStep();
      applyLock();
      return outcome;
    },
    show: () => {
      if (terminal) bindTerminal(terminal);
      if (controller.isReady()) {
        scrollToStep();
        requestAnimationFrame(resizer.request);
      }
    },
  };
}


// Leave cryptographic key parsing and passphrase verification to the existing transport.
export function privateKeyReady(pem, passphrase) {
  const envelope = /^-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----\r?\n([\s\S]+)\r?\n-----END \1-----$/.exec(pem.trim());
  if (!envelope) return false;
  const [,format,body] = envelope;
  const legacyEncrypted = /^Proc-Type:\s*4,ENCRYPTED\s*$/m.test(body);
  const payload = body.replace(/^(?:Proc-Type|DEK-Info):[^\r\n]*$/gm, '').replace(/\s/g, '');
  if (payload.length < 16 || payload.length % 4 || !/^[A-Za-z0-9+/]+={0,2}$/.test(payload)) return false;
  if (format === 'ENCRYPTED PRIVATE KEY' || legacyEncrypted) return !!passphrase;
  if (format !== 'OPENSSH PRIVATE KEY') return true;
  const header = atob(payload.slice(0, 100));
  const magic = 'openssh-key-v1\0';
  if (!header.startsWith(magic) || header.length < magic.length + 5) return false;
  const cipherLength = header.charCodeAt(magic.length + 3);
  if (header.slice(magic.length, magic.length + 3) !== '\0\0\0' ||
      !cipherLength || cipherLength > header.length - magic.length - 4) return false;
  const cipher = header.slice(magic.length + 4, magic.length + 4 + cipherLength);
  return cipher === 'none' || !!passphrase;
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
