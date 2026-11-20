import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createHash } from 'node:crypto';

// 普通 SSH 桌面专属设计：单一源驱动 1440×900 / 980×780 / 700×900 三档客户端内容视口。
// 坐标口径：客户区 y=0，不含 OS 窗口 chrome；不绘制伪系统标题栏。
// 语义 token 与导出办法沿用 direct-ssh-mobile.mjs 模式；本文件不修改手机成果。
const tokens = JSON.parse(readFileSync(new URL('../../validation/shared/design-tokens-v2.json', import.meta.url)));
const color = tokens.colors;
const target = 'demo@ssh.example.test:22';
const promptText = 'demo@lab:~$'; // 11 字形（4+1+3+1+1+1），无尾空格
const fingerprint = (label) => `SHA256:${createHash('sha256').update(label).digest('base64').replace(/=$/, '')}`;
const currentKey = fingerprint('herdr-pocket design example current');
const replacementKey = fingerprint('herdr-pocket design example replacement');
const sideBarExpanded = 224;
const sideBarRail = 64; // 700 档收纳轨：图标可达，toggle 展开
const readingWidth = 560; // docs/63：仅限表单等阅读列；终端等工作区用剩余宽度
const sans = 'Inter, PingFang SC, Noto Sans CJK SC, Microsoft YaHei, sans-serif';
const mono = 'JetBrainsMono Nerd Font Mono, JetBrains Mono, Menlo, monospace';
const monoColumn = 8.4; // 14px mono 每列近似宽，终端光标按列求值
const escape = (value) => String(value).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[character]);

const sizes = [
  { width: 1440, height: 900 },
  { width: 980, height: 780 },
  { width: 700, height: 900 },
];

