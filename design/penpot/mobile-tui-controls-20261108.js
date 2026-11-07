// Proposed increment only. Run once through the official Penpot MCP in the
// authorized file/page after reviewing placement and existing interactions.
const file = 'b55064db-d93d-80f9-8008-ddd22e6d398f';
const page = '7a22df08-251d-8016-8008-de03541c11da';

if (penpot.currentFile?.id !== file || penpot.currentPage?.id !== page) {
  throw Error('wrong file or page');
}

const old = penpot.root.children.filter(s => s.type === 'board');
if (old.some(s => /^S6[1-4](?![0-9])/.test(s.name))) {
  throw Error('increment already exists; inspect before retry');
}

const observe = old.find(s => s.id === '7a22df08-251d-8016-8008-de04a20d928d');
const draft = old.find(s => s.id === 'e6d238f0-ac08-8028-8008-de07ebece9ba');
const unknown = old.find(s => s.id === 'feb2a821-b263-8097-8008-de215d48f293');
if (!observe || !draft || !unknown) {
  throw Error('existing destinations missing');
}

const face = penpot.fonts.findByName('Inter');
const mono = penpot.fonts.findByName('IBM Plex Mono') || face;

function rect(p, n, x, y, w, h, c, r = 10) {
  const s = penpot.createRectangle();
  s.name = n;
  s.resize(w, h);
  s.borderRadius = r;
  s.fills = [{ fillColor: c, fillOpacity: 1 }];
  p.appendChild(s);
  s.x = p.x + x;
  s.y = p.y + y;
  return s;
}

function text(p, n, x, y, w, h, v, size, c, weight = 400, font = face) {
  const s = penpot.createText(v);
  s.name = n;
  s.resize(w, h);
  font?.applyToText(s);
  s.fontSize = String(size);
  s.fontWeight = String(weight);
  s.lineHeight = '1.35';
  s.fills = [{ fillColor: c, fillOpacity: 1 }];
  p.appendChild(s);
  s.x = p.x + x;
  s.y = p.y + y;
  return s;
}

function go(s, t) {
  s.addInteraction('click', { type: 'navigate-to', destination: t });
}

function button(p, n, x, y, w, label, target, primary = false) {
  const bg = rect(
    p, 'action · ' + n, x, y, w, 48,
    primary ? '#4F46E5' : '#E0E7FF',
  );
  const t = text(
    p, n, x + 4, y + 13, w - 8, 22, label, 14,
    primary ? '#FFFFFF' : '#3730A3', 600,
  );
  t.align = 'center';
  go(bg, target);
  go(t, target);
}

const y = Math.ceil(Math.max(...old.map(s => s.y + s.height)) + 80);

function board(name, x) {
  const b = penpot.createBoard();
  b.name = name;
  b.resize(390, 844);
  b.x = x;
  b.y = y;
  b.showInViewMode = true;
  b.borderRadius = 20;
  b.fills = [{ fillColor: '#F8FAFC', fillOpacity: 1 }];
  return b;
}

const collapsed = board('S61 · 手机功能键 · 逐键入口', 0);
const expanded = board('S62 · 手机功能键 · 展开', 450);
const composing = board('S63 · 手机功能键 · 组字中', 900);
const locked = board('S64 · 手机功能键 · 结果未知', 1350);

function header(b, title) {
  text(b, '标识', 24, 20, 342, 20, '手机终端 · 交互原型', 12, '#64748B', 600);
  text(b, '标题', 24, 52, 342, 32, title, 22, '#0F172A', 600);
  text(
    b, '目标', 24, 93, 342, 40,
    '本次已配对目标 / 同一 pane（示例）\n设计示意 · 不代表设备验证通过',
    13, '#475569', 400, mono,
  );
  rect(b, '终端背景', 24, 145, 342, 120, '#0F172A');
  text(
    b, '终端示意', 40, 155, 310, 102,
    'Pocket TUI\nF1 Help   F5 Refresh   F10 Finish\n> Build   Review\nDetail: xy   Focus: list   Refreshes: 0',
    12, '#F8FAFC', 400, mono,
  );
}

