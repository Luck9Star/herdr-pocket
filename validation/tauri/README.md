# Tauri + xterm.js 验证壳

状态：2026-10-30，包含独立的 **M1b 远端看板／持续只读入口（保留 M1a 一次性 CLI）**与**离线终端/原生 IPC 实验室**。使用 xterm.js 6.0.0、Tauri 2.12.5 与固定 russh 0.65.0；没有设备安全存储、远端输入或 overlay 接线。当前实际云端/设备验收以 evidence 记录为准；编译或纯 Rust `SessionGuard` 测试不是 SSH 握手、herdr 或手机验收。

## 手机优先的远端只读入口

默认页按手机顺序审查目标、核验主机公钥、提供实验临时凭据，然后显式读取当前会话看板并选择pane持续观察。控件至少 44 px，360/390 px 单列，键盘仅改变本地视口。未提供任意命令、远端 resize、自动重试或输入发送。浏览器预览明确显示原生 SSH 不可用，并禁用连接，不返回假快照。

配置字段、host key 与凭据只保留内存；私钥采用 `type=password` 语义输入，禁用自动填充建议，提交时重建被单行控件移除的 OpenSSH PEM 换行。没有“显示私钥”按钮或私钥日志。编辑任意资料会清除核验勾选；连接中字段锁定。取消、切换到离线页或进入后台先失效 generation，再取消原生读取、清除私钥；保留的画面标记陈旧。JavaScript/IPC 内存不提供可靠擦除保证，明确只用于实验凭据，不声称安全存储完成。

[共享 Rust 适配器](../transport-rust/README.md) 对真实 key exchange 做 pin-before-auth，再经 direct-streamlocal 查询 snapshot，绑定配置根、命名会话和用户选择的稳定 terminal ID，读取80×24 full及连续delta。视图记录本地更新时间与观察状态，停止后明确陈旧；保留的M1a CLI在首full后关闭。remote xterm `disableStdin`，没有 onData 发送处理；OSC 52、OSC 8 被消费，链接激活无操作。与离线 fixture 输入/草稿/日志完全隔离。

本轮本机已执行前端单元测试/build、Rust transport tests 与 Mac native cargo check。只有独立 CI driver 的实际运行可证明 loopback SSH/herdr 正负例；手机触控、IME、安装、相机、三网络和远端完整输入仍未验证。

## Penpot v2 视觉接入

2026-10-30 将用户认可的 Tech Indigo / Slate 配色接入本壳：主操作、选中标签和活动焦点用靛蓝，终端背景使用 `#0B0F17`。从 `../shared/design-tokens-v2.json` 读取语义颜色、组件圆角与固定 16 色 ANSI 工程基线；与 Flutter 使用同一字节 fixture、字体、80×24 网格和选择高亮透明度。ANSI 16 色是共享比较约定，不宣称是 Penpot 导出值。

离线实验室的桌面侧栏与双分屏、窄屏单目标、三模式切换、草稿预览和未知结果恢复已有可操作布局。`view-state.js` 只控制可见状态和禁用原因，实际输入仍经 `ViewGate` 核验。获取新全量画面不会解开未知结果锁定；核实后仍需显式选择输入模式。验证工具默认折叠，实验室始终标注离线边界。扫码配对与三网络仍未接线。

[本轮浏览器验收](../../docs/evidence/tauri/2026-10-30-ui-v2.md)覆盖共享四视口和核心安全交互；这些截图来自 Mac 上的 Chromium 浏览器预览，不是 Android、iOS、Tauri 系统 WebView 或手机触控证据。

后续独立审阅发现 `45b96d6` 的窄屏截图仍展示已开启的“桌面分屏”按钮，虽然实际只有单目标。已在 `<900px` 的现有窄屏 CSS 中隐藏此入口；保留分屏选择，回到宽窗可恢复双视图，不改输入 gate。原浏览器截图、记录与 SHA 保留为修复前证据，不能据此声称这处后续修复已有原生运行验收。

## 本地轻量检查

在本目录，使用 Node 22.22.2（或已安装且满足 `engines` 的兼容 Node）与已有 Rust 1.96.0：

