<a id="界面设计落实与普通-ssh-终端"></a>

# 普通 SSH 使用与平台验收

截至 2026-11-20，以合入 Windows Tauri 密码验收的 `b10d8acc` 为文档基线。查某个平台、客户端或认证方式时，以本页[验收矩阵](#普通-ssh-验收矩阵2026-11-20-更新)和各格的运行源码为准。每条结果只对应所链接的运行。[2026-11-15 界面对照与执行记录](evidence/design-parity-20261115/verification-history.md)

## 从首页选择接入方式

| 入口 | 需要什么 | 连上后看到什么 |
| --- | --- | --- |
| 普通 SSH | 标准 SSH 服务，账号密码或已有私钥 | 一条独立的交互式 SSH 终端（PTY） |
| 配对添加 | 已有远端 herdr 命名会话，设备身份经主机授权并独立核验 SSH 指纹 | herdr 工作台。默认观察，逐键或草稿输入另需满足能力与目标绑定检查 |

1. 在首页打开「添加主机 → 普通 SSH」，填写地址、端口和用户名，再选「探测并核对主机密钥」。
2. 通过服务器控制台或管理员独立核对算法及完整 SHA256 指纹，再明确确认。管理员可对服务端的公开密钥运行 `ssh-keygen -l -E sha256 -f /etc/ssh/ssh_host_ed25519_key.pub`。RSA 服务查对应的 `ssh_host_rsa_key.pub`。探测阶段没有发送账号认证信息。
3. 填写账号密码，或切换到「使用私钥认证」填入已有私钥 PEM。私钥加密时，再填私钥口令。连接完成后可在终端输入命令。
4. 主机密钥变化时，客户端锁定连接。先独立核实变更，再重新探测并确认。取消保留旧信任，确认新指纹后仍需主动连接。

普通 SSH 使用系统 TCP/DNS，可取消正在建立的连接，认证凭据仅用于本次连接。取消或断开后须重新填写凭据。keyboard-interactive、OTP/MFA 和自动发现本机 SSH agent 尚未覆盖。实际收到远端退出状态或信号时才显示「远端已报告结束」。主动断开根据本机关闭结果显示回执，失败后返回看板仍保留失败提示，未知结果的终端输入不自动重发。[Rust SSH](../validation/transport-rust/src/direct_shell.rs) · [Tauri 命令](../validation/tauri/src-tauri/src/direct_shell.rs) · [Tauri 页面](../validation/tauri/src/direct-ssh.js) · [Flutter 页面](../validation/flutter/lib/direct_ssh_page.dart)

<a id="2026-11-20-flutter-会话导航与断开回执"></a>

Flutter 切到看板、网络或设置时保留原连接和终端滚动位置。[普通 SSH 导航与断开回执](evidence/flutter-ordinary-main-delivery-20261120/README.md) · [两壳手机模拟器导航与软键盘](73-mobile-ssh-terminal-navigation.md)

<a id="普通-ssh-验收矩阵2026-11-18-汇总"></a>

## 普通 SSH 验收矩阵（2026-11-20 更新）

覆盖环境为 Android API 35 x86_64 模拟器、iOS 26.2 模拟器或受控原生桌面窗口，SSH 对端为临时回环服务。每格分别查看认证、换钥、终端和关闭。换钥 A/B/B/B 指首次探测 A、拒绝并取消保留 A、重探 B、明确确认 B 后才认证。原屏 OCR 核对本轮回显及校验词，实窗目检与驱动断言按证据标注。应用关闭、对端关闭和测试资源清理各看对应报告。

| 平台 | 客户端 / 认证 | 首次指纹与认证 | 同认证换钥 | 可见终端回显 | 断开与清理 | 验收来源 |
| --- | --- | --- | --- | --- | --- | --- |
| Android 模拟器 | Flutter / 密码 | 通过 | A/B/B/B 通过 | ADB 原屏 OCR | 主动断开、对端关闭、清凭据和受检资源 | [R4 原屏与清单](69-mobile-ssh-active-terminal.md#r4-最终同批验收) |
| Android 模拟器 | Flutter / 加密 Ed25519 | 错口令零认证，正确密钥认证通过 | A/B/B/B 通过 | Flutter 画面与 ADB 原屏 OCR | 主动断开、对端关闭、清凭据、剪贴板与资源 | [11-20 独立认证和换钥复验](evidence/ordinary-ssh-pem-reopen-20261120/README.md#第三批手机回执与-macos-交接) |
| Android 模拟器 | Tauri / 密码 | 通过 | A/B/B/B 通过 | ADB 原屏 OCR | 主动断开、对端关闭、清凭据和受检资源 | [R4 原屏与清单](69-mobile-ssh-active-terminal.md#r4-最终同批验收) |
| Android 模拟器 | Tauri / 加密 Ed25519 | 独立认证通过 | A/B/B/B 通过 | 换钥原屏 OCR，独立案驱动断言 | 主动断开、对端关闭、清凭据及五项资源 | [独立案 R2](72-mobile-ssh-auth-snapshot.md#r2-联合复验) · [换钥与重开复验](evidence/ordinary-ssh-pem-reopen-20261120/README.md#第二批加密私钥与主机换钥) |
| iOS 模拟器 | Flutter / 密码 | 通过 | A/B/B/B 通过 | 系统原屏 OCR | 主动断开、对端关闭、清理通过。R20 首页检查限普通案 | [R19 同源结果与原图](70-ios-ssh-host-key-rotation.md#r19-同源结果两壳通过活动标题与顶栏分离) · [R20](70-ios-ssh-host-key-rotation.md#r20-官方结果flutter-通过tauri-换钥冷启失败已由-r21-收口) |
| iOS 模拟器 | Flutter / 加密 Ed25519 | 错口令零认证，正确密钥认证通过 | A/B/B/B 通过 | 系统原屏 OCR | 主动断开、对端关闭、清凭据与资源 | [11-20 独立认证和换钥复验](evidence/ordinary-ssh-pem-reopen-20261120/README.md#第三批手机回执与-macos-交接) |
| iOS 模拟器 | Tauri / 密码 | 通过 | A/B/B/B 通过 | 系统原屏 OCR | 主动断开和夹具清理；R21 首页检查限普通案，断开后的凭据字段未单独复查 | [R21 定向复验](70-ios-ssh-host-key-rotation.md#r21-tauri-定向复验普通与换钥均通过) |
| iOS 模拟器 | Tauri / 手填加密 Ed25519 | 错口令零认证，正确密钥认证通过 | 待验 | 系统原屏 OCR | 主动断开、返回首页、清凭据与四项资源 | [R15 手填](evidence/ordinary-ssh-pem-reopen-20261120/README.md#第三批手机回执与-macos-交接) · [粘贴尚未证实](72-mobile-ssh-auth-snapshot.md#tauri-ios-加密私钥原生粘贴-r6-与-r7) |
| macOS 原生窗口 | Flutter / 密码 | 通过，R5 另证系统遮罩 | 待验 | `a5082d0` 本机实窗目检，独立对端核对输入 | 主动断开、对端关闭、清凭据。本机旧轮未发布逐项资源清单 | [本机实窗](evidence/design-parity-20261115/verification-history.md#本轮实际验证) · [R5 XCUITest](evidence/ordinary-ssh-pem-reopen-20261120/README.md#第三批手机回执与-macos-交接) |
| macOS 原生窗口 | Flutter / 加密 Ed25519 | 通过，R5 另证原生口令和摘要重开 | 待验 | 隔离 debug 包见中文 banner，服务端另证收 10 字节。R5 无终端原图 | 主动断开、对端关闭、清凭据与临时资源 | [本机私钥段](evidence/design-parity-20261115/verification-history.md#本轮实际验证) · [R5 XCUITest](evidence/ordinary-ssh-pem-reopen-20261120/README.md#第三批手机回执与-macos-交接) |
| macOS 原生窗口 | Tauri / 密码 | 通过 | A/B/B/B 通过，独立回环对端计数 | WKWebView 实窗目检，独立对端核对输入 | 主动断开、对端关闭、清凭据与临时运行目录 | [本机 WebKit 复核](70-ios-ssh-host-key-rotation.md#独立-macos-webkit-产品交叉复核) · [早期原生窗口记录](evidence/design-parity-20261115/verification-history.md#本轮实际验证) |
| macOS 原生窗口 | Tauri / 既有私钥 | 待验 | 待验 | 待验 | 待验 | — |
| Linux 原生窗口 | Flutter、Tauri / 密码 | 两壳通过 | 待验 | X11 应用区域或 WebKitGTK 视口 OCR | 主动断开、`peer_eof`、清凭据、返回首页与清理 | [同源六格 `3a8e655`](evidence/linux-ordinary-ssh-auth-matrix-20261120/README.md#同源六格矩阵3a8e655现行) |
| Linux 原生窗口 | Flutter、Tauri / 加密 Ed25519 | 两壳通过，错口令零认证 | 两壳 A/B/B/B 通过 | X11 应用区域或 WebKitGTK 视口 OCR | 主动断开、`peer_eof`、清凭据、返回首页与清理 | [同源六格 `3a8e655`](evidence/linux-ordinary-ssh-auth-matrix-20261120/README.md#同源六格矩阵3a8e655现行) |
| Windows 原生窗口 | Flutter / 密码 | 通过 | 待验 | Win32 客户区 OCR | 主动断开、`peer_eof`、清凭据、返回首页与四项清理 | [密码原件与复跑](evidence/windows-ordinary-ssh-password-20261120/README.md) |
| Windows 原生窗口 | Flutter / 未加密 Ed25519 | 通过 | 待验 | Win32 客户区 OCR | 主动断开、`peer_eof`、清凭据、返回首页与五项清理 | [私钥 R3 原件](evidence/windows-ordinary-ssh-publickey-20261120/README.md) |
| Windows 原生窗口 | Tauri / 密码 | 通过 | 待验 | Win32 客户区 OCR | 主动断开、`peer_eof`、清凭据、返回首页与受检清理 | [R3 原件](evidence/windows-tauri-ordinary-ssh-password-20261120/README.md) · [#58 已合入](https://github.com/Luck9Star/herdr-pocket/pull/58) |
| Windows 原生窗口 | Flutter / 加密私钥、Tauri / 既有私钥 | 待验 | 待验 | 待验 | 待验 | — |
| 实体 Android / iPhone | 两壳 / 密码及私钥 | 待验 | 待验 | 待验 | 待验 | — |

<a id="尚待独立补证"></a>

实体手机、系统输入法组字、生产 SSH 主机、真实跨网、长期运行和发布安装包仍须独立验证。Linux 系统密钥环在 [PR #59](https://github.com/Luck9Star/herdr-pocket/pull/59) 的 Linux herdr 配对草稿中，普通 SSH 使用本次输入的凭据。配对双连接及真实网络隔离见[桌面 S06](74-desktop-split-resize.md#已有-s06-运行范围)、[Linux 双网](65-dual-overlay-validation.md)和[Android 双网与共享节点](67-android-dual-network-startup.md)。

## 复跑与专题

- 普通 SSH 测试从正常首页进入，以独立服务端确认认证、PTY 和断开。Android 验收使用自建模拟器和 `adb reverse` 接入临时夹具，服务端需在驱动退出前确认连接关闭。[Android 工作流](../.github/workflows/direct-ssh-android.yml) · [Android 复跑说明](../validation/remote-harness/README-direct-ssh-android.md) · [Flutter 本地回环复跑](../validation/flutter/README.md#普通-ssh-回环验证)
- 换钥、终端可见目标和图片判据。[Android 换钥判据](68-android-ssh-host-key-rotation.md#同一目标的验收约定) · [Android 原屏与 OCR](69-mobile-ssh-active-terminal.md) · [iOS 密码换钥与底栏原屏](70-ios-ssh-host-key-rotation.md)
- <a id="3940-合入前普通-ssh-原生复验"></a>移动端指纹、私钥和焦点细项。[手机核验与认证](72-mobile-ssh-auth-snapshot.md) · [私钥收起和重开原件](evidence/ordinary-ssh-pem-reopen-20261120/README.md) · [#39/#40 三平台原生复验](evidence/ordinary-ssh-native-39-40-20261120/README.md)

## 界面对照与历史运行

- <a id="可下载的同源调试快照"></a>2026-11-15 CI 调试快照（`d925bd0`）保留 Flutter Android/macOS 与 Tauri Android/macOS/Linux 的工件内包名、架构及 SHA256。该 Tauri Android APK 只有 arm64-v8a。API 35 模拟器为另建的 x86_64 调试应用。工件下载受 Actions 保留期限影响。[五个包的来源与哈希](evidence/design-parity-20261115/verification-history.md#可下载的同源调试快照)
- <a id="s01s05-设计与可达性"></a>S01–S05 首页、观察、逐键、草稿与配对的 320／390／1200 宽度画面使用合成资料。[S01–S05 图组](evidence/design-parity-20261115/verification-history.md#s01s05-设计与可达性)
- <a id="s06-双侧界面与真实回环验收"></a>S06 双侧画面和 700 宽单侧对照使用合成适配器，真实 SSH/herdr 回环有独立报告。[S06 图组、计数与原报告](evidence/design-parity-20261115/verification-history.md#s06-双侧界面与真实回环验收)
- <a id="s19-macos-配置文件往返"></a><a id="s17-受理回执与-android-停止观察"></a><a id="s27-网络页界面增量"></a>S19 配置文件往返、S17 受理回执及 S27 网络页保留到达阶段、原图和夹具边界。[S19](evidence/design-parity-20261115/verification-history.md#s19-macos-配置文件往返) · [S17](evidence/design-parity-20261115/verification-history.md#s17-受理回执与-android-停止观察) · [S27](evidence/design-parity-20261115/verification-history.md#s27-网络页界面增量)
- <a id="easytier-linux-真实-overlay-链路2026-11-15"></a>Linux EasyTier 早期受控验收使用真实 overlay 和独立 SSH/herdr 回环。[EasyTier Linux](evidence/design-parity-20261115/verification-history.md#easytier-linux-真实-overlay-链路2026-11-15)

### 早期普通 SSH 验证

- <a id="本轮实际验证"></a>服务端测试、macOS 系统可访问性与原生窗口逐批结果。[macOS 与协议原记录](evidence/design-parity-20261115/verification-history.md#本轮实际验证)
- <a id="普通-ssh-android-设备验收入口"></a><a id="后续安卓与构建来源"></a>Android API 35 的首跑、修复及多版结果。模拟器调试构建与下载包有各自的工件。[Android 首批](evidence/design-parity-20261115/verification-history.md#普通-ssh-android-设备验收入口) · [Android 后续批次](evidence/design-parity-20261115/verification-history.md#后续安卓与构建来源)
- <a id="flutter-普通-ssh-ios-simulator"></a>Flutter iOS 26.2 的密码回环、历史失败及原图。[Flutter iOS Simulator](evidence/design-parity-20261115/verification-history.md#flutter-普通-ssh-ios-simulator)
