import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createHash } from 'node:crypto';

const tokens = JSON.parse(readFileSync(new URL('../../validation/shared/design-tokens-v2.json', import.meta.url)));
const color = tokens.colors;
const target = 'demo@ssh.example.test:22';
const fingerprint = (label) => `SHA256:${createHash('sha256').update(label).digest('base64').replace(/=$/, '')}`;
const currentKey = fingerprint('herdr-pocket design example current');
const replacementKey = fingerprint('herdr-pocket design example replacement');
const tabHeight = 56;
const sans = 'Inter, PingFang SC, Noto Sans CJK SC, Microsoft YaHei, sans-serif';
const mono = 'JetBrainsMono Nerd Font Mono, JetBrains Mono, Menlo, monospace';
const escape = (value) => String(value).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[character]);

const sizes = [
  { width: 390, height: 844, safeTop: 47, safeBottom: 34, keyboardTop: 553 },
  { width: 320, height: 640, safeTop: 24, safeBottom: 24, keyboardTop: 402 },
];

function createBoard(state, title, screen) {
  const { width, height, safeTop, safeBottom, keyboardTop } = screen;
  const margin = width < 360 ? 16 : 24;
  const span = width - 2 * margin;
  const safeEnd = height - safeBottom;
  const hasKeyboard = state === 'terminal-open' || state === 'target-focused';
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
    const end = hasKeyboard ? keyboardTop : safeEnd;
    if (Math.min(x, y, w, h) < 0 || x + w > width || y + h > height) throw new Error(`${id} 锚点 ${name} 越出画板`);
    if (role !== 'system' && (y < safeTop || y + h > end)) throw new Error(`${id} 锚点 ${name} 越出应用可用区`);
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
  function header(label, { back = true, action, danger = false } = {}) {
    layer('app-header', 0, safeTop, width, 56, () => {
      rect(0, safeTop, width, 56, color.canvas);
      line(0, safeTop + 55.5, width, safeTop + 55.5);
      if (back) {
        const x = margin - 8;
        layer('back', x, safeTop + 6, 44, 44, () => icon('M14 4 L6 12 L14 20 M6 12 H20', x + 9, safeTop + 16), 'hit');
      }
      const x = back ? margin + 44 : margin;
      text(label, x, safeTop + 35, { size: 18, bold: true, limit: action ? width - x - 84 : width - x - margin });
      if (action) {
        const right = width - margin;
        layer('disconnect', right - 60, safeTop + 6, 60, 44, () => {
          rect(right - 60, safeTop + 6, 60, 44, color.dangerSoft, 10);
          text(action, right - 30, safeTop + 33, { bold: true, align: 'middle', limit: 56, fill: danger ? color.dangerText : color.brand });
        }, 'hit');
      }
    });
  }
  function notice(name, heading, detail, y, tone = 'info') {
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
  function fingerprintCard(y, value) {
    layer('key-evidence', margin, y, span, 122, () => {
      rect(margin, y, span, 122, color.card, 16, color.border);
      text('主机密钥算法', margin + 12, y + 21, { size: 12, fill: color.textSecondary, limit: span - 24 });
      text('ssh-ed25519', margin + 12, y + 43, { family: mono, limit: span - 24 });
      line(margin + 12, y + 53.5, width - margin - 12, y + 53.5);
      text('完整 SHA256 指纹', margin + 12, y + 72, { size: 12, fill: color.textSecondary, limit: span - 24 });
      fingerprintValue('key-fingerprint', value, y + 79);
    });
  }
  function fingerprintValue(name, value, y) {
    layer(name, margin + 12, y, span - 24, 34, () => {
      text(value.slice(0, 28), margin + 12, y + 12, { size: 13, family: mono, limit: span - 24 });
      text(value.slice(28), margin + 12, y + 30, { size: 13, family: mono, limit: span - 24 });
    });
  }
  function fingerprintPair(y) {
    layer('changed-keys', margin, y, span, 167, () => {
      rect(margin, y, span, 167, color.card, 16, color.border);
      text('算法 · ssh-ed25519', margin + 12, y + 22, { size: 13, bold: true, limit: span - 24 });
      text('旧指纹 · 已核对', margin + 12, y + 45, { size: 12, fill: color.textSecondary, limit: span - 24 });
      fingerprintValue('previous-key-fingerprint', currentKey, y + 53);
      line(margin + 12, y + 93.5, width - margin - 12, y + 93.5);
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
  function safeChrome() {
    layer('system-status', 0, 0, width, safeTop, () => {
      rect(0, 0, width, safeTop, color.canvas);
      text('9:41', margin, safeTop === 47 ? 29 : 17, { size: 13, bold: true, limit: 40 });
      const x = width - margin - 54;
      const y = safeTop === 47 ? 17 : 5;
      icon('M0 11 V9 M4 11 V7 M8 11 V5 M12 11 V3 M21 5 Q27 0 33 5 M23 8 Q27 5 31 8 M26 11 H28 M40 4 H53 V11 H40 Z M55 6 V9', x, y, color.textPrimary, 1.3);
    }, 'system');
    if (!hasKeyboard) {
      layer('system-bottom', 0, safeEnd, width, safeBottom, () => {
        rect(0, safeEnd, width, safeBottom, color.canvas);
        rect((width - 120) / 2, height - 12, 120, 4, color.textPrimary, 2);
      }, 'system');
    }
  }
  function keyboardPreview() {
    layer('system-keyboard', 0, keyboardTop, width, height - keyboardTop, () => {
      rect(0, keyboardTop, width, height - keyboardTop, '#DCE2EA');
      line(0, keyboardTop + 0.5, width, keyboardTop + 0.5, color.borderStrong);
      text('系统键盘 · 示意', width / 2, keyboardTop + 21, { size: 12, fill: color.textSecondary, align: 'middle', limit: width - 32 });
      const rowHeight = width === 390 ? 54 : 44;
      ['QWERTYUIOP', 'ASDFGHJKL', 'ZXCVBNM'].forEach((row, index) => {
        const keyWidth = (width - 54) / 10;
        const stride = keyWidth + 4;
        const left = (width - (row.length * stride - 4)) / 2;
        const y = keyboardTop + 32 + index * rowHeight;
        [...row].forEach((letter, keyIndex) => {
          const x = left + keyIndex * stride;
          rect(x, y, keyWidth, rowHeight - 8, color.card, 6);
          text(letter, x + keyWidth / 2, y + (rowHeight - 8) / 2 + 5, { size: 15, align: 'middle', limit: keyWidth - 2 });
        });
      });
      const bottomRow = keyboardTop + 32 + 3 * rowHeight;
      [[16, 58, '123'], [82, width - 164, '空格'], [width - 74, 58, '回车']].forEach(([x, w, label]) => {
        rect(x, bottomRow, w, rowHeight - 8, color.card, 6);
        text(label, x + w / 2, bottomRow + (rowHeight - 8) / 2 + 4, { size: 13, align: 'middle', limit: w - 8 });
      });
      rect((width - 120) / 2, height - 12, 120, 4, color.textPrimary, 2);
    }, 'system');
  }
  return { id, title, screen, margin, span, safeEnd, pieces, anchors, textLimits, rect, text, line, icon, layer, button, header, notice, field, targetCard, fingerprintCard, fingerprintPair, footnote, options, safeChrome, keyboardPreview };
}

function home(board, returned) {
  const { screen: { safeTop }, margin, span, rect, text, icon, layer, button, notice } = board;
  const top = safeTop + 16;
  layer('home-brand', margin, top, span, 44, () => {
    rect(margin, top + 5, 34, 34, color.brand, 10);
    text('HP', margin + 17, top + 27, { size: 12, bold: true, fill: color.textInverse, align: 'middle', limit: 30 });
    text('Herdr Pocket', margin + 44, top + 28, { size: 22, bold: true, limit: span - 44 });
  });
  if (returned) notice('closed-feedback', '本机已断开', [], top + 56);
  const cardTop = top + (returned ? 116 : 72);
  layer('home-empty-card', margin, cardTop, span, 268, () => {
    rect(margin, cardTop, span, 268, color.card, tokens.radii.card, color.border);
    rect(margin + 16, cardTop + 16, 44, 44, color.brandSoft, 10);
    icon('M3 4 H21 V20 H3 Z M7 9 L10 12 L7 15 M13 15 H17', margin + 26, cardTop + 26, color.brand);
    text('还没有主机', margin + 16, cardTop + 89, { size: 18, bold: true, limit: span - 32 });
    text('添加主机后，在这里查看会话和任务状态。', margin + 16, cardTop + 116, { size: 13, fill: color.textSecondary, limit: span - 32 });
    button('home-add', '添加主机', cardTop + 144, { x: margin + 16, w: span - 32 });
    button('home-direct-ssh', '普通 SSH 终端', cardTop + 204, { x: margin + 16, w: span - 32, kind: 'secondary' });
  });
  bottomTabs(board, 'board', 'home-tabs');
}

function bottomTabs(board, selected, name) {
  const { screen: { width }, safeEnd, rect, text, icon, layer } = board;
  const navY = safeEnd - tabHeight;
  layer(name, 0, navY, width, tabHeight, () => {
    rect(0, navY, width, tabHeight, color.card, 0, color.border);
    const tabs = [
      ['board', '看板', 'M3 3 H10 V10 H3 Z M14 3 H21 V10 H14 Z M3 14 H10 V21 H3 Z M14 14 H21 V21 H14 Z'],
      ['terminal', '终端', 'M3 4 H21 V20 H3 Z M7 9 L10 12 L7 15 M13 15 H17'],
      ['network', '网络', 'M12 3 A9 9 0 1 0 12 21 A9 9 0 1 0 12 3 M3 12 H21 M12 3 C6 7 6 17 12 21 C18 17 18 7 12 3'],
      ['settings', '设置', 'M3 6 H21 M3 12 H21 M3 18 H21 M8 3 V9 M16 9 V15 M10 15 V21'],
    ];
    tabs.forEach(([tab, label, path], index) => {
      const x = index * width / 4;
      const center = x + width / 8;
      const active = selected === tab;
      const fill = active ? color.brand : color.textSecondary;
      layer(`tab-${tab}`, x, navY, width / 4, tabHeight, () => {
        if (active) rect(center - 20, navY + 5, 40, 28, color.brandSoft, 10);
        icon(path, center - 12, navY + 7, fill);
        text(label, center, navY + 47, { size: 12, fill, align: 'middle', limit: width / 4 - 8 });
      }, 'hit');
    });
  });
}

function chooser(board) {
  const { screen: { width, safeTop }, margin, span, header, layer, rect, text, icon } = board;
  header('添加主机');
  const top = safeTop + 80;
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
      icon('M8 5 L15 12 L8 19', width - margin - 36, y + 22, color.textSecondary);
      text(detail, margin + 14, y + 77, { size: 13, fill: color.textSecondary, limit: span - 28 });
    }, 'hit');
  });
}

