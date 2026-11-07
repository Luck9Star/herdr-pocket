import {invoke} from '@tauri-apps/api/core';

// Resolve once before a gesture. WebView keyboard and clipboard operations must
// remain on the original tap stack when they use a browser API.
export function createShellPlatform(callNative = invoke) {
  let platform = 'webview';
  let pending = null;

  function probe() {
    if (!pending) {
      pending = callNative('config_document_platform').then(value => {
        platform = ['android', 'ios', 'macos', 'webview'].includes(value) ? value : null;
      }).catch(() => { platform = null; }).finally(() => { pending = null; });
    }
    return pending;
  }

  function initialize(native) {
    if (!native) return;
    platform = null;
    return probe();
  }

  return {current: () => platform, initialize, probe};
}

export const shellPlatform = createShellPlatform();
