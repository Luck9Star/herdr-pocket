# herdr-pocket 阶段交接

> **本轮最新交接入口：[58-session-handoff-2026-11-09-r2.md](58-session-handoff-2026-11-09-r2.md)**（自包含，含状态、事实、待办与下一步操作参数）。上一棒入口：[57-session-handoff-2026-11-09.md](57-session-handoff-2026-11-09.md)。本文档保留为历史全量交接，主体内容不变。

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
| 看板、标签与恢复 | 公开包可从看板点选会话窗格并持续观察。包后的两壳源码支持按主机、地址、会话和网络类型检索。Flutter 修复了静默 SSH 观察通道的退出问题，在 Mac 隔离的实际 herdr 会话中连续恢复五次，均有新首帧和增量，远端输入为 0，PTY 始终为 119 × 40。[复测记录](54-mobile-host-search-and-observer-retirement.md)。Flutter 3.47.9 平台转态规范（paused→hidden→inactive→resumed）与视口滚动帧等待已修复（commit 4143bca、06a7d65）。 | 新搜索入口和修复后的隐藏标签恢复待 Android 验收。 |
| 手机终端与输入 | 两壳已有观察、逐键、辅助键、草稿、选择及粘贴审查。Tauri 在受保护的测试宿主完成十个 TUI 操作。发送结果未知时需人工核对，布局变化不隐式调整远端共享 PTY。[输入规则](24-target-input-recovery.md) · [TUI 实测](53-mobile-connection-diagnostics.md) | 原版 herdr 在本项目中走只读路径。Flutter 在 Android 的最近一次受保护输入测试中，前两笔共 10 字节已送达，隐藏恢复后遇到 `channel_cleanup_timeout`，没有新首帧，输入保持关闭。十个 TUI 操作仍待 Android 复测。 |
| 终端显示 | `terminal_view 0.5.0` 漏绘组合重音已有固定候选补丁及绘制回归。两壳有相同的 Nerd Font、CJK、emoji 和 ANSI 样例。Powerlevel10k 与 Oh My Posh 的固定提示符在 Mac 的两条终端核心得到预期光标列。[组合重音修复](10-blocker-repair.md) · [真实主题样例](52-mobile-theme-prompts.md) | 真机中文 IME 预编辑／提交、复杂字符列宽、系统字体回退、触控选择及长时间重绘性能。 |
| 配置与设备身份 | 主机、公开网络参数和可选字号支持本地加密导入导出、旧版读取和冲突审查。导入后的网络默认停用，新主机需在本机配对。设备 SSH 私钥与组网身份留在原设备。[迁移实现](18-mobile-network-profiles.md) · [格式与事务](../validation/config-transfer/README.md) | Mac 系统文件选择器的导出和导入已通过。Android／iOS 文件提供方、跨手机实际迁移和耗时待验。 |
| 三种组网 | 两份 APK 包内的 EasyTier、Tailscale 原生库已核对。EasyTier 的 Linux、Windows 移植编译错误已有修复，三桌面候选完成编译、链接、加载及离线测试。ZeroTier 共享设备审查已接入两壳源码，Mac 已用固定原生身份算法通过 JNI 验证加密保存、重新读取、拒绝损坏密文及显式删除；KeyStore 线程自 onCreate 启动修复（commit 5959b0d）。ZeroTier 原生候选补丁 0008 经三轮独立评审定稿入档（`patches/0008-streams-and-hp-boundary.patch` 终版 911 行，sha256 `ba4654f9…`，`zerotier-candidate.json` 哈希闭环）：首轮评审发现 B1（run() 拆除后无条件 reopen，致分离线程帧回调 UAF），修复复评发现兜底关闭层引入 B2（`_nets_m` 与 join 路径 `_networks_m` 反序持锁成 ABBA 环），删除兜底层后聚焦复核 APPROVE；终态修复为 `_shuttingDown` 条件化 reopen + HpFrameGate 单调 seal（set-flag → seal → drain）；缺口 1 修复（IPv6 DAD PREFERRED 即刻生效消灭黑洞、IPv4 单链表防自环）与阶段 C Android 链接加固（`-Wl,--no-undefined`）与 BOUND_SYMBOLS 六元组符号校验不变，本地全量验证通过。[双网络 Android 证据](27-mobile-tailscale-cloud.md) · [桌面移植](10-blocker-repair.md) · [ZeroTier 最新记录](55-mobile-shared-network-device.md) | ZeroTier 阶段 2 门控：S1–S4 已完成并经 CI 定案（run `42632587131` 全绿，产物含 `libhp_zerotier.so`）；仅 S5 真机验收未做。系统 KeyStore 硬件隔离结论与指定网络真实拨号／SSH 链路。网络分支多机配对真机验证。五端的 15 个单网格及 20 个并发组合仍须逐格验收。[平台矩阵](../validation/shared/platform-matrix.json) |
| 设计、桌面与分发 | Penpot 有扫码双端、看板、终端输入、桌面分屏、窄窗和关键失败恢复的交互原型，也有初步组件与语义 tokens。已建立分层测试构建和来源记录。Mac 桌面与各平台构建的既有证据按版本保留。[设计覆盖](../design/v2-coverage.md) · [分层构建](07-build-and-release.md) | 要根据设备实测收敛高保真和组件状态，再验收桌面真实分屏、焦点与恢复。iOS 签名安装、五端产品运行及辅助技术待验。许可证已定为 GPL-3.0-or-later（2026-11-11 拍板，根 LICENSE 已写入）；逐产物依赖清单见 `THIRD_PARTY_NOTICES.md`，正式分发审查收口中。[分发审查](17-license-and-distribution-review.md) |