function createBoard(state, title, screen) {
  const { width, height } = screen;
  const rail = width <= 700;
  const sideBar = rail ? sideBarRail : sideBarExpanded;
  const content = { x: sideBar, y: 0, width: width - sideBar, height };
  const margin = content.x + 40;
  const span = Math.min(readingWidth, content.width - 80); // 表单阅读列
  const workWidth = width - margin - 40; // 独立 PTY 工作区：内容用满剩余宽度
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
    if (role === 'hit' && Math.min(w, h) < tokens.interaction.minTouchTarget) throw new Error(`${id} 命中区 ${name} 小于 44pt`);
    anchors[name] = { x, y, width: w, height: h, role };
    pieces.push(`<g id="${id}-${name}"><title>${escape(name)}</title>`);
    if (role === 'hit' || role === 'disabled') {
      // 命中区规范框：透明矩形声明实际可命中范围，放在控件组内，导入量测分组即得声明 44×44；
      // 可见形状允许小于它；实际系统命中行为留给两壳验收。
      pieces.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="none"/>`);
    }
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
    layer('page-header', content.x, 0, content.width, 56, () => {
      line(content.x, 55.5, width, 55.5);
      if (back) {
        const x = margin - 32;
        layer('back', x, 6, 44, 44, () => icon('M14 4 L6 12 L14 20 M6 12 H20', x + 9, 16), 'hit');
      }
      const x = back ? margin + 24 : margin;
      text(label, x, 35, { size: 18, bold: true, limit: action ? width - x - 120 : width - x - 40 });
      if (action) {
        const right = width - 40;
        layer('disconnect', right - 76, 4, 76, 44, () => {
          rect(right - 76, 6, 76, 40, color.dangerSoft, 10);
          text(action, right - 38, 32, { bold: true, align: 'middle', limit: 68, fill: danger ? color.dangerText : color.brand });
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
  function fingerprintCard(y, value, algorithm = 'ssh-ed25519') {
    layer('key-evidence', margin, y, span, 122, () => {
      rect(margin, y, span, 122, color.card, 16, color.border);
      text('主机密钥算法', margin + 12, y + 21, { size: 12, fill: color.textSecondary, limit: span - 24 });
      text(algorithm, margin + 12, y + 43, { family: mono, limit: span - 24 });
      line(margin + 12, y + 53.5, margin + span - 12, y + 53.5);
      text('完整 SHA256 指纹', margin + 12, y + 72, { size: 12, fill: color.textSecondary, limit: span - 24 });
      fingerprintValue('key-fingerprint', value, y + 79);
    });
  }
  function fingerprintPair(y) {
    layer('changed-keys', margin, y, span, 175, () => {
      rect(margin, y, span, 175, color.card, 16, color.border);
      text('旧指纹 · 已核对 · ssh-ed25519', margin + 12, y + 22, { size: 13, bold: true, limit: span - 24 });
      fingerprintValue('previous-key-fingerprint', currentKey, y + 30);
      line(margin + 12, y + 72.5, margin + span - 12, y + 72.5);
      text('新指纹 · 待核对 · rsa-sha2-512', margin + 12, y + 95, { size: 13, bold: true, fill: color.dangerText, limit: span - 24 });
      fingerprintValue('presented-key-fingerprint', replacementKey, y + 103);
      text('新旧算法可能不同，逐项独立核对。', margin + 12, y + 152, { size: 12, fill: color.textSecondary, limit: span - 24 });
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
  function sidebar(activeNav, sessionLive) {
    const rail = sideBar === sideBarRail;
    layer('app-sidebar', 0, 0, sideBar, height, () => {
      rect(0, 0, sideBar, height, color.card, 0, color.border);
      line(sideBar - 0.5, 0, sideBar - 0.5, height, color.border);
      layer('sidebar-toggle', rail ? 10 : 8, 8, 44, 44, () => {
        icon('M4 6 H20 M4 12 H20 M4 18 H20', (rail ? 10 : 8) + 10, 17, color.textPrimary);
      }, 'hit');
      const tabs = [
        ['board', '看板', 'M3 3 H10 V10 H3 Z M14 3 H21 V10 H14 Z M3 14 H10 V21 H3 Z M14 14 H21 V21 H14 Z'],
        ['terminal', '终端', 'M3 4 H21 V20 H3 Z M7 9 L10 12 L7 15 M13 15 H17'],
        ['network', '网络', 'M12 3 A9 9 0 1 0 12 21 A9 9 0 1 0 12 3 M3 12 H21 M12 3 C6 7 6 17 12 21 C18 17 18 7 12 3'],
        ['settings', '设置', 'M3 6 H21 M3 12 H21 M3 18 H21 M8 3 V9 M16 9 V15 M10 15 V21'],
      ];
      tabs.forEach(([tab, label, path], index) => {
        const y = 68 + index * 52;
        const active = activeNav === tab;
        const itemX = rail ? 10 : 8;
        const itemW = rail ? 44 : sideBar - 16;
        layer(`nav-${tab}`, itemX, y, itemW, 44, () => {
          if (!rail && active) rect(itemX, y, itemW, 44, color.brandSoft, 10);
          icon(path, itemX + (rail ? 10 : 14), y + 13, active ? color.brand : color.textSecondary);
          if (rail) {
            if (sessionLive && tab === 'terminal') {
              rect(itemX + 30, y + 6, 8, 8, color.successBorder, 4);
              pieces.push(`<title>会话在线</title>`);
            }
          } else {
            text(label, itemX + 48, y + 28, { size: 14, bold: active, fill: active ? color.brand : color.textSecondary, limit: itemW - (sessionLive && tab === 'terminal' ? 96 : 60) });
            if (sessionLive && tab === 'terminal') {
              rect(itemX + itemW - 30, y + 10, 8, 8, color.successBorder, 4);
              text('在线', itemX + itemW - 46, y + 30, { size: 11, fill: color.successText, limit: 32 });
            }
          }
        }, 'hit');
      });
      if (!rail) {
        const hostsY = 68 + 4 * 52 + 16;
        text('主机', 20, hostsY + 12, { size: 12, fill: color.textSecondary, limit: 120 });
        text('还没有主机 · 从看板添加', 20, hostsY + 34, { size: 13, fill: color.textMutedReadable, limit: sideBar - 36 });
      }
    });
  }
  return { id, title, screen, content, margin, span, workWidth, sideBar, pieces, anchors, textLimits, rect, text, line, icon, layer, button, pageHeader, notice, field, targetCard, fingerprintCard, fingerprintPair, footnote, options, sidebar };
}

function emptyHostCard(board, cardTop) {
  const { margin, span, rect, text, icon, layer, button } = board;
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
function home(board, returned) {
  const { margin, span, text, notice } = board;
  const top = 28;
  text('看板', margin, top + 14, { size: 22, bold: true, limit: span });
  if (returned) notice('closed-feedback', '本机已断开', [], top + 34);
  emptyHostCard(board, top + (returned ? 94 : 50));
}
function boardActive(board) {
  const { margin, span, text, notice } = board;
  const top = 28;
  text('看板', margin, top + 14, { size: 22, bold: true, limit: span });
  const y = notice('active-ssh', '普通 SSH 会话保持连接', ['切到看板不会断开。从侧栏「终端」返回原会话，不产生新连接或输入。'], top + 34, 'success');
  emptyHostCard(board, y + 16);
}
function networkActive(board) {
  const { margin, span, text, notice, layer, rect, icon, button } = board;
  const top = 28;
  text('网络', margin, top + 14, { size: 22, bold: true, limit: span });
  const y = notice('active-ssh', '普通 SSH 会话保持连接', ['切到网络不会断开。从侧栏「终端」返回原会话，不产生新连接或输入。'], top + 34, 'success') + 16;
  layer('network-empty-card', margin, y, span, 204, () => {
    rect(margin, y, span, 204, color.card, tokens.radii.card, color.border);
    rect(margin + 16, y + 16, 44, 44, color.cardSubtle, 10);
    icon('M12 3 A9 9 0 1 0 12 21 A9 9 0 1 0 12 3 M3 12 H21 M12 3 C6 7 6 17 12 21 C18 17 18 7 12 3', margin + 22, y + 22, color.textSecondary);
    text('还没有网络配置', margin + 16, y + 89, { size: 18, bold: true, limit: span - 32 });
    text('配置 ZeroTier、Tailscale 或 EasyTier 后，在这里管理网络。', margin + 16, y + 116, { size: 13, fill: color.textSecondary, limit: span - 32 });
    button('network-add', '添加网络配置', y + 140, { x: margin + 16, w: span - 32, kind: 'secondary' });
  });
}
function chooser(board) {
  const { width, margin, span, pageHeader, layer, rect, text, icon } = board;
  pageHeader('添加主机');
  const top = 80;
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
  const { margin, span, pageHeader, field, text, button, footnote, notice } = board;
  pageHeader('普通 SSH');
  let y = 76;
  if (feedback === 'disconnected') {
    // 用户定稿：确认本机已结束且清凭据即显示「本机已断开」；无远端报告只讲本机和凭据。
    y = notice('closed-feedback', '本机已断开', ['凭据已清空，重连时请重新填写。'], y) + 16;
  } else if (feedback === 'disconnected-remote-exit') {
    // 仅当确有明确远端结束证据（如 exit 状态报告）才加远端一句。
    y = notice('closed-feedback', '本机已断开', ['远端已报告结束，凭据已清空。重连时请重新填写。'], y) + 16;
  } else if (feedback === 'disconnect-failed') {
    // 关停失败单独说明，不声称成功；不新增操作，返回首页语义在文档说明。
    y = notice('stop-failed-feedback', '本机连接关闭失败', ['会话可能仍在。可返回首页。'], y, 'danger') + 16;
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
  if (feedback === 'disconnected' || feedback === 'disconnected-remote-exit' || feedback === 'disconnect-failed') button('return-home', '返回首页', y + 84, { kind: 'secondary' });
}
function trust(board, rotated) {
  const { margin, span, pageHeader, layer, text, button, targetCard, fingerprintCard } = board;
  pageHeader('核对主机密钥');
  const y = targetCard(76, { compact: true }) + 12;
  // 重核时展示的是待核对新密钥：算法与指纹逐项与 key-changed 的「新指纹」一致（rsa-sha2-512）。
  fingerprintCard(y, rotated ? replacementKey : currentKey, rotated ? 'rsa-sha2-512' : 'ssh-ed25519');
  layer('independent-verification', margin, y + 138, span, 52, () => {
    text('请通过服务器控制台或向管理员独立核对。', margin, y + 152, { fill: color.textSecondary, limit: span });
    text('算法和完整指纹一致后，再确认继续。', margin, y + 173, { fill: color.textSecondary, limit: span });
  });
  button('trust-confirm', '指纹一致，确认继续', y + 196);
  button('trust-cancel', rotated ? '取消核对，保留旧信任' : '取消核对', y + 256, { kind: 'secondary' });
}
function auth(board, key, pemState = null) {
  const { margin, span, pageHeader, field, button, footnote, notice, targetCard, options, layer, rect, text } = board;
  pageHeader('SSH 账号认证');
  let y = targetCard(76, { compact: true }) + 10;
  y = notice('trust-approved', '本次主机密钥已确认', [], y, 'success') + 20;
  y = options(y, Number(key)) + 14;
  if (key) {
    if (pemState == null) {
    y = field('key-pem', '私钥 PEM（仅本次使用）', '粘贴已有私钥的完整 PEM', margin, y, span, { height: 84, example: true }) + 10;
    } else {
      const h = 84;
      text('私钥 PEM（仅本次使用）', margin, y + 14, { size: 13, bold: true, limit: span });
      layer(pemState == 'collapsed' ? 'edit-pem' : 'key-pem', margin, y + 22, span, h, () => {
        rect(margin, y + 22, span, h, color.card, pemState == 'collapsed' ? h / 2 : tokens.radii.button,
          pemState == 'focused' ? color.brand : color.borderStrong, pemState == 'focused' ? 2 : 1);
        if (pemState == 'focused') {
          text('合成示意内容 · 第一行', margin + 12, y + 50, { limit: span - 24 });
          text('合成示意内容 · 第二行', margin + 12, y + 70, { limit: span - 24 });
        } else {
          text('已填写私钥 · 重新编辑', margin + span / 2, y + 22 + h / 2 + 5,
            { align: 'middle', fill: color.brand, limit: span - 24 });
        }
      }, 'hit');
      y += 22 + h + 10;
    }
    button('paste-key', '粘贴私钥', y, { kind: 'secondary' });
    y = field('passphrase', '私钥口令（加密私钥需要）', '未填写', margin, y + 60, span, { example: true }) + 14;
  } else {
    y = field('password', '密码（仅本次使用）', '••••••••', margin, y) + 14;
  }
  button('connect', '连接 SSH', y, { kind: key ? 'disabled' : 'primary' });
  footnote(key ? '填写完整私钥后才能连接。' : '断开或取消后，本次密码会清空。', y + 68);
}
function changed(board) {
  const { pageHeader, notice, targetCard, fingerprintPair, button } = board;
  pageHeader('主机指纹发生变化', { back: false });
  let y = notice('changed-warning', '已阻止连接与输入', ['主机密钥与上次核对结果不同。', '请联系管理员确认变更，再重新核验。'], 76, 'danger') + 12;
  y = targetCard(y, { compact: true }) + 12;
  fingerprintPair(y);
  button('recheck', '重新核对主机指纹', y + 191);
  button('keep-previous-trust', '取消连接，保留旧信任', y + 251, { kind: 'secondary' });
}
function terminal(board) {
  const { screen: { width, height }, margin, workWidth, pageHeader, rect, text, layer } = board;
  pageHeader('普通 SSH', { back: false, action: '断开', danger: true });
  const statusY = 68;
  layer('terminal-status', margin, statusY, workWidth, 44, () => {
    rect(margin, statusY + 10, 62, 24, color.successSoft, 8, color.successBorder);
    text('已连接', margin + 31, statusY + 26, { size: 12, fill: color.successText, align: 'middle', bold: true, limit: 54 });
    text(target, margin + 72, statusY + 27, { size: 12, family: mono, limit: workWidth - 72 });
  });
  const terminalY = statusY + 52;
  const termHeight = height - 16 - terminalY;
  layer('terminal-panel', margin, terminalY, workWidth, termHeight, () => {
    rect(margin, terminalY, workWidth, termHeight, color.termBg, 12, color.termBorder);
    const base = terminalY + 27;
    const terminalText = (value, y, fill) => text(value, margin + 12, y, { family: mono, size: 14, fill, limit: workWidth - 24 });
    terminalText('demo@lab:~$ pwd', base, color.termPrompt);
    terminalText('/home/demo', base + 20, color.termText);
    terminalText(promptText, base + 40, color.termPrompt);
    // 光标 x 按提示符字符串本身求值（promptText.length 列，无硬编码）：JetBrainsMono hmtx
    // 实测每字形 600/1000 UPM = 0.6em × 14px = 8.4px，11 列 = 92.4px；
    // 其它字体按各自 hmtx/实测字宽独立校准，不假设 fallback 字宽相同。
    rect(margin + 12 + promptText.length * monoColumn, base + 27, 8, 15, color.termCursor, 1);
  });
  // 滚动条是键鼠连续控件：不适用 44pt 控件下限，标注 geometry；滚轮行为遵循系统惯例。
  layer('terminal-scrollbar', margin + workWidth - 10, terminalY + 4, 6, termHeight - 8, () => {
    rect(margin + workWidth - 10, terminalY + 4, 6, termHeight - 8, color.cardSubtle, 3);
    rect(margin + workWidth - 10, terminalY + 8, 6, 40, color.textSecondary, 3);
  });
}
function settings(board) {
  const { margin, span, pageHeader, notice, targetCard, field, button } = board;
  pageHeader('设置', { back: false });
  let y = notice('active-ssh', '普通 SSH 会话保持连接', ['切到看板、网络或设置不会断开；显式断开后才结束。'], 76, 'success') + 10;
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
  ['board-active', '看板 · 会话保持连接', boardActive, 'board', true],
  ['network-active', '网络 · 会话保持连接', networkActive, 'network', true],
  ['settings-active', '设置 · 会话保持连接', settings, 'settings', true],
  ['disconnected', '断开连接', (board) => endpoint(board, 'disconnected'), null, false],
  ['disconnected-remote-exit', '断开 · 远端报告结束', (board) => endpoint(board, 'disconnected-remote-exit'), null, false],
  ['disconnect-failed', '断开失败', (board) => endpoint(board, 'disconnect-failed'), null, false],
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
const rowsPerSize = Math.ceil(states.length / cols);
if (pages) mkdirSync(pages, { recursive: true });
let yOffset = gutter; // 逐尺寸累计上一档实际像素高度，避免行高错位重叠
let atlasWidth = 0;
sizes.forEach((screen) => {
  const rowHeight = screen.height + labelHeight + gutter;
  const columnWidth = screen.width + gutter;
  atlasWidth = Math.max(atlasWidth, columnWidth * cols + gutter);
  states.forEach(([state, title, render, nav, sessionLive], index) => {
    const board = createBoard(state, title, screen);
    const { width, height } = screen;
    board.rect(0, 0, width, height, color.canvas);
    board.sidebar(nav, sessionLive);
    render(board);
    const x = gutter + (index % cols) * columnWidth;
    const y = yOffset + Math.floor(index / cols) * rowHeight + labelHeight;
    atlas.push(`<text x="${x}" y="${y - 12}" font-family="${sans}" font-size="16" font-weight="600" fill="${color.textPrimary}">${escape(`${board.id} · ${board.title}`)}</text>`);
    atlas.push(boardGroup(board, x, y));
    manifest.push({ id: board.id, title, width, height, sideBar: board.sideBar, atlas: { x, y, width, height }, anchors: board.anchors, textLimits: board.textLimits });
    if (pages) write(join(pages, `${board.id}.svg`), svg(width, height, boardGroup(board)));
  });
  yOffset += rowsPerSize * rowHeight;
});
const atlasHeight = yOffset;
// 总览自检：所有画板 bbox 互不重叠且在总览画布内。
manifest.forEach((a, i) => {
  const b1 = a.atlas;
  if (b1.x < 0 || b1.y < 0 || b1.x + b1.width > atlasWidth || b1.y + b1.height > atlasHeight) throw new Error(`atlas 越界 ${a.id}`);
  manifest.slice(i + 1).forEach((b) => {
    const b2 = b.atlas;
    if (b1.x < b2.x + b2.width && b2.x < b1.x + b1.width && b1.y < b2.y + b2.height && b2.y < b1.y + b1.height) throw new Error(`atlas 重叠 ${a.id} / ${b.id}`);
  });
});
write(output, svg(atlasWidth, atlasHeight, `<title>Herdr Pocket · 普通 SSH 桌面设计</title>\n<rect width="${atlasWidth}" height="${atlasHeight}" fill="${color.border}"/>\n${atlas.join('\n')}`));
if (pages) write(join(pages, 'geometry.json'), JSON.stringify({ unit: 'logical-point', tolerance: 2, viewports: sizes.map(({ width, height }) => ({ width, height, sideBarRail, sideBarExpanded, readingWidth })), boards: manifest }, null, 2) + '\n');

// 附加状态单页独立导出，不改变既有总览及其画板坐标。
const pemPages = process.argv[4];
if (pemPages) {
  mkdirSync(pemPages, { recursive: true });
  const pemManifest = [];
  for (const screen of sizes) for (const state of ['focused', 'collapsed']) {
    const title = state === 'focused' ? '私钥 · 聚焦编辑' : '私钥 · 失焦摘要';
    const board = createBoard(`private-key-${state}`, title, screen);
    board.rect(0, 0, screen.width, screen.height, color.canvas);
    board.sidebar(null, false);
    auth(board, true, state);
    write(join(pemPages, `${board.id}.svg`), svg(screen.width, screen.height, boardGroup(board)));
    pemManifest.push({ id: board.id, title, width: screen.width, height: screen.height, anchors: board.anchors, textLimits: board.textLimits });
  }
  write(join(pemPages, 'geometry.json'), JSON.stringify({ unit: 'logical-point', tolerance: 2, boards: pemManifest }, null, 2) + '\n');
}
