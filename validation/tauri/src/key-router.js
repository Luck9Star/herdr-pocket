// 桌面工作台（切片 3）：键盘导航与快捷键层。
// 依据 docs/08-ui-design-plan.md:68（D1「快捷键与焦点轮转」）与 :93（「定义桌面快捷键、焦点顺序及
// 输入/应用快捷键冲突的处理，不让快捷键绕过安全规则」——docs/08 未规定具体键位，键位表定义在此）。
// 红线 docs/05-product-design.md:143：快捷键不改变目标、不意外发送。实现策略：本层只做本地焦点轮转，
// 以及把快捷键转发到既有按钮已挂的 onclick 同一路径——自己绝不调用 invoke、绝不构造发送；
// 因此快捷键不可能绕过切片 1/2 与 src/gate.js 的任何守卫。
//
// 键位表（动作 → 键位 → 依据）：
// | 焦点轮转（下一区域） | F6 | Windows/浏览器/Office 桌面惯例：F6 在窗口区域间轮转 |
// | 焦点轮转（上一区域） | Shift+F6 | 同上 |
// | 从输入区强制离开 | Ctrl+Shift+F6 | 终端模拟器保留 Ctrl+Shift 命名空间（Ctrl+Shift+C/V 先例）；
// |   |  | 是输入焦点内唯一可用的应用快捷键 |
// | 切终端标签 1–8 | Ctrl+1..8 | 浏览器 Ctrl+数字切标签页惯例（Tauri webview 无浏览器标签，不冲突；
// |   |  | 浏览器预览里可能被浏览器自身抢占） |
// | 下一/上一终端标签 | Ctrl+Tab / Ctrl+Shift+Tab | 浏览器惯例 |
// | 切主机标签 1–8 | Alt+1..8 | 与终端标签的 Ctrl+数字区分；仅非输入焦点时生效，不与
// |   |  | tmux 等终端 Alt+数字用法冲突（输入聚焦时放行） |
// | 分屏面板焦点对调 | Ctrl+F6 | Office「Ctrl+F6 下一窗格」惯例；仅分屏双面板时生效 |
// | 开/关分屏 | Ctrl+Shift+\ | 对齐 VS Code Ctrl+\ 分屏记忆点，但落在 Ctrl+Shift 保留命名空间
// |   |  | （裸 Ctrl+\ 是终端 SIGQUIT，永不在本层消费） |
// | 返回主机看板 | Alt+Home | Home=主页/看板的桌面隐喻 |
//
// 焦点顺序（docs/08:93）：侧栏主机列表 → 侧栏待处理 → 主机标签(#host-tabs) → 终端标签(#view-tabs) →
// 各终端面板（分屏时每个面板是独立区域，DOM 顺序）→ 输入区（当前面板草稿编辑器），首尾循环；
// 每次按键时动态计算，为空/隐藏/无焦点的区域自然跳过。
//
// 输入/应用冲突处理（docs/05:143 红线）：activeElement 是 input/textarea/select/contenteditable，
// 或 IME 组合中（isComposing / keyCode 229）时，除 Ctrl+Shift+F6 外全部原样放行——不 preventDefault、
// 不 stopPropagation，可打印字符与终端快捷键按既有路径进入终端。
//
// 窄窗（<900px）决策：快捷键仍可用；侧栏区域跳过（#workbench-sidebar 由 style.css 隐藏）；
// 分屏相关（Ctrl+Shift+\、Ctrl+F6）随 #workbench-split 隐藏而拒绝，与切片 2 的窄窗守卫一致。
const EDITABLE = new Set(['INPUT', 'TEXTAREA', 'SELECT']);
const BUTTON = 'BUTTON';
const DRAFT_LABEL = '当前标签草稿';
const tag = node => String(node?.tagName || '').toUpperCase();  // 真实 DOM 大写、测试桩可能小写，统一比较

const isEditable = element => !!element && (element.isContentEditable === true || EDITABLE.has(tag(element)));
const isComposing = event => event.isComposing === true || event.keyCode === 229;
const isWide = () => (globalThis.window?.innerWidth ?? 0) >= 900;
const byId = id => globalThis.document?.getElementById?.(id);

/** root 自身与全部后代，DOM 顺序访问。 */
function visit(root, inspect) {
  if (!root) return;
  const step = node => { inspect(node); for (const child of node.children || []) step(child); };
  step(root);
}

/** 只经既有 onclick 触发：没有处理器的按钮不算可用动作，不为快捷键发明任何新副作用路径。 */
function press(button) {
  if (!button || button.disabled || button.hidden || typeof button.onclick !== 'function') return false;
  button.onclick();
  return true;
}

/** 区域首选目标：可聚焦且未禁用元素中优先 aria-pressed="true" 的当前项。 */
function preferred(root) {
  const items = [];
  visit(root, node => {
    if ((tag(node) === BUTTON || EDITABLE.has(tag(node)) || node.isContentEditable === true) && !node.disabled && !node.hidden) items.push(node);
  });
  return items.find(node => node.getAttribute?.('aria-pressed') === 'true') || items[0] || null;
}

function panels() {
  const body = byId('view-content');
  return body ? (body.children || []).filter(node => node.dataset?.role === 'workbench-panel') : [];
}

