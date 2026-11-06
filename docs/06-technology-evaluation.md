# 技术栈复评与 A/B 定案门槛

> 2026-10-30 执行增补：核心 Penpot 原型、两路线验证壳与云构建已推进，macOS 有有限原生 smoke；当前不足以锁定框架。真实结果、构建失败、15格单网络与20格并发矩阵见[验证记录](09-prototype-validation.md)。下文保留原评估／里程碑规则。

核查基线：**2026-10-29**。本页面向实现者，记录如何选择 UI、终端和协议核心；当时依据是官方文档、发布记录与源码，**未包含本项目原型或设备结果**。2026-10-30的新增实测以上方验证记录为准，仍无整App公平性能结论。此前 Flutter 单栈方向重新开放，演进见 [ADR-0001](adr/0001-single-flutter-stack.md)。

## 1. 当前结论与已定范围

用户已确定**手机优先、桌面紧随**。Flutter 保留为第一验证候选；**Tauri 2 + xterm.js + Rust 核心**进入同规格 A/B，作为主要挑战者。优先验证 Flutter 是排期选择，不是已证明其终端更正确或性能更好。Compose Multiplatform 是有效第二梯队，Qt 保留备选；首轮不同时制作四套完整产品。

五端、公开开源、首版只连接远端 herdr、三种进程内 overlay、Nerd Font/cell 正确性与输入可靠性均保持。Tailscale + EasyTier 是每个正式支持平台的核心必需，ZeroTier 同期集成；框架变化不能缩减 [ADR-0006 的十五格目标](adr/0006-three-overlay-providers.md)。

用户已确定：**五端首版都必须支持完整终端交互，手机也不例外**。手机以任务处理和辅助控件为默认交互层，同时提供显式进入的逐键输入、快捷键和 TUI 操作；草稿不能替代完整终端验收。默认观察、不自动接管共享 PTY、目标核验与未知写入不重放继续有效。

首版还包括**前台跨 provider 同时连接主机、多终端标签和桌面分屏**；手机切换标签，所有视图只有明确的当前输入焦点。Tailscale + EasyTier 并发是核心最低验收，声明 ZeroTier 支持时再验证 Tailscale + ZeroTier、EasyTier + ZeroTier 与三者同开；不外推任意同 provider 多身份。源码与测试渠道先行、逐步正式上架，签名、许可与支持矩阵条件保持。

首版接入范围已确定为**手机扫码配对、五端本地配置与加密导入/导出**，后台通知后置。框架还须验证手机相机扫码、受保护密钥与五端文件选择/加密库适配；资料 QR 不自动授权 SSH，加密文件不克隆设备身份。已选一次性主机 helper：主机端确认后添加手机专属公钥并提供撤销方式，无 GUI 的首次接入仍须实测闭环，详见 [ADR-0007](adr/0007-pairing-and-config-transfer.md)。

开源方向也已确定：**希望衍生改动继续开放源码**。具体许可证仍须结合组件来源、静态/动态链接、分发方式和兼容性审查选定，不据此自动选择 GPL/AGPL，也不作法律保证。

## 2. 候选与证据边界

| 候选 | 已核实事实 | 本项目判断与未知 |
| --- | --- | --- |
| Flutter + `terminal_view` | Flutter 官方列出五端，支持原生绑定；`terminal_view` 0.5.0 发布于 2026-10-14，发布者声明 MIT 与五端覆盖。 | 符合手机优先的首个验证路径；不能据框架支持或解析基准认定终端/IME 已过关。 |
| Tauri 2 + xterm.js + Rust | 核查 Tauri core **2.12.5**、xterm.js **6.0.0**、russh **0.65.0**；五端可通过原生后端/插件集成。 | xterm.js 的终端能力值得比较，但手机触控、输入与系统 WebView 差异是关键风险；尚不能判为更优。 |
| Compose Multiplatform | Android、iOS、Desktop JVM 在官方支持表中均为 Stable。 | 不按“iOS 实验态”排除；Kotlin/Native、JNI/JVM 的原生适配面及可用终端组合仍需验证，暂不扩首轮。 |
| Qt | 官方列出五端，具有 QML/C++ 路径。 | 原生库整合值得保留，但手机终端、输入与实际模块许可尚未证明比前两者省成本。 |
| React Native / .NET MAUI | RN Windows/macOS 由伙伴维护、Linux 属社区平台；MAUI 官方平台列表不含 Linux。 | 当前五端维护目标下不进入首轮；不是断言它们无法实现本项目。 |

