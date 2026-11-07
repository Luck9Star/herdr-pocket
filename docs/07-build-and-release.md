# 云端构建与测试分发

核查基线：**2026-10-29**；执行状态更新：**2026-10-30**。本页保留云构建与分发规则。仓库现已有并行验证壳、真实 GitHub Actions 运行与可下载测试产物；不是正式应用或商店发布。实际 run、源码SHA、失败与设备边界见[验证记录](09-prototype-validation.md)。本机未安装完整SDK工具链。

## 1. 已选择云端优先

**可以用 GitHub Actions 编译 Android APK，并把其他平台的构建放在对应系统 runner 上。**普通维护者可以只准备编辑器、Git 和浏览器，推送源码后下载测试产物；本地完整构建链按调试需要选装。云端优先不依赖最终选择 Flutter 还是 Tauri，两条候选都必须验证原生库和目标系统。

| 参与方式 | 本地最少准备 | 何时再安装工具 |
| --- | --- | --- |
| 修改文档 / 源码、发起构建 | 编辑器、Git、浏览器；使用 GitHub 网页编辑时也可不做本地检出 | 需要本地检查、代码补全或运行程序时安装对应最小工具 |
| 安装和体验测试包 | 对应系统 / 设备及该渠道要求的安装权限、账户或描述文件 | 需要设备日志、调试器、模拟器或热重载时增加平台工具 |
| 维护 native / 框架桥 | 可先在 CI 编译、查看日志和下载符号 | 高频 FFI、崩溃或设备问题调试通常值得安装目标平台工具链 |

“本地少装”不是“所有参与者永远零工具”。例如 Android 安装包体验不要求 Android Studio，但需要设备和允许的安装渠道；需要 `adb` 日志时可单独准备 platform-tools。Apple 测试分发仍遵守签名、设备与账户条件。目标系统的运行库也不等于构建 SDK，发行物必须说明运行前提。

## 2. 五端构建与可安装产物

下表是实施方向，不是已经通过的支持矩阵；最低系统、CPU 架构和包格式在 M0.5 锁定。**runner CPU 与 App 的目标 ABI 分别记录**，不能用 x64 构建宿主证明 ARM 真机已通过。

| 目标 | 首选云端宿主 | 预期测试 / 发布产物 | 不能由构建成功推出的结论 |
| --- | --- | --- | --- |
| Android | 标准 Ubuntu runner；固定 JDK、Android SDK / NDK、Gradle 及框架工具链 | 测试 APK；选定商店渠道后再产出 AAB 等对应材料 | APK 必须有适用签名；AAB 不是直接点击安装的 APK，模拟器不能代替手机体验 |
| iOS | macOS runner + 匹配 Xcode / SDK | simulator 产物与设备 archive / 分发包分开；测试渠道另定 | simulator 构建不证明设备可安装；设备包须满足证书、provisioning、entitlement 和渠道要求 |
| macOS | macOS runner；分别明确 Apple Silicon / Intel 目标 | App 及选定打包格式；公开分发按渠道处理签名 / 公证 | macOS 是构建宿主不代表 native 已有 macOS slice；未签名测试与正式分发不能混标 |
| Windows | 标准 Windows runner + 对应 C/C++ 等工具链 | 可运行目录 / 安装包，格式和架构另定 | CI 产物不自动获得可信签名、SmartScreen 信誉或完整运行库；ARM 支持另验 |
| Linux | 标准 Ubuntu runner + 所选 GUI / native 开发依赖 | 可运行目录 / 发行包，明确发行版、架构与动态依赖 | Ubuntu 构建不代表所有 Linux 发行版兼容；不能省略 libc、桌面库及安全存储运行条件 |

GitHub 官方提供 Linux、Windows、macOS 的标准 hosted runner，并分别列出 x64 / arm64 标签。本次可见的显式标签包括 `ubuntu-24.04`、`ubuntu-24.04-arm`、`windows-2025`、`windows-11-arm`、`macos-15` 与 `macos-15-intel`；这些是可选环境示例，**不是本项目已锁定的矩阵**。Apple 标签须与所需 Xcode 和 SDK 核对后选择。`*-latest` 会迁移；显式 OS 标签的镜像也会更新，不能把标签当不可变镜像。[GitHub runner 平台与限制](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)

