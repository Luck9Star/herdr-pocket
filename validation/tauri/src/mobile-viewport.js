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
        const pixels = insets?.overlapPx, dpr = view.devicePixelRatio;
        if (current === generation && Number.isFinite(pixels) && pixels >= 0 && Number.isFinite(dpr) && dpr > 0) root.style.setProperty('--hp-system-top-inset', `${pixels / dpr}px`);
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
