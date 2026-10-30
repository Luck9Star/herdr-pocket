# 手机优先：远端只读接入

2026-10-30。沿用已认可的 Penpot v2 视觉与手机优先顺序，开始 M1 的首个有限步骤。M0.5 的手机 IME、触控、完整终端与框架 A/B 门槛仍未完成；本步骤不将 M1 整体标为完成，不据此选定 Flutter 或 Tauri。

## 这一小步的范围

先打通手机可操作的“手动资料审查 → 明确核验主机 → SSH 认证 → 会话／pane 校验 → 一帧远端只读快照”。手动入口是扫码流程的兜底和传输验证入口；首版扫码、公钥授权 helper、设备安全存储及多标签完整终端目标保留。

选择一次性只读快照，是为了先核实两条 GUI 所用的 SSH/herdr 适配器能绑定同一远端目标。页面必须写明快照、更新时间和连接已结束，不能显示实时在线、开放输入或把旧画面当作新状态。刷新由用户主动发起，取消立即使当前 generation 失效；迟到结果不能覆盖新尝试。

两端共用[接入契约](../validation/shared/remote-contract.json)，固定 80×24、有限配置／RPC／观察缓冲。仅支持本步骤明确核实的 Ed25519 公钥 pin 和临时内存凭据；不读取 SSH agent、`~/.ssh`、真实授权文件或 overlay 身份，不提供明文保存兜底。实验入口中的内存凭据不是产品级受保护存储，设备密钥生成／安全保存另行实现。

认证必须发生在实际 SSH host key 与已审查公钥匹配之后。每次 snapshot RPC 使用独立 direct-streamlocal channel；observe 使用严格引用的固定命令，不申请 SSH PTY，不发送 resize/control/takeover。适配器没有远端输入方法；原离线 fixture 的逐键／草稿测试与此入口隔离。

本步骤固定 herdr release **0.9.5 / wire protocol 22**。它的 snapshot／terminal.frame 不直接回传 session 身份，多个 session 也可能有相同 `w1:p1`。因此从规范 socket 路径派生同一 `XDG_CONFIG_HOME`，显式指定非 default 命名 session，并用 snapshot 中所选 pane 的稳定 `terminal_id` 作为 observe 目标；不把 pane 名字当跨会话身份。非规范路径、socket/session 名称错配、缺失目标、其他版本明确拒绝，不回默认 session。此绑定依赖已核查的服务端路径与目标解析行为，不能描述为帧自带身份认证。

## 手机验收优先级

1. 360／390px 手机布局先验收：表单可滚动，长指纹不撑开页面，操作目标至少 44px；键盘占用后审查、连接、取消和返回仍可达。桌面仅做适应布局，不新增桌面专属功能占用本轮范围。
2. 审查确认不从扫码、导入、默认值或旧尝试继承；更改目标／公钥后重新核验。连接失败区分主机身份不符、认证失败、会话／pane 不符、观察失败与取消，诊断不直接暴露远端原文或凭据。
3. 云端先构建 Android、iOS 候选，保留五端矩阵。CI 临时 loopback SSH/herdr 实测与手机设备运行分列，不能互相替代。
4. 当前只有云端与 Mac 可用。手机触控、真实中文 IME、相机、iOS 签名安装及后台恢复继续标未验证；不重复索要这些条件。

## 验证与交付状态

首轮代码提交 `b88a0ad9b2a173ac743568ec5ce479f22b6844ca`：Flutter 用固定 `dartssh2 4.1.0`；Tauri 调用新建的独立 `validation/transport-rust`，固定 `russh 0.65.0`。后者不依赖 Tauri，CLI 和 GUI 调用同一适配实现。依赖锁、来源与许可分别见 [Flutter 记录](../validation/flutter/remote-dependencies.json)和 [Rust 记录](../validation/transport-rust/README.md)。本机没有安装 Flutter SDK。

已执行本地检查：25 项 Tauri JavaScript 测试、9 项 Rust adapter 测试（包含自建无凭据 TCP 的取消与 EOF）、Tauri native `cargo check --locked`、Vite 构建，以及 8 项隔离 harness 守卫检查通过。Flutter 的 5 项候选工具 Python 检查通过；第三轮候选云端 analyze、20 项 Dart／Widget、10 项 Linux 渲染检查和 14 项 Mac headless 检查通过，包含 320px 放大字号布局回归；这仍不是手机触控／IME 实测。

