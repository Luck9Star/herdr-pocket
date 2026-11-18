# iOS 普通 SSH 与主机换钥验收

状态：2026-11-18，**R21 Tauri 定向复验（运行 44326045427，源 `cdbb41a`）通过：普通与换钥均通过、冷启失败未复现、按钮几何与 R20 一致；R20 官方批次（运行 44320783638，源码 `d28ed26`）：Flutter 普通 SSH 与换钥均通过（返回首页仅在普通场景验证）；Tauri 普通 SSH 通过、底部按钮遮挡已消除，换钥在重新冷启后 `native_home_identity_unproven` 失败，已由 R21 收口**。R19 同源批次两壳普通 SSH 与换钥均通过，作为对照保留；R18、R17、R15 及更早结果保留为历史。

范围为 GitHub 托管 macOS 上的受控 iOS Simulator、临时 loopback SSH 和密码认证。模拟器安装、应用界面、服务端协议、完整测试通过及最终画面复核分别记录；本页不证明 iPhone 真机、手工／中文 IME、外部网络、生产主机或五平台支持。

## R21 Tauri 定向复验：普通与换钥均通过

R20 换钥失败的定向复验批次：源码 [`cdbb41ac5878ff93a88cbf0fcdb5088f9dc0473b`](https://github.com/Luck9Star/herdr-pocket/commit/cdbb41ac5878ff93a88cbf0fcdb5088f9dc0473b)（验收测试代码），[Actions 运行 44326045427](https://github.com/Luck9Star/herdr-pocket/actions/runs/44326045427)，`status=passed`、`stage=complete`、`nativeCheckpoint=key_change_disconnect`。工件 `tauri.zip`（SHA256 `c17aa0ec…48d8f5c`）与逐文件校验见 [R21 官方证据归档索引](evidence/ios-ssh-20261118/r21-official-index.json)。运行于 iPhone 17 Pro Max / iOS 26.2 Simulator。

普通案例：AA 两连接可数（探测零认证；末条 auth 1/1、PTY/shell、9B 输入／102B 回显、主动断开全关闭）；OCR 三判据通过；断开后点击「看板」验证返回首页（`return_home` →『还没有主机』→ ready，`ordinary_returned_home` 放行）。换钥案例：ABBB 四连接可数（探测、拒绝、重探零认证；确认 B 后末条 auth 1/1、PTY/shell、9B/102B、全关闭）；`cancelKeptTrust=true`、`freshFingerprintConfirmed=true`；rotationEvidence stage2（2 连接取消保留 A）→ stage3（3 连接重探 B）→ stage4（4 连接确认后认证）；终端与 review 两图 SHA 与 result 一致，OCR 三判据通过；**换钥场景无 return_home 步骤，仅证主动断开（`key_change_disconnect`）**。`homeReadiness`/`homeEntry` 为各案例冷启进入 SSH 前的首页导航数据（ordinary shell 715ms→ready 12498ms；keyChange 1464ms→2773ms），不代表断开后状态；R20 的 `native_home_identity_unproven` 未复现（样本一次；两次冷启 shell→ready 不证明曾触发 R20 未识别首帧分支）。清理 `simulatorDeleted/fixturesClosed/privateFilesRemoved` 全真；`navigationTrace.credentialsEmpty` 为冷启导航时点断言；活动终端截图未见凭据，取消／重探时相应字段为空；断开后未单独检查凭据字段。本批无 `physicalImeVerified` 字段，不声称物理 IME。

独立像素测量（与 R19/R20 同法）：R21 两张终端图导航上缘行仍为 2571，左按钮下边框行 2543–2545，净空约 26px（≈8.7 逻辑点），与 R20 一致、未见回归。R21 仅 Tauri；Flutter 无本批（R20 已通过，返回首页验证仅普通场景）。

## R20 官方结果：Flutter 通过；Tauri 换钥冷启失败（已由 R21 收口）

同一源码 [`d28ed2603677147907e24bf392b6ab9aa25aeef7`](https://github.com/Luck9Star/herdr-pocket/commit/d28ed2603677147907e24bf392b6ab9aa25aeef7)（与本地验收提交 `20aeb16` 同 patch；产品布局修复 [`19f867e`](https://github.com/Luck9Star/herdr-pocket/commit/19f867e) 与本地 `ba8fcb7` 同 patch，基线 `f378e9a`）的 [Actions 运行 44320783638](https://github.com/Luck9Star/herdr-pocket/actions/runs/44320783638)：[Flutter 作业 134858825151](https://github.com/Luck9Star/herdr-pocket/actions/runs/44320783638/job/134858825151) 通过至 `returned_home`；[Tauri 作业 134858825773](https://github.com/Luck9Star/herdr-pocket/actions/runs/44320783638/job/134858825773) 普通案例通过、换钥失败，整批 `failed`。完整映射见 [R20 官方证据归档索引](evidence/ios-ssh-20261118/r20-official-index.json)。

Flutter 普通与换钥均通过：换钥 ABBB 四连接可数（探测、拒绝、重探均零认证；确认 B 后末条认证、PTY/shell、回显、关闭）；两张终端原图 OCR 三判据通过；清理五项全真、`peerClosedBeforeDriverExit=true`；`physicalImeVerified=false`。顶层 `deviceStage=returned_home` 与首页返回验证仅属普通场景，换钥场景未测试返回首页。

Tauri 普通案例通过：AA 两连接可数（探测零认证；末条认证、PTY/shell、9 字节输入／102 字节回显、主动断开关闭）；OCR 三判据通过。换钥在 `key_change_form` 阶段失败：重新冷启后 317ms 首页身份未证实（`native_home_identity_unproven`、`error=tauri_ios_native_check_failed`），未进入表单；服务端 before/afterCleanup 均 0 连接无残留。失败阶段与 SSH 协议无关；该失败已由 R21 定向复验收口（见上节）。

R20 官方原图同时收口 R19 遗留的底部按钮遮挡：独立像素测量（非控件推算）R19 与 R20 两张 Tauri 普通终端原图底部导航上缘同为第 2571 行（约 857 逻辑点）；R19 按钮边框被导航截断不可见（文字行延至 2545，与 R19 记录的约 8 点遮挡一致），R20 两按钮下边框行 2543–2545 完整可见，距导航上缘净空约 26px（约 8.7 逻辑点）；辅助键行整体上移约 20 逻辑点，PTY 25×46→24×46。同尺寸本地模拟 IPC WebKit 前后图已入库（[r20-webkit-before-ios-r19.png](evidence/ios-ssh-20261118/r20-webkit-before-ios-r19.png)、[r20-webkit-after-ios-r19.png](evidence/ios-ssh-20261118/r20-webkit-after-ios-r19.png)，几何数值与完整 JSON SHA 见 [r20-local-webkit-index.json](evidence/ios-ssh-20261118/r20-local-webkit-index.json)）；该夹具为模拟传输，不代表 iOS 系统证据。Flutter 侧同批另有协作方交接报告的 37 件定向既有测试与 3 个几何探针随源运行（本审计未独立复算，仓库可数的集成 `testWidgets` 为 18 项，口径以协作方报告为准）；本机 Node 658／Python 73 项等见 R19 记录，不重复罗列。

## R19 同源结果：两壳通过，活动标题与顶栏分离

同一源码 [`58fe474384fe7aa644f41b1662d2919100cb0842`](https://github.com/Luck9Star/herdr-pocket/commit/58fe474384fe7aa644f41b1662d2919100cb0842) 的 [Actions 运行 44278328784](https://github.com/Luck9Star/herdr-pocket/actions/runs/44278328784) 完成：[Flutter 作业 134712097532](https://github.com/Luck9Star/herdr-pocket/actions/runs/44278328784/job/134712097532) 与 [Tauri 作业 134712098125](https://github.com/Luck9Star/herdr-pocket/actions/runs/44278328784/job/134712098125) 均通过。两份结果均为 `passed`；Flutter 为 iPhone 11、Tauri 为 iPhone 17 Pro Max，均为 iOS 26.2 Simulator。此前本机检查分别为 Node 658 项、Python 73 项和 Swift 5 项通过，不替代官方设备作业。

两壳服务端均记录普通 AA 与换钥 ABBB：探测、拒绝和重新探测阶段零认证、PTY、shell 与输入输出；取消保留 A，重新探测并明确确认 B 后，最后一条 B 才认证、取得 PTY／shell 并回显，最终主动断开且连接关闭。两壳各两张终端原图的标记、八词及连续顺序 OCR 均通过，原图与判据哈希相符；审查图不运行终端 OCR。[R19 官方证据归档索引](evidence/ios-ssh-20261118/r19-official-index.json)提供两壳结果、原图与判据的映射。

Tauri 普通和换钥终端原图均记录：系统栏下缘 `y=54` 点，品牌与添加按钮上缘 `y=80`，相距 26 点；固定顶栏下缘 `y=130`，页面 H2 上缘 `y=161`，相距 31 点；目标上缘为 `y=246`。普通与换钥两次首页就绪观察分别为 25.822 秒和 1.444 秒，这只是本批采样，不代表性能保证。

Tauri 两张自然终端截图底部的「打开键盘」和「断开连接」按钮边框末约 8 点被底部导航遮挡；文字可见、实际点击通过，也可滚动查看。这一剩余视觉问题与本批 SSH、OCR 及顶栏几何结果分别记录，不称为界面完全无缺陷。

本批仅覆盖受控 iOS 模拟器、loopback 与密码认证，不证明实体 iPhone、手工／中文输入法、外网生产主机或五平台就绪；Flutter 记录 `physicalImeVerified=false`。两壳受检清理通过。

## R18 历史结果：Tauri 冷启动首页未进入 SSH

[运行 44271043975](https://github.com/Luck9Star/herdr-pocket/actions/runs/44271043975) 的 Flutter 通过；Tauri 在 `ordinary_form / ordinary_open_add` 报 `native_home_identity_unproven`，普通案例失败、换钥未运行，未进入 SSH。该观察不足以归因为某条原生命令；R19 是独立后续批次。

## R17 同源结果：两壳通过，活动顶栏已分离

源码 [`023124f907554807b6a781f44569f05f7ea1ac51`](https://github.com/Luck9Star/herdr-pocket/commit/023124f907554807b6a781f44569f05f7ea1ac51) 的 [Actions 运行 44256953094](https://github.com/Luck9Star/herdr-pocket/actions/runs/44256953094) 中，[Flutter 作业 134640823640](https://github.com/Luck9Star/herdr-pocket/actions/runs/44256953094/job/134640823640) 与 [Tauri 作业 134640824084](https://github.com/Luck9Star/herdr-pocket/actions/runs/44256953094/job/134640824084) 均成功。两份 `result.json` 同为 `status=passed`，分别运行于 iOS 26.2 的 iPhone 11 和 iPhone 17 Pro Max Simulator。

普通连接的 AA 与换钥 ABBB 均由服务端记录：探测与拒绝阶段无认证、PTY、shell 或输入输出；用户确认后连接的末条会话认证成功、输入及回显，最后主动断开。换钥拒绝后取消保留 A，重新探测并明确确认 B 后才连接。两壳各两张终端图的 OCR 均通过标记、八词和连续顺序检查，原图与判据 SHA256 相符；审查图不作终端 OCR。

Tauri 的普通与换钥终端原图均记录同一窗口／WebView 的品牌、添加按钮与系统栏：系统栏下缘为 `y=54` 点，品牌和添加按钮上缘均为 `y=80` 点；两个控件完整位于安全区内。三张 Tauri 原图：[普通终端](evidence/ios-ssh-20261118/r17-tauri-ordinary-terminal.png) · [换钥审查](evidence/ios-ssh-20261118/r17-tauri-key-change-review.png) · [确认 B 后终端](evidence/ios-ssh-20261118/r17-tauri-key-change-terminal.png)。该证明覆盖这两张活动终端图的顶栏与系统状态栏分离；页面已有滚动时，通用 H2 标题仍可能被固定栏部分遮挡。R17 不证明其已解决；后续 R19 的活动页面几何见本页开头。

两壳结果、原图与 OCR 文件的来源、映射及哈希见 [R17 官方证据归档索引](evidence/ios-ssh-20261118/r17-official-index.json)。

本批限于模拟器、受控 loopback 和密码认证，不代表 iPhone 真机、手工／中文输入法、外网生产环境或五平台验收。Flutter 记录 `physicalImeVerified=false`；两壳受检清理通过。

## R16 历史结果：换钥重连未完成

[运行 44252632619](https://github.com/Luck9Star/herdr-pocket/actions/runs/44252632619) 中 Tauri 最后完成 `key_change_password_b`，随后在 `key_change_connect` 等待目标文本时报告 `native_expected_text_missing`；普通案例通过，换钥案例失败。已有审查截图、取消保留 A 与重新探测 B 的证据，但该结果没有最终第四连接的公开服务端快照，不能据此确定重连失败原因。R17 是独立后续同源批次。

## R15 历史同源结果：两壳均通过

同一源码 [`4c0ec6554538b00001224694734d2dd73892b967`](https://github.com/Luck9Star/herdr-pocket/commit/4c0ec6554538b00001224694734d2dd73892b967) 的 [Actions 运行 44248995630](https://github.com/Luck9Star/herdr-pocket/actions/runs/44248995630) 完成。以下是受控模拟器上的该次结果；两作业各自构建，不是同一个二进制。

| 客户端 | 官方作业与工件 | 模拟器 | 结果 |
| --- | --- | --- | --- |
| Flutter | [作业 134614777786](https://github.com/Luck9Star/herdr-pocket/actions/runs/44248995630/job/134614777786) · [工件 14403298345](https://github.com/Luck9Star/herdr-pocket/actions/runs/44248995630/artifacts/14403298345) | iPhone 11，iOS 26.2 | `status=passed`；XCTest 1 项通过、0 项失败；`layoutOverflows` 为空。 |
| Tauri | [作业 134614777774](https://github.com/Luck9Star/herdr-pocket/actions/runs/44248995630/job/134614777774) · [工件 14403502869](https://github.com/Luck9Star/herdr-pocket/actions/runs/44248995630/artifacts/14403502869) | iPhone 17 Pro Max，iOS 26.2 | `status=passed`，普通和换钥案例均 `passed`。 |

两壳均通过普通 AA：第一次 A 探测无认证、PTY、shell 与输入输出；第二次 A 经用户确认后认证、打开 PTY 与 shell、输入并显示远端回显，最后由界面主动断开。换钥采用同一目标 ABBB：A 初次探测、B 拒绝和 B 重新探测三条均无认证、PTY、shell 与输入输出；拒绝后取消保留 A，再重新探测并明确核对 B，第四条 B 才认证、输入与回显，最后主动断开。成功会话各有认证尝试／成功 1 次、PTY／shell 各 1 次、输入 9 字节、输出 102 字节；各连接最终关闭。Flutter 记录的 UI 断开确认与 Tauri 的 `disconnected=true` 分别来自各自驱动；服务端闭合是独立证据。

两壳各有普通终端、换钥审查、B 确认后终端三张系统原图，以及两份终端 OCR。已核对本次下载文件与各自结果中的 SHA256：四份 OCR 均绑定对应原图，`markerVisible`、`tokenVisible`、`proofSequenceVisible` 均为 `true`，引擎为 Tesseract 5.5.4。审查图用于设计画面复核，不运行终端 OCR；这些技术检查与下述原图目检分别记录。Tauri 的两张终端图以同窗控件限定候选带，再由原图内收实际终端背景用于 OCR。

| 客户端／场景 | 系统原图 SHA256 |
| --- | --- |
| Flutter 普通 | `d2e58aab638b83c95eb5fb1392139a82f88176545fd5e74580ad02fc1fefb02c` |
| Flutter 换钥审查 | `76cd3457b4224774d236afddc5ea98b9b9cfc71e3060224e4344b9f46ad6aaa5` |
| Flutter 换钥终端 | `71030b9c9dd51a7b09a7c7747f3b34e1aaf6df0c90d54c111d7d2df4b810e4af` |
| Tauri 普通 | `3186054bb898d15bf13f96613f6be08c7eeb419493725babcbf9c0529aef76bc` |
| Tauri 换钥审查 | `5a20cf6e3c05c27161a90b7b0f9afb9561ffaa45f400ad4f886130b4cce322e3` |
| Tauri 换钥终端 | `1943179d971615b8500e0b7ac525d13d7d2a418450696e412736da2fa97a2b52` |

两份 `result.json` 的 SHA256 分别为 Flutter `e21e0bf668fe5f38ce6fe634d5eec2e05e1cb85b7f7d86aac9702adc1bb2783a`、Tauri `181b70b11c85e85f5afe262f38ac2982766b5224c6eefc8b712821bba509bac6`。两壳报告的模拟器、fixture 和私密文件清理均成功；Flutter 还报告工具退出、临时应用删除及未上传原始日志。R15 两壳原文件的来源、文件名映射与 SHA256 见[官方证据归档索引](evidence/ios-ssh-20261118/r15-official-index.json)。Actions 工件有到期时间（当前元数据为 2027-02-16），作业链接不保证工件永久可下载。

原图目检确认两壳核心场景可见：Tauri 的 S10 审查页标题、指纹和两个操作按钮完整；普通连接及换钥后的终端目标、键盘操作与回显完整。另发现独立的 Tauri iOS 显示缺陷：这两个活动终端画面的通用顶栏中，系统时钟遮挡品牌，Wi-Fi／电池区域遮挡「添加主机」按钮上缘。该缺陷不改变本批 SSH 协议和 OCR 结果；后续 R17 活动终端顶栏复验见本页开头。

本批仅证明指定 iOS 模拟器、loopback 夹具和密码认证下的自动化场景；不证明真实 iPhone、物理键盘或手工／中文输入法、外网及生产主机，也不证明五平台生产就绪。Flutter 明确记录 `physicalImeVerified=false`。

## R6 历史同源结果：Flutter 通过，Tauri 表单仍未证实

本地修复提交为 [`9c9f93d37d503dc27ef4cf840fb39f554e59e64b`](https://github.com/Luck9Star/herdr-pocket/commit/9c9f93d37d503dc27ef4cf840fb39f554e59e64b)：真实驱动先确认控件存在并取得有效快照，再读取元数据；非空标识优先精确匹配，无命中才按标签，避免空 identifier 误选或正确标识与同名标签取并集导致歧义。端口、checkbox 与密码值按已知类型处理，兼容数值／placeholder，未知对象不再当作空值或已清空凭据。

本地反例覆盖空标识、唯一标识与同名标签并存、缺失／歧义控件、端口与 stepper／label 区分、checkbox 0／1、空密码／placeholder 及未知 value。主控独立 **87 项 iOS 检查通过**，Swift 语法、工作流与空白检查通过；本地检查与下述官方运行分别判断。[R6 官方同批 44043428381](https://github.com/Luck9Star/herdr-pocket/actions/runs/44043428381) 使用同一源码，已完成；本次授权仅追加这一批，未因 Tauri 失败继续重跑。

| 客户端 | 官方作业／工件 | 官方结果 | ZIP 字节数／SHA256 |
| --- | --- | --- | --- |
| Flutter | [作业 133903241512](https://github.com/Luck9Star/herdr-pocket/actions/runs/44043428381/job/133903241512) · [工件 14311845519](https://github.com/Luck9Star/herdr-pocket/actions/runs/44043428381/artifacts/14311845519) | 成功；普通／S10／换钥重连、XCTest 与受检清理通过。 | 673,644 · `89654bd5ec7695d367b2d52d8f89d3fb529002c9f0d9a65437d62813a52e3b29` |
| Tauri | [作业 133903241041](https://github.com/Luck9Star/herdr-pocket/actions/runs/44043428381/job/133903241041) · [工件 14311980335](https://github.com/Luck9Star/herdr-pocket/actions/runs/44043428381/artifacts/14311980335) | 失败；停在 `ordinary_open_ssh / native_ssh_form_unproven`，尚无认证及终端验收。 | 2,016 · `edb46ca21ac23f3a38edda6f0c3359bb46e68192ff6adb9f4544af49dd7c8632` |

[来源与各文件哈希清单](evidence/ios-ssh-20261117/r6-official-index.json)记录源码、运行、作业、官方 ZIP 及七份原文件的大小和 SHA256；已与官方元数据、下载 ZIP 和解包原字节逐一核对。归档文件加客户端前缀区分来源，原始 JSON 不改写，内层文件名与归档名的映射见清单。

| Flutter 场景 | 系统原图（828×1792） | 原字节判据／画面复核 |
| --- | --- | --- |
| 普通 SSH | [ordinary-terminal](evidence/ios-ssh-20261117/r6-flutter-ordinary-terminal.png) | [OCR](evidence/ios-ssh-20261117/r6-flutter-ordinary-terminal-ocr.json)；目标 `fixture@127.0.0.1:49478`，两行词串为 `FADE PAST LEAF DECK`／`STAR LEAF DUSK PART`。 |
| S10 拒绝页 | [key-change-review](evidence/ios-ssh-20261117/r6-flutter-key-change-review.png) | 旧／新完整指纹和重新核对／取消按钮已目检；只作设计复核，不执行终端 OCR。 |
| 确认 B 后重连 | [key-change-terminal](evidence/ios-ssh-20261117/r6-flutter-key-change-terminal.png) | [OCR](evidence/ios-ssh-20261117/r6-flutter-key-change-terminal-ocr.json)；目标 `fixture@127.0.0.1:49483`，两行词串为 `DUSK HAVE SEAT STAR`／`HEAT PART SALT SAND`。 |

[Flutter 完整结果](evidence/ios-ssh-20261117/r6-flutter-result.json)记录 iOS 26.2／iPhone 11 Simulator。普通 AA 与换钥 ABBB 的前置探测／拒绝传输均零认证／PTY／shell／输入输出；两个末条会话才各有认证尝试／成功 1 次、PTY／shell 各 1 次、输入 9、输出 102 字节，主动断开并关闭。两份 OCR 的 `imageSha256` 与原图一致，三个像素判据均为 `true`；主控另以目视与 Apple Vision 核对当次目标及八词，归档者也已逐张目检。`physicalImeVerified=false`，系统软键盘呈现不等于手工输入法或真机验收。

[Tauri 未完成结果](evidence/ios-ssh-20261117/r6-tauri-result.json)记录：页眉添加按钮首次未进展，随后 `emptyAdd` 的真实点击进入 `addChoice`，再真实点击 `sshChoice`。后一采样的输入数从 0 增为 4，SSH 标题存在、添加页标题消失，前台且无弹窗，仍为 2 个窗口、3 个 WebView AX 节点；但 `formByStructure=false / formOwnerResolved=false`，四个必需表单控件的身份与同窗归属未全部证实，故停止。聚合的 4 个输入不能替代主机地址、端口、用户名及探测按钮的逐项证明；现有报告不能定位具体哪项控件，也不支持空白页面或产品连接失败的结论。没有 Tauri 认证／终端截图，不能用 Flutter 或本机 macOS 的通过补足。

后续定位应只针对这四项分别记录角色、候选数量、稳定标签／非空标识、实际位置及所属窗口／共同 WebView 祖先，再与当前表单身份核对。此为后续诊断建议，本轮不实现或新启 CI。两壳受检清理通过；公开 JSON 只有脱敏状态／计数／几何／固定错误码，未见密码值、私钥或原始日志。三张原始 PNG 的 EXIF 仅含色彩空间与尺寸信息，保持原字节；遮盖预连接附图和历史重复图片均未加入本次归档。

## R5：Flutter 完整通过，Tauri 仅取得首轮诊断

统一源码为 [`bda9834f53910861bfb379b269060152cd221713`](https://github.com/Luck9Star/herdr-pocket/commit/bda9834f53910861bfb379b269060152cd221713)，[同批运行 44036481852](https://github.com/Luck9Star/herdr-pocket/actions/runs/44036481852)。两份官方工件的源码、下载 ZIP 大小与 SHA256 均已核验。

| 客户端 | 官方作业／工件 | R5 实际结果 | ZIP 字节数／SHA256 |
| --- | --- | --- | --- |
| Flutter | [作业 133880471778](https://github.com/Luck9Star/herdr-pocket/actions/runs/44036481852/job/133880471778) · [工件 14308101356](https://github.com/Luck9Star/herdr-pocket/actions/runs/44036481852/artifacts/14308101356) | 作业与公开结果通过，iOS 26.2／iPhone 11 Simulator，XCTest 1 项通过、0 项失败；普通／S10／换钥重连三图、两份终端判据与受检清理齐全，`layoutOverflows` 为空。 | 670,758 · `9eb763ac1f0723459ee69b63c94ec0d7de9a0ff93b315b7a22bb7f4478eb3523` |
| Tauri | [作业 133880471294](https://github.com/Luck9Star/herdr-pocket/actions/runs/44036481852/job/133880471294) · [工件 14308655631](https://github.com/Luck9Star/herdr-pocket/actions/runs/44036481852/artifacts/14308655631) | `ordinary_form / ordinary_open_add`，固定错误码 `tauri_ios_xctest_failed`；普通／换钥未验收，场景工件为空，受检清理通过。 | 1,192 · `c6e2f9a8eda1325e9a28834fa32946cc5d2fa12be4cd03ba5ad5b744cd403f05` |

Flutter 独立服务端普通 AA／换钥 ABBB 顺序成立；各探测／拒绝阶段认证、PTY、shell、输入／输出均为 0，两个末条会话各认证尝试／成功 1 次、PTY／shell 各 1 次、输入 9、输出 102 字节，最终关闭。两份终端判据的原图哈希与结果清单一致，Tesseract 5.5.4 的三个像素判据均为 `true`。`physicalImeVerified=false`，本批不证明手工输入法或真机。

Tauri 的首个 `homeDiagnostics` 仅记录前台应用、1 个窗口、3 个 WebView AX 节点及 0 个 alert；所有已知首页成员计数为 0，`knownEmptyHome=false`。这是首轮原生树采样，不能据此确认实际首页已显示，也不能认定应用为空白页、资源加载失败或某个具体标签导致失败。`ordinary_open_add` 是当前驱动阶段，不等于已点击添加按钮；R3／R4 的首页证据及下述 macOS 复核均不能替代本次 iOS 运行事实。

## 独立 macOS WebKit 产品交叉复核

本机复核使用既有 **`HerdrNativeR3.app` 临时原生 Tauri 产品快照**，原可执行文件 `herdr-pocket-tauri-probe` 的 SHA256 为 `ab277801afb20143e94368008be588569f7dd1a4d928b1c2e17bcd408457e61e`。该二进制未独立绑定到某个完整源码提交，不能称为当前 R6 或正式发布包。只复制快照，将其中唯一一处 23 字节编译配置标识与 bundle ID 改为独立的 `dev.herdrpocket.v63d42e`，随后本机 ad-hoc 重签，以隔离应用数据；原 R3 目录及原作者窗口保持不动。改标识／重签的本机包不是官方 iOS 二进制。

真实窗口从 **`tauri://localhost` 内嵌页面**打开，使用产品原生 Rust SSH 路径及私有回环 peer，没有浏览器模拟 SSH 响应。实际完成添加入口、普通指纹核对与密码认证、终端回显及主动断开；另完成同一目标 A→B 拒绝、取消保留 A、重新探测并明确确认 B、重新输入密码、连接及主动断开。普通 AA 与换钥 ABBB 各阶段均由独立服务端确认，两个成功会话各认证 1 次、PTY／shell 各 1 次、只用一次原生文本输入发送 `hp-check` 加换行；各输入 9、输出 102 字节，`singleMarkerLineExact=true`。三次换钥前置传输均零认证／PTY／shell／输入输出，所有传输最终关闭；实际窗口可见目标、回显及两组独立词串。

| 本机真实 AX 元素 | 实际观察 | 与 iOS 驱动比对的边界 |
| --- | --- | --- |
| 主机地址／用户名 | 各为带相应中文标签的 text field。 | 不是旁边的中文 label 文本节点。 |
| 端口 | number field，初值 22，内含 stepper。 | 工具显示的角色和值不能证明 iOS 的 XCUI enum 或底层 value 对象类型；不能把端口 label 当可编辑字段。 |
| 指纹确认 | checkbox，未确认／确认值为 0／1；取消后 disabled 且为 0，重新探测 B 后可用但仍为 0。 | 保留明确确认要求；macOS 观察不替代 iOS checkbox 的类型核验。 |
| 密码 | secure text field；合成密码输入后显示圆点，尝试后及断开后为空，已连接时节点消失；S10 取消后字段存在但 disabled 且空。 | 空字段的 AX 存在不等于秘密泄露；同时核对清空、锁定与实际可见状态。 |
| 连接／断开 | “连接 / 重新连接”“断开连接”均为实际 button；点击断开后回表单，peer 记录正常关闭。 | 精确选中正确动作；未配置标识时不得用任意空 identifier 代替目标标签。 |
| 终端／S10 | 终端为“SSH 终端输出”容器及“Terminal input”文本输入区；S10 标题有 heading 和文本叶节点，旧／新指纹、目标各为独立文本，两出口均为 button。 | 不把正常父／叶语义重复当作两份独立内容；macOS 无 iOS 软键盘，未验证 iOS 键盘窗口或遮挡规则。 |

上述本机验证不使用个人 SSH 身份，不保存实际密码或私钥。独立应用已退出，两个 peer 已停止，临时应用副本及该唯一标识的 Application Support／Caches／WebKit 数据目录已删除；只保留脱敏复核记录。本机图片未重复归档；当时 R6 只归档 Flutter 三张官方场景图，R15 两壳原图另见本页开头的索引。

## 本机源码绑定复核：普通 SSH 表单四项控件

本节只补足上节缺的两点：宿主与源码／构建的绑定，以及四项控件在本机真实 WKWebView 中的确切形态。R6 的 iOS 原结论（Flutter 完整通过、Tauri 表单身份与同窗归属仍未全部证实）不变；本节是本机 macOS 观察，不补足也不替代 iOS 缺项。

绑定方式为从当前工作树重建：分支 `codex/tauri-ios-form-identity`，提交 `a803a3ad1af3`；`validation/tauri` 源码按 SHA256 核对后复制到独立临时目录，`npm ci && npm run build` 生成前端，`npm run tauri -- icon icon.svg` 生成图标，`cargo build --offline --features tauri/custom-protocol` 生成 arm64 原生二进制（未启用 `tauri/custom-protocol` 时宿主走 devUrl、窗口空白，不能用作核验宿主）。本次加载的前端即由当前源码新构建；工作树内既有的本机 `dist` 产物字节与之不同，未被本次运行加载。宿主以独立标识与隔离 HOME 启动；核验以 AX 只读读取为主，另对主机地址、端口、用户名三项做合成值的实写与独立读回，未接触真实主机、SSH 密钥或个人身份。

| 控件 | 本机真实 AX 形态 | 可编辑／可用 |
| --- | --- | --- |
| 主机地址 | `AXTextField`，无 subrole；可访问名来自 `<label>` 包裹产生的 `AXTitle` | 可编辑；改值后独立 AX 读回一致 |
| 端口 | `AXTextField`（非 AXNumberField／AXComboBox／AXSlider），无 subrole | 可编辑；改值后独立 AX 读回一致 |
| 端口 stepper | `AXIncrementor` 是该端口 `AXTextField` 的**子节点**，两个 `AXIncrementorArrow`（subrole 分别为 `AXIncrementArrow`／`AXDecrementArrow`）又是 stepper 的子节点 | stepper 自身的 `AXValue` 恒为 `0`，与输入框实际值不同步，不能据其判断端口值 |
| 用户名 | `AXTextField`，无 subrole | 可编辑；改值后独立 AX 读回一致 |
| 探测主机指纹 | `AXButton`，无 subrole，`AXEnabled=1`，可用动作 `AXPress` | 启用且可按；点击后落到原生探测分支并给出失败反馈 |

四项控件的 `AXIdentifier` 均为 nil：本机 WebKit 未把 HTML `id` 映射为 AX 标识，控件只能靠标签文本与结构识别。标签文字以独立 `AXStaticText` 呈现并与输入框同窗；四项控件同属一个 `AXWindow`（`AXStandardWindow`，标题「Herdr Pocket」），父链一致：`AXWindow → AXScrollArea → AXWebArea(desc=herdr-pocket · 远端终端原型) → AXGroup(AXLandmarkMain) → AXGroup(AXLandmarkForm) → 字段容器 → 控件`。

端口改写走普通用户输入途径，改值后由独立的 AX 属性读取复核；另经 stepper 上箭头 `AXPress` 改值，同样复核一致。探测按钮的点击落到 `src/direct-ssh-ui.js:138` 之后的原生探测分支（`$('ssh-probe').disabled = !native`，浏览器预览下该按钮为禁用），点击后得到失败反馈。本轮表单写入使用合成占位值并已清除，未建立 SSH 会话、未使用任何密钥；只取得失败反馈，未验证指纹成功路径、主机密钥轮换，也未做任何 iOS 复核。

最终驱动的选中口径：按 XCTest 控件角色与名称匹配控件，并要求与目标表单同窗、同 WebView；以真实表单标题证明归属时，允许窗口列表中另存在无关 Web 窗；命中错窗，或仅匹配到标签文字／按钮文字而无对应控件时，判为拒绝。失败时四项控件各自保留独立结果，不因单项失败整体弃置。主控随后在本机重跑：iOS 相关 93 项通过（`python3 -m unittest discover -s validation/remote-harness -p 'test_*ios*.py'`），另有 17 项 SSH 夹具通过（`test_direct_ssh_fixture_deadline.py` 与 `test_direct_ssh_rotation_fixture.py`）；本轮未新增 iOS 端到端验证。

逐项字段、角色、父子关系、哈希绑定与步骤见 [本机表单身份 JSON](evidence/ios-ssh-20261117/local-macos-form-identity.json)。核验后应用已退出，临时构建树、target 目录、应用封装与日志全部删除；既有 `dist` 未改动。

## R4：夹具守卫与导航报告门槛受阻

统一源码为 [`80acd9af3477702852543d71033ec9e609ef9a15`](https://github.com/Luck9Star/herdr-pocket/commit/80acd9af3477702852543d71033ec9e609ef9a15)，[同批运行 44025958192](https://github.com/Luck9Star/herdr-pocket/actions/runs/44025958192)。两项作业均失败，须分别判断停止层级：

| 客户端 | 官方作业／工件 | R4 已证实边界 |
| --- | --- | --- |
| Flutter | [作业 133846225390](https://github.com/Luck9Star/herdr-pocket/actions/runs/44025958192/job/133846225390)；无正式 Flutter 设备工件。 | CI 宿主的 `test_peer_cancel_closes_before_deadline_without_authentication` 观察到 `socket_error`，未满足当时只允许 `peer_eof / transport_closed` 的夹具测试断言。Python guard 阶段失败；Flutter 准备、构建与模拟器设备步骤均跳过，不能据此作本批设备连接或界面结论。 |
| Tauri | [作业 133846225590](https://github.com/Luck9Star/herdr-pocket/actions/runs/44025958192/job/133846225590) · [工件 14304077315](https://github.com/Luck9Star/herdr-pocket/actions/runs/44025958192/artifacts/14304077315) | 正式应用及原生驱动已运行。`headerAdd` 的真实中心点击后记录 `after.page=addChoice`；后续为 `ordinary_open_ssh / tauri_ios_home_retry_unsafe`，普通／换钥均仍为 `not_run`，没有 SSH 场景图。 |

Tauri 原始导航记录的屏幕为 **440×956 pt**；添加按钮矩形为 **[334, 78, 91, 44] pt**，中心 **(379.5, 100) pt**；所属可见区域为 **[0, 54, 440, 902] pt**。点击时 `enabled / hittable / ownerResolved / centerVisible` 均为 `true`，结果进入添加方式页，且 `noAlerts / noKnownErrors / credentialsEmpty` 仍为 `true`。`windowCount` 从 **1 变为 2**，WebView AX 节点数仍为 **3**。

固定源码 [Python 导航 guard](https://github.com/Luck9Star/herdr-pocket/blob/80acd9af3477702852543d71033ec9e609ef9a15/validation/remote-harness/tauri_ios_direct_ssh.py#L517) 对每条导航报告的前态强制 `windowCount == 1`，因此下一步报告被拒绝。窗口数量变化本身不能证明产品目标错位或凭据风险，也不确定新增窗口的具体来源。原生点击在报告发送前执行，缺少第二条有效报告不能进一步证明第二次触摸或 SSH 表单的实际结果；本批真实 SSH 会话仍未验收。

官方与下载原字节相符的 Tauri ZIP 为 **1,626 字节**，SHA256 为 `989548fbe3440312756793802e1175bbbf8c136589647bf7c4aa69e10caa9a41`，内层 `sourceSHA` 相符，受检清理通过。本批不新增正式图片归档，最终两壳六张系统原图仍待官方完整通过后整理。

## R3：换钥局部完成，普通连接与首页点击受阻

统一源码为 [`d5f6da062e28ade57c685faed96a848b7f82162c`](https://github.com/Luck9Star/herdr-pocket/commit/d5f6da062e28ade57c685faed96a848b7f82162c)，[同批运行 44020819913](https://github.com/Luck9Star/herdr-pocket/actions/runs/44020819913)；两壳均失败。两份官方工件的源码、ZIP 大小与 SHA256 已独立核验。

| 客户端 | 官方作业／工件 | R3 实际完成与失败边界 | ZIP 字节数／SHA256 |
| --- | --- | --- | --- |
| Flutter | [作业 133829627237](https://github.com/Luck9Star/herdr-pocket/actions/runs/44020819913/job/133829627237) · [工件 14301965991](https://github.com/Luck9Star/herdr-pocket/actions/runs/44020819913/artifacts/14301965991) | 换钥 ABBB 四检查点与终端原图／OCR 通过；普通连接在 `await_terminal` 失败，只有第二条 A 完成握手，认证尝试／成功、PTY、shell、输入／输出均为 0，全部连接最终关闭。没有普通终端图。 | 476,285 · `6d7a8fc5246f83e0f7211ac85eb30c87211f1a12cafdb6e1b3013cc8e1ca5325` |
| Tauri | [作业 133829627481](https://github.com/Luck9Star/herdr-pocket/actions/runs/44020819913/job/133829627481) · [工件 14300864652](https://github.com/Luck9Star/herdr-pocket/actions/runs/44020819913/artifacts/14300864652) | 原生诊断已见首页内容；`ordinary_open_add` 报 `native_home_add_did_not_open_page`，点击后未观察到添加页。普通／换钥仍为 `not_run`，无 SSH 场景图。 | 1,270 · `3e6ad04a06a083b363cd99abb11976cf5ea0398550619b6332709a5b2e471d49` |

R2 到 R3 的 Flutter 产品／测试文件及 iOS 宿主驱动均无源码变化；这不保证每次运行条件相同，也不能用 R2 的普通连接通过补足 R3。本次换钥前三条仍零认证／PTY／shell／输入输出，末条认证尝试／成功各 1 次、PTY／shell 各 1 次、输入 9、输出 102 字节，全部关闭。换钥终端 `imageSha256=fbe0962ec12c18105cea347baf7ad330cb4696e6e91997bafde54f7897c77f62`，三个像素判据均为 `true`；`layoutOverflows` 为空，不将本次普通连接失败写成 R1 的 58px 溢出复发。

Tauri 的 `homeDiagnostics.ordinary` 在本轮采样中记录前台应用、1 个窗口、3 个 WebView AX 节点；页眉添加按钮、空列表添加按钮、普通 SSH 快捷各 1 个，另见首页标题与零主机文本。应用／系统 alert 均为 0。由此可确认本次首页内容已进入原生可访问性树；不能仅凭节点计数确认触摸命中、事件执行或具体未跳转原因，也不能反推 R2 的实际原因。

离线夹具延迟 10 秒的复现与新增截止时间回归属于**候选因果及修复验证**。它们不能单独证明 R3 第二条 A 的关闭时间或真实关闭原因；仍须用新批次的客户端阶段、独立服务端证据及完整终端图验收。两壳本次受检清理通过，R3 图片继续保留官方入口，未提前归档为最终交付。

## R2：Flutter 通过，Tauri 首页入口检查受阻

统一源码为 [`b0596340d05aac3d3c223af7df41e119f376b243`](https://github.com/Luck9Star/herdr-pocket/commit/b0596340d05aac3d3c223af7df41e119f376b243)，专用分支 `codex/acceptance/direct-ssh-ios-s10-r2-20261117`，[同批运行 44015612863](https://github.com/Luck9Star/herdr-pocket/actions/runs/44015612863)。官方工件元数据、下载 ZIP 与内层 `sourceSHA` 均已核验。

| 客户端 | 官方作业／工件 | 实际结果 | ZIP 字节数／SHA256 |
| --- | --- | --- | --- |
| Flutter | [作业 133812707983](https://github.com/Luck9Star/herdr-pocket/actions/runs/44015612863/job/133812707983) · [工件 14299192105](https://github.com/Luck9Star/herdr-pocket/actions/runs/44015612863/artifacts/14299192105) | 作业与公开结果均通过；XCTest 1 项通过、0 项失败，三张主要系统原图、两份终端像素判据和受检清理齐全。 | 665,517 · `4c834677a5f8dd4bcaeec4168c89b7767fca17e8ab69c1d6d12dcf31a12d79a0` |
| Tauri | [作业 133812708002](https://github.com/Luck9Star/herdr-pocket/actions/runs/44015612863/job/133812708002) · [工件 14298539936](https://github.com/Luck9Star/herdr-pocket/actions/runs/44015612863/artifacts/14298539936) | 正式应用与 XCTest 测试程序已构建并启动；`stage=ordinary_form`，`nativeCheckpoint=ordinary_open_add`，`nativeFailureCode=native_control_missing`。普通／换钥仍为 `not_run`，无场景图；清理通过。 | 885 · `505cd8940ce53fae25304a0de7a9598de8d2733fd84aaf8144ad158777e68af0` |

Flutter 实际为 **iOS 26.2 / iPhone 11 Simulator**。普通 AA 共 2 条连接，首条零认证／PTY／shell／输入输出；末条认证尝试／成功各 1 次、PTY／shell 各 1 次、输入 9、输出 102 字节，全部关闭。换钥 `rejected`、`cancelled`、`reprobed`、`complete` 四个检查点齐全，仍为 A／B／B／B：前三条零认证／PTY／shell／输入输出，末条才各 1 次认证、PTY／shell，输入 9、输出 102 字节，全部关闭。取消前后连接数仍为 2；确认 B 不自动连接，不重放旧输入。

Flutter 三张原图均为 **828×1792**，已目测核对当次目标、终端回显与各场独立词串，S10 的旧／新指纹及重新核对／取消按钮可读。两份终端判据均由 Tesseract 5.5.4 对相应原字节核验，`imageSha256` 与清单一致，`markerVisible`、`tokenVisible`、`proofSequenceVisible` 均为 `true`。S10 拒绝页只做设计画面复核，不作为终端 OCR 样本。

| R2 Flutter 系统原图 | 原字节 SHA256 |
| --- | --- |
| `ordinary-terminal.png` | `660e19a490e60153850c2c1c31abfd8178059e13079ff71c41be4b5b6ea9d701` |
| `key-change-review.png` | `336b2f9dbdfb4612d965845ec38453d40df299f96e763be4d1e93d95240ec196` |
| `key-change-terminal.png` | `36fc092d2f9d0d28d7a0997defa46a840a3a315394a2f1e5ebc65b1d27122352` |

Tauri 记录 **Xcode 16.4 / Simulator SDK 18.5 / iOS 26.2 / iPhone 17 Pro Max Simulator**。本次已越过 R1 的测试程序构建失败，但首个“添加主机”原生查询未找到预期控件，尚未进入 SSH 场景。仅凭该错误不能确定网页加载、WKWebView 标签映射或其他具体原因；构建配置和入口假设仍需运行时证据验证，不能写成已证实根因。

R2 仍是自动化模拟器输入，`physicalImeVerified=false`；Flutter 结果确认模拟器删除、fixture 关闭、工具退出及临时应用／私密文件删除，`rawLogsUploaded=false`。本页暂保留官方工件链接与哈希，不提前归档 R2 原图为最终交付；两壳同一最终新源码完整通过后，再整理各三张正式系统原图与对应判据。

## R1 官方来源

统一源码为 [`230f20ec5cd8c3d834c8272c302d28159a40f825`](https://github.com/Luck9Star/herdr-pocket/commit/230f20ec5cd8c3d834c8272c302d28159a40f825)，专用分支为 `codex/acceptance/direct-ssh-ios-s10-r1-20261117`。同一次 [Actions 44011843657](https://github.com/Luck9Star/herdr-pocket/actions/runs/44011843657) 中两项作业均为 `failure`；公开证据上传步骤均成功，上传成功不改变验收失败结论。

| 客户端 | 官方作业与工件 | R1 已证实范围 | 尚未完成 |
| --- | --- | --- | --- |
| Flutter | [作业 133800454447](https://github.com/Luck9Star/herdr-pocket/actions/runs/44011843657/job/133800454447) · [工件 14297033858](https://github.com/Luck9Star/herdr-pocket/actions/runs/44011843657/artifacts/14297033858) | 普通终端、S10 拒绝页、确认新 key 后的终端均有系统原图；两份终端 OCR 通过；独立服务端普通 AA 与换钥 ABBB 阶段完成，受检清理通过。 | XCTest 1 项失败，布局溢出未消除；不能认定整条通过。 |
| Tauri | [作业 133800454765](https://github.com/Luck9Star/herdr-pocket/actions/runs/44011843657/job/133800454765) · [工件 14297501756](https://github.com/Luck9Star/herdr-pocket/actions/runs/44011843657/artifacts/14297501756) | 正式 arm64 Simulator `.app` 构建、平台／架构检查与安装完成；受检清理通过。 | `stage=xctest_build`、`error=tauri_ios_command_failed`；普通与换钥均为 `not_run`，没有界面图或 SSH 场景通过结论。 |

实际作业日志记录宿主镜像为 `macos-15-arm64`、Xcode **16.4**；Flutter 结果记录 **iOS 26.2 / iPhone 11**。Flutter 三张主要系统原图均为 **828×1792**。宿主镜像名称与 workflow 的 `runs-on: macos-15` 分别记录，不把 runner 标签当作设备型号。

两份完整 ZIP 已按下载原字节重算，大小、SHA256、工件元数据及内层 `sourceSHA` 相符：

| 官方工件 | ZIP 字节数 | ZIP SHA256 | `result.json` 字节数／SHA256 |
| --- | --- | --- | --- |
| Flutter `14297033858` | 812,326 | `8805dd4f05601451c23bfdabbc595e30c13087d675852ea34eb54cd6368a37bb` | 14,958 · `cb3637f146a1e8c3d04c71d315e64e72c96db333aea657ab90f989c938f638b8` |
| Tauri `14297501756` | 574 | `e6ba62e3a0f26523f5b61e852d578d19a6355b41d6d54ff3dbbcf4d753c25f9d` | 773 · `31c778df7d9145c98611c91eb86561877c4a2da00de39a5e040bdde376255463` |

本页保留官方工件入口，不重复归档 R1 图片。Flutter 工件另含既有遮盖凭据预连接图 `preconnect.png`；它不替代三张主要场景图或终端像素判据。

## Flutter 已取得的场景证据

| 场景 | 系统原图与判据 | 独立服务端与画面结论 |
| --- | --- | --- |
| 普通 SSH | `ordinary-terminal.png` · `ordinary-terminal-ocr.json` | 两条 A 连接：首条仅探测，认证／PTY／shell／输入输出均为 0；第二条认证尝试／成功各 1 次、PTY／shell 各 1 次、输入 9、输出 102 字节，最后均关闭。原图可读当次 `fixture@127.0.0.1:49447`、远端回显与本场两行词串。 |
| S10 拒绝与取消 | `key-change-review.png`；仅作设计画面复核，不运行终端 OCR。 | 第 1 条 A、第 2 条 B，均已关闭且零认证／PTY／shell／输入输出；取消后仍为 2 条连接。原图中旧／新完整 SHA256 指纹、同一目标、重新核对与取消保留旧信任两个按钮均可读；未见凭据入口。 |
| 明确复核 B 后重连 | `key-change-terminal.png` · `key-change-terminal-ocr.json` | 第 3 条 B 为新探测，仍零认证／PTY／shell／输入输出；第 4 条 B 才成功认证，认证尝试／成功各 1 次、PTY／shell 各 1 次、输入 9、输出 102 字节，最后均关闭。原图可读 `fixture@127.0.0.1:49449`、远端回显与另一组本场词串。 |

上述输出字节数是服务端成功发送的 shell 应用数据；是否显示另由系统原图证明。两份终端判据均为 Tesseract **5.5.4**，`markerVisible`、`tokenVisible`、`proofSequenceVisible` 均为 `true`，并以 `imageSha256` 绑定对应原图；目标像素判据与场景采样亦为通过。回显使用跨平台夹具共用的 `POCKET-ANDROID-SSH-OK` 标记，名称不代表此次运行在 Android。

| Flutter 系统原图 | 原字节 SHA256 |
| --- | --- |
| `ordinary-terminal.png` | `c157d3bc045f0677e9b1b30a200cb1ca16c475c384dafdbf73c02469d1890107` |
| `key-change-review.png` | `dda9e82f118bf62a81c2be6f69143e496b20bfb550fc035e7b3ff11b491ae2da` |
| `key-change-terminal.png` | `588f2e31d67ee553523d1768da45308d593a7bdbb89d3ba220b875a0d0c2013d` |

换钥客户端记录另确认取消保留旧信任、确认前凭据锁定、重新探测 B、明确确认 B、不自动连接，以及断开后凭据清空。ABBB 检查点 `rejected`、`cancelled`、`reprobed`、`complete` 均存在。三张采样帧和这些阶段事实不覆盖测试末尾的全部布局状态。

## R1 失败的准确边界

Flutter 的 `status=failed`、`failureCode=ios_device_test_failed`，捕获阶段为 `disconnect_exception`，最后宿主阶段为 `await_driver_exit`。XCTest 记录 **1 项执行、0 项通过、1 项失败**；`launchFailed`、`installFailed`、`timedOut`、`crashed` 均为 `false`。`frameworkDiagnostic.excerpt` 明确记录 **`A RenderFlex overflowed by 58 pixels on the bottom.`**，溢出方向为底部；不凭 XCTest 截短文本猜测方向。

捕获位置对应该源码 [断开流程后的 `tester.takeException()` 检查](https://github.com/Luck9Star/herdr-pocket/blob/230f20ec5cd8c3d834c8272c302d28159a40f825/validation/flutter/integration_test/direct_ssh_ui_steps.dart#L213)。这说明异常在此检查被取出，不足以证明布局缺陷首次发生在断开动作，也不足以定位具体溢出组件；布局根因须由后续复现、修改和新批次证明。不能因服务端已关闭、OCR 已通过或清理成功而忽略这项失败。

Tauri 的正式应用构建成功与 XCTest 测试程序构建失败属于不同层。公开结果仅给出固定失败码，没有保存未审原始构建输出；其两个场景均未运行、`artifacts` 为空。R1 不支持关于 Tauri 首页、S10、终端像素或换钥协议成功的推断，也不将构建失败原因的猜想记为已证实根因。应用可执行文件 SHA256 为 `a985e7827874fd6afa1805d31cee7948fe0e3ccdcc9b03110fabb276f27245bf`，它只标识本次正式应用，不代表 UI 验收通过。

Flutter 结果确认模拟器删除、fixture 关闭、工具退出、临时应用与私密文件删除，且 `rawLogsUploaded=false`；Tauri 结果确认模拟器删除、fixture 关闭与私密文件删除。公开工件未包含临时密码、私钥或原始测试日志。

## R1 本机检查与历史验收计划

R1 前的本机检查记录为：Flutter **594 项通过、7 项跳过**，独立点击测试 **2 项通过**；Tauri 前端 **641 项通过**；本轮 iOS 驱动／守卫 **65 项通过**，换钥 fixture **5 项通过**。跳过不计通过，这些检查不替代系统应用运行。

R1 时的后续计划为同一新源码一次触发两壳，完整验证普通 SSH、S10 拒绝／取消／重新核对／确认 B 后重连及清理，再逐图核验各三张系统原图与两份终端判据。当时工作止于上文 R6 的部分完成结果；后续 R15 结果见本页开头，R1 的局部完成事实与失败记录继续保留。

相关历史：[普通 SSH 与界面设计](63-design-parity-and-direct-ssh.md) · [Android 换钥专项](68-android-ssh-host-key-rotation.md) · [Android 活动终端像素验收](69-mobile-ssh-active-terminal.md)。这些历史结果不补足本次 iOS 的缺项。
