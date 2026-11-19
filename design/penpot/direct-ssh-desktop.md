# 普通 SSH 桌面设计与逐点验收

手机版设计见[普通 SSH 手机设计](direct-ssh-mobile.md)；本文只覆盖桌面（macOS / Linux / Windows 客户端内容区）。行为沿用 [docs/63 普通 SSH](../../docs/63-design-parity-and-direct-ssh.md)：标准服务器每连接独立 PTY，普通 SSH 页面本批独立，不复用 herdr 面对的观察政策。D1/D2 分屏只作为共用桌面外壳/窗口参考。

## 决策口径（本批冻结）

- 看板/网络/设置切换后返回终端：保持原连接；显式断开才退役会话。
- 三档客户端内容视口：1440×900、980×780、700×900。侧栏 224、标题栏 40、表单阅读宽度 560（docs/63）。
- 不画手机系统键盘；不拿当前实现截图反推尺寸。
- 字体 fallback：`Inter, PingFang SC, Noto Sans CJK SC, Microsoft YaHei`；终端 `JetBrainsMono Nerd Font Mono, JetBrains Mono, Menlo`。离线 SVG 渲染使用本机字体链，与各平台实际系统字体存在差异；Penpot 在线导入未执行，导入后逐点数值以重新导出的 geometry 为准。

## 打开与编辑

[打开离线画板总览](direct-ssh-desktop.svg)。生成源 `direct-ssh-desktop.mjs`（Node ≥ 20）：

```sh
cd design/penpot
node direct-ssh-desktop.mjs                        # 重生成 direct-ssh-desktop.svg
node direct-ssh-desktop.mjs out.svg pages/         # 另存总览 + 每屏单页 + geometry.json
```

单一源驱动三档视口。每屏 `<g id="{state}-{width}">` 下锚点 `<g id="{state}-{width}-{name}">` 带 `<title>`；`geometry.json` 记录每屏锚点 `{x,y,width,height,role}` 与文本 `maxWidth` 上限，`tolerance: 2` 逻辑像素为逐点验收门槛。角色：`system`（标题栏/侧栏壳）、`geometry`（卡片、面板、滚动条）、`hit`（≥44×44 可命中）、`disabled`。

## 状态清单（14 状态 × 3 视口 = 42 屏）

首页 → 普通 SSH 选择 → 目标表单（含聚焦态）→ 完整可信指纹 → 密码 / 已有私钥 → 活动终端 → 设置（会话保持）→ 已断开 → 返回首页；换钥拒绝、取消仍旧信任、明确重核。

| 状态 | id | 关键锚点（hit） | 滚动/上下文 |
| --- | --- | --- | --- |
| 空首页 | `home` | `home-add`, `home-direct-ssh`, `nav-*` | 卡片内纵向内容固定 |
| 选择接入方式 | `choose` | `choose-ssh`, `choose-herdr` | 无需滚动（980 档亦完整） |
| 填写连接目标 | `target` | `host`, `username`, `port`, `probe` | 560 阅读列；700 档列宽自适应 396 |
| 目标聚焦 | `target-focused` | `host`（含光标） | 同上 |
| 首次核对指纹 | `trust` | `trust-confirm`, `trust-cancel` | 完整 SHA256 两行展示，不截断 |
| 密码认证 | `password` | `password`, `connect` | 凭据仅本次使用 |
| 已有私钥 | `private-key` | `key-pem`, `paste-key`, `passphrase`, `connect`（disabled 直至填键） | PEM 两行框内滚动 |
| 活动终端 | `terminal` | `disconnect`, `terminal-scrollbar`（geometry） | 终端占满剩余高度；滚动条为键鼠连续控件 |
| 设置 · 会话保持 | `settings-active` | `font-size`, `save-font-size`, `transfer-settings`, `nav-*` | 顶部提示会话仍连接 |
| 已断开 | `disconnected` | `return-home`, `probe` | 凭据清空反馈 |
| 返回首页 | `returned` | `home-direct-ssh` | 断开反馈条 |
| 换钥拒绝 | `key-changed` | `recheck`, `keep-previous-trust` | 新旧指纹并列 |
| 保留旧信任 | `previous-trust` | `probe` | 提示重新探测 |
| 重新核对 | `recheck-trust` | `trust-confirm`, `trust-cancel` | 与 `trust` 同构，新指纹 |

侧栏在会话进行中的状态（`terminal`、`settings-active`）于 `terminal` 导航处显示 8×8 在线圆点；`nav-*` 命中区允许位于侧栏（x < 224），其余 hit 全部位于内容区。

## 逐点验收门槛

对每屏、每锚点（以 `geometry.json` 为准）：

1. 锚点几何 `{x,y,width,height}` 与实现实测差值 ≤ 2 逻辑像素（tolerance）。
2. `hit` 角色最小边 ≥ 44；`disabled` 视觉与 `hit` 区分。
3. 文本不越过 `textLimits[].maxWidth`（溢出即失败）。
4. 三档视口下同一状态锚点集合一致；700 档阅读列收窄但语义位置不变。
5. 终端滚动条为连续控件（`geometry`），无 44pt 要求；键盘输入为系统级，不在画板内绘制。

## 实测与界限

- 本批验证：生成器运行通过（Node 24）；42 屏 SVG 可解析；锚点 `g` 元素、`hit ≥ 44`、内容区归属、跨视口锚点集合一致、无越界、id 唯一均以脚本核验通过（命令见上）。三档中关键状态已抽查渲染几何。
- 界限：离线 SVG 是设计真源，不是实现截图；未执行 Penpot 在线导入/发布；未在真实桌面窗口上做像素级比对；系统标题栏控件为示意（`system` 角色），实际窗口 chrome 由各平台提供。
