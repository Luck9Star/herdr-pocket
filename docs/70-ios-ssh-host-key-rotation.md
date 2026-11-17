# iOS 普通 SSH 与主机换钥验收

状态：2026-11-17，**本次唯一获准追加的 R6 同源批次已结束：Flutter 完整通过，Tauri 表单身份与同窗归属仍未全部证实，两壳同批未通过**。已归档该批 Flutter 三张场景原图、两份 OCR、两壳结果和来源哈希清单；本轮收尾不再追加 CI。独立 macOS Tauri／WKWebView 产品快照的闭环只作本机交叉复核，不补足 iOS 缺项；R1–R5 历史结果继续保留。

范围为 GitHub 托管 macOS 上的受控 iOS Simulator、临时 loopback SSH 和密码认证。模拟器安装、应用界面、服务端协议、完整测试通过及最终画面复核分别记录；本页不证明 iPhone 真机、手工／中文 IME、外部网络、生产主机或五平台支持。

## R6 最终同源结果：Flutter 通过，Tauri 表单仍未证实

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

上述本机验证不使用个人 SSH 身份，不保存实际密码或私钥。独立应用已退出，两个 peer 已停止，临时应用副本及该唯一标识的 Application Support／Caches／WebKit 数据目录已删除；只保留脱敏复核记录。本机图片未重复归档；本轮最终归档见上文 R6，只有 Flutter 三张官方场景图，尚无 Tauri 三图。

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

R1 时的后续计划为同一新源码一次触发两壳，完整验证普通 SSH、S10 拒绝／取消／重新核对／确认 B 后重连及清理，再逐图核验各三张系统原图与两份终端判据。实际本轮止于上文 R6 的部分完成结果，未继续触发；R1 的局部完成事实与失败记录继续保留。

相关历史：[普通 SSH 与界面设计](63-design-parity-and-direct-ssh.md) · [Android 换钥专项](68-android-ssh-host-key-rotation.md) · [Android 活动终端像素验收](69-mobile-ssh-active-terminal.md)。这些历史结果不补足本次 iOS 的缺项。
