// Presets control only the next observer canvas, never the shared PTY.
export const canvasPresets = Object.freeze(['80x24','120x40','160x50']);
export function parseCanvas(value) {
  if (!canvasPresets.includes(value)) return null;
  const [cols,rows]=value.split('x').map(Number);
  return {cols,rows};
}