function endpoint(board, feedback, focused = false) {
  const { screen: { safeTop }, margin, span, header, field, text, button, footnote, notice } = board;
  header('普通 SSH');
  let y = safeTop + 76;
  if (feedback === 'disconnected') {
    // 用户定稿：确认本机已结束且清凭据即显示「本机已断开」；无远端报告只讲本机和凭据。
    y = notice('closed-feedback', '本机已断开', ['凭据已清空，重连时请重新填写。'], y) + 16;
  } else if (feedback === 'disconnected-remote-exit') {
    // 仅当确有明确远端结束证据（如 exit 状态报告）才加远端一句；320 窄屏拆两行避免超宽。
    const lines = board.screen.width > 320 ? ['远端已报告结束，凭据已清空。重连时请重新填写。'] : ['远端已报告结束，凭据已清空。', '重连时请重新填写。'];
    y = notice('closed-feedback', '本机已断开', lines, y) + 16;
  } else if (feedback === 'disconnect-failed') {
    // 关停失败单独说明，不声称成功；不新增操作，返回首页语义另页说明。
    y = notice('stop-failed-feedback', '本机连接关闭失败', ['会话可能仍在。可返回首页。'], y, 'danger') + 16;
  } else if (feedback === 'previous-trust') {
    y = notice('trust-preserved', '已保留旧信任', ['请重新探测并独立核对主机指纹。'], y) + 16;
  }
  text('填写连接目标', margin, y + 20, { size: 22, bold: true, limit: span });
  y = field('host', '主机地址', 'ssh.example.test', margin, y + 36) + 14;
  const portWidth = 84;
  field('username', '用户名', 'demo', margin, y, span - portWidth - 12, { focused });
  y = field('port', '端口', '22', margin + span - portWidth, y, portWidth) + 20;
  button('probe', '探测并核对主机密钥', y);
  if (feedback !== 'previous-trust') footnote('探测时仅获取主机密钥，认证在核对之后进行。', y + 70);
  if (feedback === 'disconnected' || feedback === 'disconnected-remote-exit') button('return-home', '返回首页', y + 84, { kind: 'secondary' });
  if (feedback === 'disconnect-failed') button('return-home', '返回首页', y + 84, { kind: 'secondary' });
  if (focused) board.keyboardPreview();
}

