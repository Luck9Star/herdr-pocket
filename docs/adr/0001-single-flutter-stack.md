# ADR-0001 · Flutter 第一候选与技术栈 A/B

状态：**暂定，待 A/B 定案**（2026-10-29）。本记录原先接受 Flutter 单栈方向；用户随后要求重新比较技术栈，并确定手机优先、桌面紧随。因此重新开放框架选择，保留原决策的演进，不把旧方向当作已实测胜出。

## 背景

目标是公开开源的 iOS、Android、Windows、macOS、Linux 统一远端 herdr 客户端，三种进程内 overlay、终端字体/cell 和输入可靠性不因框架变化而缩减。此前 dartssh2、自定义字节流和 observe NDJSON 提供了 Flutter 的可行起点，但这些能力不是 Flutter 独占，也没有本项目的真机结果。

用户已确定五端首版均须支持完整终端，手机默认任务辅助但仍提供逐键输入、快捷键与 TUI；辅助控件不替代完整终端验收。开源方向为希望衍生改动持续开放，具体许可证待组件来源、链接与分发方式审查，不自动指定 GPL/AGPL。

## 当前决策

1. **Flutter 为第一验证候选，Tauri 2 + xterm.js + Rust 为同规格 A/B 主要挑战者。**先做手机真机闭环，桌面紧随；Windows 原生桥最小验证并行，避免推迟发现五端阻断项。优先顺序来自 mobile-first，不是性能排名。
2. **UI 与 core 分开定案。**DartSSH2 与 russh 均有 streamlocal、exec 和自定义流路径；Rust core 可供 Flutter FFI 或 Tauri 使用。不为了语言统一增加无实证收益的层，也不以选 Flutter 为由锁死 SSH 实现。
3. **协议与可靠性只有一套。**共享 Host/session 身份、可信路由、事件恢复、generation/epoch、输入草稿与禁止重放规则；原生网络、凭据和生命周期通过平台适配实现。Flutter 候选可先用 Riverpod，但业务模型不依赖 Widget。
4. **手机完整终端先过同一正确性门槛。**逐键输入、IME、快捷键、TUI、选择、字体及辅助控件均必测，不能以草稿输入成功绕过。Flutter 侧首先验证 `terminal_view` 0.5.0，Tauri 侧验证 xterm.js 6.0.0；两者都不是已选产品组件。具体证据、限制和 A/B 产物见[技术栈复评](../06-technology-evaluation.md)。

`terminal_view` 声明 MIT 与五端覆盖，解析基准不含绘制；其 SGR 4 能力与 iOS 重复回车、resize 选区修复史须纳入验收。xterm.js 的手机触控/选择问题和系统 WebView 差异也需实测，不能以桌面生态替代手机结论。用户的持续开源方向允许进一步评估 `xterm3` AGPL 备选，但仍须许可兼容与实测，不自动更换候选，也不通过锁旧 MIT 版本跳过维护评估。来源：[terminal_view 0.5.0](https://pub.dev/packages/terminal_view/versions/0.5.0)、[变更记录](https://pub.dev/packages/terminal_view/changelog)、[xterm.js 6.0.0](https://github.com/xtermjs/xterm.js/releases/tag/6.0.0)、[xterm3 6.3.7](https://pub.dev/packages/xterm3/versions/6.3.7)。

终端 spike 同时包含字体资源和 cell 布局：使用相同、可再分发且锁定版本/样式的 Nerd Font 文件及受控 CJK/emoji fallback；Oh My Zsh 主题、Powerlevel10k、Oh My Posh 使用同一图标/宽度/光标/IME/重绘 fixture。图标存在不等于 wcwidth 一致，不因换字体改写远端主题或 profile。规则见[架构字体契约](../02-architecture.md#nerd-font字形与终端-cell)。

## 其他候选

Compose Multiplatform 是有效第二梯队，不能按“iOS 实验态”排除；Qt 保留为备选，但两者尚无本项目五端终端和原生桥能降低总维护成本的证据。React Native 和 MAUI 因五端维护覆盖、官方 Linux 缺口等原因不进首轮；PWA 的网关路径不满足当前进程内原生 overlay 目标。官方来源及筛选边界集中在[技术栈复评](../06-technology-evaluation.md)，不把排期筛选写成技术不可能。

## 定案与退出门槛

先验证正确性、手机交互、原生最小链路与有界资源，再以相同设备、字体、cell/viewport 和输出 fixture 比较整 App 输入反馈、内存及维护补丁；Tauri 计入 WebView 和原生进程，不拿 Dart 解析 benchmark 对浏览器绘制。

Tauri 若手机核心流程不退步，且终端正确性或维护成本有可复现优势，可以替代 Flutter。两者均通过而无明确优势时保留 Flutter 的第一验证路径；均失败则调整终端/桥接组件，不降低可靠性要求。结果需包括版本、设备、步骤、实际输出、未通过项与预算，再更新本 ADR 为最终选择。

任何框架都不豁免 Tailscale、EasyTier、ZeroTier 的逐平台字节流、受保护存储、取消与可安装产物验收。框架支持列表不等于依赖覆盖；系统 VPN 不能代替内置网络。参见[五端矩阵](0005-unified-mobile-desktop.md)、[三网络目标](0006-three-overlay-providers.md)、[共同可靠性边界](0004-mvp-reliability-boundaries.md)与[路线图](../04-roadmap.md)。