官方依据：[Flutter 平台](https://docs.flutter.dev/reference/supported-platforms)、[Flutter 原生绑定](https://docs.flutter.dev/platform-integration/bind-native-code)、[terminal_view 0.5.0](https://pub.dev/packages/terminal_view/versions/0.5.0)、[Tauri core 2.12.5](https://github.com/tauri-apps/tauri/releases/tag/tauri-v2.12.5)、[xterm.js 6.0.0](https://github.com/xtermjs/xterm.js/releases/tag/6.0.0)、[russh 0.65.0](https://github.com/Eugeny/russh/releases/tag/v0.65.0)。Tauri CLI 与 core 独立发版，不用 CLI 版本代替 core 版本。

第二梯队依据：[Compose 平台稳定性](https://kotlinlang.org/docs/multiplatform/supported-platforms.html)、[Compose 系统兼容](https://kotlinlang.org/docs/multiplatform/compose-compatibility-and-versioning.html)、[Qt 平台](https://doc.qt.io/qt-6/supported-platforms.html)、[Qt 许可](https://doc.qt.io/qt-6/licensing.html)、[RN 外部平台](https://reactnative.dev/docs/out-of-tree-platforms)、[MAUI 支持平台](https://learn.microsoft.com/en-us/dotnet/maui/supported-platforms?view=net-maui-10.0)。这些是框架范围证据，不是本项目支持声明。

## 3. 将 UI 选择与协议核心分开

herdr 的 streamlocal RPC、无 PTY 的 observe exec/NDJSON、事件恢复和禁止写入重放都不依赖 Flutter。dartssh2 的 `forwardLocalUnix` 与自定义 `SSHSocket` 是可用起点，不构成 Flutter 独占理由。russh 0.65.0 同样有 `channel_open_direct_streamlocal`、session channel 的 `exec` 和接受 `AsyncRead + AsyncWrite` 的 `connect_stream`，可以承接统一 overlay 字节流。依据：[dartssh2 更新记录](https://pub.dev/packages/dartssh2/changelog)、[russh Handle](https://docs.rs/russh/0.65.0/russh/client/struct.Handle.html)、[Channel](https://docs.rs/russh/0.65.0/russh/struct.Channel.html)、[connect_stream](https://docs.rs/russh/0.65.0/russh/client/fn.connect_stream.html)。

Rust 核心可供 Tauri 使用，也可通过 FFI 供 Flutter 使用；Flutter 不自动锁定 DartSSH2。先以最小桥验证复用收益，再决定核心语言，不为语言统一额外引入一层。Host/session 身份、可信路由、generation/epoch、未知结果和资源所有权仍只有一套语义。

三网络中的 Go/tsnet、Rust/EasyTier、C/C++/libzt 都仍需五端构建、ABI、异步字节流、安全存储和生命周期适配。Tauri 的 Rust 后端不会自动消除 Go/C 库集成或 Heeler 的 Unix/Apple 假设；Flutter 的 FFI 也不会自动完成移植。Tauri 移动插件使用 Swift/iOS、Kotlin/Android，并经 C FFI/JNI 与 Rust 互通。来源：[Tauri 移动插件](https://v2.tauri.app/develop/plugins/develop-mobile/)、[三网络迁移边界](adr/0006-three-overlay-providers.md)。

russh 的 host key 回调必须实现既有信任规则，默认拒绝不能改成无条件接受；其默认功能含 `aws-lc-rs` 等依赖，不能宣传为没有原生构建负担。依据：[Handler](https://docs.rs/russh/0.65.0/russh/client/trait.Handler.html)、[0.65.0 Cargo 清单](https://github.com/Eugeny/russh/blob/v0.65.0/russh/Cargo.toml)。两条候选都须完成自定义流、exec、host key、取消及关闭的实际链路验证。

## 4. 终端与手机风险必须对称验证

Flutter 终端候选尚有具体缺口：`terminal_view` 变更记录称 0.2.0 停止绘制 SGR 4 下划线，0.3.2 修复 iOS 回车重复发送，0.3.1 修复 resize 后选区错行。旧缺陷被修复不表示当前版本仍失败，但这些都应进入回归 fixture；SGR 能力需明确验收。其基准只测解析/缓冲，不含绘制。来源：[terminal_view changelog](https://pub.dev/packages/terminal_view/changelog)、[发布页基准](https://pub.dev/packages/terminal_view/versions/0.5.0)。

xterm.js 6.0.0 声明支持 CJK、emoji、IME 和主流浏览器，但不是对每个手机 WebView 的验收。官方仓库的[触控支持问题 #5377](https://github.com/xtermjs/xterm.js/issues/5377)与[触控复制粘贴问题 #3727](https://github.com/xtermjs/xterm.js/issues/3727)在本轮核查仍开放；不能因桌面终端生态成熟就推断手机选择、滚动与软键盘已解决。这是风险证据，不是“移动端不可用”的结论。支持声明见 [6.0.0 README](https://github.com/xtermjs/xterm.js/blob/6.0.0/README.md)。

Tauri 使用系统 WebView：iOS/macOS 为 WKWebView，Android 为系统 WebView，Windows 为 WebView2，Linux 为 WebKitGTK。内核/系统版本与原生依赖进入测试和安装记录，不能按统一 Chromium 运行时估算。来源：[进程模型](https://v2.tauri.app/concept/process-model/)、[平台前提](https://v2.tauri.app/start/prerequisites/)。

两种引擎使用同一套[字体与 cell 契约](02-architecture.md#nerd-font字形与终端-cell)。xterm.js 加载字体后仍需测量 cell 和 fit；`rescaleOverlappingGlyphs` 不会替 Nerd Font/Powerline/emoji 解决宽度问题。Unicode 表或 addon 不能直接证明组合字符正确；6.0.0 的 grapheme addon 明示实验且尚未发布 npm，不作为已具备的稳定能力。依据：[终端选项](https://xtermjs.org/docs/api/terminal/interfaces/iterminaloptions/)、[6.0.0 grapheme addon](https://github.com/xtermjs/xterm.js/blob/6.0.0/addons/addon-unicode-graphemes/README.md)。

## 5. Tauri 流桥的最小验证设计

Tauri 官方不建议以 events 承载低延迟/高吞吐数据，Channel 提供有序流消息。候选设计由 Rust 解码 NDJSON/base64，再以 raw binary Channel 传终端块；不能把 `Vec<u8>` 的 JSON 数组序列化叫二进制零拷贝。Channel 的发送成功只表示分发，不能当作前端已消费。来源：[调用前端与 Channels](https://v2.tauri.app/develop/calling-frontend/)、[2.12.5 Channel 源码](https://github.com/tauri-apps/tauri/blob/tauri-v2.12.5/crates/tauri/src/ipc/channel.rs)。

**以下是客户端拟定设计，不是 Tauri 自带保证：**以字节预算限制在途块，使用 xterm.js `write` 回调返回消费额度；目标/视图身份、连接 generation 与 observe epoch 随块关联。WebView 卡住、重建或切目标时停止生产并清理，不能无限缓存、任意丢增量或让迟到块进入新终端。xterm.js 写入为异步队列，需实现端到端背压；参考[官方流控说明](https://xtermjs.org/docs/guides/flowcontrol/)。该桥是否足够高效须实测，不能只比较一次 IPC 调用耗时。

凭据保留在原生受保护存储，前端只使用受限命令与引用；页面和字体随 App 打包。终端输出按不可信数据处理，不能通过外部页面、输出控制序列或宽泛 native 命令扩大权限。既有[安全与输入契约](02-architecture.md)同样约束 WebView 路径。

## 6. A/B 产物与定案规则

先做 iOS、Android 真机的相同小闭环，桌面紧随验证构建、键盘/窗口与原生库覆盖；Windows 原生桥最小验证与手机 A/B 并行，避免推迟发现五端阻断项。每次记录精确版本、设备/系统、字体文件、Unicode 宽度策略与 fixture；未运行的格标未执行。

两条候选均优先由 GitHub Actions 的目标系统 runner 提供测试产物，native 库与 App 分层构建；云 CI 可行不作为任何 UI 框架独占优势。本地完整工具链按调试需要选装，设备验收仍使用对应安装渠道和真实签名条件。分别记录构建、签名/安装、渠道分发与真机结果，不把未签 iOS 包、模拟器运行或桌面编译计为手机 A/B 通过；细则见[云端构建与测试分发](07-build-and-release.md)。框架定案后再收敛正式流水线，不预先维护两套完整发行系统。

| 验证 | 两条候选共用的通过条件 | 否决或回退条件 |
| --- | --- | --- |
| 手机完整终端与辅助操作 | 同字体、cell/viewport、ANSI/full/delta 输出；实测逐键输入、快捷键/组合键、交互式 TUI、IME 提交、回车、粘贴、选区/复制与软键盘 resize；同时验证辅助键栏/草稿切换，核对 SGR、Nerd Font/PUA、CJK/emoji/组合字符。 | 丢字/重复发送、错误目标、关键属性缺失、光标列或选区损坏、核心触控操作不可用；不能用草稿输入成功绕过完整终端失败。 |
| 有界流与恢复 | 持续输出、慢消费、切 pane、后台恢复、视图销毁重建；队列有界、可取消、旧 epoch 不污染新画面。 | 无界积压、增量丢失后继续显示、取消泄漏或重连自动重发；组件或桥需调整。 |
| 多标签与桌面分屏 | 同机多标签、桌面可见分屏各有独立 epoch/VT buffer/viewport；切焦点和 IME 迟到事件不串目标，隐藏标签恢复新 full；本地布局不静默 resize 远端 PTY。 | 旧帧串画面、按键发错 pane、隐藏恢复仍用旧增量、一个视图阻塞全部视图，或用单终端结果代替并行场景。 |
| 跨 provider 并发 | Tailscale + EasyTier 同时连接并持续收发；单个 provider 取消/离网不终止其他 lease，总资源有界；声明 ZeroTier 支持时测试 TS+ZT、ET+ZT 与三者同开，重复 IP 有底层定向证据。 | 只支持顺序切换、资源无界、身份串用、连带关闭其他连接，或用 profile 标签冒充实际路由隔离；不安全的组合必须拒绝并说明。 |
| SSH 与 native 最小链路 | 错误 host key 被拒；自定义流完成 streamlocal 与 observe；手机链接 Tailscale/EasyTier 最小桥，记录 crypto/FFI 构建与安全存储边界。 | 只能依赖系统 VPN、无法关闭流、凭据明文兜底或平台库不可构建；不能由 UI 演示掩盖。 |
| 扫码与配置迁移 | 手机无本项目桌面 GUI 的资料获取/授权/连接；相机权限拒绝可恢复；五端加密文件预览与冲突处理，错误口令/截断/篡改不部分导入。 | QR 暗含长期秘密或自动信任，未说明公钥传递/授权前提，复制设备 identity，或导入后自动连接；不以静态解码演示替代闭环。 |
| 性能与维护成本 | 正确性通过后，在相同设备、字体、cell/viewport 与输出 fixture 测整 App 输入反馈延迟、帧表现、峰值内存和清理；Tauri 计入 WebView 及原生进程。 | 未设预算或超预算不能通过；不得拿 Dart 解析基准与浏览器绘制对比，未测不判胜负。 |

**定案规则：**先过正确性和原生能力门槛，再比较实测资源、输入体验以及为通过同一 fixture 所需的补丁/维护面。Tauri 若手机核心流程不退步，且终端正确性或维护成本表现出可复现优势，可取代 Flutter；两者均通过但无明确优势时保留 Flutter 的手机优先验证路径。两者均失败则调整终端或桥接组件，不降低可靠性要求。框架确定后更新 ADR-0001，并把最终依赖版本、预算与平台限制写入[路线图](04-roadmap.md)及支持矩阵。

许可单独设门槛：核查版本的 Tauri 为 MIT/Apache-2.0 双许可、xterm.js 为 MIT、russh 为 Apache-2.0；这些不覆盖原生依赖、字体及本项目再分发义务。用户希望衍生持续开源，允许进一步评估 Flutter 的 `xterm3` AGPL 路径，但仍须通过实际组件、链接/分发方式的兼容审查及完整终端实测；不因此自动更换候选或认定全部组合合规。最终许可证审查后确定，本轮不新增 LICENSE。来源：[Tauri 清单](https://github.com/tauri-apps/tauri/blob/tauri-v2.12.5/Cargo.toml)、[xterm.js 清单](https://github.com/xtermjs/xterm.js/blob/6.0.0/package.json)、[russh 清单](https://github.com/Eugeny/russh/blob/v0.65.0/russh/Cargo.toml)。

## 2026-11-06 手机闭环复评

Flutter 与 Tauri 使用同一提交、同一 API 35 AVD 配置和受控 SSH/herdr 目标，均通过“生成设备身份 → 审查 helper 响应 → 实际 SSH 认证 → 会话看板 → 选定 pane → full/delta → 主动停止”。两端用 AndroidKeyStore 包装本机 Ed25519 种子，临时 sshd 以实际接受的公钥指纹核对 GUI 候选。两种 debug 安装包和自动化变体分别标记来源。[证据与下载](15-mobile-gui-validation.md)

| 路线 | 已观察到的维护与正确性证据 | 仍需独立判断 |
| --- | --- | --- |
| Flutter | 目录记录类型和 Android 目录同步均发现并修正实际错误；独立原生签名探针通过验签和删除。修补过的 terminal_view 仍须维护组合重音回归。 | 真机 IME、选择/粘贴、TUI、设备休眠与终端性能 |
| Tauri | 原生目录锁曾阻断 Android 配对；改用平台可用的文件锁后，正式 WebView 路径通过设备身份认证和连续观察。iOS 模拟器包已经编译链接。 | WebView 逐键输入、手机相机、平台生命周期及 native bridge 的维护成本 |

首个只读手机闭环已有两条可运行路线，继续并行评估。下一关先验证安全输入在断线、目标切换和结果未知时的正确性，再比较同一设备上的性能。以上结果没有提供框架定案所需的真机 IME、字体、三网并发或长期运行对照。