function trust(board, rotated) {
  const { screen: { safeTop }, margin, span, header, layer, text, button, targetCard, fingerprintCard } = board;
  header('核对主机密钥');
  const y = targetCard(safeTop + 76, { compact: true }) + 12;
  fingerprintCard(y, rotated ? replacementKey : currentKey);
  layer('independent-verification', margin, y + 138, span, 52, () => {
    text('请通过服务器控制台或向管理员独立核对。', margin, y + 152, { fill: color.textSecondary, limit: span });
    text('算法和完整指纹一致后，再确认继续。', margin, y + 173, { fill: color.textSecondary, limit: span });
  });
  button('trust-confirm', '指纹一致，确认继续', y + 196);
  button('trust-cancel', rotated ? '取消核对，保留旧信任' : '取消核对', y + 256, { kind: 'secondary' });
}

function auth(board, key) {
  const { screen: { width, safeTop }, margin, span, header, field, button, footnote, notice, targetCard, options } = board;
  header('SSH 账号认证');
  let y = targetCard(safeTop + 76, { compact: true }) + 10;
  y = notice('trust-approved', '本次主机密钥已确认', [], y, 'success') + (width < 360 ? 12 : 20);
  y = options(y, Number(key)) + 14;
  if (key) {
    y = field('key-pem', '私钥 PEM（仅本次使用）', '粘贴已有私钥的完整 PEM', margin, y, span, { height: width < 360 ? 68 : 84, example: true }) + 10;
    button('paste-key', '粘贴私钥', y, { kind: 'secondary' });
    y = field('passphrase', '私钥口令（加密私钥需要）', '未填写', margin, y + 60, span, { example: true }) + 14;
  } else {
    y = field('password', '密码（仅本次使用）', '••••••••', margin, y) + 14;
  }
  button('connect', '连接 SSH', y, { kind: key ? 'disabled' : 'primary' });
  footnote(key ? '填写完整私钥后才能连接。' : '断开或取消后，本次密码会清空。', y + 68);
}

