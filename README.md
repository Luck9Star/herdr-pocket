# herdr-pocket

> 面向 herdr 用户公开开源的统一 GUI：目标覆盖 iOS、Android、Windows、macOS、Linux，手机优先、桌面紧随，共享主机管理、agent 看板、终端与输入流程。仓库名保留 `herdr-pocket`。

状态：**M0.5 并行验证阶段，尚非正式产品**。2026-10-30 已保存 Penpot 核心交互原型，新增 Flutter/Tauri 离线验证壳与实际云构建测试产物，并完成 [macOS 有限原生 smoke](docs/evidence/mobile-observe/macos/verification.json)。完整远端交互闭环、手机 IME、三网络运行及跨平台支持仍待验证。见[实际证据与完整矩阵](docs/09-prototype-validation.md)、[验证入口](validation/README.md)。

新版视觉沿用用户认可的 Penpot 靛蓝／Slate 方案，已补恢复与核验状态，并接入两条验证壳；本轮结果及后续集成顺序见[UI v2 接线记录](docs/11-ui-v2-integration.md)。视觉确认不等于框架定案。

当前按手机优先推进[会话看板与持续观察](docs/13-mobile-dashboard-observe.md)：两条适配器已在同一云端临时 SSH/herdr 目标完成 **18/18** 项真实对照，覆盖显式 pane 选择后的 full/delta、主动停止和手动再次连接，远端输入为 0。配对 v2 契约、Apple 内存签名探针与 Android 桥编译同步推进。手机界面布景、真实 SSH CLI、原生包构建分别记录；GUI 真实接入、设备密钥存储、手机运行与完整输入仍待验证。

当前批次已开始手机设备配对、主机目录、多标签和带目标保护的远端输入实验。Android 基线包、首轮失败与批次验收入口见[手机配对工作台](docs/14-mobile-pairing-workbench.md)。

## 首版做什么

五端首版都连接**远端 herdr 主机**：手机扫码配对（手动配置兜底）→ 审查连接配置与主机身份 → 主动连接 → 查看 agent 和终端 → 显式输入 → 断线后核实状态。扫码不要求先安装本项目桌面 GUI。桌面本机 herdr 接入后续再做，首版不管理本地进程或 WSL 服务；后台通知、文件 / diff 后置，不承诺后台常连。

配对采用按需运行并退出的一次性主机辅助命令：主机用户明确确认后添加手机专属 SSH 公钥，并提供撤销入口；不静默修改授权或留下常驻服务。

配置保存在本地，首版支持连接配置与偏好的加密导入导出；不复制设备 SSH 私钥或 overlay 节点身份，不引入云账号/自动同步。扫码或导入不自动连接、信任 host key 或发送输入。

五端首版均提供**完整交互终端**，包括逐键、快捷键与交互 TUI；手机以任务操作为默认入口，并增加组合键、草稿与粘贴等输入辅助。默认观察、显式进入输入，断线或发送结果未知时不自动重放。

首版支持**前台跨 provider 同时连接**及**多终端标签**：手机切换标签，桌面可分屏，输入始终指向明确的活动目标。标签保留状态不等于隐藏终端持续观察或后台常连；同 provider 任意多身份并发不在承诺内。

**Flutter 是第一验证候选，尚未最终定案**；Tauri 2 + xterm.js + Rust 是同规格手机终端 A/B 的主要挑战者。先验证触控、IME、Nerd Font 与恢复正确性，再比较性能与集成成本，见[技术方案评估](docs/06-technology-evaluation.md)。SSH `direct-streamlocal`、herdr observe 与原生网络桥接不专属于某个 UI 框架；窗口、键鼠、触控与安全存储按平台适配。

**Tailscale、EasyTier、ZeroTier 三种内置网络均进入设计与集成目标，Tailscale + EasyTier 是每个平台正式支持的最低网络门槛**；完整三网支持需逐平台验收。Flutter 路径先验证 MIT 候选 `terminal_view` 0.5.0；其他候选须通过相同终端门槛。

**Windows 内置 Tailscale 是已知缺口**：候选 Dart `tailscale` 0.9.0 不支持 Windows，不能作为五端唯一实现。需要验证 Windows 适配路径；这不等于判定上游 tsnet 本身不支持 Windows，也不能把依赖系统 VPN 的路径当成内置方案已通过。

