# herdr-pocket 阶段交接

截至 2026-11-08，手机端可演示的主线是 **配对审查 → 手机专属密钥 SSH 认证 → 主机／会话看板 → 选中终端持续观察 → 主动停止**。Flutter 和 Tauri 均已在 Android API 35 的 x86_64 云模拟器上走通这条主线。当前仍是原型验证阶段。公开源码比可下载 APK 更新，框架与终端引擎的最终选择仍待真机输入、显示与性能数据。[两条路线的设备记录](53-mobile-connection-diagnostics.md) · [技术选型门槛](06-technology-evaluation.md)

## 现在可以从哪里开始

| 入口 | 对应内容 |
| --- | --- |
| [公开首页](https://github.com/Luck9Star/herdr-pocket) · [原型分支](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation) | 默认分支为 `main`，首页列有原型、测试包和验证入口。本次收尾的功能与测试源码快照为 [`22d53e2`](https://github.com/Luck9Star/herdr-pocket/commit/22d53e272a9acbeb2345bbcd0a1201fd7449af52)。 |
| [Flutter APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185/artifacts/13591233797) · [Tauri APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185/artifacts/13591323156) | 两份 arm64-v8a debug 包来自同一提交 [`dd02595`](https://github.com/Luck9Star/herdr-pocket/commit/dd025952321fb944465a48ec762ae76adc74f830)。登录 GitHub 下载、解压，按[步骤与 SHA-256](53-mobile-connection-diagnostics.md)核验。11 月 8 日查询时均可下载，分别于北京时间 11 月 22 日 05:32、05:33 到期。 |
| [Penpot 手机配对](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e8e75ef79937) · [看板与任务检索](54-mobile-host-search-and-observer-retirement.md) · [共享设备审查](55-mobile-shared-network-device.md) | 原型保存在同一 Penpot v2 文件，沿用靛蓝／Slate 配色。状态页可点击刷新、恢复和返回。各页的实际点击、重载与适用范围随记录保存。 |
| [Flutter 验证壳](../validation/flutter/README.md) · [Tauri 验证壳](../validation/tauri/README.md) · [共享 fixture](../validation/shared/README.md) | 两条路线共用终端输入、字体、负载和目标身份样例。可按各壳的说明重跑，再对照同一场景。 |

## 已完成到哪一层

| 功能 | 已有证据 | 尚缺证据或实现 |
| --- | --- | --- |
| 配对与观察 | 两套手机 GUI 可审查连接资料、创建专属 SSH 密钥、提交公钥请求并核对 helper 的授权回执。模拟器通过生产 GUI 接收测试资料，隔离 sshd 核对了获批公钥，手机收到原目标首帧和增量。两端也都从同名历史记录准确选到 B，只读观察期间远端收到 0 字节。Tauri 设备作业还覆盖了撤销。[配对交接](45-mobile-pairing-handoff.md) · [设备记录](53-mobile-connection-diagnostics.md) | 实体手机摄像头扫码、跨设备交接、锁屏和重启后恢复。 |
| 看板、标签与恢复 | 公开包可从看板点选会话窗格并持续观察。包后的两壳源码支持按主机、地址、会话和网络类型检索。Flutter 修复了静默 SSH 观察通道的退出问题，在 Mac 隔离的实际 herdr 会话中连续恢复五次，均有新首帧和增量，远端输入为 0，PTY 始终为 119 × 40。[复测记录](54-mobile-host-search-and-observer-retirement.md) | 新搜索入口和修复后的隐藏标签恢复待 Android 验收。 |
| 手机终端与输入 | 两壳已有观察、逐键、辅助键、草稿、选择及粘贴审查。Tauri 在受保护的测试宿主完成十个 TUI 操作。发送结果未知时需人工核对，布局变化不隐式调整远端共享 PTY。[输入规则](24-target-input-recovery.md) · [TUI 实测](53-mobile-connection-diagnostics.md) | 原版 herdr 在本项目中走只读路径。Flutter 在 Android 的最近一次受保护输入测试中，前两笔共 10 字节已送达，隐藏恢复后遇到 `channel_cleanup_timeout`，没有新首帧，输入保持关闭。十个 TUI 操作仍待 Android 复测。 |
| 终端显示 | `terminal_view 0.5.0` 漏绘组合重音已有固定候选补丁及绘制回归。两壳有相同的 Nerd Font、CJK、emoji 和 ANSI 样例。Powerlevel10k 与 Oh My Posh 的固定提示符在 Mac 的两条终端核心得到预期光标列。[组合重音修复](10-blocker-repair.md) · [真实主题样例](52-mobile-theme-prompts.md) | 真机中文 IME 预编辑／提交、复杂字符列宽、系统字体回退、触控选择及长时间重绘性能。 |
| 配置与设备身份 | 主机、公开网络参数和可选字号支持本地加密导入导出、旧版读取和冲突审查。导入后的网络默认停用，新主机需在本机配对。设备 SSH 私钥与组网身份留在原设备。[迁移实现](18-mobile-network-profiles.md) · [格式与事务](../validation/config-transfer/README.md) | Mac 系统文件选择器的导出和导入已通过。Android／iOS 文件提供方、跨手机实际迁移和耗时待验。 |
| 三种组网 | 两份 APK 包内的 EasyTier、Tailscale 原生库已核对。EasyTier 的 Linux、Windows 移植编译错误已有修复，三桌面候选完成编译、链接、加载及离线测试。ZeroTier 共享设备审查已接入两壳源码，Mac 已用固定原生身份算法通过 JNI 验证加密保存、重新读取、拒绝损坏密文及显式删除。[双网络 Android 证据](27-mobile-tailscale-cloud.md) · [桌面移植](10-blocker-repair.md) · [ZeroTier 最新记录](55-mobile-shared-network-device.md) | ZeroTier 手机原生身份引擎绑定、系统 KeyStore、指定网络拨号和 SSH 链路。五端的 15 个单网格及 20 个并发组合仍须逐格验收。[平台矩阵](../validation/shared/platform-matrix.json) |
| 设计、桌面与分发 | Penpot 有扫码双端、看板、终端输入、桌面分屏、窄窗和关键失败恢复的交互原型，也有初步组件与语义 tokens。已建立分层测试构建和来源记录。Mac 桌面与各平台构建的既有证据按版本保留。[设计覆盖](../design/v2-coverage.md) · [分层构建](07-build-and-release.md) | 要根据设备实测收敛高保真和组件状态，再验收桌面真实分屏、焦点与恢复。iOS 签名安装、五端产品运行及辅助技术待验。仓库根目录尚无项目许可证，逐产物依赖清单和正式分发审查尚未完成。[分发审查](17-license-and-distribution-review.md) |

## 最新代码与公开包的差别

在 `dd02595` 的[集中构建](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185)中，两份分发 APK 构建成功，工作流总体失败。之后的 [Flutter 定向复测](https://github.com/Luck9Star/herdr-pocket/actions/runs/42417473474)通过了只读闭环与同名目标 B 的检查，仍因受保护 TUI 恢复失败。该次复测没有重建 APK。

后续源码已包含看板搜索、Flutter 静默观察修复、网络共享设备的影响范围与恢复审查。设备服务不可用时，手机仍可显示已读到的关联主机和网络。目录读取失败时显示范围未知。Mac 已在 320 与 390 CSS px 的实际 Tauri 页面、两套 Android 宿主的隔离 JVM，以及原生身份算法的 JNI 联跑中验证相应路径。Android 的系统 KeyStore 与原生入网尚未运行。Penpot 两张新状态页有 10 次独立预览点击记录。[手机行为与复跑步骤](55-mobile-shared-network-device.md) · [结构化证据](evidence/mobile-pair-gui/shared-network-device-20261108.json)

## 恢复工作时的顺序

1. **先复测 Flutter 在 Android 上的观察恢复。** 在同一批 API 35 作业中复测两壳的配对、看板与观察。对 Flutter 单独要求隐藏标签恢复后出现原目标的新完整帧、同一观察代的增量，再核对十个 TUI 操作的远端回执。在模拟器脚本补上看板检索和共享设备审查断言，再触发同批验收。随后核验两份同源 arm64 APK 的哈希、ABI 与来源清单。[云端工作流](../.github/workflows/android-network-experiment.yml) · [分场景步骤](53-mobile-connection-diagnostics.md)
2. **补手机原生网络链路。** 先验证 ZeroTier 身份在 Android 系统 KeyStore 下的创建、重启读回、拒绝错误实例和显式移除，再接指定网络上的 SSH、看板和观察。用独立获准的测试节点分别验收 Tailscale、EasyTier、ZeroTier，再验前台跨网并发。[设备存储与拨号的边界](55-mobile-shared-network-device.md)
3. **用真机结果决定选型。** 目前可用环境为云端和 Mac。取得实体 Android／iOS 后，使用相同字体、fixture、视口和负载检查扫码、输入法、滚动选择、锁屏、恢复及性能。以正确性作首要门槛，再比较维护成本、收敛高保真和组件库，接续桌面三平台。[技术栈复评](06-technology-evaluation.md) · [设计计划](08-ui-design-plan.md)

本次收尾没有再触发云构建。核对时运行中和排队的 GitHub Actions 均为 0。测试浏览器、独立 Penpot 预览、临时服务与测试 JVM 均已退出，原有 Penpot 编辑页保留。工作区尚有早先的原生流和设计草稿，这些改动继续保留，未计入上述交付。
