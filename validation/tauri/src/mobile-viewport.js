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
      Promise.resolve().then(readTopInset).then(top => {
        if (current === generation && Number.isFinite(top) && top >= 0) root.style.setProperty('--hp-system-top-inset', `${top}px`);
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