/** 输入区 = 当前焦点面板（dataset.focus="true"）的可写草稿编辑器；只聚焦不启用——
 *  输入模式仍须经既有「启用草稿输入/逐键输入」显式开启（gate.js 租约不变）。 */
function inputEditor() {
  for (const panel of panels()) {
    if (panel.dataset.focus !== 'true') continue;
    let draft = null;
    visit(panel, node => {
      if (!draft && tag(node) === 'TEXTAREA' && node.getAttribute?.('aria-label') === DRAFT_LABEL && !node.disabled && !node.hidden) draft = node;
    });
    if (draft) return draft;
  }
  return null;
}

function regions() {
  const roots = [];
  if (isWide()) roots.push(byId('workbench-host-list'), byId('workbench-pending-list'));
  roots.push(byId('host-tabs'), byId('view-tabs'), ...panels());
  const editor = inputEditor();
  if (editor) roots.push(editor);
  return roots.map(root => ({root, target: preferred(root)})).filter(region => region.target);
}

function rotate(backward) {
  const list = regions();
  if (!list.length) return false;
  const active = globalThis.document?.activeElement;
  let index = -1;
  // 从后往前找包含焦点的最内层区域：输入区在面板内，必须由后序匹配胜出。
  for (let i = list.length - 1; i >= 0; i--) {
    const root = list[i].root;
    if (root === active || root.contains?.(active)) { index = i; break; }
  }
  const next = index < 0 ? 0 : (index + (backward ? -1 : 1) + list.length) % list.length;
  list[next].target.focus?.();
  return true;
}

function navButtons(id) {
  const nav = byId(id);
  return nav ? (nav.children || []).filter(node => tag(node) === BUTTON) : [];
}

function selectByNumber(id, number) {
  const buttons = navButtons(id);
  return number >= 1 && number <= buttons.length && press(buttons[number - 1]);
}

function cycleViewTab(forward) {
  const buttons = navButtons('view-tabs');
  if (buttons.length < 2) return false;
  const current = Math.max(buttons.findIndex(button => button.getAttribute?.('aria-pressed') === 'true'), 0);
  return press(buttons[(current + (forward ? 1 : -1) + buttons.length) % buttons.length]);
}

/** 分屏直达对调：点击非焦点面板的「设为输入焦点」，与按钮点击走同一条 select/租约路径。 */
function swapPanelFocus() {
  const partner = panels().find(node => node.dataset.focus === 'false');
  if (!partner) return false;  // 未分屏没有可对调的面板；F6 轮转已覆盖单面板场景
  let button = null;
  visit(partner, node => { if (!button && node.dataset?.role === 'panel-focus') button = node; });
  return press(button);
}

function handleKeydown(event) {
  const doc = globalThis.document;
  if (!doc || event?.type !== 'keydown') return;
  if (isComposing(event) || event.repeat) return;  // IME 组合与按住重复键：应用层一律不碰
  const page = byId('remote-page');
  if (!page || page.hidden) return;  // 仅桌面工作台页启用；主机看板/离线实验室不抢键
  if (doc.querySelector?.('dialog[open]')) return;  // 模态（如字体诊断）打开时不越过对话框
  if (event.metaKey) return;  // ⌘/Win 修饰留给系统与平台快捷键
  const {key, ctrlKey, shiftKey, altKey} = event;
  const consume = () => { event.preventDefault(); event.stopPropagation(); };

  // 唯一允许穿透输入焦点的快捷键：Ctrl+Shift+F6 离开输入区（键位表：终端保留命名空间）。
  // 焦点离开由既有 blur 路径处理（loseDirect 显式释放租约；在途输入进入待核实而非重放）。
  if (ctrlKey && shiftKey && !altKey && key === 'F6') { if (rotate(false)) consume(); return; }

  // 输入/应用冲突处理：文本输入聚焦时其余按键全部原样放行（不 preventDefault / stopPropagation）。
  if (isEditable(doc.activeElement)) return;

  if (!ctrlKey && !altKey && key === 'F6') { if (rotate(shiftKey)) consume(); return; }
  if (ctrlKey && !shiftKey && !altKey && key === 'F6') { if (swapPanelFocus()) consume(); return; }
  if (ctrlKey && !altKey && key === 'Tab') { if (cycleViewTab(!shiftKey)) consume(); return; }
  if (ctrlKey && !shiftKey && !altKey && key >= '1' && key <= '8') { if (selectByNumber('view-tabs', Number(key))) consume(); return; }
  if (altKey && !ctrlKey && !shiftKey && key >= '1' && key <= '8') { if (selectByNumber('host-tabs', Number(key))) consume(); return; }
  if (ctrlKey && shiftKey && !altKey && key === '\\') { if (press(byId('workbench-split'))) consume(); return; }
  if (altKey && !ctrlKey && !shiftKey && key === 'Home') { if (press(byId('host-return-home'))) consume(); return; }
  // 其余按键（含未映射组合）不产生任何副作用。
}

export function initKeyRouter() {
  globalThis.document?.addEventListener?.('keydown', handleKeydown, true);
  return () => globalThis.document?.removeEventListener?.('keydown', handleKeydown, true);
}