function changed(board) {
  const { screen: { safeTop }, header, notice, targetCard, fingerprintPair, button } = board;
  header('主机指纹发生变化', { back: false });
  let y = notice('changed-warning', '已阻止连接与输入', ['主机密钥与上次核对结果不同。', '请联系管理员确认变更，再重新核验。'], safeTop + 76, 'danger') + 12;
  y = targetCard(y, { compact: true }) + 12;
  fingerprintPair(y);
  button('recheck', '重新核对主机指纹', y + 183);
  button('keep-previous-trust', '取消连接，保留旧信任', y + 243, { kind: 'secondary' });
}

function terminal(board, keyboard) {
  const { screen: { width, safeTop, keyboardTop }, margin, span, safeEnd, header, rect, text, layer, icon, keyboardPreview } = board;
  header('普通 SSH', { back: false, action: '断开', danger: true });
  const statusY = safeTop + 68;
  layer('terminal-status', margin, statusY, span, 44, () => {
    rect(margin, statusY + 10, 62, 24, color.successSoft, 8, color.successBorder);
    text('已连接', margin + 31, statusY + 26, { size: 12, fill: color.successText, align: 'middle', bold: true, limit: 54 });
    const x = margin + 72;
    text(target, x, statusY + 27, { size: width < 360 ? 11 : 12, family: mono, limit: width - x - margin - 48 });
    const controlX = width - margin - 44;
    layer('keyboard-toggle', controlX, statusY, 44, 44, () => {
      rect(controlX, statusY + 4, 44, 36, color.card, 8, color.borderStrong);
      icon('M3 5 H21 V17 H3 Z M6 9 H8 M10 9 H12 M14 9 H16 M18 9 H19 M8 13 H16', controlX + 10, statusY + 10, color.brand);
      if (keyboard) icon('M9 20 L12 23 L15 20', controlX + 10, statusY + 9, color.brand);
    }, 'hit');
  });
  const terminalY = statusY + 52;
  const end = keyboard ? keyboardTop : safeEnd - tabHeight;
  const keysHeight = width < 360 ? 92 : 44;
  const keysY = end - 12 - keysHeight;
  const termHeight = keysY - 8 - terminalY;
  layer('terminal-panel', margin, terminalY, span, termHeight, () => {
    rect(margin, terminalY, span, termHeight, color.termBg, 12, color.termBorder);
    const base = terminalY + 27;
    const terminalText = (value, y, fill) => text(value, margin + 12, y, { family: mono, size: 14, fill, limit: span - 24 });
    terminalText('demo@lab:~$ pwd', base, color.termPrompt);
    terminalText('/home/demo', base + 20, color.termText);
    terminalText('demo@lab:~$', base + 40, color.termPrompt);
    if (keyboard) rect(margin + 112, base + 28, 8, 16, color.termCursor, 1);
  });
  const keys = ['Esc', 'Tab', '↑', '↓', '←', '→', 'Ctrl-C'];
  const ids = ['esc', 'tab', 'up', 'down', 'left', 'right', 'ctrl-c'];
  const perRow = width < 360 ? 4 : 7;
  layer('terminal-keys', margin, keysY, span, keysHeight, () => {
    keys.forEach((key, index) => {
      const x = margin + (index % perRow) * 48;
      const y = keysY + Math.floor(index / perRow) * 48;
      const w = index === 6 ? 54 : 44;
      layer(`key-${ids[index]}`, x, y, w, 44, () => {
        rect(x, y, w, 44, color.termKeyBg, 8, color.termKeyBorder);
        text(key, x + w / 2, y + 27, { fill: color.termText, size: 12, family: mono, align: 'middle', limit: w - 8 });
      }, 'hit');
    });
  });
  if (keyboard) keyboardPreview();
  else bottomTabs(board, 'terminal', 'terminal-tabs');
}

