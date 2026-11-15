# 界面设计落实与普通 SSH 终端

状态：2026-11-15 原型验证交接。此记录覆盖普通 SSH、S01–S06 与 S27 的界面增量，以及 Flutter / Tauri Android 模拟器普通 SSH 验收；CI 调试 APK、公开 Release、手机真机和五平台运行须分别核对。历史 ADR 和此前 APK 的证据范围保持原样。

## 可下载的同源调试快照

以下五件来自源码 `a9afe9cdbb1f3809f7bb975f41b83705a4825510` 的 [运行 43708650075](https://github.com/Luck9Star/herdr-pocket/actions/runs/43708650075)：27 项成功、7 项按条件跳过。五件均已下载并核对 GitHub 外层 ZIP digest、CI 清单及内包 SHA256；下表哈希对应内包。这是 QA 调试快照，不等同公开 Release 或设备验收。

| 平台 / 路线 | GitHub 下载与内包名 | 实际架构 | 内包 SHA256 |
| --- | --- | --- | --- |
| Flutter Android | [工件 14159866197](https://github.com/Luck9Star/herdr-pocket/actions/runs/43708650075/artifacts/14159866197) · `flutter-android-debug.apk` | `arm64-v8a` / `armeabi-v7a` / `x86_64` | `80e8d93bf3d90f3a3ce0cf8458ef900ac11a2b8c84a6b8a7366015ca3461f904` |
| Tauri Android | [工件 14159224253](https://github.com/Luck9Star/herdr-pocket/actions/runs/43708650075/artifacts/14159224253) · `app-universal-debug.apk` | 仅 `arm64-v8a` | `f563370e34459f113bf8a7bc0b3869eb30e48df536dbd469e31e17cd520c81aa` |
| Flutter macOS | [工件 14159817543](https://github.com/Luck9Star/herdr-pocket/actions/runs/43708650075/artifacts/14159817543) · `flutter-macos-debug.tar.gz` | Mach-O `arm64` | `ee24e490dfbf9f6442d0a858904e04daf031c1ec4e26ec0dea105a89b2f6284a` |
| Tauri macOS | [工件 14160085140](https://github.com/Luck9Star/herdr-pocket/actions/runs/43708650075/artifacts/14160085140) · `herdr-pocket-tauri-probe.app.zip` | Mach-O `arm64` | `183b2d0eaee22209119734c5b230c16746e492170e9f6395411550735d477cc5` |
| Tauri Linux | [工件 14159857019](https://github.com/Luck9Star/herdr-pocket/actions/runs/43708650075/artifacts/14159857019) · `herdr-pocket-tauri-probe_0.1.0_amd64.deb` | Debian `amd64` | `24e421ef584ea0ca21414eca94473b1c1a9c8c0646766d4fa6fccb07818b4859` |

Tauri Android 文件名虽含 `universal`，包内仅有 `arm64-v8a`；下文的 API35 模拟器验收使用另行构建的 x86_64 应用，不是上表 APK。Flutter Android 的 manifest 主哈希对应工件内另一份 ZIP，APK 自身通过同工件 `SHA256SUMS` 核对。五件与清单保存在本地 `build/verification/a9afe9c/`。

云端 Linux Flutter 候选 [工件 14159955842](https://github.com/Luck9Star/herdr-pocket/actions/runs/43708650075/artifacts/14159955842) 为 556 项通过、5 项条件跳过，另有渲染 10 项通过。macOS 本机隔离候选 `d38aff4` 为 543 项通过、5 项跳过与渲染 10 项通过，另以合成 loopback 补跑普通 SSH 10 项；两批分开记账。此前 `d5ec372` 的 Tauri 在 Node 22.22.2 上 `npm test` 为 594 项通过、0 失败，`npm run build` 通过；helper 测试 15/15 通过；测试不替代设备运行。

历史下载：[d5ec372 同源五件](https://github.com/Luck9Star/herdr-pocket/actions/runs/43699318869) · [20ef361 同源五件](https://github.com/Luck9Star/herdr-pocket/actions/runs/43696926797) · [d38aff4 同源五件](https://github.com/Luck9Star/herdr-pocket/actions/runs/43688956564) · [bc43076 同源五件](https://github.com/Luck9Star/herdr-pocket/actions/runs/43683202816) · [79d2d00 Flutter macOS 独立包](https://github.com/Luck9Star/herdr-pocket/actions/runs/43692804010/artifacts/14153820575)。历史包的已核验文件保留于本地相应 `build/verification/` 目录；各次系统 AX 和设备结果见下文。

## 从首页选择接入方式

| 入口 | 前提与结果 | 身份和输入边界 |
| --- | --- | --- |
| 普通 SSH | 标准 SSH 服务器；密码或已有私钥；开启独立 PTY shell | 探测的公钥须独立核验并明确确认；密码/私钥只用于本次连接；关闭即退休本次会话 |
| 配对添加 / herdr 工作台 | 已有远端 herdr 命名会话；公开资料审查、设备独立身份、主机 helper 确认、单独 SSH 验证 | 授权响应不代替主机身份校验；默认观察，逐键/草稿还须满足现有保护能力和目标绑定 |

普通 SSH 不调用 herdr、Unix socket 或配对 helper，也不伪造 agent 看板。目前使用系统 TCP/DNS 路由；没有把内置三网或后台恢复当作已完成。主机指纹变化时停止，不自动接受替换；认证失败与取消不会保存本次秘密。Rust 的会话 ID、原始输出字节、递增序号与逐包确认隔离多会话；连接中可取消，结果不明的输入不会自动重发。

实现入口：[Rust 标准 SSH](../validation/transport-rust/src/direct_shell.rs)、[Tauri 命令](../validation/tauri/src-tauri/src/direct_shell.rs)、[Tauri 页面](../validation/tauri/src/direct-ssh.js)、[Flutter 页面](../validation/flutter/lib/direct_ssh_page.dart)。

首次使用普通服务器时，先填写地址、端口和用户名，再选择「探测并核对主机密钥」。探测未发送认证信息；通过服务器控制台或管理员提供的独立渠道核对算法和完整 SHA256 指纹，确认一致后再继续。例如管理员可在服务器上对相应的公开 host key 执行 `ssh-keygen -l -E sha256 -f /etc/ssh/ssh_host_ed25519_key.pub`；RSA 服务器核对对应的 `ssh_host_rsa_key.pub`。不要把本次未认证网络探测本身作为独立核验渠道。

密码路径填写服务器账号的密码；私钥路径选择「使用私钥认证」，填入已有私钥 PEM，若已加密则另填私钥口令。主机公钥与用户私钥是两种用途，指纹核验不会替代账号认证。只有本次目标已确认、认证字段有效时才可连接。取消或断开后凭据清空，重连须重新填写；主机 key 变化时先核实服务器是否确实换 key，再重新探测和明确确认，不能跳过校验。keyboard-interactive、OTP/MFA 和自动发现本机 SSH agent 尚不在此入口内。

## 本轮实际验证

| 证据层 | 已验证 | 范围限制 |
| --- | --- | --- |
| Tauri / macOS 原生 debug UI | 从“添加主机 → 普通 SSH”访问临时 loopback SSH；初次 Ed25519 指纹与夹具一致；确认后密码认证、`xterm-256color` PTY；更换 key 后旧 pin 被拒，重新探测并确认新 pin 后连接；键入 `hp-check` 看见绿色 ANSI `POCKET-SSH-OK`；最终原生复验还确认错误密码显示中文认证失败，正确密码后可输入；服务端记录 `pty xterm-256color (80,24)`、`resize 106 24`、`check_received`、`closed`；进入设置再返回保留同一会话，断开后输入禁用并须重填凭据 | 通过原生窗口无障碍操作；本次原生 UI 用密码，未据此声称私钥 UI 或手机通过。CUA 截图保留在本次聊天，不把下方 Widget 图冒充原生截图 |
| Flutter / macOS arm64 原生 debug UI | `a5082d0` 云构建归档下载后，改为唯一 bundle ID，保留六项 entitlement 并本机 ad-hoc 重签隔离配置；从生产首页进入普通 SSH，核对 RSA SHA-512 算法与 SHA256 指纹、密码连接，通过实际物理窗口输入 `hp-check` / Return，看见绿色 `POCKET-ANDROID-SSH-OK`，点击断开后凭据清空。独立服务端确认两次连接全部关闭，PTY 从 80×24 改为 95×33 | 实际 Mac 窗口；回显沿用夹具共用标记，不是 Android 运行。修改 bundle ID / 本地重签的 debug 包，该次未测试私钥；不代表原签名发布包或系统公证验收 |
| Rust 实际 SSH / OS PTY | 7 项常规 shell 测试：临时 Ed25519 和 RSA SHA-256/512 server、密码/私钥、真实 `/bin/sh`、双向 ANSI 字节；真实 `stty size` 从 24×80 改到 37×117；双会话隔离、退出码 7；pin/auth/PTY/shell 失败；握手/认证/活动会话取消；精确输出 ack、排队输入回执超时退休与清理；RSA 用户签名核对与 RSA/SHA1 服务端在认证前拒绝。另显式执行 RSA-only Paramiko 互操作 1 项。完整 Rust 库 103 项与 CLI 1 项通过 | 自建 loopback、临时密钥和隔离 HOME；不访问个人 SSH 凭据或真实主机。其他 key 算法、keyboard-interactive/MFA 未实测；外部 Paramiko 用例默认 ignored，已单独补跑 |
| Flutter 普通 SSH runner | runner 执行 5 项：显式指纹确认与空凭据门槛；密码认证、实际 PTY/shell 与后台断开；旧 pin 在认证前拒绝；加密私钥认证；正常导航返回与销毁 | [runner](../validation/flutter/tool/direct_ssh_fixture_runner.py) 与[测试夹具](../validation/flutter/test/direct_ssh_fixture.py)；不属于手机真机或原生 Tauri 证据 |
| Flutter S01–S05 与安全回归冻结批次 | Flutter 3.47.9 临时工程：完整套 **521 passed / 4 skipped / 0 failed**；`flutter analyze --no-pub` 无问题。新增 320/390/1200 宽度的配对步骤、指纹可达和三模切换不发送字节检查；选择文本与字体诊断仍撤销旧输入，关闭后不恢复发送 | 使用合成 adapter 的实际 Flutter Widget 引擎渲染；4 个跳过项不计通过；不覆盖随后独立开发的 S06 |

Tauri 原生 debug app 使用隔离标识 `dev.herdrpocket.acceptance20261115`。构建日志留在本次本地运行目录；这些原生 UI 检查不构成发布验收；已有可下载的 CI 调试 APK 须核对对应源码 SHA，不能当成公开 Release 或手机真机通过。Rust 复核入口为 `cargo test --locked --offline --manifest-path validation/transport-rust/Cargo.toml direct_shell`；Flutter 准备与 runner 用法见[验证壳 README](../validation/flutter/README.md#普通-ssh-回环验证)。

Flutter macOS 归档来源为 [Actions 43669066267](https://github.com/Luck9Star/herdr-pocket/actions/runs/43669066267)、工件 `14143937188`，`flutter-macos-debug.tar.gz` 的 SHA256 已核对为 `6212b8523c7fcec5b8bbd5a688117791a42f43e046a1902065205051c2bb3561`。本机操作的[服务端脱敏报告](evidence/design-parity-20261115/flutter-macos-native-a5082d0.json)只含认证、PTY、输入标记、关闭布尔与尺寸计数；操作截图保留在聊天，不将 Widget 图冒充原生窗口图。

另以本机隔离 Flutter candidate bundle `dev.herdrpocket.axcandidate` 测试私钥入口：连接只监听 `127.0.0.1` 的[合成 SSH 夹具](../validation/flutter/test/direct_ssh_fixture.py)，界面显示的 RSA `rsa-sha2-512` 主机指纹与独立计算一致；明确确认后，使用有口令保护的临时 OpenSSH Ed25519 用户私钥登录，看到中文 banner 并发送 `key-ui-ok` 与回车。服务端记录公钥认证、PTY 80×24 → 95×33 和预期 10 字节；客户端明确断开后，表单中已无私钥或口令，临时目录已删除。该隔离包的 Dart kernel SHA256 为 `a3fe947ec0b350b66dc561b1a7687bfcec886466a38a10fe5a4ee93a39d17c7f`；其生成工程的 `direct_ssh_page.dart` blob `91fe77a24d9431d964d4c8468ca8efed7f30a1d5` 与分支同文件一致，不能据此声称整个源码或云端包一致。此项为本机 debug UI 和合成服务验证，不包含手机、其他私钥格式或正式发布包。

同一类隔离 Mac AX 检查发现：私钥口令字段获焦时，调查工具从系统可访问性树中的普通文本输入节点读回了合成测试口令；焦点移至其他字段时还观察到值挂在错误输入组。测试值只在内存中使用且已清理，没有使用个人秘密。Flutter Widget 层的口令字段启用 `obscureText`；使用合成值核对获焦与失焦状态，其可编辑语义节点均标记 `isObscured` 且语义值不含原文。固定引擎的 macOS 文本输入源码存在将活动编辑模型原文交给原生 field editor 的路径，与现象相符，但尚不足以单独证明根因或其他辅助技术的行为；该次历史观察本身不能确定修复后的系统 AX 行为。多行私钥 PEM 输入本身用于明文编辑，不应与口令遮罩等同。

独立 macOS XCUITest 对照中，[旧版 43693881242 的脱敏记录](evidence/design-parity-20261115/flutter-macos-secure-baseline-43693881242.json)显示系统树中未找到原生安全字段；[修复版 43693881355 的脱敏记录](evidence/design-parity-20261115/flutter-macos-secure-candidate-43693881355.json)确认密码和私钥口令均为系统识别的 secure 控件，合成输入均产生受保护值。密码在聚焦、失焦时以及口令在切换焦点时的系统树扫描未见合成明文；认证方式切换清空字段，普通字段哨兵可读，证明扫描并非对所有值一律失明。验收应用显式开启测试用 embedder 语义，这不是 VoiceOver 验收。

修复版验收源码为 `32cd6066a0deb07527540bd955dd1e6b8c14bcb5`；其 Flutter 产品页面、Apple 原生代码和工程生成器与历史下载包 `79d2d00` 一致，但测试应用是独立构建。整个 XCTest 仍为失败：后续未找到独立期望的主机指纹，密码和加密私钥的 SSH 认证、PTY 与关闭步骤均未到达。上述系统 AX 遮罩结论不能扩展为该修复版原生双认证通过，先前 Android/iOS 模拟器结果仍按各自源码和范围单列。

后续 macOS 原生专项 [43704701932](evidence/design-parity-20261115/flutter-macos-secure-candidate-43704701932.json) 和 [43705618468](evidence/design-parity-20261115/flutter-macos-secure-candidate-43705618468.json) 均为四项实跑、三项通过：系统遮罩、密码认证与界面主动断开、返回重开通过，密码服务端分别确认认证、PTY、shell 和应用存活期间关闭。前者中 PEM 字段的 Flutter 焦点已确认，系统快捷粘贴后控制器仍为空；后者仅在确认仍为空后以真实键盘逐行输入，PEM 和口令控制器均与一次性夹具精确相等，且已尝试连接，但 key 服务端只观察到探测，未确认认证或关闭。实际未判定粘贴失效原因，也不能据此声称原生加密私钥登录通过。测试应用使用显式测试用 embedder 语义；两次均为独立构建。与之互补的本地 Dart 加密私钥真实回环认证证据见下文，不能代替该原生 UI 结果。

普通 SSH 的 RSA 兼容增量也已从原生 macOS 窗口独立复验：纯 RSA2048 Paramiko、核对 SHA256 指纹、密码登录、输入 `hp-check` 后看到绿色 `POCKET-ANDROID-SSH-OK`，点击断开后服务端记录 `sessionClosed`。窗口缩放让服务端实际收到 80×24 → 106×28 → 106×30 → 104×27 → 104×20 → 104×19 → 106×19，包括列数相同而行数改变。该次使用前端 `f29ea6b` 与 Rust 生产文件 blob `a9e9792` / `502548b`，已纳入功能快照 `621b793`；该次 Tauri 原生私钥输入未验证，Android 范围另见下文。

Tauri 的加密私钥入口随后在 Android API 35 x86_64 模拟器实际通过：[Actions 43682217625](https://github.com/Luck9Star/herdr-pocket/actions/runs/43682217625)，源码 `664be556c5572cb9777bd0ffe6e18266a9d2889a`，验收工件 `14149575567`，APK SHA256 为 `41ca5b685b23a6a7244e214fbb8c2636733c891b2f8bf3992bef4dc6983cbf6c`。应用选择私钥认证，核对临时 loopback 对端指纹，使用有口令保护的一次性 OpenSSH Ed25519 用户私钥连接；对端只接受指定公钥，设备上确认 PTY、shell、`hp-check` 输入、终端回显和主动断开，服务端确认会话关闭；应用、转发及临时连接清理均通过。[原始脱敏 manifest](evidence/design-parity-20261115/tauri-encrypted-ssh-android-43682217625.json)只记录布尔结果。另一本地协议反例确认密码认证被拒、无口令或错误口令无法解密。此设备验证通过 CDP 操作 WebView，不证明物理手机或真实 IME 组字；也不代表其他私钥格式均已验证。

Rust 仅新增 russh 的独立 `rsa` feature，仍关闭默认 features 并保留 `ring`；普通 SSH 探测和连接禁止协商旧 RSA/SHA1，RSA 私钥采用服务端支持的 SHA-256/512。公钥 pin 的 `ssh-rsa` 前缀表示公钥编码，并不表示允许 SHA1 签名。三个消费方锁文件同步固定新增依赖，未修改 vendored russh；herdr 配对仍按原 Ed25519 身份验证。测试夹具的子进程由专用线程从创建到回收持有，取消清理继续以 3 秒内连接和子进程计数归零验收。

`d5ec372` 的本机固定 SDK、隔离 Flutter 工程与临时 SSH loopback 定向用例 11/11 通过，覆盖 macOS/Android Widget 语义，以及连接中返回后 `SSHClient.done`、`isClosed` 和重新打开的空表单；这是 Widget 与传输回环证据，云端 544/5 与渲染 10 项另行统计。

`d5ec372` 的 [macOS 系统专项记录](evidence/design-parity-20261115/flutter-macos-secure-candidate-43699318795.json)共 4 项中遮罩、实际返回及重开两项通过；测试使用专用 embedder 语义通知。密码和私钥两项均探测并精确核对独立指纹，但确认控件不可命中，尚未到认证，整个专项为失败；不得将其描述为原生 SSH 认证通过。 后续 `2c92641` 的 [运行 43701658581 原始记录](evidence/design-parity-20261115/flutter-macos-secure-candidate-43701658581.json)四项中三项通过：系统遮罩、返回重开及密码 SSH 登录后界面主动断开，密码服务端确认 auth/PTY/shell/close；两种认证的硬性 live 时间窗只导出合值，不能分项倒推，私钥已独立核验并确认指纹、输入 PEM 和口令，但连接按钮测试未命中、key 服务端仅探测；该次测试独立构建，其产品代码与 `d5ec372` 标准包一致。 另有[本机独立回环记录](evidence/design-parity-20261115/flutter-local-encrypted-openssh-ed25519.json)：固定 Dart 3.13.7、dartssh2 4.1.0 与同一夹具类，使用本地新生成的加密 OpenSSH Ed25519 和仅允许 publickey 的服务端，真实验证独立 pin、错误口令拒绝、PTY、回显与关闭；该证据与原生 UI 互补，两次凭据和输入路径各自独立。

## S01–S05 设计与可达性

沿用 [Penpot v2 设计与工程映射](../design/README.md)、[原始 S01–S07 读回](../design/evidence/v2-initial.json)，以及 [S08 未知发送](../design/evidence/v2-S08.png)、[S13 主机确认/撤销](../design/evidence/v2-S13.png)、[S43 键盘收起](../design/evidence/v2-S43-keyboard-20261107.png)、[S49 指纹审查](../design/evidence/v2-S49-profile-review-20261107.png)。靛蓝表示操作与选择，绿色只表示状态；终端保持黑曜石背景。

- S01：看板、终端、网络、设置四个入口；普通 SSH 与 herdr 配对可由正常首页进入。
- S02–S04：显示实际 pane 标签、观察/逐键/草稿三态、安全提示、终端文本/字体工具和辅助键。切换模式本身不发送字节；草稿优先编辑，发送仍须原目标预览确认，换行不会被删除或额外补回车。
- S05：将资料导入、目标核验、主机指纹卡、创建设备身份、主机响应审查与独立连接验证组织为步骤；保留取消、撤销边界和稳定测试 key。核验框不会因仅粘贴资料而自动勾选。

Flutter S18 隐藏标签显示最后一次实际终端画面的时间；尚未收到帧时显示“尚无终端画面”。时间与具体 pane/terminal 绑定，返回或主动恢复不会制造新时间，只有接受新画面后更新。390×844 的双标签合成 adapter Widget 回归覆盖隐藏、迟到帧、恢复、新 full 和无帧状态；输入许可仍须等待新 full 并显式选择，未据此声称手机真机或真实 SSH 中的该时间显示已验收。

Tauri `f1d155d` 的 S08/S09/S18 界面回归在当前会话显示待核实的原目标、提交时间和只读内容；改变目标后仅保留只读审查，不自动补发，须返回原目标、取得新 full 并人工确认才可继续。隐藏标签显示实际最后帧时间；本地前端测试 586 项和构建通过。[未知发送](evidence/design-parity-20261115/tauri-s08-unknown-390.png)、[隐藏暂停](evidence/design-parity-20261115/tauri-s18-paused-390.png)与[恢复等待](evidence/design-parity-20261115/tauri-s18-resuming-390.png)是 390 宽合成资料截图，不是设备或真实远端验证。

以下截图使用合成资料，没有个人凭据。S01 的 Flutter 图为 320、390、1200×844、DPR 1 的实际 Widget 渲染；Tauri 图为 320、390 宽的合成界面渲染。S02–S05 为 390×844、DPR 1 的 Flutter Widget，来自[本轮可达性与截图测试](../validation/flutter/test/herdr_workflow_visual_test.dart)。它们用于设计与界面对照，不证明真实 SSH 或手机设备。

| 画面 | 稳定截图 |
| --- | --- |
| S01 首页与正常入口 | Flutter：[320](evidence/design-parity-20261115/s01-board-multi-320.png)、[390](evidence/design-parity-20261115/s01-board-multi-390.png)、[1200](evidence/design-parity-20261115/s01-board-multi-1200.png)；Tauri：[320](evidence/design-parity-20261115/tauri-s01-populated-320.png)、[390](evidence/design-parity-20261115/tauri-s01-populated-390.png) |
| S02 观察 | [默认只读与真实标签条](evidence/design-parity-20261115/s02-observe-390.png) |
| S03 逐键输入 | [显式输入与安全提示](evidence/design-parity-20261115/s03-direct-390.png) |
| S04 草稿 | [本地编辑与预览发送](evidence/design-parity-20261115/s04-draft-390.png) |
| S05 配对 | [扫码/资料步骤](evidence/design-parity-20261115/s05-pairing-390.png)、[完整指纹卡与独立核验](evidence/design-parity-20261115/s05-fingerprint-390.png) |

首页增量将主机状态、真实报告会话和受阻 pane 分行，使用简短本地同步时间；原目标、精确时间和资料管理按需展开。普通 SSH、配对、搜索与历史筛选保留，缺少在线、延迟或预览资料时不虚构。Flutter 固定候选隔离工程完整测试 **541 passed / 5 skipped**，含 320/390 首屏、真实形状的合成报告、同名主机与目标保护；跳过项不计通过。Tauri 的 `efe29cb` [Android stock 运行 43681215342](https://github.com/Luck9Star/herdr-pocket/actions/runs/43681215342) 工件 `14147958900` 的 manifest 为 passed：正常配对、指定 pane full/delta、同名受阻目标与看板搜索、停止及撤销通过，服务端输入 0 字节。它是 API 35 模拟器上的只读 stock 证据，不代表首页截图中的合成数据或物理手机验收。

## S06 双侧界面与真实回环验收

2026-11-15 冻结提交 `cacae2f` 已在独立临时工程通过完整 Flutter 套 **527 passed / 4 skipped / 0 failed**，analyzer 无问题。此批新增桌面主机树、两侧独立终端，以及与可见性分开的唯一输入资格。

1440 宽度下，两独立标签/会话同时可见并继续接收各自画面；只有选中侧可显式启用输入。失去输入资格时撤销旧 IME、排队字节、迟到异步与发送/粘贴预览；回到该侧不自动恢复发送模式。收窄为 700 后只显示一侧，隐藏侧按既有规则暂停；本地尺寸变化不改写远端 herdr 的固定观察网格。核心安全回归见[输入资格测试](../validation/flutter/test/remote_input_eligibility_test.dart)。

[1440 双侧与左侧主机树](evidence/design-parity-20261115/s06-split-1440.png) · [700 单侧收窄状态](evidence/design-parity-20261115/s06-single-700.png)。这些是实际 Flutter Widget 渲染和两个合成适配器，证明界面与输入隔离契约，不代表两条真实 SSH、桌面原生窗口或手机设备验收。

随后 `beee7ca901fb61454f8e0a5df14e0a7b3aa6684f` 补上两条真实 SSH/herdr 连接的独立验证：[专用入口与运行说明](../validation/remote-harness/README-s06-real-ssh.md)、[实际 Widget 用例](../validation/flutter/test/s06_real_ssh_test.dart)。在受控 Linux OpenSSH 上，从正常主机首页完成两次审查和配对，各用一个临时设备身份、一个原样 `RemoteReadOnlyAdapter` 与一个命名 herdr session；两个目标故意有相同 pane ID、不同 terminal ID，分屏后显式恢复第一侧，两侧各收自己的完整帧和持续增量。

| 模式 | 固定运行与真实 manifest | 独立服务端与界面结果 |
| --- | --- | --- |
| stock 只读 | [43672254449](https://github.com/Luck9Star/herdr-pocket/actions/runs/43672254449)，工件 `14145046282`；[原始公开 manifest](evidence/design-parity-20261115/flutter-s06-stock-43672254449.json) | 两侧各建立 1 次 SSH，A 总帧/delta 为 8 / 6，B 为 10 / 9；两侧均不可启用输入，远端精确字节计数 `[0,0]` |
| guarded 输入 | [43672256984](https://github.com/Luck9Star/herdr-pocket/actions/runs/43672256984)，工件 `14145440795`；[原始公开 manifest](evidence/design-parity-20261115/flutter-s06-guarded-43672256984.json) | 两侧各建立 1 次 SSH，A 总帧/delta 为 12 / 10，B 为 14 / 13；B 选中时只收到逐键 `b`，换焦点并明确选择草稿后 A 只收到确认的 `Pocket测`，远端精确字节计数 `[9,1]` |

两轮均通过独立密钥的实际 sshd 认证、原目标绑定、双侧持续画面、唯一输入焦点、旧侧迟到输入拒绝、换焦点不自动恢复发送、双侧停止与授权撤销；两份 PTY 数字采样均保持 119×40，未观察到尺寸变化，进程与临时密钥清理全部通过。guarded 使用另行校验固定来源、补丁、二进制哈希与能力探针的输入夹具，不把 stock 改成可写。

早期用例曾因 Live binding 的逻辑渲染面仍为 800×600，使分屏按窄窗规则收起；已用本地最小复现确认，并显式设置、断言真实 1440×1000 画布及按钮命中、active/split 目标和两侧可见性后完成上述同源重跑。另一次前置失败来自新 iOS 测试的可选 Paramiko 导入，尚未执行 S06；不能把这些测试修正声称为产品或真机故障修复。

此增量证明实际 Flutter Widget 引擎中的两条真实 SSH/herdr 连接；signer、目录和输入 journal 是明确的测试实现，没有帧或适配器替身。它不证明原生桌面窗口、系统密钥/journal 落盘、物理 IME 或跨网络。上面的 S06 PNG 仍属于先前合成适配器批次，不冒充这两轮的截图。

Tauri 的 `042c80f` 已在原生 Linux GTK WebView 以两条真实隔离 SSH/herdr 连接复验 S06：[stock 运行 43676588247](https://github.com/Luck9Star/herdr-pocket/actions/runs/43676588247) 工件 `14146414384` 和 [guarded 运行 43676590579](https://github.com/Luck9Star/herdr-pocket/actions/runs/43676590579) 工件 `14146323622` 的 manifest 均为 passed；已保留 [stock 摘要](evidence/design-parity-20261115/tauri-s06-stock-43676588247.json)与 [guarded 摘要](evidence/design-parity-20261115/tauri-s06-guarded-43676590579.json)。两侧对应不同 terminal、真实可见文本帧各自递增，两个连接在驱动退出前关闭；stock 两端输入均为 0，guarded 两端收到的字节分别为 9 与 1 且与预期完全匹配，焦点切换不自动恢复输入、迟到输入被拒。第二共享 PTY 分别采样 463 / 402 次，均无 resize；使用的是进程内临时测试身份，不证明系统密钥存储或物理 IME。

这次同时修正了桌面分屏说明占据网格单格、未选标签在暗底对比度不足，以及折叠表单的未绘制矩形被误判为终端遮挡的问题；实际 GTK 可见文本选择在两侧均成功。[stock 原始截图](evidence/design-parity-20261115/tauri-s06-stock-43676588247.png)显示两侧同顶、标签可读与 CJK 字形；[runner 字体记录](evidence/design-parity-20261115/tauri-s06-gtk-fonts-042c80f.txt)显示安装了 Noto CJK，它不是未安装字体环境的证据。Linux Tauri 的 `042c80f` 成品 .deb 工件 `14146599628` 独立读回 `Depends: fonts-noto-cjk | fonts-wqy-microhei, libwebkit2gtk-4.1-0, libgtk-3-0`，并由 Linux 构建中的 `dpkg-deb -f` 检查；字体作为 Debian 系统依赖，不改变其他平台或随包嵌入大型字体。图形字形可读和终端网格/所有字符组合的完整正确性仍需分别验证。

作为另一层独立证据，`e5cdaeb` 的 Linux 原生 Flutter 与 Tauri stock herdr 配对都通过，两个 manifest 均记录输入 0 字节；`bd083d8` 的双壳五端构建通过。它们分别证明对应版本的配对观察路径与构建，不可扩成普通 SSH Android UI 或 S06 真实双连接运行通过。

Flutter 的 `a2ffb4b` [guarded Android 运行 43667868489](https://github.com/Luck9Star/herdr-pocket/actions/runs/43667868489)也已独立回读通过：stock 路径输入 0 字节，guarded 工件 `14143482126` 记录 10 字节，逐键与草稿各自受理；粘贴取消、再次预览和本地追加没有额外 SSH 字节，生命周期与原目标核对通过。这是对应版本单端受保护输入的模拟器证据，不是 S06 真实双连接或物理 IME 验证。旧 `fba4` 运行的 AVD 255 根因仍未查明，诊断或用例依赖修复不构成该故障已根治的证据；专用 TUI 运行另行核对。

专用 TUI 的 Tauri `c9f191d` [运行 43670510076](https://github.com/Luck9Star/herdr-pocket/actions/runs/43670510076)中，`android-device-key` 作业通过；工件 `14145185000` 的真实 curses 主机状态与 10 个输入回执匹配，`manifest.stoppedStale=true`，`progress.postStopInputUnchanged=true`，停止按钮首次命中。另记录 7 个系统 IME 显示/收起检查点，不能扩大为真实中文组字或实体键盘通过。`receivedInputBytes=10` 是 curses 之外的原始捕获阶段，不代表全部 TUI 输入只有 10 字节。该混合工作流另有 Flutter 作业失败，不能写成整条运行全部通过。

S11 的 Tauri 窄窗回归覆盖宽屏观察、收窄后的 pausing、后端 paused 确认及恢复：只有确认暂停后才显示「观察已暂停」，恢复后消失，并检查没有触发共享 PTY resize。普通 SSH 重连回归使用真实 xterm：旧实例尾留半个 emoji 时，复用实例会错误显示 `😀Z中!`；新会话创建新实例后显示 `Z中!`，旧实例已释放。两项是隔离测试及实际 xterm 渲染证据，不声称新的原生设备验证。 [390×844 截图](evidence/design-parity-20261115/tauri-s11-390.png)和 [900×900 截图](evidence/design-parity-20261115/tauri-s11-900.png)通过真实 `initRemote` 路由与 DOM/CSS、合成网络数据生成：前者显示两个标签，后者显示左侧主机栏和右侧双面板；它们是浏览器界面证据，不是原生设备截图。截图提交位于未选标签跨宽度对比度修正之后；至 `d5ec372` 的 Tauri 页面代码没有后续变动，对应本批界面。

## S19 macOS 配置文件往返

Tauri `f64717b` 的 macOS 原生 debug 包工件 `14146348398` 经隔离 bundle ID 本机验收，内层 app.zip SHA256 `e706c3dfe4179a67e38bb224d38dc224464db13342315a4d0a6f3e55f537a496`。在无主机资料的临时配置中，将字号设为 19，经系统文件对话框导出 126 字节 HPKT，再改为 13；错误口令被拒且不改变设置，正确口令导入预览中 19 默认未选，手动勾选并确认后字号恢复为 19，主机仍为 0。该证据只覆盖字号偏好及系统文件交互，不扩大为主机、身份或其他配置迁移验证；不保存测试口令和密文。

## S17 受理回执与 Android 停止观察

Tauri 主连接与终端标签均只在原生回复的 request ID、pane、terminal 与受理字节数和当前目标及发送长度匹配时，显示可展开的最近一次受理回执；“已受理”只表示服务器入队，执行结果仍看终端。新一笔发送、目标失效或标签切换会清除对应旧回执；未确认或不匹配的回复不能作为成功展示。标签与主连接的显示逻辑有本地回归，下面 Android 设备步骤直接核对的是**主连接草稿回执**，不将其扩大为标签页设备验证。

`3cef14b` 的 [Android 综合运行 43672278898](https://github.com/Luck9Star/herdr-pocket/actions/runs/43672278898)中，Tauri guarded 工件 `14145033655` 的 manifest 为 passed；实际收到并独立核对草稿回执后，通过 CDP 点击展开，比较显示的 request ID、pane、terminal 和字节数，再点击折叠，`progress.receiptDetailsReviewed=true`。同次受保护输入和 curses 10 项动作通过，停止按钮在终端仍持焦时实际触发、画面标记陈旧，`postStopInputUnchanged=true`；7 项 Android 15 系统键盘窗口/Insets 检查通过，设备影响复审及撤销和隔离资源清理确认。该证据来自 API 35 x86_64 模拟器与 CDP 操作，不证明物理手机触控、真实中文 IME 组字或标签页 S17 设备路径。

同一 `3cef14b` 批次 Flutter guarded 在**首个**系统键盘检查 `keyboard-direct-shown` 失败：`adb shell dumpsys input_method` 返回 255、标准输出 382,989 字节、标准错误为空。工件没有原始输出，无法据此认定具体设备原因；清理前模拟器进程仍在，cgroup 未记录 OOM。该轮没有进入 F10，因此不能用它判断前轮 `c9f191d` 的 `tui_finish` 失败，也不能将 Flutter guarded 记为通过。`c9f191d` 主机侧确认 10 项 TUI 动作到达并恢复终端模式，但旧测试把最后一次点击与回执等待放在同一业务行，尚无法确定首错；后续加入不含回执内容的布尔诊断。`22bb42e` [Flutter 窄复测 43673885906](https://github.com/Luck9Star/herdr-pocket/actions/runs/43673885906) 的 guarded 工件 `14146580202` 实际 manifest passed：10 个 TUI 回执、10 个屏幕检查、主机目标及初始/最终输入、应用状态、终端模式恢复与结束后无残留输入均匹配；8 个系统 IME 检查点含 Back 与重开，均确认目标归属和相应显隐，停止后输入禁用、隔离清理完成。本轮未产生 `adbReadRetries`，没有复现 c9 的 F10 首错，也不能证明 3cef 的 ADB 255 原因或根治；模拟器窗口检查不等于物理 IME 组字。

普通 SSH 表单采用 560 逻辑像素最大阅读宽度、分组状态与间隔字段。[390 宽截图](evidence/design-parity-20261115/flutter-direct-ssh-form-390.png)和[桌面截图](evidence/design-parity-20261115/flutter-direct-ssh-form-desktop.png)是从真实首页控件入栈、使用合成地址与用户名及空密码的 Flutter Widget 渲染；截图测试为中文加载本机字体，不冒充原生窗口像素。另以固定 SDK 编译 Dart kernel，替换 4db debug app 的隔离副本、独立 bundle ID 重签后检查 macOS 系统 AX：地址、端口、用户名、密码及私钥/口令分别是**有名容器，内含 text field**；text field 自身并非有名节点。随后对云端 `38630b3` macOS arm64 工件 `14145048657` 独立复核：压缩包 SHA256 `2ccb6b6c49561a3bf2d7fb48e54c3d74b75111ef77e2c44b7f564b144f8183f6`；为隔离测试更换 bundle ID、保留原六项 entitlement 后临时重签，Dart kernel 原样。首页进入普通 SSH 后，系统 AX 的密码模式四组以及切换后的私钥 PEM 和可选口令分组均包含相应 text field。此项为系统 AX 分组证据，不把 Widget 语义等同系统 AX，也不声称输入框自身具名。

Tauri 普通 SSH 会话新增 Esc、Tab、方向键与 Ctrl-C；方向键按实际 xterm 光标模式输出普通或应用模式序列，隐藏、断开和切换后不重放旧输入。[320×844](evidence/design-parity-20261115/tauri-ordinary-ssh-keys-320.png) 和 [390×844](evidence/design-parity-20261115/tauri-ordinary-ssh-keys-390.png) 使用真实首页与 `initRemote` 路由、真实 xterm 和合成主机目录/SSH 对端：从看板进入、探测并确认后主动连接；另在 320×500 缩小视口滚动并逐一点击七键，控件均至少 44×44，页面无横向溢出。这些截图是浏览器与合成对端证据；后续 Android 模拟器的服务端字节结果见下文，仍未验证真实软键盘。

Flutter 普通 SSH 新增显式“粘贴私钥”入口：只在私钥模式主动读取，异步结果须仍属于原页面、目标及编辑状态；连接重开时创建新的终端实例，退休旧实例的输出与尺寸回调。`a9afe9c` 云端 Flutter 候选包含这些 Widget 回归，合计 556 项通过、5 项按条件跳过及 10 项渲染回归通过；这不等同于系统剪贴板或真实 IME 的设备验收。

## S27 网络页界面增量

`4be102e` 冻结了手机 S03、普通 SSH 凭据门槛和 S27 网络页；独立归档源码完整验证为 **533 passed / 4 skipped / 0 failed**，analyzer 无问题。S27 使用紧凑配置与节点状态、实际绑定主机名和按需展开管理；40 项定向回归包含停用影响以及撤销、删除保护。[320 宽度](evidence/design-parity-20261115/s27-networks-320.png)与[390 宽度](evidence/design-parity-20261115/s27-networks-390.png)是使用合成节点数据的实际 Widget 渲染，证明界面与交互，不替代真实组网或设备路由证据。

## EasyTier Linux 真实 overlay 链路（2026-11-15）

`a11a357f63ca4040d4e200c4db6f2ee57cdd6440` 的 [运行 43682653413](https://github.com/Luck9Star/herdr-pocket/actions/runs/43682653413)、工件 `14149790312` 已完成真实 EasyTier 验收；[原始脱敏 manifest](evidence/design-parity-20261115/easytier-real-overlay-ssh-43682653413.json)保留固定源码与二进制哈希。一侧使用现有产品 `OverlayRuntime`、`OverlayDialer`、`read_once_with_dialer` 和真实候选 ABI；另一侧使用固定上游的临时节点，在用户态虚拟 TCP 端口监听并仅桥接至临时 loopback OpenSSH/herdr。两节点位于只有 `lo` 的 Linux network namespace，网络名、秘密和 SSH 身份均临时生成，STUN/公共 peer/打洞关闭，没有接入个人或公共网络。

每个场景先经真实 overlay 收到 SSH banner，再由独立 runner 采样服务端基线并放行目标尝试；下表只统计该次目标尝试，不把 native open 次数当成服务端连接数。

| 场景 | 目标 TCP 连接 | 服务端认证受理 | 实际结果 |
| --- | --- | --- | --- |
| 正确 pin | 1 | 1 | 主机密钥匹配，收到真实 herdr `80×24` 完整帧与夹具标记 |
| 错误 pin | 1 | 0 | `host_key_mismatch`，认证请求为 0，未发布帧 |
| 无 overlay 路由 | 0 | 0 | 本机 SSH 仍可用，目标尝试以 `handshake_failed` 结束，全部 SSH 审计为 false |
| 已连 peer 停止 | 0 | 0 | 确认真实 peer 停止后再尝试，同样拒绝；本机 SSH 仍可用 |

两个负例的目标认证请求均为 0，证明本轮没有改走可用的系统 TCP。peer 的 6 条实际桥接连接与 sshd 总计数相符；停止后桥接任务为 0，每场景的 runtime node/stream 保留数均为 0，namespace 删除前残留进程为 0，临时凭据与测试 bundle 已删除。远端输入共 0 字节。该结果补足的是 **Linux 产品 Rust 的 herdr 只读链路**；使用测试内存配置源，不能扩大成 GUI 路由、平台 vault、Android/实体设备、物理网络或 Tailscale/ZeroTier 及三网并发通过，也不改变普通 SSH GUI 当前使用系统 TCP/DNS 的范围。

## 普通 SSH Android 设备验收入口

已新增[独立工作流](../.github/workflows/direct-ssh-android.yml)、[设备测试与共享夹具说明](../validation/remote-harness/README-direct-ssh-android.md)。它从正常首页进入普通 SSH，在 runner 自建 API35 AVD 中经 `adb reverse` 访问临时 loopback Paramiko，断开必须在测试 driver 仍存活时由服务端独立确认；仅上传安全 JSON 和认证字段清空后的截图。工作流支持约定验收分支 push，不要求先合并默认分支。

首轮 `4f13dcd63d0c542153eed02263e987e23fa7de75` 的 [Flutter Android 普通 SSH](https://github.com/Luck9Star/herdr-pocket/actions/runs/43665538052) 未通过，只留下通用 runner 失败和全部清理成功；不能据此判定 app 连接失败。随后定位到读取 app-private 结果的轮询缺陷：`adb exec-out` 可能以零退出码返回尚未安装或文件不存在的文字，旧代码直接解析 JSON。`db91fce` 改用明确的包状态、`adb shell` 文件存在性检查及严格 JSON 验证，并补非 JSON 等反例和无秘密阶段化诊断。

修复后 [Flutter API35 Android 模拟器复测 43666350464](https://github.com/Luck9Star/herdr-pocket/actions/runs/43666350464) **通过**，源码 `db91fce84640c4dfdb1c51558ade419f8e5dca39`，Actions 工件 ID `14142083552`。设备报告确认从首页进入、pin 一致且明确确认、真实 `TerminalView` 的正常文本提交、远端回显可见、界面断开与凭据清空；独立服务端确认认证、PTY、shell、标记输入和关闭，且在测试驱动退出前已关闭，全部清理项通过。实际[已连接截图](evidence/design-parity-20261115/flutter-android-ssh-connected-43666350464.png)记录的是 READY 阶段；回显断言与关闭证据见[脱敏报告](evidence/design-parity-20261115/flutter-android-ssh-43666350464.json)。该模拟器使用测试输入接口提交文本，物理 IME 未验证。

RSA 功能快照 `621b793349d7e44332d617e76a345086c272e931` 的两壳 API35 Android 模拟器普通 SSH 均已通过，并独立回读实际工件：

| 路线 | 固定运行与工件 | 实际证据与输入方式 |
| --- | --- | --- |
| Flutter | [run 43668558676](https://github.com/Luck9Star/herdr-pocket/actions/runs/43668558676)，工件 `14143074595`；[最终脱敏报告](evidence/design-parity-20261115/flutter-android-ssh-43668558676.json) | 从首页进入、明确指纹确认、真实 TerminalView 正常文本提交、远端回显、界面断开和凭据清空均通过；服务端在驱动退出前确认关闭，清理全部通过。输入来自 Flutter 平台测试接口 |
| Tauri | [run 43668503928](https://github.com/Luck9Star/herdr-pocket/actions/runs/43668503928)，工件 `14143189049`；[最终脱敏报告](evidence/design-parity-20261115/tauri-android-ssh-43668503928.json) | 真实 Android WebView 的首页与指纹审查、认证、终端输入/回显、界面断开、密码清空及服务端关闭均通过，清理全部通过。输入来自 CDP；x86_64 调试 APK SHA256 为 `4121aa825ac4d6f3913efb4e710f3f7081ed0ddccb52024708ddce6794fd87ae` |

两者均访问 runner 自建的 RSA2048 loopback 夹具，不访问个人主机；没有验证物理 IME 组字或手机真机。上面的 Flutter READY 截图来自前一轮 `db91fce`，保留原 SHA，不将近似画面冒充后续快照截图。[Tauri 首轮](https://github.com/Luck9Star/herdr-pocket/actions/runs/43665538049)保留为 RSA 修复前的历史运行。

本地普通 SSH 真实 Widget 复核已执行 5/5，包含新增空凭据门槛与正常返回销毁回归。只有服务端后验与 UI 身份拒绝断言全部通过，runner 才输出成功摘要；认证未发生但连接未尝试的情况不算身份验证成功。Android 集成源码与普通 SSH 页面 analyzer 无问题，修复后的 CI/目录/设备守卫、结果解析反例与真实 Paramiko loopback 5/5。这些本地检查与上面的实际模拟器结论分层记录。

## 后续安卓与构建来源

生产界面 `4db7c49` 的两壳普通 SSH 又在同源 API35 模拟器通过：Flutter [43671665945](https://github.com/Luck9Star/herdr-pocket/actions/runs/43671665945) 的验收工件 `14144632159`，Tauri [43671665972](https://github.com/Luck9Star/herdr-pocket/actions/runs/43671665972) 的验收工件 `14144802062`；Tauri 的 x86_64 调试 APK 另在工件 `14144653085`，不可把验收 JSON/图片工件当成 APK。该版两壳 APK 已另行下载、解析 ABI 并核对来源与哈希。共享测试改为 `3cbfcb5` 后，Flutter [43671869018](https://github.com/Luck9Star/herdr-pocket/actions/runs/43671869018)、工件 `14144522738` 也通过；各次输入方式与物理 IME 限制仍按上文分开记录。

`38630b3` 的[完整批次 43672818989](https://github.com/Luck9Star/herdr-pocket/actions/runs/43672818989)为 27 个启用作业通过、7 个跳过；包含双壳五端构建、Linux stock/guarded 及各自实际执行的模拟器路径。相同源码的普通 SSH API35 也独立完成：[Flutter 43673540526](https://github.com/Luck9Star/herdr-pocket/actions/runs/43673540526) 工件 `14145477748` 的首页、指纹确认、终端回显和断开及服务端 auth/PTy/shell/marker/关闭均通过；[Tauri 43673540478](https://github.com/Luck9Star/herdr-pocket/actions/runs/43673540478) 工件 `14145333807` 对应指纹、凭据状态、输入回显、断开及服务端关闭和清理通过。两者都是临时 loopback 服务器和 API35 模拟器；Flutter 明确 `physicalImeVerified=false`，Tauri 使用 CDP 输入，不作为实体手机或真实 IME 组字证据。

最新同源码 `a9afe9cdbb1f3809f7bb975f41b83705a4825510` 的 API35 模拟器普通 SSH 已通过：Flutter [43708649955](https://github.com/Luck9Star/herdr-pocket/actions/runs/43708649955) 的[脱敏记录](evidence/design-parity-20261115/flutter-ordinary-ssh-android-43708649955.json)覆盖首页、指纹确认、临时密码、终端输入回显、断开与凭据清空，独立服务端确认认证、PTY、shell、输入标记及两次连接关闭；Tauri [43708649975](https://github.com/Luck9Star/herdr-pocket/actions/runs/43708649975) 的[脱敏记录](evidence/design-parity-20261115/tauri-ordinary-ssh-android-43708649975.json)分别覆盖密码和加密私钥连接、回显与关闭，密码路径还由服务端精确确认 Esc、Tab、左方向、Ctrl-C 依次为 `1b 09 1b 5b 44 03`；该键序未在私钥路径重复验证。模拟器使用独立测试构建和合成 loopback，Tauri 使用 CDP、Flutter 使用测试接口，均不证明实体手机或真实 IME。

此前同源码 `d5ec372d50060f4824401755e213c826f0c4ab01` 的 API35 模拟器普通 SSH 已通过：Flutter [43699318300](https://github.com/Luck9Star/herdr-pocket/actions/runs/43699318300) 的[脱敏记录](evidence/design-parity-20261115/flutter-ordinary-ssh-android-43699318300.json)覆盖首页、指纹确认、临时密码、终端输入回显、断开与凭据清空，服务端确认认证、PTY、shell、输入标记及两连接关闭；Tauri [43699318224](https://github.com/Luck9Star/herdr-pocket/actions/runs/43699318224) 的[脱敏记录](evidence/design-parity-20261115/tauri-ordinary-ssh-android-43699318224.json)分别覆盖密码与加密私钥路径及关闭。独立测试构建与合成 loopback 不等同下载包二进制；Flutter 测试接口和 Tauri CDP 未验证真实 IME，也不代表实体手机。

此前同源码 `20ef361ae4a7624c6de0afd9d970764d4429a588` 的 API35 模拟器复测通过：Flutter [43696926794](https://github.com/Luck9Star/herdr-pocket/actions/runs/43696926794) 的[脱敏记录](evidence/design-parity-20261115/flutter-ordinary-ssh-android-43696926794.json)覆盖首页、主机指纹确认、临时密码、终端输入回显、断开与凭据清空，服务端确认认证、PTY、shell、输入标记与两次连接关闭；Tauri [43696926711](https://github.com/Luck9Star/herdr-pocket/actions/runs/43696926711) 的[脱敏记录](evidence/design-parity-20261115/tauri-ordinary-ssh-android-43696926711.json)分别覆盖密码和加密私钥的对应流程及关闭。两者使用独立 debug 测试构建和合成 loopback 服务；Tauri 使用 CDP，Flutter 测试接口也未验证真实 IME，不代表实体手机。

同源码 `d38aff40852d4859cd1e95b4a43899a21740cb9b` 的 API35 模拟器复测通过：Flutter [43689181389](https://github.com/Luck9Star/herdr-pocket/actions/runs/43689181389) 的[脱敏记录](evidence/design-parity-20261115/flutter-ordinary-ssh-android-43689181389.json)覆盖首页进入、指纹确认、临时密码连接、终端输入回显、断开和凭据清空；独立 loopback 服务确认认证、PTY、shell、输入标记和两次连接关闭。Tauri [43689181428](https://github.com/Luck9Star/herdr-pocket/actions/runs/43689181428) 的[脱敏记录](evidence/design-parity-20261115/tauri-ordinary-ssh-android-43689181428.json)分别覆盖密码及加密私钥的确认、输入回显、断开和清理，服务端记录了认证、PTY 和 shell。两项使用独立测试构建与合成服务，同源码不等于同一二进制；模拟器测试接口或 CDP 输入不证明实体手机和真实 IME 组字。

更新的同源码 `bc430761b71a470eeba94a01b148f0521343c822` 两壳普通 SSH 又分别通过 API35 模拟器：Flutter [43684909905](https://github.com/Luck9Star/herdr-pocket/actions/runs/43684909905) 的[原始脱敏记录](evidence/design-parity-20261115/flutter-ordinary-ssh-android-43684909905.json)确认首页、指纹、实际终端输入/回显、断开及服务端提前关闭；Tauri [43684909875](https://github.com/Luck9Star/herdr-pocket/actions/runs/43684909875) 的[原始脱敏记录](evidence/design-parity-20261115/tauri-ordinary-ssh-android-43684909875.json)分别验证了密码与加密私钥的相应流程及清理。两次使用临时 loopback 服务与各自 debug 构建；**同源码不等于同一二进制**，也不证明实体手机或真实 IME 组字。

`a5082d0` 的[完整批次 43669066267](https://github.com/Luck9Star/herdr-pocket/actions/runs/43669066267)已独立分页核对：32 个作业中 27 个启用作业全部通过、5 个跳过不计通过，包含双壳五端构建与 Linux 双壳 stock/guarded。它证明对应源码的构建和明确执行的 Linux 路径，不能扩大成五端设备运行。Flutter macOS 原生窗口的本机实测来源与重签范围见上文；iOS 模拟器证据只限下节单独记录的源码和场景，不由 Android 成功或 iOS 编译结果代替。

## Flutter 普通 SSH iOS Simulator

`a9afe9c` 的 [运行 43708649945](https://github.com/Luck9Star/herdr-pocket/actions/runs/43708649945)及[脱敏失败记录](evidence/design-parity-20261115/flutter-ordinary-ssh-ios-43708649945.json)在 iPhone 11 / iOS 26.2 模拟器进入主机密钥探测后等待确认对话框超时，XCTest 0/1；服务端记录一次连接并已关闭，认证、PTY、shell 和输入标记均未到达，模拟器与临时资料已清理。当前证据不足以确定握手或界面未显示的根因，不记为该源码 iOS 验收通过；下方成功结果属于各自历史源码。

最新同源码 `d5ec372d50060f4824401755e213c826f0c4ab01` 的 [运行 43699319130](https://github.com/Luck9Star/herdr-pocket/actions/runs/43699319130)与[原始脱敏记录](evidence/design-parity-20261115/flutter-ordinary-ssh-ios-43699319130.json)显示，专属 iPhone 11 / iOS 26.2 模拟器 XCTest 1 项通过、0 失败。首页、主机指纹确认、临时密码、真实终端输入回显和主动断开清空均已验证；独立服务端确认认证、PTY、shell、输入标记和两连接关闭，模拟器及临时资料已清理。测试未记录输入总字节数，语义固定开启，不证明 VoiceOver、真实 IME、实体设备或 iOS 私钥认证；它是独立 debug 构建，与下载包同源码但非同一二进制。

此前同源码 `20ef361ae4a7624c6de0afd9d970764d4429a588` 的 [运行 43696926742](https://github.com/Luck9Star/herdr-pocket/actions/runs/43696926742)及[原始脱敏记录](evidence/design-parity-20261115/flutter-ordinary-ssh-ios-43696926742.json)显示，专属 iPhone 11 / iOS 26.2 模拟器上的 XCTest 1 项通过、0 项失败。从首页进入并确认临时主机指纹，以临时密码连接，终端输入和远端回显可见，主动断开后凭据清空；独立服务端确认认证、PTY、shell、输入标记及两次连接关闭，模拟器与临时资料已清理。测试未记录输入总字节数，语义固定开启，不证明 VoiceOver、真实 IME、实体设备或 iOS 私钥认证；它是独立 debug 构建，与下载包同源码但非同一二进制。

同源码 `d38aff40852d4859cd1e95b4a43899a21740cb9b` 的 [iOS 运行 43689182120](https://github.com/Luck9Star/herdr-pocket/actions/runs/43689182120)、[原始脱敏记录](evidence/design-parity-20261115/flutter-ordinary-ssh-ios-43689182120.json)在专属 iPhone 11 / iOS 26.2 模拟器通过 XCTest 1 项、失败 0 项。真实界面从首页进入，核对并确认临时 RSA 主机指纹、以临时密码连接、提交终端输入并看到远端回显；主动断开后界面确认且凭据清空。独立服务端确认认证、PTY、shell、输入标记、驱动退出前关闭及两次连接关闭；模拟器与临时资料已清理。此次未记录输入总字节数，语义在测试中固定开启，并不证明 VoiceOver、真实 IME、实体设备或 iOS 私钥认证；其独立 debug 构建与对应历史下载包同源码但非同一二进制。

`5037c40d33dcb3843fe84b54e6c17b6d8294a848` 的 [iOS 运行 43685830291](https://github.com/Luck9Star/herdr-pocket/actions/runs/43685830291)、工件 `14150417906` 在专属 iPhone 11 / iOS 26.2 模拟器上通过原生 XCTest，1 项通过、0 失败。实际从生产首页进入普通 SSH，独立核对临时 RSA 主机指纹并明确确认，以临时密码连接；真实 `TerminalView` 提交 `hp-check` 与 Enter，远端回显可见，主动断开后终端移除、密码字段清空。独立 loopback 服务器确认认证、PTY、shell、输入标记和驱动退出前关闭，两次连接均关闭；记录到的 PTY 为 80×24 → 49×48 → 49×33 → 49×29。夹具只确认标记匹配，没有记录接收总字节数，不将该结果描述为精确字节计数。

[原始脱敏 manifest](evidence/design-parity-20261115/flutter-ordinary-ssh-ios-43685830291.json)记录设备/服务器与清理结果；[连接前截图](evidence/design-parity-20261115/flutter-ordinary-ssh-ios-preconnect-43685830291.png)只使用本次临时 loopback 配置，密码已遮罩，展示的地址、用户名、端口及公钥指纹均为合成夹具，不含用户密钥。模拟器、服务器、临时凭据和生成工程均已清理。该用例在测试基线前固定语义开启并在结束后恢复，保留 Flutter 的句柄泄漏断言；专门的反例确认额外句柄仍会失败。系统语义开关在此次测试中由 false 变为 true，但这不是 VoiceOver 专项验收。输入来自 Flutter 测试接口，不证明真实 IME 组字、实体设备、签名发布包或 iOS 私钥认证。

## 尚待独立补证

S06 在 macOS/Windows 原生桌面及手机设备的双窗、手机真机触控/IME/相机/系统密钥存储、其他主机算法与认证组合、EasyTier 的其他平台与 GUI/vault 接入、Tailscale/ZeroTier 真实路由及三网并发、长时间运行和正式发布均不能由本页证据推出。后续每项新增结论必须对应新的实际运行记录；历史“只允许远端 herdr”作为当时基线保留，现行两类远端接入范围以本页及架构/产品设计的 2026-11-15 增量为准。