Heeler 已有三网络的源码实现可供按许可移植：EasyTier 使用 no-TUN 用户态 TCP 桥，非 SOCKS5。其现成原生包只有 iOS arm64 真机 / 模拟器产物，macOS、Android、Windows、Linux 都须移植或重新构建验证，不能直接宣布五端可用。版本、接口和复用条件见[源码证据](docs/00-research.md#23-heeler-三网络源码复核)。

## 先读哪些文档

| 文件 | 内容 |
| --- | --- |
| [`docs/13-mobile-dashboard-observe.md`](docs/13-mobile-dashboard-observe.md) | 当前手机看板、持续观察、配对／设备密钥、CI 与下载 |
| [`docs/05-product-design.md`](docs/05-product-design.md) | 首版用户、核心流程、交互状态与范围 |
| [`docs/08-ui-design-plan.md`](docs/08-ui-design-plan.md) | Penpot 关键流程、状态画板与并行验证交付计划 |
| [`docs/06-technology-evaluation.md`](docs/06-technology-evaluation.md) | 框架候选、官方依据与手机终端 A/B 关口 |
| [`docs/07-build-and-release.md`](docs/07-build-and-release.md) | 云端构建优先、本地轻量、产物与分发边界 |
| [`docs/adr/0004-mvp-reliability-boundaries.md`](docs/adr/0004-mvp-reliability-boundaries.md) | MVP 与可靠性边界 |
| [`docs/adr/0005-unified-mobile-desktop.md`](docs/adr/0005-unified-mobile-desktop.md) | 公开开源、五端统一与远端连接范围 |
| [`docs/adr/0006-three-overlay-providers.md`](docs/adr/0006-three-overlay-providers.md) | 三网络目标、统一字节流与逐平台支持门槛 |
| [`docs/adr/0007-pairing-and-config-transfer.md`](docs/adr/0007-pairing-and-config-transfer.md) | 手机扫码、本地加密迁移与秘密边界 |
| [`docs/02-architecture.md`](docs/02-architecture.md) | 领域、传输、连接生命周期与输入契约 |
| [`docs/04-roadmap.md`](docs/04-roadmap.md) | M0.5 原型门槛、后续里程碑与验收 |
| [`docs/00-research.md`](docs/00-research.md) | 历史观测、2026-10-29 上游复核及证据限制 |
| [`docs/01-comparison.md`](docs/01-comparison.md) | 12 个参考客户端的历史能力矩阵 |
| [`docs/03-pitfalls.md`](docs/03-pitfalls.md) | 协议、网络、平台和交付风险 |
| [`docs/assets/comparison.html`](docs/assets/comparison.html) | 历史对比可视化与当前决策入口 |

## 尚未验证

- 框架选择及五端真实环境中的 SSH、三种 overlay 字节流与终端闭环；框架支持某平台不代表每个原生依赖也支持。
- `terminal_view` 的中文输入、桌面快捷键、复杂 TUI、重连重绘与性能。`xterm3` 6.x 为 AGPL 备选，不能未经项目许可决策直接引入。
- Oh My Zsh 主题 / Oh My Posh 的 Nerd Font 显示：客户端字体、PUA / Powerline 图标、CJK 与终端 cell 宽度逐端验证；字体候选与随包许可见[调研依据](docs/00-research.md#22-nerd-font-与-shell-主题兼容性)。
- Tailscale 各平台绑定、取消和身份持久化。候选 Dart 包单进程单节点；Android 持久身份有 API 31+ 限制，Linux 桌面依赖 Secret Service，Windows 需另行验证。
- EasyTier 的 C ABI / 进程内 TCP 桥迁移与 LGPL 发行资料；ZeroTier 的单节点多网络隔离、逻辑 socket 桥和来源补丁。上游实现或测试文件存在不等于本项目验证通过。
- 最低系统 / CPU 架构、支持分级、项目许可证、依赖及原生构建的完整发行义务；公开开源不等于任意依赖许可都能混用。

手机优先、五端完整终端及“衍生改动继续开源”均已由用户确认；具体许可证在依赖与分发审查后确定，见[决策状态](docs/05-product-design.md#9-决策状态)。

## 公开开源发布门槛

**云端 CI 构建优先，本地保持轻量。**默认在 runner 配置 SDK/NDK、Xcode、Visual Studio、Rust/Go 等构建工具，本地以编辑器、Git、下载测试包和设备验收为主；仅按具体调试需要选装本地工具，不承诺完全零本地依赖。保留源码、锁定工具链与重建步骤，云优先不等于只能在云端构建。详见[构建与发布](docs/07-build-and-release.md)。

先发布源码与测试渠道版本，逐步正式上架；测试渠道仍遵守签名、安装与平台规则。发布前建立逐平台的构建 / 测试 / 产物及跨 provider 并发矩阵，提供可复跑步骤、来源版本与校验和、第三方声明、贡献与问题报告入口。没有通过的平台明确标为实验性或未支持，不用一个平台演示宣布五端完成。2026-10-29 设计基线未创建许可证或构建产物；2026-10-30 已有测试 CI 与 artifact，尚未选定项目许可证或正式发布，见[验证记录](docs/09-prototype-validation.md)。

## 与 herdr 的关系

本项目是第三方客户端，与 herdr 官方无关。目标能力建立在公开 socket API 与 CLI 上；每个目标版本仍需通过协议兼容性验证。
