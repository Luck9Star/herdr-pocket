# 界面设计落实与普通 SSH 终端

状态：2026-11-15 原型验证交接。此记录覆盖普通 SSH、S01–S06 与 S27 的界面增量，以及 Flutter / Tauri Android 模拟器普通 SSH 验收；CI 调试 APK、公开 Release、手机真机和五平台运行须分别核对。历史 ADR 和此前 APK 的证据范围保持原样。

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
| Flutter / macOS arm64 原生 debug UI | `a5082d0` 云构建归档下载后，改为唯一 bundle ID，保留六项 entitlement 并本机 ad-hoc 重签隔离配置；从生产首页进入普通 SSH，核对 RSA SHA-512 算法与 SHA256 指纹、密码连接，通过实际物理窗口输入 `hp-check` / Return，看见绿色 `POCKET-ANDROID-SSH-OK`，点击断开后凭据清空。独立服务端确认两次连接全部关闭，PTY 从 80×24 改为 95×33 | 实际 Mac 窗口；回显沿用夹具共用标记，不是 Android 运行。修改 bundle ID / 本地重签的 debug 包，不代表原签名发布包、私钥 UI 或系统公证验收 |
| Rust 实际 SSH / OS PTY | 7 项常规 shell 测试：临时 Ed25519 和 RSA SHA-256/512 server、密码/私钥、真实 `/bin/sh`、双向 ANSI 字节；真实 `stty size` 从 24×80 改到 37×117；双会话隔离、退出码 7；pin/auth/PTY/shell 失败；握手/认证/活动会话取消；精确输出 ack、排队输入回执超时退休与清理；RSA 用户签名核对与 RSA/SHA1 服务端在认证前拒绝。另显式执行 RSA-only Paramiko 互操作 1 项。完整 Rust 库 103 项与 CLI 1 项通过 | 自建 loopback、临时密钥和隔离 HOME；不访问个人 SSH 凭据或真实主机。其他 key 算法、keyboard-interactive/MFA 未实测；外部 Paramiko 用例默认 ignored，已单独补跑 |
| Flutter 普通 SSH runner | runner 执行 5 项：显式指纹确认与空凭据门槛；密码认证、实际 PTY/shell 与后台断开；旧 pin 在认证前拒绝；加密私钥认证；正常导航返回与销毁 | [runner](../validation/flutter/tool/direct_ssh_fixture_runner.py) 与[测试夹具](../validation/flutter/test/direct_ssh_fixture.py)；不属于手机真机或原生 Tauri 证据 |
| Flutter S01–S05 与安全回归冻结批次 | Flutter 3.47.9 临时工程：完整套 **521 passed / 4 skipped / 0 failed**；`flutter analyze --no-pub` 无问题。新增 320/390/1200 宽度的配对步骤、指纹可达和三模切换不发送字节检查；选择文本与字体诊断仍撤销旧输入，关闭后不恢复发送 | 使用合成 adapter 的实际 Flutter Widget 引擎渲染；4 个跳过项不计通过；不覆盖随后独立开发的 S06 |