function settings(board) {
  const { screen: { safeTop }, margin, span, header, notice, targetCard, field, button } = board;
  header('设置', { back: false });
  let y = notice('active-ssh', '普通 SSH 会话保持连接', [], safeTop + 76, 'success') + 10;
  y = targetCard(y, { compact: true }) + 16;
  y = field('font-size', '终端字号（10–28）', '14', margin, y, span) + 12;
  button('save-font-size', '保存字号', y, { kind: 'secondary' });
  button('transfer-settings', '导入 / 导出配置', y + 64, { kind: 'secondary' });
  bottomTabs(board, 'settings', 'settings-tabs');
}

const states = [
  ['home', '空首页', (board) => home(board, false)],
  ['choose', '选择接入方式', chooser],
  ['target', '填写连接目标', (board) => endpoint(board)],
  ['target-focused', '填写目标 · 键盘展开', (board) => endpoint(board, undefined, true)],
  ['trust', '首次核对主机密钥', (board) => trust(board, false)],
  ['password', '密码认证', (board) => auth(board, false)],
  ['private-key', '已有私钥认证', (board) => auth(board, true)],
  ['terminal-open', '终端 · 键盘展开', (board) => terminal(board, true)],
  ['terminal-closed', '终端 · 键盘收起', (board) => terminal(board, false)],
  ['settings-active', '设置 · 会话仍连接', settings],
  ['disconnected', '断开连接', (board) => endpoint(board, 'disconnected')],
  ['disconnected-remote-exit', '断开 · 远端报告结束', (board) => endpoint(board, 'disconnected-remote-exit')],
  ['disconnect-failed', '断开失败', (board) => endpoint(board, 'disconnect-failed')],
  ['returned', '断开后返回首页', (board) => home(board, true)],
  ['key-changed', '指纹变化 · 阻止连接', changed],
  ['previous-trust', '取消并保留旧信任', (board) => endpoint(board, 'previous-trust')],
  ['recheck-trust', '重新核对主机密钥', (board) => trust(board, true)],
];

