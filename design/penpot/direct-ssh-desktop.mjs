import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createHash } from 'node:crypto';

// 普通 SSH 桌面专属设计：单一源驱动 1440×900 / 980×780 / 700×900 三档客户端内容视口。
// 语义 token、导出办法与 geometry/anchor 校验沿用 direct-ssh-mobile.mjs 的既有模式；
// 本文件只新增桌面壳（标题栏 + 侧栏）与键鼠形态，不修改手机成果。
const tokens = JSON.parse(readFileSync(new URL('../../validation/shared/design-tokens-v2.json', import.meta.url)));
const color = tokens.colors;
const target = 'demo@ssh.example.test:22';
const fingerprint = (label) => `SHA256:${createHash('sha256').update(label).digest('base64').replace(/=$/, '')}`;
const currentKey = fingerprint('herdr-pocket design example current');
const replacementKey = fingerprint('herdr-pocket design example replacement');
const titleBarHeight = 40;
const sideBarWidth = 224;
const readingWidth = 560; // docs/63 表单阅读宽度上限
const sans = 'Inter, PingFang SC, Noto Sans CJK SC, Microsoft YaHei, sans-serif';
const mono = 'JetBrainsMono Nerd Font Mono, JetBrains Mono, Menlo, monospace';
const escape = (value) => String(value).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[character]);

const sizes = [
  { width: 1440, height: 900 },
  { width: 980, height: 780 },
  { width: 700, height: 900 },
];

