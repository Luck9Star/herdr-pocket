/** Align fixed mobile controls with the actual visible viewport during IME resize. */
export function observeMobileViewport(view = globalThis.window, root = globalThis.document?.documentElement, body = globalThis.document?.body, readTopInset) {
  const viewport = view?.visualViewport;
  if (!view || !root || !body || !viewport) return () => {};
  let generation = 0;
  const update = () => {
    const height = Math.max(0, viewport.height || view.innerHeight);
    const inset = Math.max(0, view.innerHeight - height - (viewport.offsetTop || 0));
    const keyboard = view.innerWidth <= 599 && inset >= 100;
    root.style.setProperty('--hp-visual-inset', `${keyboard ? Math.round(inset) : 0}px`);
    root.style.setProperty('--hp-visual-height', `${Math.round(height)}px`);
    body.classList.toggle('keyboard-visible', keyboard);
  };
  const updateWithTopInset = () => {
    update();
    if (readTopInset) {
      const current = ++generation;
      Promise.resolve().then(readTopInset).then(insets => {
        if (current !== generation) return;
        const pixels = insets?.overlapPx, dpr = view.devicePixelRatio;
        const property = insets?.connectionEntry ? '--hp-connection-native-top' : '--hp-system-top-inset';
        if (Number.isFinite(pixels) && pixels >= 0 && Number.isFinite(dpr) && dpr > 0) root.style.setProperty(property, `${pixels / dpr}px`);
        else if (insets?.connectionEntry) root.style.removeProperty(property);
      }).catch(() => {});
    }
  };
  viewport.addEventListener('resize', updateWithTopInset);
  viewport.addEventListener('scroll', update);
  view.addEventListener('resize', updateWithTopInset);
  view.addEventListener('orientationchange', updateWithTopInset);
  view.addEventListener('focus', updateWithTopInset);
  updateWithTopInset();
  return () => {
    viewport.removeEventListener('resize', updateWithTopInset);
    viewport.removeEventListener('scroll', update);
    view.removeEventListener('resize', updateWithTopInset);
    view.removeEventListener('orientationchange', updateWithTopInset);
    view.removeEventListener('focus', updateWithTopInset);
    generation++;
    root.style.removeProperty('--hp-visual-inset');
    root.style.removeProperty('--hp-visual-height');
    root.style.removeProperty('--hp-system-top-inset');
    root.style.removeProperty('--hp-connection-native-top');
    body.classList.remove('keyboard-visible');
  };
}

