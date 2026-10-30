const ansiKeys = ['black','red','green','yellow','blue','magenta','cyan','white','brightBlack','brightRed','brightGreen','brightYellow','brightBlue','brightMagenta','brightCyan','brightWhite'];
/** Read shared design values without changing terminal dimensions or fixture bytes. */
export function readTheme(tokens) {
  if (tokens.schemaVersion !== 1 || tokens.terminal?.columns !== 80 || tokens.terminal?.rows !== 24) throw Error('Unsupported shared visual contract');
  for (const value of [...Object.values(tokens.colors), ...ansiKeys.map(key => tokens.terminal.ansi[key])]) {
    if (!/^#[\da-f]{6}$/i.test(value)) throw Error('Invalid shared palette value');
  }
  const c = tokens.colors;
  return {
    css: Object.fromEntries([...Object.entries(c).map(([key, value]) => [`--hp-${key}`, value]), ...Object.entries(tokens.radii).map(([key,value]) => [`--hp-radius-${key}`, `${value}px`])]),
    terminal: { background:c.termBg, foreground:c.termText, cursor:c.termCursor, cursorAccent:c.termBg, selectionBackground:`${c.brand}55`, ...tokens.terminal.ansi },
  };
}