function boardGroup(board, x = 0, y = 0) {
  return `<g id="${board.id}" transform="translate(${x} ${y})">\n<title>${escape(`${board.id} · ${board.title}`)}</title>\n${board.pieces.join('\n')}\n</g>`;
}

function svg(width, height, body) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">\n${body}\n</svg>\n`;
}

const write = (path, content) => writeFileSync(path, content, 'utf8');
const output = process.argv[2] ?? new URL('./direct-ssh-mobile.svg', import.meta.url);
const pages = process.argv[3];
const atlas = [];
const manifest = [];
const cols = 4;
const gutter = 24;
const labelHeight = 36;
const columnWidth = 390 + gutter;
const rowHeight = 844 + labelHeight + gutter;
const rowsPerSize = Math.ceil(states.length / cols);
if (pages) mkdirSync(pages, { recursive: true });

sizes.forEach((screen, sizeIndex) => {
  states.forEach(([state, title, render], index) => {
    const board = createBoard(state, title, screen);
    const { width, height } = screen;
    board.rect(0, 0, width, height, color.canvas);
    board.safeChrome();
    render(board);
    const x = gutter + (index % cols) * columnWidth;
    const y = gutter + (sizeIndex * rowsPerSize + Math.floor(index / cols)) * rowHeight + labelHeight;
    atlas.push(`<text x="${x}" y="${y - 12}" font-family="${sans}" font-size="16" font-weight="600" fill="${color.textPrimary}">${escape(`${board.id} · ${title}`)}</text>`);
    atlas.push(boardGroup(board, x, y));
    manifest.push({ id: board.id, title, ...screen, atlas: { x, y, width, height }, anchors: board.anchors, textLimits: board.textLimits });
    if (pages) write(join(pages, `${board.id}.svg`), svg(width, height, boardGroup(board)));
  });
});

const atlasWidth = columnWidth * cols + gutter;
const atlasHeight = rowHeight * rowsPerSize * sizes.length + gutter;
write(output, svg(atlasWidth, atlasHeight, `<title>Herdr Pocket · 普通 SSH 手机设计</title>\n<rect width="${atlasWidth}" height="${atlasHeight}" fill="${color.border}"/>\n${atlas.join('\n')}`));
if (pages) write(join(pages, 'geometry.json'), JSON.stringify({ unit: 'logical-point', tolerance: 2, boards: manifest }, null, 2) + '\n');
