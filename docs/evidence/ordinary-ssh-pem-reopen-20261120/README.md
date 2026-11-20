# 普通 SSH 私钥收起与重开验收

2026-11-20，[PR #56](https://github.com/Luck9Star/herdr-pocket/pull/56) 的首批七个原生作业已按各自源码归档。Windows Flutter、Linux Flutter 和 Linux Tauri 完成受控回环会话。Windows 和 Tauri Linux 证实私钥摘要可实际点击，编辑器重开后得到同一份完整草稿，再失焦时收起。Flutter Linux 证实点击摘要并逐字读回，第二次收起仍需用加强后的驱动复验。第二批结果见[加密私钥与主机换钥](#第二批加密私钥与主机换钥)。

## 原生作业与新交互

| 客户端和范围 | 作业实际结果 | 私钥交互实证 | 官方来源 |
| --- | --- | --- | --- |
| Flutter Windows，Win32 调试窗口 | 未加密私钥通过。A → A，探测零认证，第二条连接认证、PTY 和 shell 各一次。终端 OCR、关闭、返回首页和清理均通过。 | 工件直接记录 `collapsedSemanticsAbsent`、`summaryHit`、`reopenedExactFocused`、`collapsedAgain` 和空口令均为真。语义检查属 Flutter 测试框架。 | [作业 136026510470](https://github.com/Luck9Star/herdr-pocket/actions/runs/44657280869/job/136026510470) · [工件 14594141698](https://github.com/Luck9Star/herdr-pocket/actions/runs/44657280869/artifacts/14594141698) |
| Flutter Linux，GTK/Xvfb | 加密 Ed25519 通过。切换认证方式后清空原草稿并保留主机信任。错口令本地拒绝，服务端仍只有首条探测。正确口令后认证、PTY 和 shell 各一次，终端 OCR、关闭、返回首页和清理均通过。 | 同 SHA 的 `pastePem` 强制等待摘要、实点并逐字读回。明确验证重开焦点和再次收起的断言出现在后续驱动，此运行未覆盖。 | [作业 136021736998](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655843951/job/136021736998) · [工件 14592029874](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655843951/artifacts/14592029874) |
| Tauri Linux，WebKitGTK/Xvfb | 加密 Ed25519 通过。错口令分支完成一次握手并关闭，认证、PTY 和输入均为零。第三条连接有两次认证尝试和一次成功，PTY 和 shell 各一次。终端 OCR、关闭、返回首页和清理均通过。 | 同 SHA 的 `fill_encrypted_credentials` 在错／对口令两轮均强制实点摘要、读回完整草稿并核对编辑器焦点，再点口令框验证收起。与成功作业联证，报告没有逐项布尔值。 | [作业 136035013147](https://github.com/Luck9Star/herdr-pocket/actions/runs/44659819875/job/136035013147) · [工件 14595262144](https://github.com/Luck9Star/herdr-pocket/actions/runs/44659819875/artifacts/14595262144) |
| Flutter iOS，iPhone 11／iOS 26.2 模拟器 | 作业失败。普通密码与密码换钥已通过各自的回环、终端 OCR 和连接关闭。加密案在 `encrypted_review` 报 `StateError`，服务端仅一条已关闭 A 探测，零认证、PTY 和收发。模拟器与临时凭据已清理。 | 报告第 897 行指向等待确认后回调，具体抛出位置由本地 Flutter Widget 复现定位。旧脚本在切换到私钥后读取已收起的编辑控件。修复已纳入 `bb989d7d` 并通过本地回归。此作业尚未验到新的重开路径。 | [作业 136021575113](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655797075/job/136021575113) · [工件 14593164376](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655797075/artifacts/14593164376) |
| Tauri iOS，iPhone 17 Pro Max／iOS 26.2 模拟器 | 手填加密案完成指纹确认及错误 PEM 逐字读回，在口令检查点报 `native_encrypted_key_owner_unproven`。唯一探测已关闭，认证、PTY、shell 和收发均为零。普通密码与换钥未运行，清理通过。 | 记录只到错误 PEM 读回。口令填入、摘要重开全链路和成功认证仍待验。 | [作业 136021697365](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655832397/job/136021697365) · [工件 14593878299](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655832397/artifacts/14593878299) |
| Flutter macOS，原生窗口 XCUITest | 四项运行，三项通过。密码、加密私钥及返回后重开通过。系统遮蔽综合用例 `testSystemMasking` 在第 302 行报焦点／交互失败，整项作业失败。加密案已观测口令输入、服务端鉴权、PTY、shell 和断开窗口内关闭。 | 该次工件没有私钥收起／重开的完整断言与截图。加密 SSH 子用例通过，系统遮蔽全流程仍待复验。 | [作业 136023680726](https://github.com/Luck9Star/herdr-pocket/actions/runs/44656429126/job/136023680726) · [工件 14593682533](https://github.com/Luck9Star/herdr-pocket/actions/runs/44656429126/artifacts/14593682533) |
| Flutter Android，API 35 x86_64 模拟器 | 已观察应用包，未观察应用检查点，也未交付凭据。SSH 连接数为零。Emulator 37.3.10 的受管进程退出值为 132，反向转发及卸载两项清理未证实。 | 本次未达私钥交互。退出码记录了模拟器进程的终止状态，现有工件不足以定位触发原因。 | [作业 136021715465](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655838242/job/136021715465) · [工件 14593502076](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655838242/artifacts/14593502076) |

作业使用临时 SSH 夹具和受控回环。Win32、GTK/Xvfb 与 macOS XCUITest 均运行对应原生桌面应用，输入由验收驱动完成。手机记录来自模拟器。实体设备、物理 IME 和真实远端或跨网连接不在本批范围内。

## 第二批加密私钥与主机换钥

Tauri Android API 35 和 Linux 两壳完成加密私钥与主机换钥组合。每案各有四条已关闭的连接，顺序为 A 探测、B 拒绝、B 重探、B 公钥认证。前三条均为零认证、零 PTY、零输入。最后一条均完成一次认证成功、一次 PTY、一次 Shell，服务端收到 9 字节输入并发出 102 字节输出。

| 平台和作业源码 | 实测结果 | 私钥收起与重开证据 | 官方来源 |
| --- | --- | --- | --- |
| Tauri Android API 35 x86_64，`d1ed8646` | 换钥拒绝、取消保旧、重探确认后以公钥连接。最后一条两次认证尝试、一次成功。系统原屏通过终端 OCR，主动断开、凭据清空与五项清理通过。 | 同源码驱动以 CDP 点击口令框验证收起，再点击唯一摘要。检查编辑器焦点和草稿逐字一致，再点口令框核对第二次收起。通过作业与驱动源码共同支撑这些检查。口令与私钥录入为 WebView 交互，系统 IME 组字待验。[驱动](https://github.com/Luck9Star/herdr-pocket/blob/d1ed86462745556ad020189c4dd3ad066fd69cf1/validation/remote-harness/tauri_android_direct_ssh.py#L784-L869) | [作业 136044961608](https://github.com/Luck9Star/herdr-pocket/actions/runs/44662840108/job/136044961608) · [工件 14596169777](https://github.com/Luck9Star/herdr-pocket/actions/runs/44662840108/artifacts/14596169777) |
| Tauri Linux，WebKitGTK/Xvfb，`0ae850ea` | 拒绝新密钥并取消后保留旧信任。重探确认 B，最后一条两次认证尝试、一次成功。终端 OCR、主动断开、返回首页和清理通过。 | 同源码驱动强制真实 WebDriver 点击摘要、核对焦点及完整草稿，再点击口令框核对第二次收起。通过作业与驱动源码共同支撑这些检查。[驱动](https://github.com/Luck9Star/herdr-pocket/blob/0ae850eae4fc6aa492c1bf01304ee222f1907a5d/validation/remote-harness/tauri_linux_direct_ssh.py#L250-L268) | [作业 136038119946](https://github.com/Luck9Star/herdr-pocket/actions/runs/44660753647/job/136038119946) · [工件 14594674668](https://github.com/Luck9Star/herdr-pocket/actions/runs/44660753647/artifacts/14594674668) |
| Flutter Linux，GTK/Xvfb，`0ae850ea` 与 `2720e2f5` | 两次均保留旧信任并重探确认 B。错口令在客户端被拒绝，当时仅 A 探测且零认证。最后一条一次认证尝试、一次成功。终端 OCR、主动断开、返回首页、凭据清空和清理通过。 | `0ae850ea` 证实摘要点击和逐字读回。`2720e2f5` 的 `pemReopen` 四项均为真，覆盖摘要出现、实点后草稿逐字一致且获焦、再次收起，以及编辑器与其 Flutter 语义节点消失。[加强后的驱动](https://github.com/Luck9Star/herdr-pocket/blob/2720e2f536c69adbed9ce3f91d70e0466114af0d/validation/flutter/integration_test/linux_direct_ssh_test.dart#L263-L330) | [早期作业 136038119937](https://github.com/Luck9Star/herdr-pocket/actions/runs/44660753582/job/136038119937) · [早期工件 14596196132](https://github.com/Luck9Star/herdr-pocket/actions/runs/44660753582/artifacts/14596196132) · [严格复验 136049825334](https://github.com/Luck9Star/herdr-pocket/actions/runs/44664325486/job/136049825334) · [严格复验工件 14596687636](https://github.com/Luck9Star/herdr-pocket/actions/runs/44664325486/artifacts/14596687636) |

| 平台和作业源码 | 实测断点 | 官方来源 |
| --- | --- | --- |
| Flutter iOS，`939097e1` | 加密案已核对指纹并拒绝错口令。第二次尝试在 `encrypted_connect` 报 `StateError`，同源码第 617 行读取口令字段失败。加密夹具仅一条已关闭 A 探测，零认证、PTY 和收发。普通和密码换钥的终端证据与加密案独立。[字段读取](https://github.com/Luck9Star/herdr-pocket/blob/939097e17ffceef1ca5739f580eda36e4572932b/validation/flutter/integration_test/direct_ssh_ui_steps.dart#L611-L629) · [重试](https://github.com/Luck9Star/herdr-pocket/blob/939097e17ffceef1ca5739f580eda36e4572932b/validation/flutter/integration_test/direct_ssh_ui_steps.dart#L905-L929) | [作业 136034860976](https://github.com/Luck9Star/herdr-pocket/actions/runs/44659776085/job/136034860976) · [工件 14595348177](https://github.com/Luck9Star/herdr-pocket/actions/runs/44659776085/artifacts/14595348177) |
| Flutter Android API 35，`0ae850ea` | 加密案已拒绝错口令。最后完成的 `encrypted_rejected` 之后，正确口令字段的点击在同源码第 154 行因控件未就绪失败。工件没有足够细节定位候选缺失或遮挡。服务端仅一条已关闭 A 探测，零认证、PTY 和收发。[点击条件](https://github.com/Luck9Star/herdr-pocket/blob/0ae850eae4fc6aa492c1bf01304ee222f1907a5d/validation/flutter/integration_test/direct_ssh_ui_steps.dart#L143-L157) · [重试](https://github.com/Luck9Star/herdr-pocket/blob/0ae850eae4fc6aa492c1bf01304ee222f1907a5d/validation/flutter/integration_test/direct_ssh_ui_steps.dart#L950-L966) | [作业 136037669336](https://github.com/Luck9Star/herdr-pocket/actions/runs/44660617833/job/136037669336) · [工件 14596052057](https://github.com/Luck9Star/herdr-pocket/actions/runs/44660617833/artifacts/14596052057) |
| Tauri iOS R13，`1684d15e` | `encrypted_key_open_add` 阶段索引到 `163×22pt` 的 AX 候选，同时 XCUIScreen 原图在系统状态栏以下全白。快照在 9.531 秒已报告结构就绪，图像只证明其采样时刻的渲染状态。快捷入口点击未发生，对端零连接，私钥与口令阶段未运行。 | [作业 136036755995](https://github.com/Luck9Star/herdr-pocket/actions/runs/44660347850/job/136036755995) · [工件 14595039692](https://github.com/Luck9Star/herdr-pocket/actions/runs/44660347850/artifacts/14595039692) |
| Flutter macOS R3，`34c3e54c` | 四项运行，系统遮罩、密码 SSH、从首页重新进入后密码清空三项通过。加密案已观测原生口令字段输入，在第 281 行未证明私钥收起及唯一可命中摘要，整项作业失败。原生加密认证和摘要重开仍待验。[私钥门禁](https://github.com/Luck9Star/herdr-pocket/blob/34c3e54ce276ad52a43909ff582ddfdfd570502c/validation/remote-harness/macos_secure_xcuitest.swift#L265-L281) | [作业 136043832798](https://github.com/Luck9Star/herdr-pocket/actions/runs/44662494257/job/136043832798) · [工件 14596239411](https://github.com/Luck9Star/herdr-pocket/actions/runs/44662494257/artifacts/14596239411) |

### 第二批可恢复图像与工件

| 场景 | 可恢复图像 |
| --- | --- |
| Tauri Android | [换钥审查，CDP WebView PNG](followup/android-tauri-rotation/s10-host-key-change-android.png) · [回显，1080 × 2340 系统原屏](followup/android-tauri-rotation/ssh-rotation-terminal-android.png) |
| Tauri Linux | [换钥审查](followup/linux-tauri-rotation/rotation-rejected.png) · [回显](followup/linux-tauri-rotation/ordinary-terminal.png) · [首页，沿用同字节副本](linux-tauri/ordinary-home.png)。两张新增图均为 1440 × 1200 WebKitGTK 视口。 |
| Flutter Linux，严格复验 `2720e2f5` | [换钥审查](followup/linux-flutter-rotation/rotation-rejected.png) · [回显](followup/linux-flutter-rotation/ordinary-terminal.png) · [首页，沿用同字节副本](linux-flutter/ordinary-home.png)。两张新增图均为 1920 × 1080 X11 framebuffer。 |
| Tauri iOS R13 | [首页采样，1320 × 2868 系统原屏](followup/ios-tauri-r13/tauri-manual-key-empty-home.png) |

八份 ZIP 的 CRC 均有效，大小和 SHA-256 与官方工件记录一致，清单源码与 Actions 的工件关联 `head_sha` 一致。新增七张图经过 Vision OCR 与目视检查，检测到的长编码串位于公开主机指纹栏。Android 和 Linux 六张新增图保留原 PNG 字节。iOS R13 白屏图只移除 `eXIf` 和 `iTXt`，解码像素逐字节一致。两张 Linux 首页图与首批副本逐字节一致。其余图像在索引保留原成员哈希，可在工件保留期内下载原件。校验步骤见下文。 [第二批工件索引](official-followup-index.json) · [归档文件校验](SHA256SUMS)

## 第三批手机回执与 macOS 交接

Flutter 在 Android API 35 与 iPhone 11／iOS 26.2 模拟器的加密案直接提交三项私钥回执：失焦后收起、点击摘要后获焦且草稿逐字一致、再次失焦后收起。回执来自同源码的自动化交互。终端截图用于核对界面回显，私钥编辑和重开以回执为准。

| 场景与源码 | 原生运行和协议结果 | 官方来源 |
| --- | --- | --- |
| Flutter Android 独立加密，`2720e2f5`，第 2 次尝试 | 错口令本地拒绝。当时仅 A 探测，认证、PTY、shell 和收发均为零。第二条 A 连接一次公钥认证、一次 PTY 和 shell，输入 9 字节、累计输出 144 字节。Flutter 画面与 ADB 系统原屏均通过终端 OCR。两条连接均在驱动退出前关闭，凭据、剪贴板与测试资源已清理。 | [作业 136053359719](https://github.com/Luck9Star/herdr-pocket/actions/runs/44664325627/job/136053359719) · [工件 14597538810](https://github.com/Luck9Star/herdr-pocket/actions/runs/44664325627/artifacts/14597538810) |
| Flutter iOS 独立加密 R4，`9865dafa` | 本作业的普通密码、密码换钥和独立加密三案均通过终端 OCR。独立加密案错口令在本地被拒，第一条 A 探测零认证。第二条 A 连接一次公钥认证、一次 PTY 和 shell，精确输入 9 字节、累计输出 102 字节。主动断开、返回首页并清理，连接均在驱动退出前关闭。 | [作业 136061669086](https://github.com/Luck9Star/herdr-pocket/actions/runs/44667921130/job/136061669086) · [工件 14598134983](https://github.com/Luck9Star/herdr-pocket/actions/runs/44667921130/artifacts/14598134983) |
| Flutter Android 与 iOS 加密换钥，同源码 `9865dafa` | 两端均观察 A → B → B → B。拒绝 B，取消保留旧信任，重探并显式确认 B 后才认证。前三条零认证、PTY、shell 与收发。两端末条各一次公钥认证、一次 PTY 和 shell，输入 9 字节、累计输出 102 字节。系统原屏通过终端 OCR，主动断开、对端均提前关闭，凭据、剪贴板与测试资源已清理。 | Android [作业 136061803542](https://github.com/Luck9Star/herdr-pocket/actions/runs/44667958941/job/136061803542) · [工件 14599262098](https://github.com/Luck9Star/herdr-pocket/actions/runs/44667958941/artifacts/14599262098)；iOS [作业 136061804279](https://github.com/Luck9Star/herdr-pocket/actions/runs/44667959004/job/136061804279) · [工件 14599441889](https://github.com/Luck9Star/herdr-pocket/actions/runs/44667959004/artifacts/14599441889) |
| Flutter macOS R4，`55edd094` | 系统遮罩、密码 SSH、返回后重开通过。加密案完成四次收起状态核验与两次摘要重开；各阶段均有可命中摘要，未见私钥标头或正文。第二次点击原生口令后，Swift 第 883 行的单次键入读回失败，未完成加密认证。整项 3/4，无截图。 | [作业 136054326156](https://github.com/Luck9Star/herdr-pocket/actions/runs/44665701940/job/136054326156) · [工件 14597913708](https://github.com/Luck9Star/herdr-pocket/actions/runs/44665701940/artifacts/14597913708) |

Android 两次通过作业使用 Emulator 37.2.13（build 16740729）与 API 35 x86_64 rev 9。两次均记录验收正常结束、独占模拟器序列已移除。手机作业使用模拟器、受控回环和自动化输入。实体手机、物理输入法组字和真实外网未验证。 [作业版本、计数与清理索引](official-device-index.json)

macOS 本机用 Flutter 3.47.9 与可见 AppKit 窗口复现焦点被渲染视图取回。源 `572e0a6d` 修复后，在默认和启用辅助功能两种模式各两次实点摘要、完整重开并再次收起，再单次派发 AppKit 键入。原生和 Flutter 均读回，AppKit 本地辅助功能值仍为遮罩；过程使用隔离宿主与合成草稿。完整系统 XCUITest 与加密 SSH 复验见独立作业。 [前后布尔回执](device-receipts/macos-local-handoff.json)

### 第三批可恢复图像

| 场景 | 图像 |
| --- | --- |
| Flutter Android 独立加密／加密换钥 | [独立加密回显](device-receipts/android-ordinary-terminal.png) · [换钥后回显](device-receipts/android-rotation-terminal.png)，均为 1080 × 2340 ADB 系统原屏。 |
| Flutter iOS 独立加密／加密换钥 | [独立加密回显](device-receipts/ios-ordinary-terminal.png) · [换钥审查](device-receipts/ios-rotation-review.png) · [换钥后回显](device-receipts/ios-rotation-terminal.png)，均为 828 × 1792 模拟器系统原屏。 |

五张归档图经 Vision OCR 与目检，未发现私钥正文或可读口令。iOS 换钥审查图可见公开主机指纹。Android 两张 PNG 保留原字节，三张 iOS 图只移除 EXIF，解码像素与原件逐字节一致。其余图像保留原成员摘要，可按官方工件取回。 [第三批工件索引](official-device-index.json) · [归档文件校验](SHA256SUMS)

## 截图和源码

| 场景 | 截图 | 实测驱动 |
| --- | --- | --- |
| Flutter Windows，1024 × 705 Win32 客户区 | [终端](windows-flutter/ordinary-terminal.png) · [断开](windows-flutter/ordinary-disconnect.png) · [首页](../windows-ordinary-ssh-publickey-20261120/ordinary-home.png) | [`32e1a7c7` 私钥交互](https://github.com/Luck9Star/herdr-pocket/blob/32e1a7c7d1083d9d86119a2681e3b9213cce6fa8/validation/flutter/integration_test/windows_direct_ssh_test.dart#L422-L505) |
| Flutter Linux，1920 × 1080 X11 原屏 | [终端](linux-flutter/ordinary-terminal.png) · [断开](linux-flutter/ordinary-disconnect.png) · [首页](linux-flutter/ordinary-home.png) | [`8769fd5` 粘贴及逐字读回](https://github.com/Luck9Star/herdr-pocket/blob/8769fd50e6044d632a9427bd38c578a06dadd6fa/validation/flutter/integration_test/linux_direct_ssh_test.dart#L263-L306) |
| Tauri Linux，1440 × 1200 WebKitGTK 视口 | [终端](linux-tauri/ordinary-terminal.png) · [断开](linux-tauri/ordinary-disconnect.png) · [首页](linux-tauri/ordinary-home.png) | [`939097e1` 错／对口令共用驱动](https://github.com/Luck9Star/herdr-pocket/blob/939097e17ffceef1ca5739f580eda36e4572932b/validation/remote-harness/tauri_linux_direct_ssh.py#L250-L272) |
| Flutter iOS 模拟器，828 × 1792 系统原屏 | [普通密码终端](ios-flutter/ordinary-terminal.png) · [密码换钥后终端](ios-flutter/key-change-terminal.png) | [`8769fd5` 确认后回调](https://github.com/Luck9Star/herdr-pocket/blob/8769fd50e6044d632a9427bd38c578a06dadd6fa/validation/flutter/integration_test/direct_ssh_ui_steps.dart#L883-L905) |

归档图逐张检查画面和 OCR，未发现私钥正文或可读口令。图中端点和终端验证词来自公开合成夹具。桌面图保持原 PNG 字节，Windows 首页图与已有归档字节完全一致。两张 iOS 原屏图只移除 EXIF 块，解码像素逐字节一致。首轮 iOS 工件内的密码遮罩、换钥核对和 Tauri 首页图仍可按原 ZIP 取回。原图及 OCR 判据的 SHA-256 单独记录。[工件索引](official-index.json) · [归档文件校验](SHA256SUMS)

同尺寸合成对照使用 Flutter Widget 产品基线 `72afe632` 和 Tauri Playwright WebKit 产品基线 `8769fd5`。图片用于比较表单空间与摘要位置。Flutter 的修复前后对照使用同一配置和公开合成文本。[Flutter 修复前失焦图](../../../design/evidence/ordinary-ssh-pem-geometry-20261120/before-blur.png) · [Flutter 修复后失焦图](../../../design/evidence/ordinary-ssh-pem-geometry-20261120/after-blur.png)

| 视口 | Flutter Widget 摘要 | Tauri Playwright WebKit 摘要 |
| --- | --- | --- |
| 390 × 844 | [Flutter 手机图](../../../design/evidence/ordinary-ssh-pem-geometry-20261120/mobile-collapsed.png) | [Tauri 手机图](../tauri-pem-collapse-geometry-20261120/pem-collapsed-390.png) |
| 980 × 780 | [Flutter 桌面图](../../../design/evidence/ordinary-ssh-pem-geometry-20261120/desktop-collapsed.png) | [Tauri 桌面图](../tauri-pem-collapse-geometry-20261120/pem-collapsed-980.png) |

[Flutter 几何、源图和复跑](../../../design/evidence/ordinary-ssh-pem-geometry-20261120/README.md)覆盖 Widget 几何、语义树和焦点，含本机受控回环指纹探测。[Tauri 双尺寸探针与复跑](../tauri-pem-collapse-geometry-20261120/README.md)覆盖公开合成草稿、DOM 和焦点，使用合成 IPC。两项均属于本地界面证据。

## 校验和复跑

首批七个 ZIP 的大小、SHA-256 和源码 SHA 均与 GitHub Actions 工件记录一致。每个 ZIP 的 CRC 和 `result.json` 的源码、状态已复核，内图逐张核对原始报告的摘要。Windows 测试源码按检出时的 CRLF 核对，Linux Flutter 按 LF 核对。索引保留原报告哈希、判定和协议计数，原始报告和日志仍由首批工件链接提供。

在本目录执行下列命令。若 GitHub 工件仍在保留期，需使用有读取权限的 GitHub CLI。ZIP 存在于独立临时目录。

```sh
shasum -a 256 -c SHA256SUMS

artifact=14594141698
zip=$(mktemp)
gh api "repos/Luck9Star/herdr-pocket/actions/artifacts/$artifact/zip" > "$zip"
unzip -t "$zip"
shasum -a 256 "$zip"
unzip -p "$zip" result.json | shasum -a 256
```

将下载的 ZIP 和报告哈希与对应批次的索引比较。清单成员路径以 `manifestFile` 为准，第二批 Tauri Android 使用 `tauri-direct-evidence/manifest.json`，Flutter Android 使用 `direct-ssh-public/result.json`。 [首批工件索引](official-index.json) · [第二批工件索引](official-followup-index.json) · [第三批工件索引](official-device-index.json)

本地 Flutter 回归从目标提交导出到临时目录，使用 Flutter 3.47.9 和 Paramiko 4.0.0。几何测试使用本机临时 SSH 夹具，工作树无需切换。

```sh
set -eu
repo=$(git rev-parse --show-toplevel)
tmp=$(mktemp -d)
mkdir "$tmp/source"
git -C "$repo" archive 8769fd50e6044d632a9427bd38c578a06dadd6fa | tar -x -C "$tmp/source"
python3 "$tmp/source/validation/flutter/tool/ci.py" prepare --destination "$tmp/app"
python3 -m venv "$tmp/venv"
"$tmp/venv/bin/pip" install 'paramiko==4.0.0'
(
  cd "$tmp/app"
  flutter pub get --enforce-lockfile
  HERDR_FIXTURE_PYTHON="$tmp/venv/bin/python" \
    flutter test --no-pub test/direct_ssh_pem_geometry_test.dart test/direct_ssh_pem_collapse_test.dart
)
```

云端须用已授权的验收分支，先核对远端分支指向索引中的目标 SHA。每次选需复验的作业，参数和分支要求取决于目标工作流。以下 `ref` 是已存在的 `codex/` 验收分支名。

```sh
git ls-remote --exit-code origin "refs/heads/$ref"
gh workflow run windows-ordinary-ssh.yml --ref "$ref" -f authentication=publickey
gh workflow run paired-gui-validation.yml --ref "$ref" -f linux_direct_ssh=flutter-key
gh workflow run paired-gui-validation.yml --ref "$ref" -f linux_direct_ssh=tauri-key
gh workflow run flutter-macos-secure-xcui.yml --ref "$ref"
gh workflow run direct-ssh-android.yml --ref "$ref" -f auth_case=encrypted-key
gh workflow run direct-ssh-android.yml --ref "$ref" -f auth_case=encrypted-key-rotation
```

iOS 通过分支前缀选择必需路径。Flutter 使用 `codex/acceptance/direct-ssh-ios-flutter-only-encrypted-key-`，Tauri 使用 `codex/acceptance/direct-ssh-ios-tauri-only-encrypted-manual-`，后缀标识独立复跑。Flutter 独立加密还能因匹配 push 条件启动。加密换钥单案用 `codex/acceptance/direct-ssh-ios-flutter-only-encrypted-rotation-` 前缀，只接受手动调度。检查已有 run 后再决定是否调度。

```sh
gh workflow run direct-ssh-ios.yml --ref "$ios_ref"
```

复验时核对作业 SHA、设备、凭据交互门禁、服务端认证与 PTY 计数、终端 OCR、主动断开和清理。回环会话通过与私钥交互结果各自记录。
