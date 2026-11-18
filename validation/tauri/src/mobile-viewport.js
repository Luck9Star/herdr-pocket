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

// Fit the connected SSH actions above the actual fixed navigation at scroll top.
export function observeIosSshActions(view = window, doc = document) {
  const home = doc.getElementById('host-home');
  const terminal = doc.getElementById('ssh-terminal-output');
  const actions = doc.getElementById('ssh-disconnect').parentElement;
  const header = doc.querySelector('.app-header');
  const nav = doc.querySelector('.route-tabs');
  const property = '--hp-ssh-terminal-max-height';
  let frame = 0, previous = '';
  const update = () => {
    frame = 0;
    const terminalHeight = terminal.getBoundingClientRect().height;
    const navHeight = nav.getBoundingClientRect().height;
    let next = '';
    if (terminalHeight && navHeight && view.getComputedStyle(nav).position === 'fixed') {
      // Subtract the actual non-terminal content height. A user's scroll
      // position and the previous terminal height must not affect the budget.
      const actionsEnd = actions.getBoundingClientRect().bottom + view.scrollY;
      next = `${Math.floor(view.innerHeight - navHeight - (actionsEnd - terminalHeight) - 8)}px`;
    }
    if (next === previous) return;
    previous = next;
    if (next) terminal.style.setProperty(property, next);
    else terminal.style.removeProperty(property);
  };
  const schedule = () => { if (!frame) frame = view.requestAnimationFrame(update); };
  const resize = new ResizeObserver(schedule);
  for (const element of [header, home, actions, nav]) resize.observe(element);
  view.addEventListener('resize', schedule);
  schedule();
  return () => {
    resize.disconnect();
    view.removeEventListener('resize', schedule);
    view.cancelAnimationFrame(frame);
    terminal.style.removeProperty(property);
  };
}