所选框架的宿主要求继续有效；Flutter 的 [Windows](https://docs.flutter.dev/platform-integration/windows/setup)、[macOS](https://docs.flutter.dev/platform-integration/macos/setup)、[Linux](https://docs.flutter.dev/platform-integration/linux/setup) 文档以及 [Tauri 前提](https://v2.tauri.app/start/prerequisites/) 不能被“CI 支持五端”替代。具体签名与渠道依据见下文来源。

实施时按所选框架收敛包格式，不同时承诺所有安装器：

- Android 首个可安装试用物是 APK。一次性 runner 的 debug key 可能变化，不承诺跨 run 原地升级；稳定 preview 采用独立应用 ID 与受控测试签名，和正式签名隔离，具体实现随框架确定。
- iOS 可选择注册设备的 Ad Hoc 或 App Store Connect / TestFlight 等适用渠道；各自账户、签名、profile 和设备条件必须满足。未签 IPA 或 simulator 包不列为手机安装渠道。
- macOS 先验证 `.app`，DMG 是可选包装；公开直发采用 Developer ID 签名和公证。文件扩展名不证明 Gatekeeper 接受或应用运行通过。
- Windows 的 Flutter bundle 包含 DLL / data 等配套文件；Tauri 的安装器及 WebView2 运行前提另验。不能只上传单个可执行文件就假定是完整发行物。
- Linux 先选定发行版 / libc 基线与一种分发方式，分别验证目标架构。包格式封装不能消除 GTK / WebKitGTK 等运行依赖或自动完成 ARM 交叉构建。

## 3. CI 分层与触发范围

| 层 | 来源 / 触发 | 执行内容 | 权限与输出 |
| --- | --- | --- | --- |
| PR 检查 | 普通 `pull_request`，包括外部 fork | 格式、静态检查、协议 / 配置 / 终端 fixture、相关平台编译；按变更范围扩矩阵 | 默认只读代码权限，无分发签名秘密；日志和临时调试 artifact |
| 受信分支集成 | 主分支等明确允许的 ref | 组合构建、native 与 App ABI 校验、可执行的自动化测试 | 未签名或独立测试身份产物；不因来自主分支就自动商店发布 |
| 测试分发 / Release | 受信 tag 或手动触发，且验证目标 ref / commit 与来源 | 读取对应构建记录，执行所需签名、公证和打包，生成校验清单及发布材料 | 仅需要的 job 取得对应签名 / 发布权限；向已选渠道显式发布 |
| 设备验收 | 下载与版本对应的产物，在目标设备执行 fixture | 输入、字体、扫码、三网并发、生命周期、安装升级等 | 记录设备 / 系统 / 产物哈希、结果和限制；不把上传 artifact 算作通过 |

按变更范围运行检查可以控制排队和耗时，但正式声明某个平台 / provider 可用前，必须完成该格的构建、运行与产品验收。核心 Tailscale + EasyTier 十格、完整三网十五格和并发组合仍按 [ADR-0006](adr/0006-three-overlay-providers.md) 执行；云构建不降低门槛。

tag 名称或手动按钮本身不产生信任。发布 job 只接受允许来源的固定 commit，并核对同 commit 的构建、依赖与测试记录；发布引用的变更受仓库权限 / ruleset 约束。设计不额外要求每次发布再增加一轮人工审批，但不能允许任意外部 PR ref 借手动参数进入签名步骤。

## 4. native、App 与主机 helper 分开产出

三网络包含 Go / tsnet、Rust / EasyTier、C/C++ / libzt，不因 UI 框架或 GitHub runner 存在而自动跨平台。Heeler 参考产物只有已核对的 iOS slice；其他目标、ABI 与桥接仍需移植和构建，详见[固定来源证据](00-research.md#23-heeler-三网络源码复核)。

1. **native 层**：锁定上游 commit、子模块、补丁、构建选项、目标 ABI、最低系统及工具链；逐目标产出库、头文件 / 绑定与符号。
2. **App 层**：只消费匹配的 native 清单及校验和，构建 UI / SSH / 终端与包；ABI 或来源不匹配即失败，不静默取另一个缓存版本。
3. **一次性 helper**：按远端 Unix 主机的 OS / CPU 建立独立构建与测试矩阵，随源码或独立发布资产分发。它不是五端 GUI 的另一个安装包，也不要求主机安装桌面 GUI。

helper 的实现语言与发行格式仍待定。CI 在隔离测试环境的临时 home / fixture 中验证规范公钥解析、权限、幂等追加和撤销；不操作维护者真实 `authorized_keys` 或给真实主机添加授权。用户安装 / 运行正式 helper 时仍遵循 [ADR-0007 的主机端确认](adr/0007-pairing-and-config-transfer.md)，CI 发布不能代替该确认。

native 分发须附来源清单、实际源码 / 补丁取得方式、适用许可与 NOTICE、构建材料及适用的重链接 / 安装资料，和对应文件校验和。字体同样锁定文件、版本和许可材料。项目希望衍生改动保持开源，具体许可证仍待定；产物生成不等于许可审查通过。

原生关口包括 cgo 的目标 C 编译器、Windows Go/C 库与 Rust/MSVC 的 ABI 互通，以及 Android 所有预编译库的 ABI、STL、最低 API 与 16 KB 页适配。只设置 `GOOS` / `GOARCH`、使用新 NDK 或得到一个 `.so` 文件，都不能替代链接和运行验证。[cgo 官方说明](https://pkg.go.dev/cmd/cgo)、[Android ABI](https://developer.android.com/ndk/guides/abis)、[16 KB 页支持](https://developer.android.com/guide/practices/page-sizes)

## 5. 固定工具链，缓存只作加速

每次构建至少记录以下信息，随日志或非秘密 manifest 保存：

- 项目 commit、dirty 状态、workflow 版本、构建类型与目标 OS / ABI。
- runner 标签、实际镜像版本及所选 Xcode / SDK 或 Windows 工具集。
- 框架 / CLI、JDK / Gradle、SDK / NDK / CMake、Go / Rust / C/C++ 编译器的实际版本。
- 依赖 lockfile、native 上游 / 补丁哈希、字体文件及构建选项。

Ubuntu hosted image 已包含多种 Java 与 Android 工具，缺少的精确版本可以在 job 内安装。必须显式选择版本并检查实际值，不依赖镜像默认的 JDK / NDK。Android 官方 `sdkmanager` 支持安装特定 SDK、NDK 和 CMake 包及处理必要许可，CI 不要求安装 Android Studio GUI。[runner 工具清单](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)、[setup-java](https://github.com/actions/setup-java)、[Android sdkmanager](https://developer.android.com/tools/sdkmanager)

缓存适合 Gradle、pub / npm、Cargo、Go 等可重新取得的依赖及可重建中间文件。key 至少区分 OS / 架构、工具链、依赖锁定内容和影响产物的 native 补丁；缓存缺失也必须能完成构建。不同信任来源的缓存不可未经校验进入发布链。

**缓存不保存签名私钥、密码、证书私钥、SSH 凭据、overlay 节点身份 / 状态或真实用户配置。**fork PR 可能读取可访问的分支缓存；缓存不是秘密存储，也不是可信二进制发布仓库。恢复内容按不可信输入处理，发布构建不能直接信任 PR 写入的编译输出。[依赖缓存与安全边界](https://docs.github.com/en/actions/concepts/workflows-and-actions/dependency-caching)

耗时 native 库可在来源变化时独立构建，向 App job 提供带完整来源与校验的版本化产物；不要求每个 UI 变更从头编译三套库。此优化必须保持 ABI / 来源可验证，并可从锁定源码重新构建，不能变成只有某次缓存还在才可发布。

## 6. artifact、Release 与签名秘密

workflow artifact 用于暂存构建包、符号、报告以及 job 间传递，随 run 和保留策略管理。GitHub 的下载流程要求登录并有仓库 read 权限；它不是普通用户长期下载渠道。[保存 artifact](https://docs.github.com/en/actions/tutorials/store-and-share-data)、[下载与保留](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)

GitHub Release 以 tag 组织版本、说明和分发资产，须单独发布；上传 artifact 不会自动创建 Release。测试版可使用清晰标记的 prerelease，正式商店分发另有上传和审核环节。渠道未选定前不承诺从任意系统下载文件即可安装。[Release 的用途](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)

可分发资产的命名和 manifest 应包含版本 / commit、平台、ABI、测试或正式类型、签名状态；提供 SHA-256 等校验和、构建来源、依赖 / 许可材料及已验证范围。签名前后的产物分别记录，实际提供下载的文件使用最终哈希。可验证来源不等于已证明位级可复现，后者须另作重复构建比较。

依赖 / 许可材料同时提供可机读 SBOM；调试符号按适用的 build ID / UUID 和产物哈希关联，避免用其他构建的符号诊断发布包。

PR 检查默认使用最小 `GITHUB_TOKEN` 权限；发布 job 按需提高，如写 Release 才需相应仓库写权限。外部 fork 的普通 PR 默认不接收仓库 secrets，token 为只读；本项目继续保持这条边界，不放宽来换取签名包。[fork 触发与权限](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflows-in-forked-repositories)

不要用带 secrets / 写权限的 `pull_request_target` 或后续高权限 workflow 执行、签名未经验证的 PR 代码 / artifact。签名凭据只在受信 job 的临时环境中使用，结束时清理；不进入 cache、artifact、Release 或普通日志，也不把签名公钥证书与私钥混为一类材料。[安全使用 Actions](https://docs.github.com/en/actions/reference/security/secure-use)

外部 actions 固定完整 commit SHA 并核对来源仓库，依赖升级通过审阅；tag 可移动，不能作为唯一锁定依据。实施时可评估 GitHub 官方 workflow dependency lockfile 对传递依赖的锁定能力。不能把依赖 pin 当作无需审查 action 代码及权限的理由。

## 7. 费用与容量边界

截至核查日，**public 仓库使用标准 GitHub-hosted runner 的计算免费**，包括官方标准列表中的相应 macOS runner；不是所有带 macOS 名称的规格都免费。larger runner 即使服务 public 仓库仍收费。private / internal 仓库的规则与公开仓库不同，不沿用此结论。[GitHub Actions 计费](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

artifact / cache 等存储存在额度、保留和计费规则，不能从计算免费推出无限免费存储。实施时为调试包 / 日志设有限保留、清理失效产物，并检查账户和仓库配置；本设计不固定可能变化的价格、额度或把 Release、Actions 存储、商店账户费用混在一起。

先使用标准 runner；只有实际构建证实资源或平台限制后再评估付费规格或其他方案。并行矩阵、重复 PR 和大体积 native 产物须控制资源使用。无需为此先购置本地全套构建机器或配置自托管 runner。

## 8. 落地顺序与验收记录

1. M0.5 出现最小原型后，先让 Ubuntu 构建 Android 测试 APK，生成工具链 manifest、校验和及临时 artifact；同时建立 Apple / Windows / Linux 的最小构建验证，尽早暴露 native 目标缺口。
2. Flutter / Tauri A/B 使用相同设备 fixture 与记录格式；框架定案后再收敛正式 App pipeline，避免维护两套发行系统。
3. native 产物与 helper 分别建立来源锁定和目标矩阵；App 集成验证每个目标实际链接的版本，不能只复用相同文件名。
4. 选定测试分发渠道、包身份、更新签名与许可证后，配置受信签名 / 分发 job；不承诺临时调试签名包可跨 run 无缝升级。
5. 各平台分别记录构建、自动化检查、签名、分发、目标设备运行和功能验收。失败或未执行独立标明，逐步开放正式支持。

真机测试仍覆盖完整终端、Nerd Font / CJK / IME、相机扫码、加密配置迁移、Tailscale + EasyTier 并发、声明支持的 ZeroTier 组合，以及前后台 / 休眠恢复。CI 的构建或模拟器成功不能替代这些体验与系统行为；测试不使用维护者的真实网络节点身份。[产品验收](05-product-design.md#7-产品验收)、[技术栈 A/B](06-technology-evaluation.md)、[路线图](04-roadmap.md)

## 9. 平台官方来源

- Android：[命令行构建](https://developer.android.com/build/building-cmdline)、[App 签名](https://developer.android.com/studio/publish/app-signing)。
- Apple：[Xcode 分发路径](https://help.apple.com/xcode/mac/current/en.lproj/dev31de635e5.html)、[TestFlight](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview)、[macOS 公证](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)。
- 框架发行：[Flutter Android](https://docs.flutter.dev/deployment/android)、[Flutter iOS](https://docs.flutter.dev/deployment/ios)、[Flutter macOS](https://docs.flutter.dev/deployment/macos)、[Tauri GitHub pipeline](https://v2.tauri.app/distribute/pipelines/github/)、[Tauri Windows 安装器](https://v2.tauri.app/distribute/windows-installer/)。
- Windows：[MSIX 签名概览](https://learn.microsoft.com/en-us/windows/msix/package/signing-package-overview)；最终包格式不同则核对相应渠道。
- Linux：依据所选 [Flutter](https://docs.flutter.dev/platform-integration/linux/setup) 或 [Tauri](https://v2.tauri.app/distribute/) 的发行前提，发行版 / ABI / 格式在实施时锁定。

以上动态官方文档只证明核查日的能力与限制；实施时记录实际版本、runner 镜像与发行渠道要求，并更新本页。尚未编译、签名、上传或设备验收的格不能标记已支持。

## 开发批次与集中验收（2026-11-05）

日常实现在 `codex/core-prototype-validation` 积累，经本地检查和审阅后提交。需要集中验收时，将同一已审阅提交推到新的 `codex/batch/<批次名>`。GitHub 只启动一个[批次工作流](../.github/workflows/batch-validation.yml)，由它调用各层的可复用工作流，以同一来源 SHA 生成 GUI、协议和 helper 证据。日常开发分支的 push 不自动发起这些验证。

普通批次优先覆盖两套 GUI、设备密钥、原版只读 SSH、候选扩展输入和 Android 模拟器。`codex/batch/full-<批次名>` 另行运行原生网络移植与原有 SSH 矩阵。上游原版终端绘制 characterization 可单独手动诊断，保留已有失败证据。测试包及构建与签名状态写入 manifest，源码实验、云模拟器、真机与真实组网分别验收。工作流权限为只读，不创建 tag、Release 或商店提交。

手机集中复验使用 `codex/batch/android-<批次名>`。两壳只重建 Android 应用，继续运行配对、SSH 与 GUI 用例；其他系统保留各自历史验证结果。Flutter 的依赖锁须先验证，验证过的锁可用于生成诊断用 debug APK。单元或 GUI 失败仍保留在 Actions 和 manifest，得到 APK 只证明打包步骤成功。一次性 POSIX helper 单独输出含固定依赖、操作说明和源码 SHA 的源码包。

`codex/batch/phones-<批次名>` 在同一次运行中额外构建两条路线的 iOS 候选产物，仍跳过 Windows、Linux 与 Mac 安装包重建。产物保留签名、架构和工具链状态，Linux 的 SSH/GUI 用例及临时 Android 模拟器独立报告真实经过的步骤。

手机闭环修复批次 `phones-observe-*` 只复验原版主机的 GUI、两套 Android 安装包、两个 API 35 模拟器和本次需要修复的 iOS/辅助工具 runner。已取得的协议、输入扩展和 overlay ABI 记录保留其原有 SHA。Flutter iOS 和 helper 的 macOS 任务使用本项目已成功调度的 `macos-15`。[GitHub 托管 runner](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)

若 iOS 与 helper 已有同系列的独立结果，`android-observe-<批次名>` 只重建两套 Android 包并验证两种模拟器及 Flutter Linux widget，不再重复启动 Linux Tauri driver。已通过的 helper、协议与原生 ABI 对照保留原来运行的证据，避免重复申请桌面或 iOS runner。

Android 组网候选另设[显式批次同源实验工作流](../.github/workflows/android-network-experiment.yml)：先产出 arm64/API 35 原生库与来源材料，再由两套 GUI 校验后消费。它只匹配新的 `codex/network-batch/**`，不匹配常规开发或既有 `codex/batch/**`，不改变常规包的 feature/ABI。手动入口须先在默认分支注册，不能依赖未注册的原型分支 dispatch。该工作流已实际运行，原始接线记录见[原生通道](21-flutter-native-network.md)，最新双网络 Android 编译和静态产物见[集中验收](27-mobile-tailscale-cloud.md)。Android 动态加载、安装、真实节点与实际 overlay SSH 仍另验。

手机独立标签批次继续使用同一个组网工作流：Flutter 先固定组合重音修复候选与依赖锁，分别分析、运行 widget／绘制和隔离 SSH GUI；共享 Rust 单独运行受控观察测试。两包报告保留 `sourceChecks`、`transportChecks`、打包和 Android 运行状态，不以成功打包抹去测试失败。新增 russh 固定源码候选的完整 Apache 许可证、变更声明、补丁与来源摘要随构建 assets 和下载证据交付；来源还原检查不替代实际编译或运行。[标签、依赖修复与集中结果](22-mobile-terminal-tabs.md)

Tailscale 手机源码批次将同一组网工作流扩为 EasyTier＋Tailscale 双库：固定 Go module zip 的 h1、补丁后 tar 全文件、两库 APK 字节、JNI 与 DT_NEEDED 同时校验。该扩展在 `750798fe` / run 42247482105 实际完成，两份 APK 同源、五个 job 成功，保留首轮失败与修复后的独立证据；不继承旧包的设备运行结果，仍按功能批次集中执行。[接线与来源门禁](26-mobile-tailscale-login.md) · [本批下载、校验与边界](27-mobile-tailscale-cloud.md)

手机输入和双网络 APK 一起验收时，用同一已审阅提交创建 `codex/network-batch/with-emulators-input-<批次名>`。工作流按该 SHA 构建受保护输入夹具，供两条 Android 模拟器路线和 Flutter 的隔离 SSH 用例使用。原生库及两个 arm64 测试包仍分别构建并关联来源。只需要普通观察的批次继续使用 `with-emulators-<批次名>`。[手机终端验收](36-mobile-paste-and-auxiliary-input.md)

该输入批次已在 `a9914fe` / [run 42339225239](https://github.com/Luck9Star/herdr-pocket/actions/runs/42339225239) 实际运行，最终状态为失败。原生库、共享 Rust、输入夹具、Flutter 源码检查和两个 arm64 包成功；两套 AVD job 失败，四个独立模拟器场景为 1 通过、3 失败。Linux Flutter 隔离 SSH GUI 通过且收到 9 字节。下载包的离线哈希复核、模拟器应用运行、Linux widget 及真实手机分别记证；arm64 包未在设备安装或运行。后续测试专用 AVD 重试必须保留自己的源码 SHA、run、失败／通过和清理记录，不能把本轮改为通过，也不能把调试模拟器结果继承给 arm64 组网 APK。[下载、首轮失败阶段和范围](36-mobile-paste-and-auxiliary-input.md#同源云验证与可下载测试包)

仅复验输入驱动时，使用 `codex/network-batch/with-emulators-input-recheck-*` 分支，沿用已核对的 arm64 分发包，运行同 SHA 的输入夹具和两条 API 35 x86_64 模拟器路线。源码／原生库／分发矩阵跳过。每个场景按 artifact 的 SHA、manifest 和接收端字节数记证，同时保留 analyzer 与整个工作流的真实状态。[首次定向复验](36-mobile-paste-and-auxiliary-input.md#android-定向复验)
