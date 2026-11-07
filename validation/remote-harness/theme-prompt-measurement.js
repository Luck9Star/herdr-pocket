// Evaluated in the test WebView and by the xterm regression with the same DOM.
function readThemeMeasurement(id) {
  const dialog = document.querySelector('.terminal-font-diagnostics[open]');
  const choice = dialog?.querySelector('select[aria-label="诊断样例"]');
  const status = dialog?.querySelector('[role=status]');
  if (!dialog || choice?.value !== id || status?.dataset.sampleId !== id) return null;

  const area = dialog.querySelector('.xterm-helper-textarea');
  if (!area?.readOnly || !area.disabled || area.getAttribute('inputmode') !== 'none') {
    return {columns: -1};
  }

  function integer(name) {
    const value = status.dataset[name];
    return typeof value === 'string' && /^(0|[1-9][0-9]{0,2})$/.test(value) ? Number(value) : null;
  }
  const result = {
    columns: integer('columns'),
    rows: integer('rows'),
    cursorColumn: integer('actualCursorColumn'),
    cursorRow: integer('actualCursorRow'),
  };
  return Object.values(result).includes(null) ? null : result;
}