```sh
npm ci
npm test
npm run build
cargo test --locked --manifest-path core/Cargo.toml
cargo test --locked --manifest-path ../transport-rust/Cargo.toml
npm run dev
```

浏览器访问 `http://127.0.0.1:1420`。浏览器预览不代表 Tauri 系统 WebView，更不代表手机真机。无需为这些检查安装 Flutter、Android SDK、Xcode 或 Visual Studio。原生 App 构建交 GitHub Actions；只有已具备完整目标工具链时才本地运行 `npm run tauri -- icon icon.svg` 和 `npm run tauri -- build`。

## 当前可执行

- 同一字体、80×24 fixture、ANSI 与备用屏幕；观察、逐键、目标独立草稿、辅助键、粘贴预览、选区复制入口。
- 手机标签、桌面双视图、明确单输入焦点。窄于 900 logical px 退为单可见目标；字体/网格保持固定，横向滚动查看。未实现自动拟合字号，布局和软键盘从不发远端 resize。
- 旧 generation/epoch、迟到 IME 目标、隐藏恢复、结果未知与 UTF-8 输入上限在 gate 中检查；隐藏/回前台后需主动取得 full，并回到观察。原生键盘/IME 是否在每个系统按预期发事件仍需真机。
- 1 MiB 负载在浏览器走同一字节 fixture，在原生壳通过 Rust `Channel<Response>` 发送原始二进制，xterm write 消费回调后才 ack。每流 65,536 bytes、总计最多两个流；取消旧 lease。
- Rust 不向 JavaScript 提供通用文件、shell、SSH agent 或 PTY resize 命令，前端不加载远端页面/字体。`remote_read_once`、`remote_observe`、`remote_select`、`remote_ack`、`remote_cancel` 仅用于经显式审查的 SSH 只读目标；固定可执行路径和协议边界见适配器说明。

输入记录限最近 100 条，仅供测试；不要在验证壳中粘贴真实秘密。记录“本地捕获”不代表服务端接收。草稿为内存状态，退出不保存；配对公开请求由人工转交主机操作者，生产 helper 与加密配置迁移尚未接入。

## 云端测试包

[工作流](../../.github/workflows/tauri-validation.yml) 仅在 `codex/**` 分支相关改动或手动触发运行，不创建 Release、不合并、不调用商店。固定 JS 依赖 `package-lock.json`、Rust `Cargo.lock`、Rust 1.96.0、Node 22.22.2；外部 actions 固定提交 SHA。runner 镜像随 GitHub 更新，实际镜像/工具链写入 manifest。

| 构建目标 | 预期 artifact | 边界 |
| --- | --- | --- |
| Android arm64 | 临时 debug 签名 APK | 可用于侧载测试；不能保证跨 run 原地升级，未安装即未验证 |
| iOS arm64 simulator | unsigned simulator `.app`/archive | 仅模拟器构建；没有真机签名/账户，不能当作手机安装包 |
| macOS runner 架构 | 未签名 `.app.zip` | Gatekeeper/签名/公证和实际运行未验 |
| Windows x64 | 未签名 NSIS 安装器 | 需 WebView2；签名信誉/目标系统运行未验 |
| Ubuntu 24.04 x64 | `.deb` | 需相应 WebKitGTK 运行依赖；不外推其他发行版 |

每个 artifact 同带 `build-manifest.json`、`SHA256SUMS`、共享fixture/字体许可及锁文件；v2 manifest 另记录 `designTokensSHA256` 和视觉基线名称，M1a 另含 `remoteContractSHA256`、`transportSourceSHA256`、transport Cargo.lock 与只读行为边界。工作流失败仍上传诊断材料；**必须看 manifest 的 buildOutcome 和真实安装文件，不能把存在 artifact 当构建成功**。保留 14 天，下载需要 GitHub 仓库读取权限。

## 验收与已知缺口

使用[共享步骤](../shared/README.md)和[结果模板](../shared/result-template.json)，同一设备先正确性、再性能。当前合成备用屏幕不替代 vim/htop/herdr TUI；终端组件的 SGR/列宽正确性、中文 IME/触控复制、后台生命周期、真实 SSH/herdr、三网及并发均保持未验证。

