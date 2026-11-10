import { isTauri } from '@tauri-apps/api/core';
import '@xterm/xterm/css/xterm.css';
import xtermLicense from '../node_modules/@xterm/xterm/LICENSE?raw';
import graphemesLicense from '../node_modules/@xterm/addon-unicode-graphemes/LICENSE?raw';
import './style.css';
import { readTheme } from './theme.js';
import { initRemote } from './remote.js';
import { initKeyRouter } from './key-router.js';
import { initializePasteClipboard } from './mobile-clipboard.js';

document.getElementById('xterm-license').textContent = xtermLicense;
document.getElementById('xterm-graphemes-license').textContent = graphemesLicense;

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
const native = isTauri();
void initializePasteClipboard(native);
initRemote({native,theme,onFixture:openFixture,onLeaveFixture:() => workbench?.pause()});
// 桌面键盘层（切片 3）：事件期自查页面状态与既有按钮挂钩，不依赖装配顺序（键位表见 key-router.js）。
initKeyRouter();
