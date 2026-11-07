import { AuxiliaryModifiers } from './input-codec.js';

// The owner supplies the existing input lease and queue. This component never
// changes terminal focus, subscribes to IME text, or obtains native permission.
export function createTabInputToolbar({ canSend, send, applicationCursorMode }) {
  const modifiers = new AuxiliaryModifiers();
  const encoder = new TextEncoder();
  const element = document.createElement('section');
  element.setAttribute('aria-label', '终端辅助键');
  const status = document.createElement('p');
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  const modifierRow = document.createElement('div');
  modifierRow.className = 'remote-actions';
  const keyRow = document.createElement('div');
  keyRow.className = 'remote-actions';
  const letters = document.createElement('div');
  letters.className = 'remote-actions remote-combination-bases';
  letters.setAttribute('aria-label', '选择组合基础键');
  const keys = [];
  const allowed = () => {
    try { return canSend() === true; } catch { return false; }
  };

  function button(text, label, action) {
    const node = document.createElement('button');
    node.type = 'button';
    node.textContent = text;
    node.setAttribute('aria-label', label);
    // Keep the xterm textarea focused during touch/mouse activation.
    node.addEventListener('pointerdown', event => event.preventDefault());
    node.onclick = action;
    return node;
  }
  const ctrl = button('Ctrl', '保持 Ctrl 组合键', () => toggle('ctrl'));
  const alt = button('Alt', '保持 Alt 组合键', () => toggle('alt'));
  const cancel = button('取消组合键', '取消组合键', () => { modifiers.reset(); refresh(); });
  modifierRow.append(ctrl, alt, cancel);

  function toggle(name) {
    modifiers.toggle(name, allowed());
    refresh();
  }
  function key(name, text, label, container) {
    const node = button(text, label, () => {
      // Recheck on click: a rendered enabled button is not a live permission.
      const permitted = allowed();
      let sequence = null;
      try {
        if (permitted) {
          const cursorMode = applicationCursorMode();
          if (typeof cursorMode === 'boolean') sequence = modifiers.take(name, cursorMode, true);
          else modifiers.reset();
        } else modifiers.reset();
      } catch { modifiers.reset(); }
      const stillPermitted = refresh();
      if (sequence !== null && permitted && stillPermitted && allowed()) send(encoder.encode(sequence));
    });
    node.dataset.remoteKey = name;
    keys.push(node);
    container.append(node);
  }
  for (const [name, text, label] of [
    ['esc', 'Esc', 'Escape'], ['tab', 'Tab', 'Tab'], ['enter', 'Enter', 'Enter'],
    ['up', '↑', '向上'], ['down', '↓', '向下'], ['left', '←', '向左'], ['right', '→', '向右'],
    ['home', 'Home', 'Home'], ['end', 'End', 'End'], ['pgup', 'PgUp', 'Page Up'], ['pgdn', 'PgDn', 'Page Down'],
  ]) key(name, text, label, keyRow);
  for (const letter of 'abcdefghijklmnopqrstuvwxyz') key(letter, letter.toUpperCase(), `组合键 ${letter.toUpperCase()}`, letters);
  key('space', 'Space', '组合键空格', letters);

  function refresh() {
    const permitted = allowed();
    if (!permitted) modifiers.reset();
    ctrl.disabled = !permitted;
    alt.disabled = !permitted;
    ctrl.setAttribute('aria-pressed', String(modifiers.ctrl));
    alt.setAttribute('aria-pressed', String(modifiers.alt));
    cancel.disabled = !permitted || !modifiers.held;
    for (const node of keys) node.disabled = !permitted;
    letters.hidden = !modifiers.held;
    status.textContent = !permitted ? '输入未启用；辅助键不可用。'
      : modifiers.held ? `${modifiers.ctrl ? 'Ctrl ' : ''}${modifiers.alt ? 'Alt ' : ''}保持；选择一个辅助键后释放。`
      : '组合键已释放；仅影响下一次辅助键。';
    return permitted;
  }
  function reset() { modifiers.reset(); refresh(); }
  element.append(status, modifierRow, letters, keyRow);
  refresh();
  return { element, refresh, reset };
}