function createBoard(state, title, screen) {
  const { width, height } = screen;
  const content = { x: sideBarWidth, y: titleBarHeight, width: width - sideBarWidth, height: height - titleBarHeight };
  const margin = content.x + 40;
  const span = Math.min(readingWidth, content.width - 80);

  const id = `${state}-${width}`;
  const pieces = [];
  const anchors = {};
  const textLimits = [];
  function rect(x, y, w, h, fill, radius = 0, stroke, strokeWidth = 1) {
    const outline = stroke ? ` stroke="${stroke}" stroke-width="${strokeWidth}"` : '';
    pieces.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${radius}" fill="${fill}"${outline}/>`);
  }
  function text(value, x, baseline, { size = tokens.typography.body, fill = color.textPrimary, bold = false, align = 'start', family = sans, limit = width - x } = {}) {
    const textId = `${id}-text-${textLimits.length + 1}`;
    textLimits.push({ id: textId, maxWidth: limit });
    pieces.push(`<text id="${textId}" x="${x}" y="${baseline}" font-family="${family}" font-size="${size}" font-weight="${bold ? '600' : '400'}" fill="${fill}" text-anchor="${align}">${escape(value)}</text>`);
  }
  function line(x1, y1, x2, y2, stroke = color.border) {
    pieces.push(`<path d="M ${x1} ${y1} L ${x2} ${y2}" fill="none" stroke="${stroke}" stroke-width="1"/>`);
  }
  function icon(path, x, y, stroke = color.textPrimary, border = 1.7) {
    pieces.push(`<path d="${path}" transform="translate(${x} ${y})" fill="none" stroke="${stroke}" stroke-width="${border}" stroke-linecap="round" stroke-linejoin="round"/>`);
  }
  function layer(name, x, y, w, h, render, role = 'geometry') {
    if (anchors[name]) throw new Error(`${id} 重复锚点 ${name}`);
    if (Math.min(x, y, w, h) < 0 || x + w > width || y + h > height) throw new Error(`${id} 锚点 ${name} 越出画板`);
    if (role !== 'system' && y < titleBarHeight) throw new Error(`${id} 锚点 ${name} 越出应用可用区`);
    if (role === 'hit' && Math.min(w, h) < tokens.interaction.minTouchTarget) throw new Error(`${id} 命中区 ${name} 小于 44pt`);
    anchors[name] = { x, y, width: w, height: h, role };
    pieces.push(`<g id="${id}-${name}"><title>${escape(name)}</title>`);
    render();
    pieces.push('</g>');
  }
  function button(name, label, y, { x = margin, w = span, kind = 'primary' } = {}) {
    const styles = {
      primary: [color.brand, color.textInverse, null],
      secondary: [color.card, color.textPrimary, color.borderStrong],
      quiet: ['none', color.brand, null],
      disabled: [color.cardSubtle, color.textSecondary, color.border],
    };
    const [background, foreground, border] = styles[kind];
    layer(name, x, y, w, 48, () => {
      rect(x, y, w, 48, background, tokens.radii.button, border);
      text(label, x + w / 2, y + 29, { fill: foreground, bold: true, align: 'middle', limit: w - 16 });
    }, kind === 'disabled' ? 'disabled' : 'hit');
  }
  function pageHeader(label, { back = true, action, danger = false } = {}) {
    layer('page-header', content.x, titleBarHeight, content.width, 56, () => {
      line(content.x, titleBarHeight + 55.5, width, titleBarHeight + 55.5);
      if (back) {
        const x = margin - 32;
        layer('back', x, titleBarHeight + 6, 44, 44, () => icon('M14 4 L6 12 L14 20 M6 12 H20', x + 9, titleBarHeight + 16), 'hit');
      }
      const x = back ? margin + 24 : margin;
      text(label, x, titleBarHeight + 35, { size: 18, bold: true, limit: action ? width - x - 120 : width - x - 40 });
      if (action) {
        const right = width - 40;
        layer('disconnect', right - 76, titleBarHeight + 4, 76, 44, () => {
          rect(right - 76, titleBarHeight + 6, 76, 40, color.dangerSoft, 10);
          text(action, right - 38, titleBarHeight + 32, { bold: true, align: 'middle', limit: 68, fill: danger ? color.dangerText : color.brand });
        }, 'hit');
      }
    });
  }
  function notice(name, heading, detail, y, tone = 'info') {
    if (!Number.isFinite(y)) throw new Error(`${id} notice ${name} 未初始化 y`);
    const fills = tone === 'danger' ? [color.dangerSoft, color.dangerBorder, color.dangerText] :
      tone === 'success' ? [color.successSoft, color.successBorder, color.successText] : [color.brandSoft, color.brandBorder, color.brand];
    const h = detail.length ? 48 + detail.length * 18 : 44;
    layer(name, margin, y, span, h, () => {
      rect(margin, y, span, h, fills[0], 10, fills[1]);
      text(heading, margin + 12, y + (detail.length ? 24 : 27), { fill: fills[2], bold: true, limit: span - 24 });
      detail.forEach((item, index) => text(item, margin + 12, y + 47 + index * 18, { size: 13, fill: color.textSecondary, limit: span - 24 }));
    });
    return y + h;
  }
  function field(name, label, value, x, y, w = span, { height: h = 48, example = false, focused = false } = {}) {
    text(label, x, y + 14, { size: 13, bold: true, limit: w });
    layer(name, x, y + 22, w, h, () => {
      rect(x, y + 22, w, h, color.card, tokens.radii.button, focused ? color.brand : color.borderStrong, focused ? 2 : 1);
      text(value, x + 12, y + 51, { fill: example ? color.textMutedReadable : color.textPrimary, limit: w - 24 });
      if (focused) rect(x + 12 + 8.5 * value.length, y + 32, 1.5, 20, color.brand, 1);
    }, 'hit');
    return y + 22 + h;
  }
  function targetCard(y, { compact = false, name = 'target-card' } = {}) {
    const h = compact ? 52 : 68;
    layer(name, margin, y, span, h, () => {
      rect(margin, y, span, h, color.card, 10, color.border);
      text('本次连接目标', margin + 12, y + (compact ? 18 : 23), { size: 12, fill: color.textSecondary, limit: span - 24 });
      text(target, margin + 12, y + (compact ? 37 : 48), { size: 14, family: mono, limit: span - 24 });
    });
    return y + h;
  }
  function fingerprintValue(name, value, y) {
    layer(name, margin + 12, y, span - 24, 34, () => {
      text(value.slice(0, 28), margin + 12, y + 12, { size: 13, family: mono, limit: span - 24 });
      text(value.slice(28), margin + 12, y + 30, { size: 13, family: mono, limit: span - 24 });
    });
  }
  function fingerprintCard(y, value) {
    layer('key-evidence', margin, y, span, 122, () => {
      rect(margin, y, span, 122, color.card, 16, color.border);
      text('主机密钥算法', margin + 12, y + 21, { size: 12, fill: color.textSecondary, limit: span - 24 });
      text('ssh-ed25519', margin + 12, y + 43, { family: mono, limit: span - 24 });
      line(margin + 12, y + 53.5, width - 40 - 12, y + 53.5);
      text('完整 SHA256 指纹', margin + 12, y + 72, { size: 12, fill: color.textSecondary, limit: span - 24 });
      fingerprintValue('key-fingerprint', value, y + 79);
    });
  }
  function fingerprintPair(y) {
    layer('changed-keys', margin, y, span, 167, () => {
      rect(margin, y, span, 167, color.card, 16, color.border);
      text('算法 · ssh-ed25519', margin + 12, y + 22, { size: 13, bold: true, limit: span - 24 });
      text('旧指纹 · 已核对', margin + 12, y + 45, { size: 12, fill: color.textSecondary, limit: span - 24 });
      fingerprintValue('previous-key-fingerprint', currentKey, y + 53);
      line(margin + 12, y + 93.5, width - 40 - 12, y + 93.5);
      text('新指纹 · 待核对', margin + 12, y + 116, { size: 12, fill: color.dangerText, limit: span - 24 });
      fingerprintValue('presented-key-fingerprint', replacementKey, y + 125);
    });
  }
  function footnote(value, y) {
    text(value, margin, y, { size: 12, fill: color.textMutedReadable, limit: span });
  }
  function options(y, selected) {
    const optionWidth = (span - 8) / 2;
    text('认证方式', margin, y + 14, { size: 13, bold: true, limit: span });
    ['密码', '已有私钥'].forEach((label, index) => {
      const x = margin + index * (optionWidth + 8);
      const active = selected === index;
      layer(index ? 'auth-key' : 'auth-password', x, y + 22, optionWidth, 44, () => {
        rect(x, y + 22, optionWidth, 44, active ? color.brandSoft : color.card, 10, active ? color.brand : color.borderStrong);
        text(label, x + optionWidth / 2, y + 49, { align: 'middle', bold: active, fill: active ? color.brand : color.textSecondary, limit: optionWidth - 12 });
      }, 'hit');
    });
    return y + 66;
  }
  function windowChrome() {
    layer('window-chrome', 0, 0, width, titleBarHeight, () => {
      rect(0, 0, width, titleBarHeight, color.card, 0, color.border);
      rect(16, 9, 22, 22, color.brand, 6);
      text('HP', 27, 25, { size: 10, bold: true, fill: color.textInverse, align: 'middle', limit: 20 });
      text('Herdr Pocket', 46, 25, { size: 13, bold: true, limit: 200 });
      const glyphs = [['最小化', 'M6 12 H18'], ['最大化', 'M5 5 H19 V19 H5 Z'], ['关闭', 'M6 6 L18 18 M18 6 L6 18']];
      glyphs.forEach(([label, path], index) => {
        const x = width - 52 - (2 - index) * 40;
        icon(path, x, 13, color.textSecondary, 1.4);
        pieces.push(`<title>${escape(label)}</title>`);
      });
    }, 'system');
  }
  function sidebar(activeNav, sessionLive) {
    layer('app-sidebar', 0, titleBarHeight, sideBarWidth, height - titleBarHeight, () => {
      rect(0, titleBarHeight, sideBarWidth, height - titleBarHeight, color.card, 0, color.border);
      line(sideBarWidth - 0.5, titleBarHeight, sideBarWidth - 0.5, height, color.border);
      const tabs = [
        ['board', '看板', 'M3 3 H10 V10 H3 Z M14 3 H21 V10 H14 Z M3 14 H10 V21 H3 Z M14 14 H21 V21 H14 Z'],
        ['terminal', '终端', 'M3 4 H21 V20 H3 Z M7 9 L10 12 L7 15 M13 15 H17'],
        ['network', '网络', 'M12 3 A9 9 0 1 0 12 21 A9 9 0 1 0 12 3 M3 12 H21 M12 3 C6 7 6 17 12 21 C18 17 18 7 12 3'],
        ['settings', '设置', 'M3 6 H21 M3 12 H21 M3 18 H21 M8 3 V9 M16 9 V15 M10 15 V21'],
      ];
      tabs.forEach(([tab, label, path], index) => {
        const y = titleBarHeight + 16 + index * 52;
        const active = activeNav === tab;
        layer(`nav-${tab}`, 8, y, sideBarWidth - 16, 44, () => {
          if (active) rect(8, y, sideBarWidth - 16, 44, color.brandSoft, 10);
          icon(path, 22, y + 13, active ? color.brand : color.textSecondary);
          text(label, 56, y + 28, { size: 14, bold: active, fill: active ? color.brand : color.textSecondary, limit: sideBarWidth - (sessionLive && tab === 'terminal' ? 92 : 72) });
          if (sessionLive && tab === 'terminal') rect(sideBarWidth - 28, y + 18, 8, 8, color.successBorder, 4);
        }, 'hit');
      });
      const hostsY = titleBarHeight + 16 + 4 * 52 + 16;
      text('主机', 20, hostsY + 12, { size: 12, fill: color.textSecondary, limit: 120 });
      text('还没有主机 · 从看板添加', 20, hostsY + 34, { size: 13, fill: color.textMutedReadable, limit: sideBarWidth - 36 });
    });
  }
  return { id, title, screen, content, margin, span, titleBarHeight, pieces, anchors, textLimits, rect, text, line, icon, layer, button, pageHeader, notice, field, targetCard, fingerprintCard, fingerprintPair, footnote, options, windowChrome, sidebar };
}