## 最新代码与公开包的差别

在 `dd02595` 的[集中构建](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185)中，两份分发 APK 构建成功，工作流总体失败。之后的 [Flutter 定向复测](https://github.com/Luck9Star/herdr-pocket/actions/runs/42417473474)通过了只读闭环与同名目标 B 的检查，仍因受保护 TUI 恢复失败。该次复测没有重建 APK。

后续源码已包含看板搜索、Flutter 静默观察修复、网络共享设备的影响范围与恢复审查。设备服务不可用时，手机仍可显示已读到的关联主机和网络。目录读取失败时显示范围未知。Mac 已在 320 与 390 CSS px 的实际 Tauri 页面、两套 Android 宿主的隔离 JVM，以及原生身份算法的 JNI 联跑中验证相应路径。Android 的系统 KeyStore 已有独立仪器化验证：不注册 JCE provider，直接编译清单中的三个生产文件，在 CI 的 API 35 模拟器上运行；修复了仪器化线程启动时机（commit `5959b0d`：移至 `onCreate` 启动以避免主线程竞争死锁）；本机没有 SDK，只完成编译校验，运行结果以 CI 产物为准，模拟器的软件 KeyMint 不构成硬件隔离结论。Penpot 两张新状态页有 10 次独立预览点击记录。[手机行为与复跑步骤](55-mobile-shared-network-device.md) · [结构化证据](evidence/mobile-pair-gui/shared-network-device-20261108.json)

**ZeroTier 原生候选补丁 0008 经三轮独立评审定稿**：此前暂存的 `0008-streams-in-progress.patch` 草稿（网络流与边界绑定）完成并发安全重构与缺陷修复后转正为 `candidates/zerotier/patches/0008-streams-and-hp-boundary.patch`（终版 911 行，sha256 `ba4654f9…`）并闭环录入 `zerotier-candidate.json`（补丁、manifest validationFiles 与 `run_boundary.py`、`gate_reopen_test.cpp` 三方哈希一致）。评审链与终态如下：
- **三轮评审链**：首轮发现 B1——run() 拆除后无条件 reopen，分离线程的帧回调在已析构对象上触发 UAF；B1 修复复评又发现兜底关闭层引入 B2——run() 拆除持 `_nets_m` 调 `_node->network()`，与 join 路径 `_networks_m`→`_nets_m` 反序持锁成 ABBA 死锁环；删除兜底层后聚焦复核，最终 APPROVE；
- **终态修复（a+b 两层）**：`_shuttingDown` 标志条件化 reopen，杜绝停机后的重开路径；`HpFrameGate` 改为单调 seal，按 set-flag → seal → drain 顺序收口，分离线程帧回调安全排空；
- **缺口 1 修复**：Managed IPv6 地址在虚拟接口初始化（`init_interface`）时即时提升为 `IP6_ADDR_PREFERRED`，彻底消灭 DAD 异步延迟造成的路由黑洞；IPv4 对称 re-add 修复单链表防自环；
- **评审伴随项一并修复**：N2 fd 泄漏、N3 注释链、N5 幽灵插入；新增 `gate_reopen_test` 25 项检查（含 B1 交错复刻，评审以变异验证确认非恒真）；
- **构建与符号加固**：阶段 B 清单完整收录 0008 补丁、bound fixture 与测试套件；阶段 C Android 链接加固加入 `-Wl,--no-undefined` 强链接约束，并强制核验 `BOUND_SYMBOLS` 六元组符号契约（`hp_zt_bound_open`, `hp_zt_bound_state`, `hp_zt_bound_read`, `hp_zt_bound_write`, `hp_zt_bound_shutdown_write`, `hp_zt_bound_close`）；
- **本地全量验证通过**：干净基线 4044 全过、补丁初版 31/4055 失败、终版 4055 全过；Python 套件 56/56；62 TU ASan+UBSan；boundary 118 项；tap-reconfig 8 项；manager/offline 全过；
- **待办**：N1（ZT netif RST 抑制失去 ECONNREFUSED）已由 0009 候选补丁闭环（见下节）；`board_search` 为独立于 0008 的应用层缺陷另线处理；阶段 2 门控余项：S5 真机物理网络入网与多机并发验收（需硬件）。

**ZeroTier 候选补丁 0009（N1 修复）入档**：`0009-closed-port-rst.patch`（sha256 `e2df90f7…`，1890 字节）恢复 closed-port connect 的快速失败语义——0008 在 tcp_input no-listener 分支无条件抑制 pcb-less RST 导致只能等超时；0009 让 pcb-less RST 直接在入站 netif 应答（上游 `tcp_rst_netif()`、commit `3666dcc66c8a` 语义，`tcp_output_control_segment` 在 pcb==NULL 时不再查 route 表，杜绝经重叠网络逸出），并保留 `hp_ready=0` 与已 remove netif 的 drain／teardown 静默。lwIP `ERR_RST` 即其形式的 `ECONNREFUSED`（`ECONNRESET`/104）。`zerotier-candidate.json` 闭环更新：patches 5 项、afterFiles 更新 `tcp_in.c`（`df42b49a…`）与 `tcp_out.c`（`5135c39b…`）、validationFiles 新增 `rst_closed_port_test.cpp` 与 `run_rst.py`；`test_zerotier_candidate.py` 锚点与 identity-service 补丁集合断言同步适配。真实 lwIP 内存线材测试（ASan+UBSan）验证 IPv4／IPv6 快速拒绝、peer 自身 netif 发出 RST、重叠 netif 零泄漏。

**CI 拓扑与路由机制收敛**：梳理并确认了 GitHub Actions 云端工作流矩阵展开与分支命名前缀强依赖规范。在 `.github/workflows/android-network-experiment.yml` 中：
- `codex/network-batch/with-emulators-*` 前缀激活 `android-pairing` 云端模拟器联跑矩阵；
- `with-emulators-input-*` 前缀激活受保护输入夹具（`input-fixture`）；
- `with-emulators-input-recheck-flutter-tui-*` 前缀单独激活 Flutter TUI 模拟器复测；
- 普通分支或不符合前缀规范的推送将自动跳过耗时的 Android 模拟器矩阵任务。

## 恢复工作时的顺序

1. **[已完成] 复测 Flutter 在 Android 上的观察恢复与 TUI 全量回执。** 在 API 35 模拟器作业中完成两壳配对、看板、观察及受保护 TUI 输入验收。Flutter 隐藏标签恢复后成功收到原目标新完整帧、同一观察代增量，十个 TUI 操作远端回执全量核验通过（run `42659301059`，`actionCount: 10`，`applicationStateMatched: true`，全部 checks 绿）。Tauri 端观察与配对全绿，TUI 首键布局漂移经单循环居中静止门修复（`9466e70`）。两份同源 arm64 APK 的哈希、ABI 与来源清单均已校验。[最新交接台账](docs/58-session-handoff-2026-11-09-r2.md) · [云端工作流](../.github/workflows/android-network-experiment.yml)
2. **[S1–S4 已完成] 补手机原生网络链路与阶段 2 门控解锁。** 阶段 2 门控已遵用户指令解除并完成开发：S1 声明与 JNI 导出、S2 生产切片倒置（`AndroidZeroTierNative` 纳入正式源）、S3 库构建、S4 双壳宿主接线（`System.loadLibrary` + `bindNative`、Cargo feature 与打包链接）均在 CI 全矩阵（run `42632587131`，9 成功 0 失败）通过验证，产物完整包含 `libhp_zerotier.so`。仅余 S5 实体真机在物理网络环境下的入网与多机并发待取得硬件后验收。[设备存储与拨号的边界](55-mobile-shared-network-device.md)
3. **用真机结果决定选型。** 目前可用环境为云端和 Mac。取得实体 Android／iOS 后，使用相同字体、fixture、视口和负载检查扫码、输入法、滚动选择、锁屏、恢复及性能。以正确性作首要门槛，再比较维护成本、收敛高保真和组件库，接续桌面三平台。[技术栈复评](06-technology-evaluation.md) · [设计计划](08-ui-design-plan.md)

## 五端维度遗留台账（2026-11-10 回填）

配合 [04 路线图勾选判据](04-roadmap.md)与[05 §8 支持矩阵](05-product-design.md#8-五端支持与开源发布)的回填，此处登记本批之后仍为「未完成/部分」的维度；证据细节见 05 §8 格内依据。**需硬件/真机/签名条件的项以 ▲ 标注**。

| 端 | 维度 | 状态 | 缺口性质 |
| --- | --- | --- | --- |
| Android | 签名 | 部分 | ▲ 固定 release keystore 签名已通（Release v0.1.1 双壳，run 42917936593 复核哈希与 v2 签名块）；商店签名未做 |
| Android | 分发 | 部分 | ▲ Release v0.1.0/v0.1.1 渠道已通（debug 验证批＋release 精简批）；真机安装未验 |
| Android | 设备运行 | 部分 | ▲ 模拟器闭环全通；实体手机摄像头扫码、锁屏/重启恢复、真机 IME 未做 |
| Android | 安全凭据存储 | 部分 | ▲ 模拟器软件 KeyMint 验证过；硬件 KeyStore 隔离结论未做 |
| iOS | 构建/自动化 | 部分 | r8 起含 aarch64 真机未签名构建（v0.1.0 双壳 ipa）；batch-0012 r9 起 `ios-device` 作业贯通 EasyTier 静态链接全链（静态库构建→cargo 合并→Xcode 链接→xcarchive→app 二进制符号核验，run 42946118795） |
| iOS | 三网接入 | 未做 | ▲ 依赖链：EasyTier 静态链接 ✅（2026-11-11）→ Keychain 身份层（无本地 Xcode/真机）→ 可用性翻转；Tailscale 上游阻塞、ZeroTier libzt 移植另计 |
| iOS | 签名、分发、设备运行 | 未做 | ▲ 依赖 Apple 开发者账户/证书与实体 iPhone |
| iOS | 安全凭据存储 | 部分 | Keychain 后端仅内存替身验证（系统 Keychain 调用数为 0） |
| Windows | 构建/自动化/分发 | 部分 | 停留在 2026-10-30 第一代验证壳，当前代码未重跑 |
| Windows | 签名 | 未做 | ▲ 无 Authenticode 记录 |
| Windows | 设备运行、安全凭据存储 | 未做 | 无 Windows 目标系统运行与凭据验证记录 |
| macOS | 构建/自动化/分发 | 部分 | 第一代 `.app` 证据＋Mac 本机开发验证；当前批次未重跑，安装器未验 |
| macOS | 签名 | 未做 | ▲ Developer ID 签名与公证未做 |
| macOS | 设备运行 | 部分 | 有限原生 smoke 已过；桌面分屏、焦点与恢复的完整验收未做 |
| macOS | 安全凭据存储 | 部分 | 算法级 JNI 验证过，Keychain 级未验 |
| Linux | 构建/自动化/分发 | 部分 | 第一代 deb 与 Linux loopback 集成证据；当前批次未重跑 |
| Linux | 设备运行、安全凭据存储 | 未做 | 无目标系统运行记录；凭据服务缺失/锁定行为验证待办 |
| 三网 × 五端 | 单网 15 格与 4 组并发 | 未做 | ▲ 全部止步于编译/加载/离线测试或库打包核对，无任何一格完成真实拨号＋SSH 闭环 |

本批 roadmap 勾选（3 条：M0.5 重跑留痕、M1 辅助命令、M1 看板目标观察）均为模拟器级或文档级证据，勾选依据已注记在 [04](04-roadmap.md) 各条目尾。

本轮收尾将 0008 终版修复连同哈希锚定测试与交接文档提交为单个 commit，推送 `codex/network-batch/with-emulators-zerotier-0008-<短SHA>` 触发分支由 CI 全矩阵验证（该前缀跳过 input-fixture 以规避 504 高发外依赖，run 结果以 Actions 记录为准）。测试浏览器、独立 Penpot 预览、临时服务与测试 JVM 均已退出，原有 Penpot 编辑页保留。工作区中 ZeroTier 0008 补丁经三轮独立评审定稿入档（`drafts/` 目录中无活动草稿，仅保留归档说明），`zerotier-candidate.json` 哈希闭环，本地全量验证通过。`graphify-out/` 保持未跟踪状态，严禁提交。
