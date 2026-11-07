import { invoke } from '@tauri-apps/api/core';

const byteLimit = 4096;
const messages = {
  clipboard_empty: '剪贴板中没有可粘贴的文本。',
  clipboard_unsupported: '此内容不含可粘贴的纯文本。',
  clipboard_unfocused: '请回到当前终端，再点击粘贴。',
  clipboard_too_large: '粘贴内容超过 4096 个 UTF-8 字节，请缩短后重试。',
  clipboard_denied: '系统未允许读取剪贴板。可在草稿框中使用系统粘贴菜单。',
  clipboard_unavailable: '暂时无法读取剪贴板。可在草稿框中使用系统粘贴菜单。',
};

function errorCode(error) {
  const value = typeof error === 'string' ? error : error?.message;
  if (typeof value === 'string' && Object.hasOwn(messages, value)) return value;
  if (error?.name === 'NotAllowedError' || error?.name === 'SecurityError') return 'clipboard_denied';
  return 'clipboard_unavailable';
}

export function clipboardPasteMessage(error) {
  return messages[errorCode(error)];
}

// Discover only the shell type at startup. WebKit must see readText() in the
// user's tap handler, without an intervening asynchronous platform query.
export function createPasteClipboard({
  callNative = invoke,
  webClipboard = () => globalThis.navigator?.clipboard,
  focused = () => !document.hidden && document.hasFocus(),
} = {}) {
  let platform = 'webview';
  let probing = null;

  function probeNative() {
    if (!probing) {
      probing = callNative('config_document_platform').then(result => {
        platform = ['android', 'ios', 'macos', 'webview'].includes(result) ? result : null;
      }).catch(() => { platform = null; }).finally(() => { probing = null; });
    }
    return probing;
  }

  function initialize(native) {
    if (!native) return;
    platform = null;
    return probeNative();
  }

  async function read() {
    try {
      if (!focused()) throw Error('clipboard_unfocused');
      if (!platform) {
        void probeNative();
        throw Error('clipboard_unavailable');
      }
      let text;
      if (platform === 'android') {
        text = await callNative('mobile_clipboard_read_text');
      } else {
        const clipboard = webClipboard();
        if (!clipboard?.readText) throw Error('clipboard_unavailable');
        text = await clipboard.readText();
      }
      if (!focused()) throw Error('clipboard_unfocused');
      if (typeof text !== 'string') throw Error('clipboard_unsupported');
      if (!text) throw Error('clipboard_empty');
      if (text.length > byteLimit || new TextEncoder().encode(text).length > byteLimit) {
        throw Error('clipboard_too_large');
      }
      return text;
    } catch (error) {
      throw Error(errorCode(error));
    }
  }

  return {initialize, read};
}

const clipboard = createPasteClipboard();
export const initializePasteClipboard = clipboard.initialize;
export const readClipboardForPaste = clipboard.read;
