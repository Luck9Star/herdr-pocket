# herdr-pocket

> 面向 herdr 用户公开开源的统一 GUI：目标覆盖 iOS、Android、Windows、macOS、Linux，手机优先、桌面紧随，共享主机管理、agent 看板、终端与输入流程。仓库名保留 `herdr-pocket`。

**从这里开始**　[阶段交接：已完成、未完成与恢复顺序](https://github.com/Luck9Star/herdr-pocket/blob/85c150b24dca14412cf01075b832c1014547a3aa/docs/56-project-status-and-handoff.md) · [原型分支与源码](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation) · [最新下载、验收与复测步骤](https://github.com/Luck9Star/herdr-pocket/blob/e9ddfc8d03593e03a6ae539b3f0679a9adf3c84f/docs/53-mobile-connection-diagnostics.md) · [Penpot 手机配对交互原型](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e8e75ef79937)

**手机闭环 · 2026-11-07**　Flutter 和 Tauri 已在 Android API 35 x86_64 云模拟器上走通设备配对审查、SSH 认证、看板、选定 pane 的持续观察和停止。主机摘要显示已知受阻数、状态未知数、原会话和最后同步时间；返回列表保留上次快照。[验收结果、两轮失败及复测](docs/34-mobile-host-task-summary.md)

两份 arm64-v8a 测试包来自同一源码 `e54f23c`，已下载并核对 APK 哈希、原生来源及包内字节。[Flutter 下载](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342/artifacts/13556637167) · [Tauri 下载](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342/artifacts/13556314095) · [7 项云任务](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342) · [实测数据](docs/evidence/mobile-pair-gui/host-board-cloud-20261107.json)

Flutter 的隔离 SSH 测试还验证了同一连接上的隐藏、显式恢复与新快照。两次视口变化期间远端输入为 0，共享 PTY 保持 119×40。两包包含 EasyTier 和 Tailscale；arm64 真机、真实中文 IME、相机扫码、三网及五端并发仍待验证。上一批源码和下载校验记录保留在[双网络测试包记录](docs/27-mobile-tailscale-cloud.md)。

**手机端进度 · 2026-11-08**　Flutter 和 Tauri 已把身份审查、手机专属密钥、主机授权回执和设备密钥 SSH 接入手机 GUI。从主机看板点选具体终端后，能看到首帧和持续输出，再主动停止。本批 Tauri 在 API 35 模拟器还走通了「两条同名受阻记录 → 重审 → 精确观察 B」，远端收到 0 字节；受保护输入完成十个远端 TUI 操作。Flutter 定向复测也走通配对、看板、持续观察、停止，再从同名记录准确选中 B，远端输入为 0 字节。Flutter 的受保护 TUI 在前两笔共 10 字节后仍因 SSH 通道关闭确认超时，未恢复新首帧，输入保持关闭。[本批设备记录](https://github.com/Luck9Star/herdr-pocket/blob/e9ddfc8d03593e03a6ae539b3f0679a9adf3c84f/docs/53-mobile-connection-diagnostics.md) · [Flutter 定向运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/42417473474)

两条路线均可展开查看本次连接的网络路径、主机指纹、公钥认证、看板和终端首帧。字体诊断使用固定 Powerlevel10k 与 Oh My Posh 样例；手机实体键盘、真实中文输入法和真机性能仍待实测。[受阻窗格交互](https://github.com/Luck9Star/herdr-pocket/blob/d5a6dc06a876d05ef98815759595c042b05b1cfd/docs/51-mobile-blocked-targets.md) · [主题及已保存的 Penpot 原型](https://github.com/Luck9Star/herdr-pocket/blob/d5a6dc06a876d05ef98815759595c042b05b1cfd/docs/52-mobile-theme-prompts.md)

历史 `040eb26` 云模拟器、`546c3eb` 独立终端标签包及各次失败保留原 SHA 与范围，不外推为本批设备运行通过。[ZeroTier 后续实现](docs/29-zerotier-managed-device.md)已修复 ECC 未定义左移并移除排除，新增共享设备 owner／多网络租约和 AndroidKeyStore 包装；Mac 整库 114 TU、动态加载及未启动节点的初始化／退休通过。最新工作区另有[手机共享设备宿主](docs/31-mobile-shared-device-host.md)及[待定操作恢复界面与验证](docs/32-mobile-device-recovery.md)，尚未提交、未启用 ZeroTier 拨号，也不在上述 APK 内。原生定向流及真实节点仍有未完成项，下一批继续手机集成，再集中云验收。桌面分屏紧随手机闭环。[历史手机结果](docs/18-mobile-network-profiles.md) · [前一测试包](docs/22-mobile-terminal-tabs.md)

本轮另补[手机草稿找回、看板同步时间与恢复设计](docs/33-mobile-recovery-design.md)：Tauri 154 项前端测试及构建通过；Flutter 63 份 Dart 文件仅完成语法解析，新增 widget／SSH 断言未运行。Penpot v2 已保存 S31–S38 并重载核对，共 38 画板／212 交互对象；新增恢复路径已实际点击。该段为当时的工作区记录；已打包的草稿与摘要、最新 Flutter 和 Android 实测范围见[手机闭环验收](docs/34-mobile-host-task-summary.md)。

**测试包之后的原型进度**　两套手机看板都能按名称、地址、命名会话及网络类型检索主机，并区分当前待处理和上次受阻。Flutter 修复静默 SSH 观察通道后，在 Mac 隔离的真实 herdr 会话中连续恢复五次，每次均收到新首帧和后续增量，远端输入为 0。修复后的 Android 受保护 TUI 尚待复测。下方两份 APK 对应较早的 `dd02595`。[源码、Penpot 与实测记录](https://github.com/Luck9Star/herdr-pocket/blob/8703b0d37a2497357c5c6c07c6e4f28ce2a3fe1c/docs/54-mobile-host-search-and-observer-retirement.md)

**手机网络配置**　Flutter 和 Tauri 都已接入「审查 ZeroTier 共享设备」。设备服务不可用时，仍可核对关联网络和主机；目录读取失败时显示范围未知。新版 Penpot 已保存两种状态。Mac 已验证临时 ZeroTier 身份经 JNI 加密保存、重新读取和删除。手机系统 KeyStore、实际入网与跨网络并发待测。下方已验证的 APK 来自此前的版本。[原型源码与本批实测](https://github.com/Luck9Star/herdr-pocket/blob/22d53e272a9acbeb2345bbcd0a1201fd7449af52/docs/55-mobile-shared-network-device.md) · [Penpot 设备审查](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=2a5fd934-a163-8057-8008-e823088d7aeb)

## Android 测试包

两份 API 35 arm64-v8a debug APK 来自同一提交 [`dd02595`](https://github.com/Luck9Star/herdr-pocket/commit/dd025952321fb944465a48ec762ae76adc74f830)。登录 GitHub 下载归档，分别解压，用 `shasum -a 256 app.apk` 核对。归档摘要、包内 APK 和原生来源均已核验；两包中的 EasyTier、Tailscale 原生库逐字节一致。下载于北京时间 **11 月 22 日 05:32（Flutter）和 05:33（Tauri）** 到期。arm64 真机安装未验证。[构建记录](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185)

| 路线 | 测试包 | app.apk SHA-256 |
| --- | --- | --- |
| Flutter | [下载 arm64 debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185/artifacts/13591233797) | `027a7881183275e966f602a8a48f0ffc51f4d718476cc9aa1fab151f45499a32` |
| Tauri | [下载 arm64 debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185/artifacts/13591323156) | `569313409cfb7e2b88fe3fa0d267817ca727276866613364824002561a567604` |

[试测步骤、首轮失败和修复](https://github.com/Luck9Star/herdr-pocket/blob/e9ddfc8d03593e03a6ae539b3f0679a9adf3c84f/docs/53-mobile-connection-diagnostics.md) · [上一批安装包与历史验收](https://github.com/Luck9Star/herdr-pocket/blob/71ce10191c2c282bc4d5258f1bfc191a3cbfb882/docs/50-android-paired-tui-validation.md)

## 手机端当前进度

| 范围 | 已有证据 | 下一项验收 |
| --- | --- | --- |
| 配对 → 看板 → 持续观察 | 两壳均有独立设备密钥 SSH、看板、所选 pane 首帧及增量、主动停止的模拟器证据。Flutter 与 Tauri 均确认只读观察全程远端收到 0 字节，两条路线均从同名受阻记录打开 B，Tauri 另验收手机撤销。[配对与闭环](https://github.com/Luck9Star/herdr-pocket/blob/e9ddfc8d03593e03a6ae539b3f0679a9adf3c84f/docs/53-mobile-connection-diagnostics.md) | arm64 安装、物理相机扫码、锁屏和重启恢复 |
| 终端与阅读位置 | 两份包包含三档观察画布。Flutter 与 Tauri 的只读模拟器场景均验收了宽画布、标记及阅读位置恢复。[画布与设备验收](https://github.com/Luck9Star/herdr-pocket/blob/71ce10191c2c282bc4d5258f1bfc191a3cbfb882/docs/50-android-paired-tui-validation.md) | 真机触控、锁屏与长时间观察 |
| 终端输入 | 原版 herdr 保持只读。Tauri 在受保护宿主完成逐键、草稿及十个 TUI 按键。发送结果未知时保留记录，供用户核查。[操作与回执](https://github.com/Luck9Star/herdr-pocket/blob/e9ddfc8d03593e03a6ae539b3f0679a9adf3c84f/docs/53-mobile-connection-diagnostics.md) | Flutter 隐藏标签恢复后的 TUI、真实中文 IME 与实体键盘 |
| 组网与平台 | 两份 APK 包含 EasyTier、Tailscale。ZeroTier 的来源、设备管理及离线原生验证另有记录。[原生验证](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/29-zerotier-managed-device.md) | 三网真实节点、并发及五平台矩阵 |

Flutter 与 Tauri 继续并行验证，物理手机的输入正确性、字形、生命周期和性能仍会影响选型。公开仓库提供源码和测试渠道，项目许可证与原生依赖的分发条件仍在审查。[技术栈复评](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/06-technology-evaluation.md) · [分发与许可](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/17-license-and-distribution-review.md)

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
| [`docs/33-mobile-recovery-design.md`](docs/33-mobile-recovery-design.md) | 后续工作区：原目标草稿找回、权威看板时间、粘贴审查及 Penpot 恢复增量 |
| [`docs/32-mobile-device-recovery.md`](docs/32-mobile-device-recovery.md) | 后续工作区：手机待定创建／删除审查恢复、原阶段核对与分层验证 |
| [`docs/31-mobile-shared-device-host.md`](docs/31-mobile-shared-device-host.md) | 后续工作区：两套手机宿主、共享设备存储合同、隔离验证与未启用边界 |
| [`docs/30-zerotier-streams-and-device-review.md`](docs/30-zerotier-streams-and-device-review.md) | 后续工作区：ZeroTier 流／JNI、共享设备界面及未完成原生草稿 |
| [`docs/34-mobile-host-task-summary.md`](docs/34-mobile-host-task-summary.md) | 手机主机摘要、配对与持续观察、双 APK 及云模拟器验证 |
| [`docs/29-zerotier-managed-device.md`](docs/29-zerotier-managed-device.md) | ECC 修复、设备／多网络管理、Android 包装与 Mac 整库证据 |
| [`docs/28-zerotier-native-foundation.md`](docs/28-zerotier-native-foundation.md) | ZeroTier 单设备身份、事件／退休修复与尚未消除的阻断项 |
| [`docs/27-mobile-tailscale-cloud.md`](docs/27-mobile-tailscale-cloud.md) | 前一批双网络 Android 测试包、实际 CI、隔离 SSH 与验收步骤 |
| [`docs/26-mobile-tailscale-login.md`](docs/26-mobile-tailscale-login.md) | 两套手机 Tailscale 身份、显式登录、原节点路由与双库装包边界 |
| [`docs/25-tailscale-native-custody.md`](docs/25-tailscale-native-custody.md) | Tailscale 原生候选、Android 加密状态与 JNI、实编及未验证边界 |
| [`docs/24-target-input-recovery.md`](docs/24-target-input-recovery.md) | 多目标输入恢复、精确租约、迁移与独立验收边界 |
| [`docs/23-mobile-session-watch.md`](docs/23-mobile-session-watch.md) | 后续源码：手机看板持续状态、目标核验与独立验证边界 |
| [`docs/22-mobile-terminal-tabs.md`](docs/22-mobile-terminal-tabs.md) | 手机独立终端标签、保留 SSH、观察 epoch 与集中云验收 |
| [`docs/21-flutter-native-network.md`](docs/21-flutter-native-network.md) | Flutter 手机原生通道、路由恢复和 Android 同源分层构建 |
| [`docs/20-mobile-node-routing.md`](docs/20-mobile-node-routing.md) | JNI 安全配置源、节点生命周期与 Tauri 手机路由 |
| [`docs/19-mobile-network-identity.md`](docs/19-mobile-network-identity.md) | Android 本机入网资料、身份影响串行与 overlay SSH 适配 |
| [`docs/18-mobile-network-profiles.md`](docs/18-mobile-network-profiles.md) | 手机网络配置、v2 迁移、字号和节点生命周期 |
| [`docs/16-mobile-input-and-config.md`](docs/16-mobile-input-and-config.md) | 最新手机输入、配置迁移、两包与失败记录 |
| [`docs/17-license-and-distribution-review.md`](docs/17-license-and-distribution-review.md) | 固定依赖许可、字体来源与发行待办 |
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
