# herdr-pocket 文档

## 按你要做的事找入口

| 任务 | 从哪里开始 |
| --- | --- |
| 下载和安装测试包 | [项目首页的 Android 测试包](../README.md#android-测试包) · [普通 SSH 的同源调试包](63-design-parity-and-direct-ssh.md#可下载的同源调试快照) |
| 连接标准 SSH 服务器 | [普通 SSH 操作与认证范围](63-design-parity-and-direct-ssh.md#从首页选择接入方式) |
| 配对 herdr 主机并观察终端 | [主机配对与撤销](../helper/README.md) · [手机操作与连接诊断](53-mobile-connection-diagnostics.md#手机上怎样核验) |
| 判断一个场景验收到哪一步 | [路线图与逐项验收](04-roadmap.md) · [普通 SSH 验收矩阵](63-design-parity-and-direct-ssh.md#普通-ssh-验收矩阵2026-11-20-更新) · [网络与桌面专项](#网络终端与桌面专项) |
| 构建、复跑或提交改动 | [云端构建与测试分发](07-build-and-release.md) · [复跑入口](../validation/README.md) · [贡献指南](../CONTRIBUTING.md) |
| 查看设计或恢复历史源码 | [Penpot 设计与访问范围](../design/README.md) · [验证分支归档](71-validation-branch-archive.md) |

## 产品、架构与交付

- [05 首版产品设计](05-product-design.md)说明用户流程、功能范围和五端支持口径。[04 路线图](04-roadmap.md)维护里程碑、验收条件与工项状态。
- [02 架构与运行契约](02-architecture.md)定义连接、输入、恢复与传输边界。[03 风险与规避](03-pitfalls.md)收录已知实现风险。
- [06 技术栈复评与定案门槛](06-technology-evaluation.md)负责 Flutter 与 Tauri 选型。[09 核心原型验证](09-prototype-validation.md)保留早期五端可行性与并发基线，[10 阻断修复与验收](10-blocker-repair.md)记录组合重音和原生集成问题。
- [08 UI 设计交付计划](08-ui-design-plan.md)说明交付顺序。[11 新版视觉集成](11-ui-v2-integration.md)记录双壳落地，[设计覆盖与截图](../design/v2-coverage.md)提供各状态的画板与证据。
- [07 构建与测试分发](07-build-and-release.md)定义构建、签名、产物与验证口径。[61 iOS 个人编译与 TestFlight](61-ios-personal-build-guide.md)和[62 iOS 测试分发选项](62-ios-free-distribution-guide.md)记录可选路径及其条件。
- [59 项目许可证决定](59-license-decision-proposal.md)记录 GPL-3.0-or-later 的决定与依据。[17 许可证与分发审查](17-license-and-distribution-review.md)记录依赖和发行缺口，[第三方声明](../THIRD_PARTY_NOTICES.md)列出组件许可与来源。
- [00 调研依据](00-research.md)和[01 参考客户端对比](01-comparison.md)保留历史调研。[对比图](assets/comparison.html)对应当时的比较口径。

## 普通 SSH 专项

[63 界面落实与普通 SSH](63-design-parity-and-direct-ssh.md)维护操作、认证范围和验收矩阵。以下是各场景的原始证据和复跑记录。

- 主机身份与认证 · [68 Android 主机换钥](68-android-ssh-host-key-rotation.md) · [70 iOS 密码与换钥](70-ios-ssh-host-key-rotation.md) · [72 手机认证快照、私钥和复跑](72-mobile-ssh-auth-snapshot.md)。
- 终端可见性与会话导航 · [69 Android 活动终端及原屏](69-mobile-ssh-active-terminal.md#r4-最终同批验收) · [73 手机终端切页与键盘](73-mobile-ssh-terminal-navigation.md)。
- Windows、macOS 和 Linux 的对应记录由[普通 SSH 验收矩阵](63-design-parity-and-direct-ssh.md#普通-ssh-验收矩阵2026-11-20-更新)索引。按各条的源码、账号认证方式和运行环境核对。

## herdr 配对、看板与输入

[主机辅助命令](../helper/README.md)负责配对及撤销操作，[53 手机操作与诊断](53-mobile-connection-diagnostics.md)负责连接后如何核验。按功能查早期设计与分项证据。

- 配对资料与设备身份 · [12 远端只读接入](12-mobile-remote-readonly.md) · [14 手机配对工作台](14-mobile-pairing-workbench.md) · [44 连接资料与首次接入](44-mobile-connection-profile.md) · [45 配对交接与撤销](45-mobile-pairing-handoff.md)。
- 手机看板与连续观察 · [13 看板和持续观察](13-mobile-dashboard-observe.md) · [23 会话状态更新](23-mobile-session-watch.md) · [34 主机摘要与 Android 测试包](34-mobile-host-task-summary.md) · [39 新配对后的看板](39-mobile-paired-dashboard.md) · [51 同名受阻终端](51-mobile-blocked-targets.md) · [54 主机检索与观察恢复](54-mobile-host-search-and-observer-retirement.md)。
- 输入资格、草稿和恢复 · [16 输入与配置迁移](16-mobile-input-and-config.md) · [22 终端标签与保留 SSH](22-mobile-terminal-tabs.md) · [24 输入结果未知时的目标隔离](24-target-input-recovery.md) · [33 草稿与看板时间](33-mobile-recovery-design.md) · [43 阅读位置和连接恢复](43-mobile-viewport-recovery.md) · [47 观察画布尺寸](47-mobile-observer-canvas.md) · [49 配对后的远端 TUI](49-mobile-paired-tui.md)。
- 键盘、选区与字体 · [35 键盘和组字](35-mobile-input-focus.md) · [36 粘贴审查和辅助键](36-mobile-paste-and-auxiliary-input.md) · [37 选区和复制](37-mobile-terminal-selection.md) · [38 系统粘贴](38-mobile-system-paste.md) · [41 软键盘收起与展开](41-mobile-system-keyboard.md) · [42 字形和列宽诊断](42-mobile-terminal-font-diagnostics.md) · [48 功能键与输入法边界](48-mobile-terminal-function-keys.md) · [52 真实 Shell 提示符样例](52-mobile-theme-prompts.md)。
- 历史 GUI 验收 · [15 配对与看板集中验证](15-mobile-gui-validation.md) · [40 Android 配对与持续观察](40-android-paired-dashboard-validation.md) · [46 Android 配对交接](46-android-pairing-handoff-validation.md) · [50 Android 配对与远端 TUI](50-android-paired-tui-validation.md)。

## 网络、终端与桌面专项

- 双网运行 · [65 Linux 隔离双网与停网](65-dual-overlay-validation.md) · [67 Android 双网启动、会话与共享节点](67-android-dual-network-startup.md)。覆盖范围以各页记录的测试环境为准。
- 配置与原生路由 · [18 手机网络配置与迁移](18-mobile-network-profiles.md) · [19 手机入网身份](19-mobile-network-identity.md) · [20 节点生命周期和 SSH 路由](20-mobile-node-routing.md) · [21 Flutter 原生通道与构建](21-flutter-native-network.md)。
- Tailscale · [25 原生运行时与 Android 状态托管](25-tailscale-native-custody.md) · [26 手机登录与路由](26-mobile-tailscale-login.md) · [27 双网云构建与历史 APK](27-mobile-tailscale-cloud.md)。
- ZeroTier · [55 共享设备审查](55-mobile-shared-network-device.md) · [28 原生身份基础](28-zerotier-native-foundation.md) · [29 设备托管与租约](29-zerotier-managed-device.md) · [30 流与审查的开发记录](30-zerotier-streams-and-device-review.md) · [31 Android 宿主接线](31-mobile-shared-device-host.md) · [32 待定操作恢复](32-mobile-device-recovery.md)。
- 桌面分屏 · [74 两壳的窗口变化、焦点、双连接与复跑](74-desktop-split-resize.md)。
- 终端内核 · [64 libghostty-vt 两壳适配评估](64-libghostty-terminal-core-evaluation.md) · [终端内核原型复跑](../validation/ghostty-vt/README.md)。

## 架构决策记录

- [ADR-0001 Flutter 第一候选与双壳 A/B](adr/0001-single-flutter-stack.md) · [ADR-0002 首发 RPC 传输](adr/0002-transport-ssh-streamlocal.md) · [ADR-0003 进程内覆盖网络](adr/0003-in-app-overlay-userspace.md)。
- [ADR-0004 身份、恢复和输入边界](adr/0004-mvp-reliability-boundaries.md) · [ADR-0005 移动与桌面统一范围](adr/0005-unified-mobile-desktop.md) · [ADR-0006 三种内置网络目标](adr/0006-three-overlay-providers.md) · [ADR-0007 配对与配置迁移](adr/0007-pairing-and-config-transfer.md)。

## 历史证据与交接

- [M0 调研证据及降级行为](60-m0-evidence-archive.md) · [原图、结构化报告与产物索引](evidence/)。
- [56 早期阶段、下载与分发台账](56-project-status-and-handoff.md) · [57 2026-11-09 第一轮交接](57-session-handoff-2026-11-09.md) · [58 2026-11-09 第二轮交接与定向复验](58-session-handoff-2026-11-09-r2.md)。
- [66 2026-11-16 迭代交接、历史故障和复跑](66-iteration-handoff-2026-11-16.md) · [71 归档标签与分支恢复](71-validation-branch-archive.md)。
