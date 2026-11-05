import { isTauri } from '@tauri-apps/api/core';
import '@xterm/xterm/css/xterm.css';
import './style.css';
import { readTheme } from './theme.js';
import { initRemote } from './remote.js';

const tokens = await fetch('/shared/design-tokens-v2.json');
if (!tokens.ok) throw Error('Design tokens unavailable');
const theme = readTheme(await tokens.json());
for (const [name, value] of Object.entries(theme.css)) {
  document.documentElement.style.setProperty(name,value);
}

// The primary host board must work before anyone opens the offline renderer.
let workbench = null, opening = null;
async function openFixture() {
  try {
    opening ??= import('./fixture-workbench.js');
    workbench = await opening;
    if (document.getElementById('fixture-workbench').hidden) workbench.pause();
    else workbench.update();
  } catch {
    opening = null;
    document.getElementById('status').textContent = '离线实验室初始化失败，可返回主机看板';
  }
}
initRemote({native:isTauri(),theme,onFixture:openFixture,onLeaveFixture:() => workbench?.pause()});