function modes(b) {
  button(b, '观察', 24, 280, 105, '观察', observe);
  button(b, '逐键', 142, 280, 105, '逐键', collapsed, true);
  button(b, '草稿', 260, 280, 106, '草稿', draft);
}

header(collapsed, '逐键输入');
modes(collapsed);
text(
  collapsed, '逐键说明', 24, 346, 342, 70,
  '逐键会立即发送到当前终端。功能键面板用于单次发送；草稿需独立审查后发送。',
  14, '#475569',
);
button(collapsed, '展开功能键', 24, 441, 342, '展开功能键', expanded, true);
button(collapsed, '未知结果说明', 24, 501, 342, '查看结果未知时的处理', locked);
text(
  collapsed, '注记', 24, 770, 342, 48,
  '设计原型 · 不发送输入、不验证设备', 12, '#64748B',
);

function keyGrid(b, disabled) {
  const rows = [
    ['F1', 'F2', 'F3', 'F4'],
    ['F5', 'F6', 'F7', 'F8'],
    ['F9', 'F10', 'F11', 'F12'],
    ['Insert', 'Delete', 'Backspace', 'Shift+Tab'],
  ];

  rows.forEach((row, r) => row.forEach((key, c) => {
    const x = 24 + c * 87;
    const y = 341 + r * 54;
    rect(
      b, '功能键 ' + key, x, y, 81, 48,
      disabled ? '#E2E8F0' : '#FFFFFF', 8,
    );
    const t = text(
      b, '键名 ' + key, x + 2, y + 13, 77, 23, key, 12,
      disabled ? '#94A3B8' : '#334155', 600, mono,
    );
    t.align = 'center';
  }));

  ['Ctrl', 'Alt'].forEach((key, i) => {
    const x = 24 + i * 174;
    rect(
      b, '一次性 ' + key, x, 563, 168, 48,
      disabled ? '#E2E8F0' : '#EEF2FF', 8,
    );
    const t = text(
      b, '修饰键状态 ' + key, x + 4, 575, 160, 24,
      key + (disabled ? ' · 组字中不可用' : ' · 未选'),
      13, disabled ? '#94A3B8' : '#3730A3', 600,
    );
    t.align = 'center';
  });
}

header(expanded, '功能键 · 逐键');
modes(expanded);
keyGrid(expanded, false);
text(
  expanded, '操作提示', 24, 640, 342, 40,
  '功能键可用 · 单次输入；Ctrl / Alt 仅作用下一辅助键。', 13, '#475569',
);
button(expanded, '组字演示', 24, 691, 342, '开始组字（演示）', composing, true);
button(expanded, '收起', 24, 748, 342, '收起功能键', collapsed);

header(composing, '组字中 · 暂停功能键');
modes(composing);
keyGrid(composing, true);
text(
  composing, '组字说明', 24, 640, 342, 44,
  '组字期间按键与 Ctrl / Alt 不可用；结束后重新启用，不自动重发。', 13, '#475569',
);
button(composing, '组字结束', 24, 701, 342, '组字结束，回到逐键', expanded, true);

header(locked, '结果未知 · 输入锁定');
text(
  locked, '未知说明', 24, 350, 342, 96,
  '原操作的结果尚未确认。停止发送并核实原目标状态；不要自动重放。观察可继续，草稿保留待审查。',
  15, '#475569',
);
button(locked, '核实原操作', 24, 480, 342, '查看待核实说明', unknown, true);
button(locked, '返回观察', 24, 540, 342, '返回只读观察', observe);

return {
  collapsed: collapsed.id,
  expanded: expanded.id,
  composing: composing.id,
  locked: locked.id,
  observe: observe.id,
  draft: draft.id,
  unknown: unknown.id,
};