// Only a visible Android SSH terminal samples its system keyboard, including when
// WebView does not emit a resize. While closed, actual UI activity wakes sampling.
export function observeAndroidSshIme(view, doc, readInsets, options = {}) {
  const viewport = view.visualViewport, root = doc.documentElement, body = doc.body;
  const nodes = ['host-home', 'home-ssh', 'ssh-live'].map(id => doc.getElementById(id));
  if (!viewport || nodes.some(node => !node)) return () => {};
  const active = () => view.innerWidth <= 599 && !doc.hidden && doc.hasFocus() && nodes.every(node => !node.hidden);
  let scope;
  const reset = () => {
    if (scope) view.clearTimeout(scope.timer);
    scope = undefined;
    body.classList.remove('ssh-ime-known', 'ssh-ime-visible');
    root.style.removeProperty('--hp-ssh-ime-height');
    root.style.removeProperty('--hp-ssh-ime-inset');
  };
  const paint = () => {
    const sample = scope?.sample;
    const known = typeof sample?.imeVisible === 'boolean';
    const shown = known && sample.imeVisible;
    body.classList.toggle('ssh-ime-known', known);
    body.classList.toggle('ssh-ime-visible', shown);
    const scale = view.devicePixelRatio * (viewport.scale ?? 1);
    const height = sample?.viewHeightPx, overlap = sample?.imeOverlapPx;
    if (shown && Number.isFinite(scale) && scale > 0 &&
        Number.isSafeInteger(height) && height > 0 && Number.isSafeInteger(overlap) && overlap >= 0 && overlap <= height) {
      // Native measures the WebView itself. Use whichever viewport ends first
      // so the browser's existing resize is never deducted a second time.
      const visualHeight = Math.min(viewport.height || view.innerHeight, (height - overlap) / scale);
      const inset = Math.max(0, view.innerHeight - visualHeight - (viewport.offsetTop || 0));
      root.style.setProperty('--hp-ssh-ime-height', `${Math.floor(visualHeight)}px`);
      root.style.setProperty('--hp-ssh-ime-inset', `${Math.ceil(inset)}px`);
    } else {
      root.style.removeProperty('--hp-ssh-ime-height');
      root.style.removeProperty('--hp-ssh-ime-inset');
    }
  };
  async function sample(current) {
    current.pending = true;
    let value;
    try { value = await readInsets(); } catch { /* Without a system sample use the existing web viewport. */ }
    if (scope !== current) return;
    if (!active()) { reset(); return; }
    current.pending = false;
    current.sample = value;
    paint();
    // A fixed WebView emits no resize when the IME finally shows. While the
    // terminal editor still owns focus, keep a slow watch after the wake window
    // so a late IME confirmation is adopted; focus/route/blur still stop it.
    const editor = typeof options.getEditor === 'function' ? options.getEditor() : null;
    const editorHeld = editor ? doc.activeElement === editor : false;
    if (value?.imeVisible === true || view.performance.now() < current.until) {
      current.timer = view.setTimeout(() => {
        current.timer = undefined;
        if (scope === current && active()) void sample(current);
        else if (scope === current) reset();
      }, 160);
    } else if (editorHeld) {
      current.timer = view.setTimeout(() => {
        current.timer = undefined;
        if (scope === current && active() && doc.activeElement === editor) void sample(current);
        else if (scope === current) reset();
      }, 500);
    }
  }
  const wake = () => {
    if (!active()) { reset(); return; }
    scope ??= {};
    scope.until = view.performance.now() + 2000;
    paint();
    if (!scope.pending && scope.timer === undefined) void sample(scope);
  };
  const intent = event => {
    if (event.target.closest?.('#ssh-focus,#ssh-hide-keyboard,#ssh-terminal')) wake();
  };
  const visibility = new MutationObserver(() => { reset(); wake(); });
  for (const node of nodes) visibility.observe(node, {attributes:true, attributeFilter:['hidden']});
  for (const event of ['pointerdown','click','focusin']) doc.addEventListener(event, intent, true);
  doc.addEventListener('visibilitychange', wake);
  for (const event of ['focus','resize','pageshow']) view.addEventListener(event, wake);
  for (const event of ['blur','pagehide']) view.addEventListener(event, reset);
  viewport.addEventListener('resize', wake);
  viewport.addEventListener('scroll', paint);
  wake();
  return () => {
    visibility.disconnect();
    for (const event of ['pointerdown','click','focusin']) doc.removeEventListener(event, intent, true);
    doc.removeEventListener('visibilitychange', wake);
    for (const event of ['focus','resize','pageshow']) view.removeEventListener(event, wake);
    for (const event of ['blur','pagehide']) view.removeEventListener(event, reset);
    viewport.removeEventListener('resize', wake);
    viewport.removeEventListener('scroll', paint);
    reset();
  };
}

// Only ordinary SSH owns this sticky header; the host-key review and other routes do not.
export function observeAndroidSshHeader(view = window, doc = document) {
  const root=doc.documentElement, header=doc.querySelector('.app-header');
  const nodes=['host-home','home-ssh','ssh-key-change'].map(id=>doc.getElementById(id));
  let active=false;
  const update=()=>{ if (active) root.style.setProperty('--hp-ssh-sticky-top', `${Math.max(0, header.getBoundingClientRect().bottom)}px`); };
  const resize=new ResizeObserver(update);
  const sync=()=>{
    const next=!nodes[0].hidden && !nodes[1].hidden && nodes[2].hidden;
    if (next===active) return;
    active=next;
    if (active) { resize.observe(header); view.addEventListener('scroll',update,{passive:true}); update(); }
    else { resize.disconnect(); view.removeEventListener('scroll',update); root.style.removeProperty('--hp-ssh-sticky-top'); }
  };
  const visibility=new MutationObserver(sync);
  for (const node of nodes) visibility.observe(node,{attributes:true,attributeFilter:['hidden']});
  sync();
  return ()=>{ active=false; resize.disconnect(); visibility.disconnect(); view.removeEventListener('scroll',update); root.style.removeProperty('--hp-ssh-sticky-top'); };
}