独立浏览器复验覆盖 360×740、390×844 和 320×380 短视口：无整页横向溢出，可操作表单／按钮最小 44px；核验后编辑资料使确认失效；离开远端页清空合成临时字段；浏览器没有 native adapter 时连接始终禁用。秘密输入框已从初稿 textarea 修为原生 password 类型，终稿图见[手机表单](evidence/mobile-remote/browser/tauri-390-full.png)，[检查台账](evidence/mobile-remote/browser/verification.json)保留范围。短视口只是键盘占用的布局近似，不是手机软键盘或触控验收。临时预览页、viewport override 与 Vite 服务均已关闭／复原。

已下载并核对来源 `4b78b6b`／17 个 SHA 条目的 Tauri Mac 包，完成原生启动、审查失效、密码字段及无效合成资料处理检查；临时字段清空，随后退出应用并确认进程消失。见[Mac 原生记录](evidence/mobile-remote/macos/verification.json)。没有在 GUI 中输入有效 SSH 凭据，此检查不能代替 GUI 的远端成功路径。

Flutter `d15da12` 候选包也已下载校验并实际打开：远端入口、纵向表单滚动及无效合成私钥拒绝／清空通过，见[原生记录](evidence/mobile-remote/macos/flutter-verification.json)。退出快捷键未结束进程；已核对本次进程的完整路径后发送 TERM，并确认退出。AX 导出未提供文本字段标签，读屏无障碍尚未验收；不从可见文字推断读屏可用。

独立审阅推动修正了 pending TCP 尝试的资源预算、cleanup 期间取消、stdout/stderr 合并输出预算、协议版本、负序号及 secret 表单异常清理。源代码修正、单测与实际 SSH 结果分别记录，不互相代替。

两路线使用同一个临时 sshd/herdr fixture，host/client keys 和授权文件仅在 runner 新建隔离目录中；fixture 配置、私钥和原始敏感错误不上传。每路线六项：正确 pin 读取 full、错误 pin 在认证前拒绝、缺失／错配会话资料拒绝、两个实际会话相同 pane ID 的错配拒绝、snapshot 后取消、显式重新连接。计数器验证未发送远端输入。CLI 的耗时包含启动／JIT，不用作框架性能排名。

| 真实 SSH/herdr 对照 | 源码 | 实际结果 |
| --- | --- | --- |
| [第一轮](evidence/mobile-remote/41046472357/README.md) | `b88a0ad` | **失败，2/12**。两路线 wrong-pin 通过；Rust 误读 snapshot envelope，Dart 异步失败未形成安全报告。 |
| [第二轮](evidence/mobile-remote/41047398465/README.md) | `4b78b6b` | **失败，7/12**。Rust 6/6；Dart wrong-pin 通过，其余认证后、snapshot 前 `async_state_error`。原始协议诊断确认 0.9.5 / 22；输入 0 bytes、清理通过。 |
| [第三轮](evidence/mobile-remote/41048094519/README.md) | `d15da12` | **成功，12/12**。Rust／Dart 各 6/6，full 读取、错误 pin、目标错配、snapshot 后取消与显式再次调用通过。输入 0 bytes；清理通过。 |

第一轮编译检查还暴露 Flutter 两处 analyzer 问题；第二轮通过 analyzer 后发现 320px 标题栏溢出。第三轮一并通过窄屏修复及取消后的迟到 cleanup 不清除下一次输入的回归。删除 Dart channel.flush 后本轮真实读取通过；前轮未采集原始异常文本，不声称已经恢复当时具体 StateError 消息。失败记录保留。

这里的 reconnect 是主动发起新的 CLI 调用，不是同一 GUI 实例恢复。缺失会话用例在有效 socket 返回 snapshot 后拒绝错配的名称绑定，没有执行不存在 session 的 observe。手机触控、真实 IME、GUI 有效凭据成功路径、连续观察与后台恢复仍未验证。

## 测试包复验顺序

