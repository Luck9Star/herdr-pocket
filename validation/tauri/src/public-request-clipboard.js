import {invoke} from '@tauri-apps/api/core';
import {shellPlatform} from './shell-platform.js';

// No asynchronous platform probing: copying starts in the explicit tap. Android
// copies its native active request by identity; other supported WebViews use
// writeText with the untouched public source. Neither path retries the other.
export function createPublicRequestClipboard({callNative=invoke,shell=shellPlatform,webClipboard=()=>globalThis.navigator?.clipboard}={}) {
  return async function copy(raw,{hostId,requestId}={}) {
    if(typeof raw!=='string' || !raw || new TextEncoder().encode(raw).length>2048)throw Error('invalid_public_request');
    const platform=shell.current();if(!platform)throw Error('clipboard_unavailable');
    if(platform==='android') {
      if(!/^[0-9a-f]{32}$/.test(hostId) || !/^[0-9a-f]{32}$/.test(requestId))throw Error('invalid_public_request');
      const reply=await callNative('pair_copy_request',{hostId,requestId});
      if(!reply || Array.isArray(reply) || Object.keys(reply).length!==3 || reply.copied!==true || reply.hostId!==hostId || reply.requestId!==requestId)throw Error('clipboard_unconfirmed');
    } else {
      const clipboard=webClipboard();if(!clipboard?.writeText)throw Error('clipboard_unavailable');
      await clipboard.writeText(raw);
    }
  };
}
export const writePublicRequest=createPublicRequestClipboard();