Tauri 原生 debug app 使用隔离标识 `dev.herdrpocket.acceptance20261115`。构建日志留在本次本地运行目录；这些原生 UI 检查不构成发布验收；已有可下载的 CI 调试 APK 须核对对应源码 SHA，不能当成公开 Release 或手机真机通过。Rust 复核入口为 `cargo test --locked --offline --manifest-path validation/transport-rust/Cargo.toml direct_shell`；Flutter 准备与 runner 用法见[验证壳 README](../validation/flutter/README.md#普通-ssh-回环验证)。

Flutter macOS 归档来源为 [Actions 43669066267](https://github.com/Luck9Star/herdr-pocket/actions/runs/43669066267)、工件 `14143937188`，`flutter-macos-debug.tar.gz` 的 SHA256 已核对为 `6212b8523c7fcec5b8bbd5a688117791a42f43e046a1902065205051c2bb3561`。本机操作的[服务端脱敏报告](evidence/design-parity-20261115/flutter-macos-native-a5082d0.json)只含认证、PTY、输入标记、关闭布尔与尺寸计数；操作截图保留在聊天，不将 Widget 图冒充原生窗口图。

普通 SSH 的 RSA 兼容增量也已从原生 macOS 窗口独立复验：纯 RSA2048 Paramiko、核对 SHA256 指纹、密码登录、输入 `hp-check` 后看到绿色 `POCKET-ANDROID-SSH-OK`，点击断开后服务端记录 `sessionClosed`。窗口缩放让服务端实际收到 80×24 → 106×28 → 106×30 → 104×27 → 104×20 → 104×19 → 106×19，包括列数相同而行数改变。该次使用前端 `f29ea6b` 与 Rust 生产文件 blob `a9e9792` / `502548b`，已纳入功能快照 `621b793`；原生私钥输入未验证，Android 范围另见下文。

Rust 仅新增 russh 的独立 `rsa` feature，仍关闭默认 features 并保留 `ring`；普通 SSH 探测和连接禁止协商旧 RSA/SHA1，RSA 私钥采用服务端支持的 SHA-256/512。公钥 pin 的 `ssh-rsa` 前缀表示公钥编码，并不表示允许 SHA1 签名。三个消费方锁文件同步固定新增依赖，未修改 vendored russh；herdr 配对仍按原 Ed25519 身份验证。测试夹具的子进程由专用线程从创建到回收持有，取消清理继续以 3 秒内连接和子进程计数归零验收。

## S01–S05 设计与可达性

沿用 [Penpot v2 设计与工程映射](../design/README.md)、[原始 S01–S07 读回](../design/evidence/v2-initial.json)，以及 [S08 未知发送](../design/evidence/v2-S08.png)、[S13 主机确认/撤销](../design/evidence/v2-S13.png)、[S43 键盘收起](../design/evidence/v2-S43-keyboard-20261107.png)、[S49 指纹审查](../design/evidence/v2-S49-profile-review-20261107.png)。靛蓝表示操作与选择，绿色只表示状态；终端保持黑曜石背景。

- S01：看板、终端、网络、设置四个入口；普通 SSH 与 herdr 配对可由正常首页进入。
- S02–S04：显示实际 pane 标签、观察/逐键/草稿三态、安全提示、终端文本/字体工具和辅助键。切换模式本身不发送字节；草稿优先编辑，发送仍须原目标预览确认，换行不会被删除或额外补回车。
- S05：将资料导入、目标核验、主机指纹卡、创建设备身份、主机响应审查与独立连接验证组织为步骤；保留取消、撤销边界和稳定测试 key。核验框不会因仅粘贴资料而自动勾选。

以下均为 **390×844、DPR 1** 的实际 Widget 渲染，使用真实字体和合成资料；没有个人凭据。S01 来自看板导航测试，S02–S05 来自[本轮可达性与截图测试](../validation/flutter/test/herdr_workflow_visual_test.dart)。它们用于设计与界面对照，不证明真实 SSH 或手机设备。

| 画面 | 稳定截图 |
| --- | --- |
| S01 首页与正常入口 | [含实际状态结构的合成看板](evidence/design-parity-20261115/s01-board-populated-390.png)、[空看板](evidence/design-parity-20261115/s01-board-empty-390.png) |
| S02 观察 | [默认只读与真实标签条](evidence/design-parity-20261115/s02-observe-390.png) |
| S03 逐键输入 | [显式输入与安全提示](evidence/design-parity-20261115/s03-direct-390.png) |
| S04 草稿 | [本地编辑与预览发送](evidence/design-parity-20261115/s04-draft-390.png) |
| S05 配对 | [扫码/资料步骤](evidence/design-parity-20261115/s05-pairing-390.png)、[完整指纹卡与独立核验](evidence/design-parity-20261115/s05-fingerprint-390.png) |

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

作为另一层独立证据，`e5cdaeb` 的 Linux 原生 Flutter 与 Tauri stock herdr 配对都通过，两个 manifest 均记录输入 0 字节；`bd083d8` 的双壳五端构建通过。它们分别证明对应版本的配对观察路径与构建，不可扩成普通 SSH Android UI 或 S06 真实双连接运行通过。

Flutter 的 `a2ffb4b` [guarded Android 运行 43667868489](https://github.com/Luck9Star/herdr-pocket/actions/runs/43667868489)也已独立回读通过：stock 路径输入 0 字节，guarded 工件 `14143482126` 记录 10 字节，逐键与草稿各自受理；粘贴取消、再次预览和本地追加没有额外 SSH 字节，生命周期与原目标核对通过。这是对应版本单端受保护输入的模拟器证据，不是 S06 真实双连接或物理 IME 验证。旧 `fba4` 运行的 AVD 255 根因仍未查明，诊断或用例依赖修复不构成该故障已根治的证据；专用 TUI 运行另行核对。

专用 TUI 的 Tauri `c9f191d` [运行 43670510076](https://github.com/Luck9Star/herdr-pocket/actions/runs/43670510076)中，`android-device-key` 作业通过；工件 `14145185000` 的真实 curses 主机状态与 10 个输入回执匹配，`manifest.stoppedStale=true`，`progress.postStopInputUnchanged=true`，停止按钮首次命中。另记录 7 个系统 IME 显示/收起检查点，不能扩大为真实中文组字或实体键盘通过。`receivedInputBytes=10` 是 curses 之外的原始捕获阶段，不代表全部 TUI 输入只有 10 字节。该混合工作流另有 Flutter 作业失败，不能写成整条运行全部通过。

## S27 网络页界面增量

`4be102e` 冻结了手机 S03、普通 SSH 凭据门槛和 S27 网络页；独立归档源码完整验证为 **533 passed / 4 skipped / 0 failed**，analyzer 无问题。S27 使用紧凑配置与节点状态、实际绑定主机名和按需展开管理；40 项定向回归包含停用影响以及撤销、删除保护。[320 宽度](evidence/design-parity-20261115/s27-networks-320.png)与[390 宽度](evidence/design-parity-20261115/s27-networks-390.png)是使用合成节点数据的实际 Widget 渲染，证明界面与交互，不替代真实组网或设备路由证据。

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

`a5082d0` 的[完整批次 43669066267](https://github.com/Luck9Star/herdr-pocket/actions/runs/43669066267)已独立分页核对：32 个作业中 27 个启用作业全部通过、5 个跳过不计通过，包含双壳五端构建与 Linux 双壳 stock/guarded。它证明对应源码的构建和明确执行的 Linux 路径，不能扩大成五端设备运行。Flutter macOS 原生窗口的本机实测来源与重签范围见上文。iOS 普通 SSH 应单列其自身模拟器/真机运行和签名来源，不由 Android 成功或 iOS 编译结果代替；本页此时没有登记 iOS 运行通过。

## 尚待独立补证

S06 的原生桌面双窗与手机设备、手机真机触控/IME/相机/系统密钥存储、其他主机算法与认证组合、三网路由、长时间运行和正式发布均不能由本页证据推出。后续每项新增结论必须对应新的实际运行记录；历史“只允许远端 herdr”作为当时基线保留，现行两类远端接入范围以本页及架构/产品设计的 2026-11-15 增量为准。