1. 从下方对应源码的 Actions artifact 下载，先核对 `manifest.json` 的 source SHA 与 `SHA256SUMS`。这是 14 天保留的测试产物；日志／校验文件单独出现不等于生成了应用。
2. 当前在 Mac 先打开候选包，进入“远端只读”，用合成无效文字检查：审查后编辑目标会取消确认；提交无效资料显示错误，临时字段清空；切回离线实验室不会留下临时秘密。结束后退出应用。Flutter 从顶部“远端只读”进入，Tauri 默认进入此页。
3. 真实传输重复验证使用[隔离云端工作流](../.github/workflows/mobile-remote-validation.yml)，检查两路线各六项和输入计数。该工作流只允许 codex 分支，在 runner 自建临时目标，不需要用户提供真实凭据或操作真实主机授权文件。
4. Android APK 当前只作为可下载候选。后续具备设备时，按相同字体／fixture／视口先核验中文 IME、触控、44px 操作与键盘遮挡，再比较正确性合格路线的性能。Tauri iOS simulator 包和 Flutter 未签名 iOS 构建均不能冒充手机可安装测试包。

[Flutter 候选 run](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094396) 与 [Tauri run](https://github.com/Luck9Star/herdr-pocket/actions/runs/41047398458) 均已完成且成功，五端构建全部通过。Tauri 包的 Rust 适配器与第三轮 `d15da12` 的 Git blob 相同；包仍按各自 source SHA 归档。最终 job 状态经独立复核，见[交付核验](evidence/mobile-remote/delivery-checks.json)。

| 平台 | Flutter 修补候选 `d15da12` | Tauri `4b78b6b` | 运行边界 |
| --- | --- | --- | --- |
| Android | [构建通过 · 测试 APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094396/artifacts/12974335322) | [构建通过 · arm64 测试 APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/41047398458/artifacts/12973202706) | 两包已下载验 SHA；未安装真机 |
| iOS | [构建通过 · 未签名构建](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094396/artifacts/12974065194) | [构建通过 · 模拟器构建](https://github.com/Luck9Star/herdr-pocket/actions/runs/41047398458/artifacts/12973266398) | 不能作为真机可安装包；运行未验证 |
| macOS | [构建通过 · 测试 App](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094396/artifacts/12972579783) | [构建通过 · 测试 App](https://github.com/Luck9Star/herdr-pocket/actions/runs/41047398458/artifacts/12973041926) | 两包已下载验 SHA，并完成有限原生表单检查；GUI 真实接入未验证 |
| Windows | [构建通过 · 测试 bundle](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094396/artifacts/12973776064) | [构建通过 · 测试安装器](https://github.com/Luck9Star/herdr-pocket/actions/runs/41047398458/artifacts/12973871407) | 云端构建通过；安装／运行未验证 |
| Linux | [构建通过 · 测试 bundle](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094396/artifacts/12972704575) | [构建通过 · 测试包](https://github.com/Luck9Star/herdr-pocket/actions/runs/41047398458/artifacts/12972044909) | 云端构建通过；安装／运行未验证 |

[Flutter 下载与来源](evidence/mobile-remote/flutter-builds/README.md)、[Tauri 下载与来源](evidence/mobile-remote/builds/tauri-4b78b6b.json)保留包大小、完整 SHA、来源／fixture／字体／锁记录。测试 artifact 保留至约 2026-11-13，需要 GitHub 访问；未创建正式 Release、合并主分支或提交商店。未下载的 iOS／Windows／Linux 包仅记录 CI 与 artifact 元数据，不冒充本地安装检查。


## 下一步

本轮结果支持继续集成两条候选的只读链路，不足以选择 UI 框架或比较性能。官方 `terminal_view 0.5.0` 的组合重音缺陷仍由未修补 baseline 实际复现；可继续测试的 Flutter 包是带来源补丁的实验候选，不能把补丁通过写成上游版本已修复。

1. **手机看板与持续观察**：沿用 v2 页面，接入会话／pane 真实状态；持续 observe、主动取消与前台重新核验，覆盖有界缓冲、旧 generation 和迟到 full。布局只调整本地视口，不更改共享 PTY 尺寸。
2. **手机配对和设备密钥并行**：把已定义的扫码／helper 双端状态接到请求响应契约，云端隔离测试授权／撤销；分别验证 Android／iOS 安全存储。相机、真机授权和安装没有设备证据时保持未验证，手动临时私钥表单不成为产品存储方案。
3. **单目标完整终端输入**：先核实目标绑定和结果未知语义，再接逐键、组合键和草稿；断线不补发。用云端可控故障注入验证，随后补手机 IME／触控验收。
4. **手机多标签与恢复**：在单连接输入可靠后接入跨网络标签，分别验证焦点与 provider 隔离；桌面适配共享模型，分屏不挤占手机验证优先级。三网络仍按平台／并发完整矩阵推进。
