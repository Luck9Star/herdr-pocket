import {invoke} from '@tauri-apps/api/core';
import {shellPlatform} from './shell-platform.js';

const checkGesture = '__herdrPocketKeyboardGesture';
const maxDelayMs = 2000;

export function createMobileKeyboard({view = globalThis, shell = shellPlatform, callNative = invoke} = {}) {
  let pending;

  function request(action, editor, isCurrent) {
    // A new tap revokes any earlier, still queued native visibility request.
    pending = undefined;
    const doc = view.document;
    if (!editor || !doc || doc.hidden || !doc.hasFocus() || !['show', 'hide'].includes(action)) return;
    function valid() {
      if (doc.hidden || !doc.hasFocus() || !isCurrent()) return false;
      const active = doc.activeElement;
      if (action === 'show') return editor.isConnected && active === editor && !editor.readOnly && !editor.disabled;
      return active === editor || !(active?.isContentEditable || active?.matches?.('input,textarea,[role="textbox"]'));
    }

    const platform = shell.current();
    if (!platform) { void shell.probe(); return; }
    if (platform !== 'android') {
      if (valid()) {
        const keyboard = view.navigator?.virtualKeyboard;
        try { keyboard?.[action]?.(); } catch { /* The focused editor remains available for a tap. */ }
      }
      return;
    }
    const bytes = view.crypto.getRandomValues(new Uint8Array(16));
    const ticket = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
    const expires = view.performance.now() + maxDelayMs;
    // The native WebView rechecks this gesture before touching its input method.
    // Neither terminal content nor connection details cross the platform bridge.
    function clear() {
      if (view[checkGesture] === guard) delete view[checkGesture];
      if (pending === guard) pending = undefined;
      view.clearTimeout(timer);
    }
    function guard(id, kind) {
      if (pending !== guard || id !== ticket || kind !== action) return false;
      clear();
      return view.performance.now() <= expires && valid();
    }
    const timer = view.setTimeout(clear, maxDelayMs);
    pending = guard;
    view[checkGesture] = guard;
    void callNative('mobile_terminal_keyboard', {ticket, action}).catch(clear);
  }

  return request;
}

export const requestMobileKeyboard = createMobileKeyboard();
