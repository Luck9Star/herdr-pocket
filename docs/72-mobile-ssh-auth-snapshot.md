# 手机普通 SSH 核验与认证快照

2026-11-19，合并前复验覆盖 Android API 35 和 iOS 26.2 模拟器。Android 两壳与 Flutter iOS 的 R2、Tauri iOS 的 R7 均通过回环普通 SSH 和主机密钥更换验收。四个作业使用一致的产品源码及构建输入，分别保留实测提交。R2 之后的 Tauri iOS 驱动诊断、R22 入口批和 R23 本地核验保留在历史记录中。

各批沿用 [PR #4 的冻结设计](https://github.com/Luck9Star/herdr-pocket/pull/4)。画板提交为 `79deef0e9c03425f368966e32ff1f1d399a3ac02`。旧版 [15 状态前测](https://github.com/Luck9Star/herdr-pocket/blob/af273abca77fe97fd4806fe624dce89c6595869b/design/evidence/direct-ssh-mobile-20261118/baseline/README.md) 与[首批入口对照](https://github.com/Luck9Star/herdr-pocket/blob/af273abca77fe97fd4806fe624dce89c6595869b/design/evidence/direct-ssh-mobile-20261118/first-batch/README.md)提供独立参照。

## 合并前原生复验

### R2 联合复验

R2 四个作业使用 `bda3c59c7f6b4e5a4da119f26838bf511fbda780`。通过案例以独立回环 SSH 服务端核对认证、PTY、终端回显和关闭。证据 ZIP 的完整性及 SHA256 已与 Actions 工件核对。

| 壳与平台 | 结果 | 作业与工件 | ZIP SHA256 |
| --- | --- | --- | --- |
| Flutter Android API 35 | 普通、换钥通过 | [运行 44415430480](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430480/job/135194350049) · [证据 ZIP](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430480/artifacts/14480096265) | `65a6ae5e7410db187c04ca9006fa4ba4827bc1fb517114ec054bb4f9c513db64` |
| Tauri Android API 35 | 普通、换钥、独立加密私钥通过 | [运行 44415430496](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430496/job/135194348118) · [证据 ZIP](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430496/artifacts/14480765497) | `0db81a636e464589634cee3a53186649226e1490f0cf4a6370b277af87331ef0` |
| Flutter iOS 26.2，iPhone 11 模拟器 | 普通、换钥通过 | [运行 44415430176，Flutter 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430176/job/135194346642) · [证据 ZIP](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430176/artifacts/14479109985) | `30ab73fc32e11f0fdfc0c91a867d5b2d1eb4efbb700a69390707a7eee7ae5827` |
| Tauri iOS 26.2，iPhone 17 Pro Max 模拟器 | `app_install` 失败，两案均为 `not_run`，清理完成 | [运行 44415430176，Tauri 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430176/job/135194347041) · [证据 ZIP](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430176/artifacts/14479754075) | `902c514e0331a45d8eeb2fed50546d2cebc8806e1fcc718afbe7ba46dd2e6e15` |

通过的普通和换钥案例均记录了终端输入回显、主动断开和凭据清理。拒绝改变的密钥时服务端记录零认证，显式重探并确认后才连通。Tauri Android 普通与独立加密私钥均记录退回首页。两壳未在该批完成系统 IME、真机及真实跨网验收。

Flutter 认证页返回会取消尚未完成的 SSH 连接并清理临时凭据（`9b23ea5`）。Flutter iOS 作业中的 Widget 回归故意延迟回环握手，四条返回路径均在服务端留下零认证和零 PTY 记录，包括按键、系统返回、完成边缘滑动、取消滑动后按键。紧凑首页保留网络入口测试标识 `hosts-networks`（`5421861`），Widget 回归实点打开网络页并返回看板。两项分别覆盖 Widget 导航和回环连接取消。[Flutter iOS 作业及测试日志](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430176/job/135194346642)

### Tauri iOS R3–R6 诊断历史

R3 沿用 R2 的 `bda3c59`。iPhone 17 Pro Max 模拟器成功安装并启动应用，经空首页、接入选择进入普通 SSH 表单。检查点推进到 `ordinary_fingerprint`，驱动报 `native_control_owner_unproven`。回环服务端记录 1 条已关闭的探测连接，认证、PTY、Shell 和输入计数均为 0。普通案失败，换钥未运行，模拟器与夹具清理完成。证据 ZIP SHA256 为 `128d3a56fcede8c919da8dcc1916afa6f54205341f7845a000c1315cc81cf073`。[运行 44418471473](https://github.com/Luck9Star/herdr-pocket/actions/runs/44418471473/job/135204869805) · [证据 ZIP](https://github.com/Luck9Star/herdr-pocket/actions/runs/44418471473/artifacts/14480489482)

R4 固定 `5af0a97c932156a01fee9c54e75fcefd5a7edd59`。相对 R2／R3，差异仅在本文及 `validation/remote-harness/` 下的 Tauri iOS Python／Swift 驱动与对应两份测试。驱动把确认、密码和连接控件限定在已核验的 WebView 下，要求当前控件唯一且可命中。出现多个候选或身份变化时停止动作。应用源码、构建输入、工作流及其余三个作业的驱动在两提交间逐字节一致。其余三个作业的证据绑定 R2 的实测 SHA。

R4 在 iPhone 17 Pro Max 模拟器上完成安装、进入普通 SSH 表单并探测主机密钥。在 `ordinary_fingerprint` 检查点，驱动点击确认后已识别认证页标题、目标端点、确认提示和仍禁用的连接按钮。随后密码框归属核验报 `native_mobile_password_owner_unproven`，未进入 `ordinary_password`，也未尝试输入凭据。公开工件和作业日志没有报告该密码框的 AX 角色、矩形和候选唯一性判定明细，具体失败条件无法从记录确认。回环服务端在清理前后均记录 1 条已关闭的 A 探测连接，认证、PTY、Shell、输入和输出均为 0。普通案失败，换钥未运行，模拟器、夹具和临时文件均已清理。工件仅含 `result.json`，ZIP SHA256 为 `75a9918eab70d01fca3335bd05b8556b0129808b8d0071f09ae4973d11543f6b`。[运行 44422766316](https://github.com/Luck9Star/herdr-pocket/actions/runs/44422766316/job/135219720647) · [证据 ZIP](https://github.com/Luck9Star/herdr-pocket/actions/runs/44422766316/artifacts/14482933932)

R5 使用 PR #6 合并前提交 `9e0a2c2af80d1395618bc15496cdf0eb70a7d2b4`。相对 R4，代码变化只在 Tauri iOS Python／Swift 驱动及其两份测试。仓库中的应用源码、构建输入、工作流和其余三个作业的驱动与 R2 一致。其余三个作业的结果仍绑定 R2 的实测 SHA。R5 在限定时间内等待完整的认证页与密码控件观测，区分可等待的未就绪状态与必须立即停止的身份异常，并记录固定的脱敏失败码。

隔离环境的本地驱动套件通过 625 项，另有 5 项因环境条件跳过。Swift 回归用模拟时钟和合成 AX 快照依次呈现字段缺失、矩形无效、坐标变化和稳定控件，覆盖驱动等待及约束。该测试模拟一种控件时序，R4 实际的 AX 变化顺序和失败条件仍无可复核记录。

R5 完成应用构建及模拟器应用选择，随后停在 `xctest_build`，固定错误码为 `tauri_ios_xctest_build_failed`。脱敏工件定位到 `Driver.swift:1410:17` 的 `swift_compile_error`，未公开编译器错误文本。普通和换钥均为 `not_run`。工件保留夹具指纹，未记录服务端认证、PTY 或会话计数。模拟器、夹具和临时文件均已清理。工件仅含 `result.json`，ZIP SHA256 为 `e5a25f0f498f68589ca9bbc71a2662ef599221bf4f358cfb9625b1bb55a67e0f`。[运行 44426897288](https://github.com/Luck9Star/herdr-pocket/actions/runs/44426897288/job/135233950568) · [证据 ZIP](https://github.com/Luck9Star/herdr-pocket/actions/runs/44426897288/artifacts/14483954956)

R6 使用 PR #6 合并前提交 `04e58eed1a088e92d53a9b83d81cec26830fc495`。相对 R5，代码变化限于 XCTest 驱动闭包中的一处显式 `self` 引用及 Swift 测试替身的类语义。用同一引用语义替身和 Swift 5 模式编译抽取的驱动方法时，R5 版本报缺少显式捕获，R6 版本通过。该对照覆盖驱动的编译回归。其余三个作业仍沿用 R2 的实测 SHA。

R6 在 iPhone 17 Pro Max、iOS 26.2 模拟器编译并运行 XCTest 驱动，经空首页与接入选择进入普通 SSH 表单。普通探测已完成。驱动点击确认后，在 `ordinary_fingerprint` 检查点识别到认证页标题、目标端点、确认提示与禁用的连接按钮。等待窗口结束时，观测中没有匹配驱动预期标识或标签的密码控件，固定码为 `native_mobile_password_identity_missing`。未进入 `ordinary_password`，也未尝试输入凭据。公开记录缺少实际密码控件的 AX 角色、标识和矩形，无法确认控件实际状态或客户端原因。

普通案失败，换钥未运行。回环服务端在清理前后均记录 1 条已关闭的 A 探测连接，认证、PTY、Shell、输入和输出均为 0。模拟器、夹具和临时文件均已清理。工件仅含 `result.json`，ZIP SHA256 为 `304e6e1a8cb34c470fc7622b5df69c833a49d0798a49857bdf48c0ac1ce3f98d`。[运行 44429685294](https://github.com/Luck9Star/herdr-pocket/actions/runs/44429685294/job/135243553257) · [证据 ZIP](https://github.com/Luck9Star/herdr-pocket/actions/runs/44429685294/artifacts/14487242429)

### Tauri iOS R7 通过

R7 在 PR #6 合并前提交 `1c441c0cae12ccb00cea64dc9db09b0949626b39` 上运行，设备为 iPhone 17 Pro Max、iOS 26.2 模拟器。对比 R2 的 `bda3c59`，仓库差异限于本文、Tauri iOS Python／Swift 驱动及其两份测试。Android 两壳和 Flutter iOS 的实测提交仍为 R2。

本地 WebKit Inspector 在移动认证页测得标签 `密码 （仅本次使用）`，括号前包含一个 ASCII 空格 `U+0020`。该结果来自同产品源码的 macOS WebKit，iOS 的控件角色由 R7 原生作业另行验证。Swift 对照对旧映射重现该单空格标签无法命中，R7 映射通过，并拒绝重复候选、错误角色、错误 WebView 和双空格变体。R7 继续验证同窗同 WebView、唯一 `secureTextField`、身份、启用状态、几何及命中。失败诊断只导出预设的角色、标识或标签类别、计数和可命中性，原始 AX 名称、矩形及凭据不进入公开工件。

- 普通案经空首页的添加入口进入普通 SSH，核对 A 后使用密码认证。服务端记录 `A → A` 两条连接，首次探测零认证、零 PTY，第二条恰有一次认证成功、一次 PTY 和一次 Shell，收到一次完整终端输入行。明确断开后两条连接均已关闭。驱动验证回到空首页并显示「普通 SSH 已断开」。
- 换钥案同样经添加入口。服务端顺序为 `A → B → B → B`。B 第一次被拒绝，取消后保留 A，重探并明确确认 B。前三条连接均零认证、零 PTY，只有最后一条密码认证成功并建立 PTY 和 Shell，收到一次完整终端输入行。驱动明确断开，四条连接均已关闭。本案验收到断开。
- 两案均由 XCTest 输入一行夹具命令。服务端每案记录 9 字节输入、102 字节输出，系统截图的 OCR 均核对了标记和回显序列。证据包含两张终端原图、各自 OCR 门禁和一张换钥核对截图。模拟器、夹具及临时文件均已清理。

R7 验收范围为受控回环密码认证与 XCTest 输入。活动终端在三个底栏页之间切换时保活、实体设备、系统 IME 组词、真实跨网和 Tauri iOS 私钥认证仍待独立验收。原始 ZIP 经完整性及 SHA256 核验，摘要为 `f4c58ce8b68da11470348ea52ff22578722c590bfafd1f297a81990bc3cba4c5`。[R7 原生作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44450826220/job/135314034354) · [证据 ZIP](https://github.com/Luck9Star/herdr-pocket/actions/runs/44450826220/artifacts/14497110066)

长期归档保留三张 1320 × 2868 的系统截图。PNG 仅移除 EXIF 和文本块，解码像素一致。终端内的 `POCKET-ANDROID-SSH-OK` 是共用夹具的回显标记。[普通终端](evidence/mobile-ssh-auth-r23/tauri-ios-r7/ordinary-terminal.png) · [换钥核对](evidence/mobile-ssh-auth-r23/tauri-ios-r7/key-change-review.png) · [换钥后终端](evidence/mobile-ssh-auth-r23/tauri-ios-r7/key-change-terminal.png) · [来源、哈希与脱敏结果](evidence/mobile-ssh-auth-r23/tauri-ios-r7/official-index.json)

[后续活动终端与切页验证](73-mobile-ssh-terminal-navigation.md)记录两壳在本地回环中的看板、网络和设置往返，以及同尺寸键盘开合对照。

## Flutter Android 加密私钥独立验收

2026-11-19，[R5 作业 135408718366](https://github.com/Luck9Star/herdr-pocket/actions/runs/44479715559/job/135408718366)在 Android API 35 模拟器通过加密 OpenSSH Ed25519 私钥路径，源码为 `36a9228df84e344ff9f9f4b4e2fecd92dd177246`。此前上表的 Flutter Android R2 已覆盖普通密码和主机换钥；R5 是独立私钥单项，并未重复换钥。

| 入口和认证 | 指纹确认与错误口令 | 正确私钥与会话 | 图像与清理 |
| --- | --- | --- | --- |
| 真实首页进入，粘贴临时加密私钥并输入遮罩口令 | 首次核对前和错误口令后，首条探测均为零认证、零 PTY；错误口令本地拒绝 | 第二条连接仅一次公钥认证、一次 PTY 和 shell，服务端记录 9 字节输入与回显，主动断开且会话在驱动退出前关闭 | Flutter 和设备原图均通过独立 OCR 检查；凭据、剪贴板、临时输入、密钥、包、reverse、forward 和 fixture 清理均获记录 |

[证据索引、原图、结构化结果、哈希及 R1–R4 停点](evidence/flutter-android-encrypted-key-r5-20261119/README.md)。[原始 Actions 工件 14508621605](https://github.com/Luck9Star/herdr-pocket/actions/runs/44479715559/artifacts/14508621605) 的 ZIP SHA256 为 `b796cc238e1775384c836242d3212ec8d03c1d024267a43462fcaf3bd178199f`。终端输入使用 Flutter 测试文本输入；物理键盘、系统中文 IME、实体设备和跨网不属于该次通过范围。

## Flutter iOS 加密私钥独立验收

2026-11-19，Flutter iOS 专用 R1 作业在 iPhone 11 / iOS 26.2 模拟器完成普通密码、密码换钥与独立加密 OpenSSH Ed25519 私钥三案，XCTest 1 项通过。源提交为 `31a4bfd08fb2922a0dff8d8259858b87502bf928`，原始 ZIP 的 SHA256 为 `b56fc432ae53d65d10512069d90bc662a55da6b135bbe43771b9cda773fc5b13`。[作业 135459578044](https://github.com/Luck9Star/herdr-pocket/actions/runs/44494931219/job/135459578044) · [原始工件 14515586833](https://github.com/Luck9Star/herdr-pocket/actions/runs/44494931219/artifacts/14515586833)

加密私钥案从首页进入并明确核对主机指纹。密码与私钥两向切换均清除前一种输入，并保留同一主机信任。错误口令在客户端被拒绝，此时只有首次探测，服务端认证、PTY、shell 和收发均为零。正确私钥在第二条连接完成一次公钥认证、一次 PTY 和一次 shell，收到一行 9 字节的终端命令并回显 102 字节。主动断开后返回首页，两条连接都在驱动退出前关闭。记录确认凭据、剪贴板、临时输入、夹具和模拟器已清理。

原件索引见 ZIP 中的 `result.json`。三张 828 × 1792 的系统终端原图各有独立 OCR 记录，PNG 与 OCR 均可按各案 SHA256 核验。

| 案例 | 系统终端原图 | OCR |
| --- | --- | --- |
| 普通密码（`ordinary`） | `ordinary-terminal.png` | `ordinary-terminal-ocr.json` |
| 密码换钥（`keyChange`） | `key-change-terminal.png` | `key-change-terminal-ocr.json` |
| 独立加密私钥（`encryptedKey`） | `encrypted-key-terminal.png` | `encrypted-key-terminal-ocr.json` |

ZIP 同时保留 `key-change-review.png` 核对原图和 `preconnect.png` 已遮罩的连接前原图。私钥与主机换钥组合、实体设备、物理键盘、系统中文 IME 及真实跨网仍待独立验证。

## R22 Android 设备证据

两次作业使用受控 API 35 x86_64 模拟器与回环 SSH，均完成普通连接、主机密钥变化、终端回显和断开。两次使用不同源码，原始 ZIP 已完整重新下载并计算 SHA256。[可复核的运行、工件及内部结果索引](evidence/mobile-ssh-auth-r23/r22-actions.json)

| 壳 | Actions 与证据工件 | 源码 | ZIP SHA256 |
| --- | --- | --- | --- |
| Flutter | [运行 44340477284](https://github.com/Luck9Star/herdr-pocket/actions/runs/44340477284) · [工件 14445171169](https://github.com/Luck9Star/herdr-pocket/actions/runs/44340477284/artifacts/14445171169) | `543ecc8ae0651df92b386dfa7d2c72692ccb229a` | `391451a82be30baefcb182721fbf106b0ee4ac45e64e0418cc14731b6335f1ab` |
| Tauri | [运行 44343883721](https://github.com/Luck9Star/herdr-pocket/actions/runs/44343883721) · [工件 14446570463](https://github.com/Luck9Star/herdr-pocket/actions/runs/44343883721/artifacts/14446570463) | `3c3105f93fba702530adf4a038939b651205a7e1` | `6846507ee0e0dfdc4372bba7306bce3917aeba7910276d958d7a0247931fa02b` |

- Flutter 回环服务端记录密码认证、PTY、输入、会话关闭，以及变钥拒绝阶段零认证。普通和换钥两案的截图门禁均通过。作业的 `physicalImeVerified` 为 `false`。
- Tauri 普通与换钥案通过终端截图门禁，保留旧信任并重探后可显式连接。独立加密私钥路径连接、回显并断开。WebView 的 CDP 输入覆盖界面事件，系统输入法组词仍需设备验证。两壳均完成受检清理。

原始 ZIP 的工件保留期由 GitHub Actions 管理。上述结果只对应 R22 入口源码。其后的同源模拟器复验见上节。

## R22 iOS 托管容量

[第一次尝试](https://github.com/Luck9Star/herdr-pocket/actions/runs/44340477261/attempts/1)与[第二次尝试](https://github.com/Luck9Star/herdr-pocket/actions/runs/44340477261/attempts/2)均使用 `543ecc8ae0651df92b386dfa7d2c72692ccb229a`。两次的 Flutter、Tauri 作业均取消、零步骤、无分配运行器。GitHub 给出了 macOS arm64 容量及未分配 hosted runner 的注解，第二次 Flutter 作业无单独注解。该批停在托管调度阶段，没有构建、设备结果或工件。

## R23 本地核验与认证

当时的统一产品与驱动检查点为 `4dc37dd3d9c1c2df75b82cc432d0e1c28956d689`，基于 R22 的 `3c3105f93fba702530adf4a038939b651205a7e1`。Tauri 产品检查点为 `58df315783c3eadd8e2d2ac5b3403a9ced47fae9`，Flutter 产品检查点为 `3fdd11b39ffdb59693d20795acccb2944a9220d9`，原生驱动检查点为 `500b1553f4efa6340a218764cfcdbb500a773473`。两壳保留独立的目标填写、可阅读的实际算法和完整指纹、显式核验与取消，以及互斥的密码和私钥输入。失败或取消无法进入会话。主动断开清空本次凭据、保留目标，返回看板时显示一次反馈。

- Flutter 3.47.9 Widget 在受控真实回环上覆盖密码、未加密与加密 OpenSSH 私钥、错误口令重试、换钥拒绝、保旧与显式重探、PTY 和回显。纯空格密码在界面保持原样，夹具未使用它认证。几何使用注入的安全区、字体与 IME inset。
- Tauri WebKit 26.5 实点运行产品 DOM、CSS 和 xterm。探测公钥由独立回环采样，IPC 夹具重放连接、拒绝、回显和关闭事件，检查原样密码、完整密钥门槛、相同会话以及看板与配对。Node 666 项及生产构建通过。安全区和键盘外框为模拟值。

Flutter 在 Widget Navigator 上复现旧版断开后边缘拖动无法开始，修复后验证取消拖动保留页面、完成拖动才返回并显示一次反馈。系统返回和按键同样复核。该修复覆盖 6 项返回测试和 11 项定向回归，该批记录来自 Widget，原生手势仍待单独实点复验。Tauri 驱动使用当前页面的精确密码标签。本地原生驱动测试发现 628 项，跳过 5 项，失败 0 项。Swift 语法解析及 7 项针对性检查通过。

两壳均采用 320×640（上 24、下 24 pt）及 390×844（上 47、下 34 pt）。原 R23 中 Flutter 的 140 个已量应用锚点在 2 pt 内，18 个源未量锚点单列；Tauri 158 个已量应用锚点最大偏差 1 pt。原始坐标与中心命中记录见[本地量测和四对截图](evidence/mobile-ssh-auth-r23/README.md)。

2026-11-19，Flutter 在产品提交 `26d8abfcd25d78fa22d5ead31e58bc39cb6e34ca` 补量原先缺失的 18 项，两档各 9 项，逐坐标偏差均为 0 pt；定向测试提交 `e69d92bcd7dc8b3b37a3c2410fa51faa8487139c`。原 140 项与独立补采的 18 项合计覆盖 158 个应用锚点，并非同一次采样；[补测矩形、原尺寸截图与哈希](evidence/mobile-ssh-auth-r23/supplement-20261119/README.md)保留独立来源。物理键盘、中文 IME、原生状态栏与键盘几何、原生设备上的活动终端与设置往返、实体设备、外网与五平台就绪仍待补证；相关本地验证见 [docs/73](73-mobile-ssh-terminal-navigation.md)。

## 恢复与回滚

### 本地复跑

从仓库根目录运行。产品检查点为 `4dc37dd`，本地复跑固定到 `21f010a`。两个提交在 `validation/` 下只有夹具运行器有差异。新克隆若缺固定对象，先从 `origin` 取交付分支，再按完整 SHA 校验。脚本把固定源码导出到临时目录，当前工作树保留在原位。

准备已安装的 Flutter 3.47.9（framework `c197ca5199`）、Python 3.12 或更高版本及 `venv`、OpenSSH `ssh-keygen`、Node 和 npm。验证使用 Node 24.22.2、npm 12.2.1。依赖下载需可访问 pub.dev、PyPI 和 npm 注册表。Flutter 的 `ci.py prepare` 需要一个尚不存在的目标目录，它使用 SDK 生成隔离工程，校验并准备 `terminal_view` 参考渲染器和 IME 观测补丁。夹具运行器自行创建虚拟环境和临时回环身份。

```sh
(
  set -e
  replay=21f010af03705e5b272e78cc009e7a852381fcf0
  if ! git cat-file -e "${replay}^{commit}" 2>/dev/null; then
    git fetch origin refs/heads/codex/ssh-mobile-auth-integration
  fi
  git cat-file -e "${replay}^{commit}"

  isolated="$(mktemp -d)"
  src="$isolated/source"
  project="$isolated/flutter-app"
  mkdir "$src"
  git archive "$replay" validation > "$isolated/source.tar"
  tar -xf "$isolated/source.tar" -C "$src"
  printf '复跑目录 %s\n' "$isolated"
  flutter --version

  (cd "$src/validation/tauri" && npm ci && npm test && npm run build)
  python3 "$src/validation/flutter/tool/ci.py" prepare --destination "$project"
  (cd "$project" && flutter pub get --enforce-lockfile)
  python3 "$src/validation/flutter/tool/direct_ssh_fixture_runner.py" --project "$project"
)
```

Flutter 四组依次通过 32 项普通 SSH、2 项换钥、5 项手机认证与 6 项断开和返回。运行器还独立检查服务端认证、PTY、输入和密钥变化时的认证门槛。

### 原生 CI 复验

原生作业在 GitHub Actions 内准备 Flutter SDK，并执行 `candidate.py apply` 与 `verify-lock`。候选依赖只允许在 CI 生成的工程中应用。本地 Widget 复跑使用上面的参考依赖。

复跑 Tauri iOS R7 时选择 `platform=ios-tauri-only`，只触发 Tauri 作业。复跑 R2 时使用表中的 `bda3c59`，`platform=ios` 触发 iOS 两壳，`platform=android` 触发两个 Android 工作流。每次将 `attempt` 设为尚未使用的分支后缀。推送即调度一次。[iOS 工作流](../.github/workflows/direct-ssh-ios.yml) · [Flutter Android 工作流](../.github/workflows/direct-ssh-android.yml) · [Tauri Android 工作流](../.github/workflows/tauri-android-direct-ssh.yml)

```sh
(
  set -e
  checkpoint=1c441c0cae12ccb00cea64dc9db09b0949626b39
  if ! git cat-file -e "${checkpoint}^{commit}" 2>/dev/null; then
    git fetch origin refs/heads/codex/ssh-mobile-auth-integration
  fi
  git cat-file -e "${checkpoint}^{commit}"
  platform=ios-tauri-only
  attempt=replay-r7-1
  git push origin "${checkpoint}:refs/heads/codex/acceptance/direct-ssh-$platform-$attempt"
)
```

核对所选作业的源码、步骤、设备、服务端计数、截图及清理。托管队列再次零步骤时，保留调度记录并停止追加同批尝试。

需要回到入口批次时，以 R22 检查点新建本地恢复分支，保留 R23 草稿与证据。

```sh
git switch -c codex/replay/mobile-ssh-entry-r22 3c3105f93fba702530adf4a038939b651205a7e1
git rev-parse HEAD
```

共享分支已纳入新批次时，先在独立工作分支审查并回退 R23 的产品与驱动合并提交，保留历史记录和其他变更。以 R22 检查点核对回退范围，再按待验平台重新取证。
