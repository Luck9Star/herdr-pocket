# 普通 SSH 桌面设计与逐点验收
手机版设计见[普通 SSH 手机设计](direct-ssh-mobile.md)；本文只覆盖桌面（macOS / Linux / Windows 客户端内容区）。行为沿用 [docs/63 普通 SSH](../../docs/63-design-parity-and-direct-ssh.md)：标准服务器每连接独立 PTY，普通 SSH 页面本批独立，不复用 herdr 面板的观察政策。D1/D2 分屏只作为共用桌面外壳/窗口参考。
## 决策口径（本批冻结）
- 坐标口径：客户端内容区 y=0，不含 OS 窗口 chrome；画板不绘制系统标题栏或窗口三键。如需示意 OS chrome，置于画板与坐标之外，且排除出逐点测项。
- 看板/网络/设置切换后返回终端：保持原连接，不产生新连接或输入；显式断开才退役会话。
- 三档客户端内容视口：1440×900、980×780、700×900（[screens.json](../../design/penpot/screens.json) 1324–1349、[coverage.md](../coverage.md) 76–78：窄桌面主机侧栏可收纳）。
  - 1440/980：侧栏展开 224，含文字标签与会话在线状态。
  - 700：侧栏收纳为 64 宽 rail，仅图标 + 在线圆点；`sidebar-toggle`（44×44 hit）为可达的展开/返回入口。