function home(board, returned) {
  const { titleBarHeight: titleBar, margin, span, rect, text, icon, layer, button, notice } = board;
  const top = titleBar + 28;
  text('看板', margin, top + 14, { size: 22, bold: true, limit: span });
  if (returned) notice('closed-feedback', '普通 SSH 已断开', [], top + 34);
  const cardTop = top + (returned ? 94 : 50);
  layer('home-empty-card', margin, cardTop, span, 268, () => {
    rect(margin, cardTop, span, 268, color.card, tokens.radii.card, color.border);
    rect(margin + 16, cardTop + 16, 44, 44, color.brandSoft, 10);
    icon('M3 4 H21 V20 H3 Z M7 9 L10 12 L7 15 M13 15 H17', margin + 26, cardTop + 26, color.brand);
    text('还没有主机', margin + 16, cardTop + 89, { size: 18, bold: true, limit: span - 32 });
    text('添加主机后，在这里查看会话和任务状态。', margin + 16, cardTop + 116, { size: 13, fill: color.textSecondary, limit: span - 32 });
    button('home-add', '添加主机', cardTop + 144, { x: margin + 16, w: span - 32 });
    button('home-direct-ssh', '普通 SSH 终端', cardTop + 204, { x: margin + 16, w: span - 32, kind: 'secondary' });
  });
}
function chooser(board) {
  const { width, titleBarHeight: titleBar, margin, span, pageHeader, layer, rect, text, icon } = board;
  pageHeader('添加主机');
  const top = titleBar + 80;
  text('选择连接方式', margin, top + 20, { size: 22, bold: true, limit: span });
  const options = [
    ['choose-ssh', '普通 SSH 终端', '使用服务器密码或已有私钥打开远程 Shell。', color.brandSoft, color.brand, 'M3 4 H21 V20 H3 Z M7 9 L10 12 L7 15 M13 15 H17'],
    ['choose-herdr', 'herdr 配对 / 手动连接', '接入 herdr 工作台，查看会话和任务。', color.cardSubtle, color.textSecondary, 'M4 6 H20 V18 H4 Z M4 10 H20 M9 10 V18'],
  ];
  options.forEach(([id, title, detail, iconBackground, iconColor, path], index) => {
    const y = top + 44 + index * 112;
    layer(id, margin, y, span, 100, () => {
      rect(margin, y, span, 100, color.card, tokens.radii.card, index ? color.border : color.brandBorder);
      rect(margin + 14, y + 14, 40, 40, iconBackground, 10);
      icon(path, margin + 22, y + 22, iconColor);
      text(title, margin + 66, y + 39, { size: 16, bold: true, limit: span - 102 });
      icon('M8 5 L15 12 L8 19', margin + span - 36, y + 22, color.textSecondary);
      text(detail, margin + 14, y + 77, { size: 13, fill: color.textSecondary, limit: span - 28 });
    }, 'hit');
  });
}
function endpoint(board, feedback, focused = false) {
  const { titleBarHeight: titleBar, margin, span, pageHeader, field, text, button, footnote, notice } = board;
  pageHeader('普通 SSH');
  let y = titleBar + 76;
  if (feedback === 'disconnected') {
    y = notice('closed-feedback', '已断开连接', ['本次凭据已清空。重新连接时请重新填写。'], y) + 16;
  } else if (feedback === 'previous-trust') {
    y = notice('trust-preserved', '已保留旧信任', ['请重新探测并独立核对主机指纹。'], y) + 16;
  }
  text('填写连接目标', margin, y + 20, { size: 22, bold: true, limit: span });
  y = field('host', '主机地址', 'ssh.example.test', margin, y + 36, span, { focused }) + 14;
  const portWidth = 84;
  field('username', '用户名', 'demo', margin, y, span - portWidth - 12);
  y = field('port', '端口', '22', margin + span - portWidth, y, portWidth) + 20;
  button('probe', '探测并核对主机密钥', y);
  if (feedback !== 'previous-trust') footnote('探测时仅获取主机密钥，认证在核对之后进行。', y + 70);
  if (feedback === 'disconnected') button('return-home', '返回首页', y + 84, { kind: 'secondary' });
}
function trust(board, rotated) {
  const { titleBarHeight: titleBar, margin, span, pageHeader, layer, text, button, targetCard, fingerprintCard } = board;
  pageHeader('核对主机密钥');
  const y = targetCard(titleBar + 76, { compact: true }) + 12;
  fingerprintCard(y, rotated ? replacementKey : currentKey);
  layer('independent-verification', margin, y + 138, span, 52, () => {
    text('请通过服务器控制台或向管理员独立核对。', margin, y + 152, { fill: color.textSecondary, limit: span });
    text('算法和完整指纹一致后，再确认继续。', margin, y + 173, { fill: color.textSecondary, limit: span });
  });
  button('trust-confirm', '指纹一致，确认继续', y + 196);
  button('trust-cancel', rotated ? '取消核对，保留旧信任' : '取消核对', y + 256, { kind: 'secondary' });
}
function auth(board, key) {
  const { titleBarHeight: titleBar, margin, span, pageHeader, field, button, footnote, notice, targetCard, options } = board;
  pageHeader('SSH 账号认证');
  let y = targetCard(titleBar + 76, { compact: true }) + 10;
  y = notice('trust-approved', '本次主机密钥已确认', [], y, 'success') + 20;
  y = options(y, Number(key)) + 14;
  if (key) {
    y = field('key-pem', '私钥 PEM（仅本次使用）', '粘贴已有私钥的完整 PEM', margin, y, span, { height: 84, example: true }) + 10;
    button('paste-key', '粘贴私钥', y, { kind: 'secondary' });
    y = field('passphrase', '私钥口令（加密私钥需要）', '未填写', margin, y + 60, span, { example: true }) + 14;
  } else {
    y = field('password', '密码（仅本次使用）', '••••••••', margin, y) + 14;
  }
  button('connect', '连接 SSH', y, { kind: key ? 'disabled' : 'primary' });
  footnote(key ? '填写完整私钥后才能连接。' : '断开或取消后，本次密码会清空。', y + 68);
}
function changed(board) {
  const { titleBarHeight: titleBar, pageHeader, notice, targetCard, fingerprintPair, button } = board;
  pageHeader('主机指纹发生变化', { back: false });
  let y = notice('changed-warning', '已阻止连接与输入', ['主机密钥与上次核对结果不同。', '请联系管理员确认变更，再重新核验。'], titleBar + 76, 'danger') + 12;
  y = targetCard(y, { compact: true }) + 12;
  fingerprintPair(y);
  button('recheck', '重新核对主机指纹', y + 183);
  button('keep-previous-trust', '取消连接，保留旧信任', y + 243, { kind: 'secondary' });
}
function terminal(board) {
  const { id, screen: { width, height }, content, margin, span, titleBarHeight, pageHeader, rect, text, layer } = board;
  pageHeader('普通 SSH', { back: false, action: '断开', danger: true });
  const statusY = titleBarHeight + 68;
  layer('terminal-status', margin, statusY, span, 44, () => {
    rect(margin, statusY + 10, 62, 24, color.successSoft, 8, color.successBorder);
    text('已连接', margin + 31, statusY + 26, { size: 12, fill: color.successText, align: 'middle', bold: true, limit: 54 });
    text(target, margin + 72, statusY + 27, { size: 12, family: mono, limit: span - 72 });
  });
  const terminalY = statusY + 52;
  const termHeight = height - 16 - terminalY;
  layer('terminal-panel', margin, terminalY, span, termHeight, () => {
    rect(margin, terminalY, span, termHeight, color.termBg, 12, color.termBorder);
    const base = terminalY + 27;
    const terminalText = (value, y, fill) => text(value, margin + 12, y, { family: mono, size: 14, fill, limit: span - 24 });
    terminalText('demo@lab:~$ pwd', base, color.termPrompt);
    terminalText('/home/demo', base + 20, color.termText);
    terminalText('demo@lab:~$', base + 40, color.termPrompt);
    rect(margin + 124, base + 28, 8, 16, color.termCursor, 1);
  });
  // 滚动条是键鼠连续控件：不适用 44pt 控件下限，标注 geometry；滚轮行为遵循系统惯例。
  layer('terminal-scrollbar', margin + span - 10, terminalY + 4, 6, termHeight - 8, () => {
    rect(margin + span - 10, terminalY + 4, 6, termHeight - 8, color.cardSubtle, 3);
    rect(margin + span - 10, terminalY + 8, 6, 40, color.textSecondary, 3);
  });
}
function settings(board) {
  const { titleBarHeight: titleBar, margin, span, pageHeader, notice, targetCard, field, button } = board;
  pageHeader('设置', { back: false });
  let y = notice('active-ssh', '普通 SSH 会话保持连接', ['切到看板、网络或设置不会断开；显式断开后才结束。'], titleBar + 76, 'success') + 10;
  y = targetCard(y, { compact: true }) + 16;
  y = field('font-size', '终端字号（10–28）', '14', margin, y) + 12;
  button('save-font-size', '保存字号', y, { kind: 'secondary' });
  button('transfer-settings', '导入 / 导出配置', y + 64, { kind: 'secondary' });
}
const states = [
  ['home', '空首页', (board) => home(board, false), 'board', false],
  ['choose', '选择接入方式', chooser, null, false],
  ['target', '填写连接目标', (board) => endpoint(board), null, false],
  ['target-focused', '目标输入聚焦', (board) => endpoint(board, undefined, true), null, false],
  ['trust', '首次核对主机密钥', (board) => trust(board, false), null, false],
  ['password', '密码认证', (board) => auth(board, false), null, false],
  ['private-key', '已有私钥认证', (board) => auth(board, true), null, false],
  ['terminal', '活动终端', terminal, 'terminal', true],
  ['settings-active', '设置 · 会话保持连接', settings, 'settings', true],
  ['disconnected', '断开连接', (board) => endpoint(board, 'disconnected'), null, false],
  ['returned', '断开后返回首页', (board) => home(board, true), 'board', false],
  ['key-changed', '指纹变化 · 阻止连接', changed, null, false],
  ['previous-trust', '取消并保留旧信任', (board) => endpoint(board, 'previous-trust'), null, false],
  ['recheck-trust', '重新核对主机密钥', (board) => trust(board, true), null, false],
];
function boardGroup(board, x = 0, y = 0) {
  return `<g id="${board.id}" transform="translate(${x} ${y})">\n<title>${escape(`${board.id} · ${board.title}`)}</title>\n${board.pieces.join('\n')}\n</g>`;
}
function svg(width, height, body) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">\n${body}\n</svg>\n`;
}
const write = (path, content) => writeFileSync(path, content, 'utf8');
const output = process.argv[2] ?? new URL('./direct-ssh-desktop.svg', import.meta.url);
const pages = process.argv[3];
const atlas = [];
const manifest = [];
const cols = 4;
const gutter = 24;
const labelHeight = 36;
const columnWidth = 1440 + gutter;
const rowsPerSize = Math.ceil(states.length / cols);
if (pages) mkdirSync(pages, { recursive: true });
let sizeOffset = 0;
sizes.forEach((screen, sizeIndex) => {
  const rowHeight = screen.height + labelHeight + gutter;
  states.forEach(([state, title, render, nav, sessionLive], index) => {
    const board = createBoard(state, title, screen);
    const { width, height } = screen;
    board.rect(0, 0, width, height, color.canvas);
    board.windowChrome();
    board.sidebar(nav, sessionLive);
    render(board);
    const x = gutter + (index % cols) * columnWidth;
    const y = gutter + (sizeOffset + Math.floor(index / cols)) * rowHeight + labelHeight;
    atlas.push(`<text x="${x}" y="${y - 12}" font-family="${sans}" font-size="16" font-weight="600" fill="${color.textPrimary}">${escape(`${board.id} · ${title}`)}</text>`);
    atlas.push(boardGroup(board, x, y));
    manifest.push({ id: board.id, title, width, height, titleBar: titleBarHeight, sideBar: sideBarWidth, atlas: { x, y, width, height }, anchors: board.anchors, textLimits: board.textLimits });
    if (pages) write(join(pages, `${board.id}.svg`), svg(width, height, boardGroup(board)));
  });
  sizeOffset += rowsPerSize;
});
const atlasWidth = columnWidth * cols + gutter;
const atlasHeight = gutter + sizes.reduce((sum, screen) => sum + rowsPerSize * (screen.height + labelHeight + gutter), 0);
write(output, svg(atlasWidth, atlasHeight, `<title>Herdr Pocket · 普通 SSH 桌面设计</title>\n<rect width="${atlasWidth}" height="${atlasHeight}" fill="${color.border}"/>\n${atlas.join('\n')}`));
if (pages) write(join(pages, 'geometry.json'), JSON.stringify({ unit: 'logical-point', tolerance: 2, viewports: sizes.map(({ width, height }) => ({ width, height, titleBar: titleBarHeight, sideBar: sideBarWidth, readingWidth })), boards: manifest }, null, 2) + '\n');
