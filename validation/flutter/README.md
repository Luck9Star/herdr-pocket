# Flutter 终端验证壳

2026-10-30：验证壳包含本地 fixture、保留的 M1a 一次性 CLI，以及 **M1b 看板／持续只读 SSH 入口**，尚非完整产品。实际编译结果以 [Flutter Actions](https://github.com/Luck9Star/herdr-pocket/actions/workflows/flutter-validation.yml) 对应提交为准；手机字体、IME、选择、性能与三网络仍未验证；同一只读适配器的真实 SSH 证据限于下述云端隔离 loopback，不代表手机或 GUI 远端验收。

## 固定输入与边界

- Flutter **3.47.9**，源码提交 `c197ca5199e9ee5661e865596c9c07294dfab51c`；终端 `terminal_view: 0.5.0`，MIT。
- 两路线共用 [`../shared/fixture.json`](../shared/fixture.json)、同一 TTF 与 4096-byte 负载块；80×24 cells、14px 字号。手机视口 390×844，桌面 1440×900；同设备和系统字体回退仍须人工记录。
- 输入接收端只有本地有界字节记录器。UTF-8 hex 是“已交给本地 sink”，不是 SSH 已发送或命令已完成。
- 每个焦点/模式 epoch 重建终端输入连接，并重新显示 fixture full，以阻止旧 IME 回调进入新焦点。**因此当前壳不保留模式切换前的滚动历史**；这是需要真实流接入后消除的验证壳限制，不是产品设计。
- `autoResize: false` 且没有远端 resize 入口；窗口/键盘变化只改变可见空间。
- 输出队列上限 65536 bytes；溢出丢弃本轮观察并等待显式新 full，不带损坏画面继续输入。负载消费计量为解析器提交，不代表 GPU 完成绘制，不能据此比较整 App 性能。
- 默认 fixture 模式不建立网络。远端入口仅使用用户显式提供的内存测试私钥与预期 host key，不读取 SSH 配置、私钥文件或 agent，不修改主机授权。

## 云端构建

工作流先在 Ubuntu 上生成临时平台工程、解析一次依赖锁并运行 analyze/tests，再让五端构建任务下载**同一个 lock**并使用 `--enforce-lockfile`。应用 `pubspec.lock` 已从 run 40982743142 取回并核对 terminal_view 归档 hash 后落库；构建脚本使用该锁并 `--enforce-lockfile`。原离线基线锁 SHA256 为 `5b3979bec9c6487bb79f9bba82e66908fe735248923aeced14568cb101c9fa99`；M1a 新增依赖锁已在 [run 41046472225](https://github.com/Luck9Star/herdr-pocket/actions/runs/41046472225) 的准备／解析步骤通过，并在 [run 41048094396](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094396) 继续使用同一锁与候选逐依赖校验。首轮错误模板锁已排除，见来源记录。

平台脚手架只在 runner 临时目录生成，未将完整 SDK/平台模板安装到本机。`ci.py bootstrap` 在非 GitHub Actions 环境拒绝执行。

| 产物 | 安装/验证范围 |
| --- | --- |
| Android debug APK | 开发签名，仅测试；下载安装后才能确认设备运行 |
| iOS device `.app` | `--no-codesign` 编译产物，**不能直接安装真机**；还缺签名与实际设备 |
| macOS debug `.app` | 测试构建；未公证，实际启动和门禁提示待验 |
| Windows Debug 目录 | 需对应运行时，启动待验 |
| Linux debug bundle | 需 GTK 及目标 ABI 环境，启动待验 |

每个包附源提交、Flutter 提交、fixture/lock/产物 SHA256 与范围说明。Apple/Linux 使用 tar 保留 framework 符号链接与执行位。不会发布 release、合并 main 或提交商店。

已具备 SDK 的开发环境可手动复跑（没有 SDK 时直接使用 Actions）：

```sh
python3 validation/flutter/tool/ci.py prepare --destination /tmp/herdr-flutter-probe
cd /tmp/herdr-flutter-probe
flutter pub get
flutter analyze
flutter test
flutter run
```

目标目录必须不存在，脚本拒绝覆盖。重新跑用新的临时路径。

## 同设备人工测试

1. 下载相同源提交两路线产物，记录设备、系统、字体 SHA、输入法/键盘、视口。查看默认观察，输入键不得增加 sink 计数。
2. 点击“逐键”，使用真实中文输入法组合/取消/提交；组合期间 sink 不增，提交后 UTF-8 只出现一次。依次输入共享 `inputCases`，比较 hex。
3. 测试 Esc、Tab、方向、Ctrl-C/D、回车、硬件组合键。当前仅记录字节；vim/top 等真实 TUI 待 SSH 链路接入后测试。
4. 长按拖选、复制选区；点击“粘贴”或 Ctrl/Cmd-V，确认预览、取消和发送；草稿发送不额外加回车。手机键盘展开/收起，检查 80×24 契约未改变。
5. 中文组合期间切换标签/焦点/模式，提交不得进入新目标。宽度 ≥960 可开启本地分屏；窄窗只显示当前目标。
6. 隐藏后返回，输入保持禁用，点击“获取新 full”再显式逐键。注入未知/断线，恢复后先人工核实，确认 sink 计数没有自动增加。
7. 跑“1 MiB paced”；再注入“慢消费者 / 溢出”，确认 peak ≤65536 且恢复前不可输入。结果记录到共享矩阵，分别记构建、安装、运行和设备测试。

## 尚未具备

三网络原生桥、真机性能采样、手机配对及加密迁移仍未实现。M1a 已新增真实 SSH 只读适配源码，下述独立 CI 与设备结果才决定其验证状态。它们不能因本壳编译或单元测试通过而改为“已验证”。`terminal_view` 的 Unicode 宽度表、emoji grapheme、SGR 支持与系统 fallback 需运行同 fixture 后判定；没有预先认定其优于 xterm.js。
# 组合字符渲染诊断

Mac GUI smoke 发现分解重音 `e\u0301 A\u030a n\u0303` 看起来只有基字符。固定 `terminal_view 0.5.0` 源码中 buffer 将零宽字符存入 `getCombined`，`getText` 保留它们；`TerminalPainter._paintLineForeground` 的 ASCII 批处理却只采集基字符，未检查/传递 combined。新增 `diagnostic/combining_render_test.dart` 用同一字体、真实 buffer 和 painter 写入输入/复制 API codepoints、cursorX、两张 PNG 与像素对照 JSON，直接验证该假设。

诊断在独立 `render-characterization` CI job 中运行；可见重音与基字符像素相同时 job 必须失败，不能称字符正确性通过。五端包构建不依赖此诊断 job，便于继续设备比较。源码检查/目视现象不替代 CI 诊断结果；该诊断也不等价于原生剪贴板或系统 IME 验证。尚未对上游做补丁或改换终端引擎。

## 可追溯的组合重音修复候选

默认仍使用未修改 `terminal_view: 0.5.0`，原始失败证据保留。`patches/` 与 `tool/candidate.py` 提供显式实验分支：官方归档与补丁 hash 校验后，仅在新建 CI 临时工程启用 path override，不修改 pub cache。候选锁必须通过逐依赖基线比较；候选包附来源 manifest、LICENSE 和 NOTICE。

修复涉及 ASCII 批处理分流、选区和 block cursor 的 combined 传递，不改输入、parser 或列宽。[修复说明与来源](../../docs/evidence/flutter/2026-10-30-combining-repair.md)；真实绘制回归位于 `regression/combining_patch_test.dart`。构建和测试结果需以独立候选工作流为准，不能把本地脚本检查当作已修复证明。

## Penpot v2 视觉接线（2026-10-30）

验证壳现在读取两路线共享的 [`design-tokens-v2.json`](../shared/design-tokens-v2.json)：靛蓝操作色、浅色应用面板、深色终端，以及独立的状态文字色。桌面增加主机／会话侧栏，手机保留标签与模式入口；诊断操作集中到“验证工具”，发送结果未知的锁定和人工核实入口保持常显。此处是已认可视觉方案的离线适配，不是完整手机看板、配对或远端产品闭环。

两壳显式使用相同 16 色 ANSI 工程基线；JSON 将它与 Penpot 实际 tokens 分开记录。fixture 字节、固定 Nerd Font、14px 和 80×24 不变。布局收窄时只保留当前目标，隐藏的分屏标签恢复仍需要新 full；布局和键盘不发送远端 resize。极小或键盘占用后的视口允许工作区整体垂直滚动，保留终端与发送控件可达，不通过负尺寸 Flex 或远端 resize 硬塞布局。包 manifest 新增视觉 token 文件 SHA256。

新增 `test/probe_ui_test.dart` 从实际控件驱动未知恢复、隐藏标签与窄屏切换，并检查 320×640／键盘 260px／1.3 倍 UI 字号下的布局和真实 terminal 几何。CI 保存的 `probe-results/ui-v2` 是 **headless widget 布局证据**，系统文字可能使用测试 fallback 字体，不能代替原生 App 视觉、真实输入法或触控验收。候选工作流继续生成带受控 terminal_view 修复的五端测试包；普通 baseline 工作流仍使用未补丁的官方 0.5.0，其已知组合绘制失败不可与候选包混用。

手工步骤沿用上文：负载、故障注入和 UTF-8 记录现在位于“验证工具”；刷新图标是“获取新 full”，未知状态在 fresh full 后仍需显式“人工核实未知”。仅切换模式、标签、布局或刷新不得增加本地接收次数。

## M1a · 手机手动只读接入

以下保留一次性快照阶段的入口和预算说明；当前GUI已采用下方M1b看板／持续观察，M1a一次性CLI继续保留。

顶部具名“远端只读”进入独立页面：连接目标 → 主机身份核验 → 内存临时凭据 → 显式确认 → 读取一张真实远端完整画面。手机表单可垂直滚动，连接按钮至少44px；连接期间字段锁定，任何编辑清除确认。成功后明确显示目标、获取时间和“连接已关闭／非实时”。取消、离开页面或应用暂停都会使本次 generation 失效；没有自动重连、远端输入或 PTY resize。原 fixture 逐键／草稿与远端路径隔离。

此实验仅接受未加密 OpenSSH Ed25519 私钥（隐藏单行输入可粘贴完整 PEM，保留边界并在内存恢复换行），不读取或发现磁盘私钥／SSH agent，不保存或输出凭据。Dart 字符串由运行时管理，清空字段不是可证明的内存擦除；设备安全存储、长期凭据和相机配对仍后置。

`remote_adapter.dart` 与 `tool/remote_probe.dart` 使用同一纯 Dart 适配器。固定 `dartssh2 4.1.0`（MIT）和 `pointycastle 4.0.0`，新增传递包锁为 `asn1lib 1.5.8`、`pinenacl 0.6.0`；归档、hash、原始许可证见 [`remote-dependencies.json`](remote-dependencies.json)、`licenses/`。Context7 先 `library dartssh2` 再 `/vicajilau/dartssh2` 文档；PointyCastle同样先解析后 `/bcgit/pc-dart` 文档。4.1.0实际源码 `ssh_transport.dart:40-50` 明确回调 fingerprint 是 UTF-8 `SHA256:<无padding base64>`，并非原始32字节digest。禁止省略回调、跳过签名或退回其他认证方法。

目标绑定限于已核实 herdr 0.9.5 / protocol22：reviewed socket 必须符合 `/<XDG_CONFIG_HOME>/herdr/sessions/<显式非default会话>/herdr.sock`，只读 `session.snapshot` 核对RPC ID、`result.type=session_snapshot` 与嵌套 `result.snapshot` 的版本、唯一 pane ID 和稳定 terminal ID；固定 exec 使用从socket派生且严格shellquote的 XDG root、herdr绝对路径、同一session和snapshot解析的terminal ID。不存在会话或错误socket绑定立即拒绝，不回退默认会话。协议frame不echo目标身份，绑定依据是snapshot与上述固定命令，不宣称另有服务端目标签名。

仅打开 direct-streamlocal 并发送 `session.snapshot`；observe不申请SSH PTY或交互式SSH shell，也不暴露控制、takeover或任意命令入口。首frame必须full／ANSI／80×24／非负seq／有效base64和UTF-8；RPC单行上限1MiB，observe单行1MiB，stdout＋stderr合计2MiB、stderr另限64KiB。没有远端输出到系统标题、剪贴板、URL或输入的回调。原始连接future占用单一拨号预算，取消不能提前释放；迟到socket销毁、generation旧结果不发布。

CI CLI只允许运行器本次 `/tmp/hp-mobile-<run>-...` 中的合成配置、loopback非特权端口，报告只有布尔检查、计数和稳定错误码；配置和keys不能打包。由独立 `validation/remote-harness` 验证同一adapter，不安装本机SDK或连接真实主机。[第三轮候选 run 41048094396](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094396) 的20项常规测试、Linux与macOS headless绘制诊断已通过；[真实只读链路 run 41048094519](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094519) 已成功，设备、GUI实际远端操作和正式凭据仍未验证。构建与下载验SHA见[Flutter结果记录](../../docs/evidence/mobile-remote/flutter-builds/README.md)。前两轮失败保留；第三轮移除与异步SSH上传并发的 `channel.flush()` 后真实RPC通过，原始异常文本没有采集，不能声称已证实其具体消息。

在4.1.0中，channel flush只转发到底层transport flush，并不等待channel上传循环完成；本适配器以匹配RPC响应作为请求已送达的证据。取消后的迟到结果、剪贴板回复和旧cleanup均不得更新新页面状态。意外的库异步错误在独立Dart error zone内转为固定错误码，未知错误仍失败，不输出远端文本。相关API已按Context7先library后docs核对 [runZonedGuarded](https://api.dart.dev/stable/latest/dart-async/runZonedGuarded.html) 和 [IOSink](https://api.dart.dev/stable/latest/dart-io/IOSink-class.html)。

## M1b · 当前会话看板与持续只读观察

2026-10-30 源码增量（本机无 Flutter SDK；实际 Dart/Widget、真实 SSH 与包构建结果见[本轮记录](../../docs/13-mobile-dashboard-observe.md)）：审查接入 → 当前明确 named session 的真实 snapshot pane 看板 → 显式选择 pane → 持续只读观察 → 停止／断线旧画面。没有跨 session 自动发现；看板只显示实际 `pane_id`、`terminal_id`，不从屏幕内容推测任务状态。空 pane 保留为空，不借用默认会话。

`RemoteReadOnlyAdapter.observe` 在同一个经过 pin、认证和 snapshot 校验的连接中等待 `selectPane(generation,paneId)`，只把当前 snapshot 的唯一稳定 terminal ID 传给固定 observe 命令。`read` 保留 M1a 一次性 CLI 调用语义；空 `paneId` 只用于看板发现，不能在一次性读取时回退。两种路径都不提供输入、SSH PTY、resize、control 或 takeover。

首个完整合法 full 有绝对 10 秒预算，partial line 不重置它；之后允许合法静默，不因 idle 自动失败。后续 full/delta 均须 seq 恰好加一且不超出 JS 安全整数上限 `9007199254740991`，尺寸始终 80×24、encoding 为 ANSI。每行最多 1 MiB、解码帧最多 65536 bytes、stderr 累计最多 64 KiB；持续模式不设累计 stdout 字节上限。帧消费者逐帧 await，消费确认后才读下一帧，没有帧历史队列；远端入口 Terminal 上限 24 行，只保留屏幕，不累计 scrollback（离线实验室不变）。缺帧、重复、乱序、坏编码、版本不符、EOF 或超限终止整个观察，不跳过损坏增量继续。

取消先使 generation 失效，再关闭资源；单一连接／未决拨号预算保留到其真实完成。等待器每帧替换并移除，不向长期 cancellation future 累积监听器。退至任意非 resumed 生命周期、返回或 dispose 都停止；回前台不重连。旧画面保留更新时间与陈旧标记，重新接入需再次确认并主动提供内存凭据。手机表单和看板可纵向滚动，pane 选择与停止目标至少 44px；320/360/390px、放大字号及键盘占位是 headless 布局用例，不是触控／IME 真机证据。

同一 CI CLI 保留原 CLI case（harness 对应六项），并新增 `observe-positive`（至少3帧且含delta后主动取消）、`observe-cancel`（首full后主动取消）和 `observe-reconnect`（同adapter显式第二次调用，每次至少full+delta）。报告只增加 pane/frame/delta/connection 计数、lastSeq 和解码帧缓冲高水位；主动取消完成才标成功，不输出 pane 内容、公钥、配置或原始错误。固定依赖及锁未变化。API核查使用 Context7 library→docs：`/vicajilau/dartssh2` 的 execute/stdout/close 与 `/websites/api_flutter_dev` 的生命周期；版本行为仍以锁定源码和真实隔离 CI 为准。

固定 `dartssh2 4.1.0` 归档已按依赖清单 SHA256 复核：`SSHSession` stdout pause/resume 会传给 channel subscription，channel 暂停时不补发 window credit；底层预授信窗口固定 2 MiB、最大包 32 KiB，并拒绝越界包。此为 SSH 层额外有限接收预算，未混入只报告解码帧的 `bufferHighWaterBytes`；单测或该源码核查不替代真实慢消费者实测。

## 设备身份配对 GUI（2026-11-05 源码）

顶部“设备配对”进入 `PairingPage`，原手动 PEM 入口改称“手动实验”。目标、公钥、账号和命名会话先审查，设备身份只通过 `DeviceKeys.create/public/sign/delete` 的 opaque handle 使用。公开 v2 请求交给主机审查；粘贴响应后同时显示实际响应账号、主机与设备指纹、授权／撤销、是否新增以及期限，再独立确认来源。响应仅到 `authorized-unverified`，主动进入冻结目标的只读连接页，再次审查后才拨号；同连接 pin 和 SSH 认证成功才进入 paired，随后 snapshot 看板要求明确选择 pane，接收 full／delta。

固定 `dartssh2 4.1.0` 归档 SHA256 `39359aceafcf5940b868249e3c9c6d86e4e0f989eec7417d033c943157c84c51` 已复核，其 `SSHIdentity.custom` 与 `await identity.sign` 原生支持异步 signer，无需依赖补丁／升级。设备路径没有 PEM 字段，私钥不进入 Dart。native 返回的64字节签名经 RFC4253 signature envelope 包装后供 SSH 使用；签名前后核验 generation，取消／锁定／错误 pin 都不能使用迟到签名或切换身份。

`ci.py prepare` 在新建临时工程接 Android MethodChannel，应用共享 `validation/pairing/native/android/device-keys.gradle`；四个Java源、Java17、BC1.86及MIT notice由共享脚本接线。Apple临时runner从共享 `DeviceKeys.swift` 加入同样四方法 channel，Swift采用现有 Keychain backend；注册没有系统存储副作用。Windows/Linux明确显示设备桥不可用并禁用创建，手动隔离实验保留。本机没有执行系统Keychain或Keystore；源码接线／编译不等于系统存储、锁屏、备份或手机运行验证。

取消、过期、重复或错绑定响应拒绝；未知授权不重放，匹配且经审查的撤销响应仍可关闭未知状态。请求和已返回handle在同进程保留：离开再进可明确删除原身份；创建后的public读取或清理未确认则保留已知handle，禁止重放创建。**跨进程配对元数据／handle目录恢复尚未实现**；native身份存在不等于GUI可恢复其记录。取消与本机删除均不声称撤销主机授权，不自动创建替代身份。

新增 `pairing_test.dart`、`device_keys_test.dart`、`pairing_gui_test.dart` 覆盖严格 UTF-8／2048byte／重复键／TTL、完整绑定和代际、SSH签名封装、锁定与真实Widget状态流程。memory double明确标为double，不作为SSH证据。 opt-in `test/pairing_gui_ssh_test.dart` 由隔离harness提供 `HERDR_PAIRING_GUI_CONFIG`（公开目标JSON路径）、`HERDR_PAIRING_GUI_DIR`（临时目录）和 `HERDR_PAIRING_GUI_TEST_KEY`（显式临时测试signer PEM路径）；真实Widget先原子写`request.json`，等待harness审查授权后写`response.json`，经实际控件完成只读连接、选pane、full／delta与停止并写脱敏`result.json`。此测试signer仅在test文件，生产没有私钥导入设备store或测试开关。是否实际通过以本轮云端日志为准。