- 560 只限表单等阅读列（docs/63）；独立 PTY 工作区使用剩余宽度呈现完整桌面终端（1440 档终端面板 1136 宽，700 档 556 宽）。
- 不画手机系统键盘；不拿当前实现截图反推尺寸。
- 字体 fallback：`Inter, PingFang SC, Noto Sans CJK SC, Microsoft YaHei`；终端 `JetBrainsMono Nerd Font Mono, JetBrains Mono, Menlo`。离线 SVG 渲染使用本机字体链，与各平台实际系统字体存在差异；Penpot 在线导入未执行，导入后逐点数值以重新导出的 geometry 为准。
## 打开与编辑
[打开离线画板总览](direct-ssh-desktop.svg)。生成源 `direct-ssh-desktop.mjs`（Node ≥ 20）：
```sh
cd design/penpot
node direct-ssh-desktop.mjs                        # 重生成 direct-ssh-desktop.svg
node direct-ssh-desktop.mjs out.svg pages/         # 另存总览 + 每屏单页 + geometry.json
```
单一源驱动三档视口。每屏 `<g id="{state}-{width}">` 下锚点 `<g id="{state}-{width}-{name}">` 带 `<title>`；`geometry.json` 记录每屏锚点 `{x,y,width,height,role}` 与文本 `maxWidth` 上限，`tolerance: 2` 逻辑像素为逐点验收门槛。角色：`geometry`（卡片、面板、滚动条）、`hit`（≥44×44 可命中）、`disabled`。命中区规范框是透明矩形，与可见形状分离；实际系统命中行为留给两壳验收。
## 状态清单（16 状态 × 3 视口 = 48 屏）
首页 → 普通 SSH 选择 → 目标表单（含聚焦态）→ 完整可信指纹 → 密码 / 已有私钥 → 活动终端 → 看板/网络/设置（会话保持）→ 已断开 → 返回首页；换钥拒绝、取消仍旧信任、明确重核。
| 状态 | id | 关键锚点（hit） | 滚动/上下文 |
| --- | --- | --- | --- |
| 空首页 | `home` | `home-add`, `home-direct-ssh`, `nav-*` | 卡片内纵向内容固定 |
| 选择接入方式 | `choose` | `choose-ssh`, `choose-herdr` | 无需滚动（980 档亦完整） |
| 填写连接目标 | `target` | `host`, `username`, `port`, `probe` | 560 阅读列；700 档实际列宽 `span=556`（客户区 636 − 双边 80） |
| 目标聚焦 | `target-focused` | `host`（含光标） | 同上 |
| 首次核对指纹 | `trust` | `trust-confirm`, `trust-cancel` | 完整 SHA256 两行展示，不截断；算法 ssh-ed25519 与旧指纹一致 |
| 密码认证 | `password` | `password`, `connect` | 凭据仅本次使用 |
| 已有私钥 | `private-key` | `key-pem`, `paste-key`, `passphrase`, `connect`（disabled 直至填键） | PEM 两行框内滚动 |
| 活动终端 | `terminal` | `disconnect`, `terminal-scrollbar`（geometry） | 终端占满剩余宽度与高度；滚动条为键鼠连续控件 |
| 看板 · 会话保持 | `board-active` | `nav-terminal`（返回原会话）, `home-*` | 顶部提示不断开 |
| 网络 · 会话保持 | `network-active` | `nav-terminal`, `network-add` | 顶部提示不断开 |
| 设置 · 会话保持 | `settings-active` | `font-size`, `save-font-size`, `transfer-settings`, `nav-*` | 顶部提示会话仍连接 |
| 已断开 | `disconnected` | `return-home`, `probe` | 凭据清空反馈 |
| 返回首页 | `returned` | `home-direct-ssh` | 断开反馈条 |
| 换钥拒绝 | `key-changed` | `recheck`, `keep-previous-trust` | 新旧指纹并列，算法可不同（旧 ssh-ed25519 / 新 rsa-sha2-512） |
| 保留旧信任 | `previous-trust` | `probe` | 提示重新探测 |
| 重新核对 | `recheck-trust` | `trust-confirm`, `trust-cancel` | 算法与指纹逐项等于 `key-changed` 新指纹（rsa-sha2-512） |
会话进行中的状态（`terminal`、`board-active`、`network-active`、`settings-active`）在 `terminal` 导航处显示在线状态：1440/980 为 8×8 圆点加「在线」文字；700 rail 为 8×8 圆点（`<title>` 会话在线）。`nav-*` 与 `sidebar-toggle` 命中区允许位于侧栏（x < 224 / < 64），其余 hit 全部位于内容区。
### 键盘焦点顺序与返回语义（双壳同一规则）
- 表单页：`host` → `username` → `port` → `probe`；认证页：方式选择（`auth-password`/`auth-key`）→ 凭据框 → `connect`；核对页：`trust-confirm` → `trust-cancel`。
- 页面标题栏 `back` 返回上一页，不提交任何输入；`disconnect` 需显式点击，断开后凭据清空。
- 切到看板/网络/设置再经 `nav-terminal` 返回：恢复原终端视图与会话状态，不产生新连接、不发送输入、不重置滚动位置。
- Flutter 与 Tauri 两壳按同一 geometry/锚点顺序验收；实际系统命中（点击/聚焦/按键）由各壳平台输入实现，不由画板断言。
## 逐点验收门槛
对每屏、每锚点（以 `geometry.json` 为准）：
1. 锚点几何 `{x,y,width,height}` 与实现实测差值 ≤ 2 逻辑像素（tolerance）。
2. `hit` 角色最小边 ≥ 44；规范框是控件组内首个透明矩形，导入量测分组即得声明的 44×44；可见形状允许小于规范框；`disabled` 视觉与 `hit` 区分。设计命中声明与真实运行时点击是两回事：后者由各壳平台输入实现验收，不由画板断言。
3. 文本不越过 `textLimits[].maxWidth`（溢出即失败）；长主机名/指纹可滚动或换行，不截断声明值。
4. 三档视口下同一状态锚点集合一致；700 档阅读列收窄但语义位置不变。
5. 终端滚动条为连续控件（`geometry`），无 44pt 要求；键盘输入为系统级，不在画板内绘制。终端光标 x 按提示符字符串本身求值：`demo@lab:~$` 为 11 字形（4+1+3+1+1+1，无尾空格，JS `length` = 11）；JetBrainsMono hmtx 实测每字形 600/1000 UPM = 0.6em，14px → 8.4px/列，11 列 = 92.4px（生成器用 `promptText.length * monoColumn`，无硬编码列数）。其它字体按各自 hmtx/实测字宽独立校准，各 fallback 字宽不保证相同。
6. atlas 总览中所有画板 bbox 互不重叠且在总览画布内（生成器逐尺寸累计实际行高并自检，重叠即构建失败）。
## 实测与界限
- 本批验证：生成器运行通过（Node 24）；48 屏 SVG 可解析；锚点 `g` 元素、`hit ≥ 44`、内容区归属、跨视口锚点集合一致、无越界、id 唯一、atlas bbox 正交不重叠均以脚本核验通过（离线可复算命令见上）。三档关键状态已抽查渲染几何。
- 界限：离线 SVG 是设计真源，不是实现截图；未执行 Penpot 在线导入/发布；未在真实桌面窗口上做像素级比对；实际窗口 chrome 由各平台提供，画板客户区 y=0。