终端 full 恢复会销毁并重建 xterm 实例，以隔离旧异步写入；此壳不保存完整滚动历史或隐藏期间历史。移动系统可能缺少 `navigator.clipboard` 权限，预览框支持系统粘贴；这不是已完成的五端剪贴板适配。native Channel 延迟/吞吐和整 App 内存必须在原生包中测，不使用浏览器数字判胜负。

来源与本地执行证据：[2026-10-30 核查](../../docs/evidence/tauri/2026-10-30-sources.md)。

M1a 新查询：Context7 `library xterm.js` → `/xtermjs/xterm.js` → `docs` 核实 read-only、`parser.registerOscHandler` 与 `linkHandler`，再核对已安装固定 xterm 6.0.0 的公开实现；parser API 不需要启用 proposed API。Rust/herdr 固定来源见[适配器记录](../transport-rust/README.md#api-与协议来源)。

## M1b 持续观察候选

远端入口在核验后只列出同一次 snapshot 的 pane/terminal ID；用户选择后启动只读观察。首 full 后的每帧需严格连续，原生到页面一次仅允许一帧，xterm 渲染完成后才发送 ack；异常、断线、停止或后台进入后标记画面陈旧，不自动恢复。80×24 是本地观察视口，窗口尺寸变化不发共享 PTY resize。隔离云端真实SSH连续流已18/18通过（两路线各9项），浏览器布景检查另记；对应源码、最新构建与未验范围见[M1b记录](../../docs/13-mobile-dashboard-observe.md)。手机触控/IME、原生GUI实际远端接入和设备生命周期仍未验证。

## 配对 v2 与设备签名接线（实验）

远端入口可显式选择设备配对：先独立核对账号与主机公钥并生成公开请求，再人工粘贴响应、预览、单独确认来源，最后再次审查连接资料并手动连接。响应只绑定请求，不能证明主机身份；实际 SSH 先验证预期公钥，再由绑定该请求的本机句柄签名，认证后进入既有 pane 看板。取消或删除本机身份不会撤销主机授权；授权未知时仍须向主机核查。拒绝响应不会消耗请求，已接受授权的重放、错配、过期、签名错误与迟到结果被拒绝。没有自动连接或重放。

Linux/macOS 的 signer 是明确标示的**仅进程内测试身份**，退出消失，不是系统安全存储。Android 经注册的原生桥使用共享 Java 设备密钥实现；iOS 使用共享 Swift CryptoKit Ed25519 实现，种子保存在 `WhenUnlockedThisDeviceOnly` Keychain，签名在软件中执行，**不是 Secure Enclave 签名**。签名材料及本机句柄只在原生层使用，页面只得到公开请求和指纹；找不到原密钥或公钥不匹配时不会重建。Windows 的设备配对仍 fail closed。仍可使用原有手动实验私钥入口。此接线不表示系统密钥存储、锁屏/重装或 GUI 已运行验证。

Android 云构建在 `tauri android init` 后运行 `scripts/wire-android.py`，将 Tauri 插件复制到生成工程，并应用共享 `device-keys.gradle`（Java 17、BC 1.86 和许可证 notice）；生成工程不入库。本机不安装 SDK。移动平台运行、系统存储、设备锁定行为、桌面 GUI 到隔离 SSH 的实际完整流程均须以独立运行记录为准，不能从编译或单测推断。

iOS 构建在 Cargo build script 中引用固定 Tauri crate 的 Swift API，并从仓库共享 Swift 源在临时构建目录生成静态 Swift 包，无需修改生成的 Xcode 工程；`Info.ios.plist` 提供相机用途说明。相机返回的仅是待人工审查的公开响应，取消和权限拒绝均可继续手动导入。在有 Swift 命令行工具的 macOS 上执行 `python3 test/ios_wire_test.py` 可运行 plist/注册接线检查、无系统 Keychain 的 CryptoKit 内存替身和 Swift 接口桩类型检查；这些检查不替代 iOS SDK 链接、模拟器或真机验证。
