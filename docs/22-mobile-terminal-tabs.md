# 手机独立终端标签与保留连接

2026-11-06，延续 [Flutter 原生网络通道](21-flutter-native-network.md)。本批推进手机从配对、看板进入多个独立终端视图：同一主机可打开不同 pane，隐藏视图撤销输入并暂停观察，回到前台后由用户显式恢复。**第四轮 `546c3eb` 已完成同源两份 Android arm64 测试包，5 个 CI job 全部成功，下载字节与来源核对通过。** 前三轮失败完整保留在下文；旧 `040eb26` 手机模拟器结果不代替本批设备运行。[历史手机结果](18-mobile-network-profiles.md)

## 当前下载与验证结果

[Actions 42208702281](https://github.com/Luck9Star/herdr-pocket/actions/runs/42208702281) 对应 `546c3eb34bf166a22effa033d9862544641a308a`。两份归档均已实际下载，GitHub ZIP digest、包内 SHA256SUMS、APK、原生 manifest、Heeler 实装字节及共享来源材料均匹配。[完整构建与下载核对记录](evidence/mobile-pair-gui/mobile-tabs-ci-final-20261106.json)

| 路线 | 下载 | 解压后 APK SHA256 | APK 字节数 |
| --- | --- | --- | --- |
| Flutter | [测试归档](https://github.com/Luck9Star/herdr-pocket/actions/runs/42208702281/artifacts/13498293296) | `0e71db3d2e8bb3799cf5ace33ecf6bf5c5639ed53c62302e57bfd0a2c0166fab` | 452169182 |
| Tauri | [测试归档](https://github.com/Luck9Star/herdr-pocket/actions/runs/42208702281/artifacts/13498208754) | `f9c75e2608b67afa0ec31b03a687740bb1a6d5a08df322cfbe8449da9512a59f` | 553750689 |

下载 ZIP 后解压 `app.apk`，对照 SHA256 并保留 `report.json`、来源 manifest 与声明文件。当前测试目标为 API 35、arm64-v8a；包保留调试符号以核对原生来源字节，体积不代表正式包。Artifacts 保留至 2026-11-20；没有创建 Release 或商店版本。

Flutter analyzer 无问题；常规移动测试 182 通过、1 个 opt-in SSH 用例跳过；独立隔离 job 随后执行该 SSH GUI 用例并通过，绘制回归 10 通过，harness 31 通过。真实 widget 经 runner 生成的临时测试身份签名、隔离 OpenSSH 和 herdr 0.9.5，完成待授权恢复、配对审查、看板、full/delta、同一 SSH 隐藏恢复及主动停止，签名 1 次，5 帧（3 delta），远端输入 0；共享 PTY 始终 119×40，临时授权撤销与自有进程清理已核对。[原始脱敏 manifest](evidence/mobile-pair-gui/mobile-tabs-flutter-ssh-20261106.json)

此处是 Ubuntu headless widget／loopback 证据，设备签名和 journal 为明确的测试替身；不是 AndroidKeyStore、Android 动态加载、真机触控、IME、相机或真实 overlay 的通过证明。本批 Tauri 是 Node 测试、Android 构建与静态校验通过，没有新增其手机 GUI runtime 结果。框架仍未定案；看板事件订阅的后续源码不包含在这两份包中。

## 两套 GUI 的共同契约

- 每个标签有独立的视图 ID、主机 ID、连接代际和观察 epoch。pane ID 与稳定 terminal ID 一起冻结；相同主机地址或 pane 名称不代表相同目标。
- 最多 8 个标签、8 条连接。正在连接、取消后尚未完成清理的连接继续占额；上限包含系统 TCP 和显式 overlay 路由。关闭一个标签不停止共享网络节点，也不自动激活邻项。
- 前台仅一个输入焦点。隐藏前同步撤销输入，清除尚未发送的逐键队列，停止观察通道；已认证 SSH 在清理成功时保留。隐藏标签不持续绘制。
- 恢复必须显式操作，在原 SSH 上重新取得快照，核对原 pane 与 terminal，消费新 full 后才重新开放输入模式选择。旧 epoch 的 frame、渲染 ACK、模式和发送回执不得套用到新视图。
- 配置、网络版本或设备身份变化仅关闭受影响的标签；绑定已变化的旧页面不能自行改用系统网络。应用进入后台关闭全部连接，回到前台不自动拨号。
- 发送结果未知不自动重放，不回填成可自动发送的草稿。当前仍共用一个持久化未知输入记录；A 的未决记录可能阻止 B 输入，但不能因此取消 B 的只读观察。这一限制尚未改为按目标存储。

共享 [mobile-tabs-v1.json](../validation/shared/mobile-tabs-v1.json) 给出 MT01–MT12 条件和虚构目标。用例存在本身不算通过；下面分别记录实际执行范围。终端仍采用 80 × 24 的观察网格和本地横向滚动，布局、字号、标签切换均不发送远端共享 PTY resize。

## SSH 通道清理的依赖修复

固定 `russh 0.65.0` 的本地主动关闭路径先移除加密通道表，但收到对端 CLOSE 时又先检查该表，因而跳过 client 发送索引的回收。隔离回归中，正常服务器回应 CLOSE 后，旧通道仍不能结束等待；反复暂停会残留索引。

采用完整固定源码的最小候选补丁，在处理本地 Close 时退休对应发送索引。transport、Tauri 和 Flutter 原生通道三个 Cargo 根指向同一候选；独立 `validation/ssh` 保留原 registry 版本用于对照。来源、官方归档 SHA、逐文件摘要、补丁与许可证见 [候选说明](../validation/vendor/RUSSH-NOTICE.md)。这不是上游正式版本，也没有改写本机 Cargo registry。

Rust 暂停回执只证明本地观察和输入已退休、关闭请求已处理；它不证明远端观察进程已经退出。没有为关闭增加远端 SIGTERM、共享 PTY 操作或自动重连。测试须分别覆盖正常恢复、远端不回复关闭、快速恢复后再次隐藏，以及另一连接不受影响。

如果关闭时加密通道仍有未发送数据，候选会保守关闭该 SSH，不提前报告通道清理成功；输入结果继续按未知处理。8 个 SSH 额度要等待拨号 Future 和 SSH driver 所拥有的 I/O 结束才能归还。overlay 内部迟到 native open 则仍由独立的 32 个 reservation 额度约束；SSH 额度归还不表示这层 native 清理也已归零。

Flutter 使用固定 `dartssh2 4.1.0` 的消息 trace 识别入站通道确认与关闭，解决本地 destroy 早于内部通道表回收的问题。仅匹配完整消息格式、方向和通道 ID，不保存或输出其他 trace；格式不能识别或清理超时则关闭 SSH。它依赖非公开格式，属于固定版本实验契约，升级前必须复验。官方归档 SHA 为 `39359aceafcf5940b868249e3c9c6d86e4e0f989eec7417d033c943157c84c51`。连接额度还要等待迟到拨号、通道打开和原 close Future 收敛。

## 构建与验收边界

[Android 集中批次](../.github/workflows/android-network-experiment.yml)使用同一提交构建固定来源的 EasyTier 原生库，再生成 Flutter 和 Tauri arm64-v8a、API 35 测试包。Flutter 沿用组合重音修复候选，并单独运行分析、widget、绘制和隔离 SSH 配对／持续观察检查；共享 Rust 传输独立运行 loopback 测试。测试失败与 APK 编译结果分开保存，不能以能构建覆盖失败。

产物记录来源提交、原生库 manifest、终端候选、SSH 补丁来源、SHA256 和共享用例。`sourceChecks` 与 `transportChecks` 保留各自结果；安装、Android 动态加载和真实入网在没有设备证据时仍为未验证。测试通道不创建 Release，不提交商店，也不合并产品代码到 main。

本机证据见 [mobile-tabs-source-20261106.json](evidence/mobile-pair-gui/mobile-tabs-source-20261106.json)，包含 61 项来源摘要和逐项边界。父代理独立复跑共享 transport 默认 51 项单元 + 1 项 CLI、Tauri 91 项 Node／27 项 Rust、前端构建、Flutter native 默认 3 项，均通过。作者的 native fixture 60 + 1 项通过，父代理核对了日志；其中 8 项 controlled 回归覆盖同 SSH 反复恢复、目标替换、迟到 ACK、未知输入、静默对端、零窗口、人工选择等待与实际 I/O 释放。

首次本机沙盒拒绝 loopback bind，11 项测试因此失败；在仅允许自建隔离测试的执行环境复跑后通过。原版 russh 的同用例失败已复现，候选通过；官方归档、90 文件还原和三 Cargo 根唯一候选由父代理独立核对。整库严格 Clippy 仍有 12 项既有诊断，两个 vendor 内部单测因离线开发依赖缺项未运行，均未标通过。

首轮 [Actions 42184737889](https://github.com/Luck9Star/herdr-pocket/actions/runs/42184737889) 对应 `cc3f988e476527e9dd67bd12d197767aca4f7051`，5 个 job 中 2 成功、3 失败。共享传输测试通过；Flutter 组合字符绘制 10 项通过，但分析和 mobile widget 测试被两个编译错误阻断：`SSHPrintHandler` 接受可空字符串，原 trace 回调参数不可空；`SSHSocket` 的路由接口需显式转换。已修复类型并增加空值、非字符串和实际 socket 路由回归，复验完成前仍不标通过。

Android 原生库编译和静态检查成功，但上传默认遗漏 `portable-stream/.gitignore`，两套 APK job 均被来源清单校验拦下，未进入 APK 构建。仅对全新生成的 `android-native` 来源包启用 `include-hidden-files`，保留原清单严格校验；该目录与构建 worktree、认证文件分离，输入仅为固定来源归档、候选源码和构建记录。[官方上传规则](https://github.com/actions/upload-artifact/blob/v4/README.md#uploading-hidden-files)已经 Context7 查询核实。原生 job 成功不能代表其上传产物可用；隔离 SSH GUI 检查本轮跳过。详见[首轮失败记录](evidence/mobile-pair-gui/mobile-tabs-ci-first-20261106.json)。Tauri 合成 DOM 测试不等于手机触控或 IME 通过。

第二轮 [Actions 42187302052](https://github.com/Luck9Star/herdr-pocket/actions/runs/42187302052) 对应 `16575c06bf47b11e9aca8169b36fbf501e2ff1ff`，共享传输与 native job 成功，两套消费端均通过原生包完整校验，首轮类型错误也已消失。但整体仍是 2 成功、3 失败，未上传 APK：

- Flutter mobile 测试 173 通过、1 跳过、5 失败；绘制 10 通过，隔离配对 GUI 跳过。三项身份测试把内存身份替身与未模拟的 native 通道混用，被正确拒绝；现显式注入节点运行时，生产默认保持真实通道，并加停止未知不写身份的反例。另修复原始 URL 的 `:0`／`:00` 端口被 URI 规范化掩盖，以及平台相关 widget 测试；移除导致 analyzer 非零退出的冗余 import。
- Tauri 91 项 Node 测试通过，Android Rust 构建缺少 `icons/32x32.png`。补上 `android init` 前用现有 SVG 生成图标的步骤；本机固定 CLI 已验证 5 个 bundle 图标和 Android launcher 资源，尚不代替 Android 构建。
- Flutter APK 编译成功，但实装 Heeler 库 SHA 与原生来源包不一致，严格校验拦截后没有上传。当前推断是 Gradle 打包时移除符号；按[官方 `keepDebugSymbols` 配置](https://developer.android.com/reference/tools/gradle-api/8.0/com/android/build/api/dsl/JniLibsPackaging#keepDebugSymbols())，仅保留 `libheeler_easytier.so` 原始字节。两壳应用同一配置，下一轮仍须通过原有逐字节与 ELF 校验，不能以此配置本身证明原因或修复已验证。

完整 job、产物 ID 和边界见[第二轮记录](evidence/mobile-pair-gui/mobile-tabs-ci-second-20261106.json)。修复后本机 Python 构建辅助 8 项、原生包检查 9 项通过；Dart 51 文件仅语法检查通过，尚无修复后的 analyzer／widget 结果。

第三轮 [Actions 42206577343](https://github.com/Luck9Star/herdr-pocket/actions/runs/42206577343) 对应 `027a61e73281f5ccd560075c6a58c8a57a98c5a5`，仍是 2 成功、3 失败，但已确认 Flutter analyzer 通过、原 5 项失败消失、移动测试 180 通过／1 跳过／2 失败、绘制 10 通过。新失败来自两个测试的 `debugDefaultTargetPlatformOverride` 在 widget 不变量检查之后才清理；已改为测试体 `try/finally`，原行为断言保留，待复验。隔离 SSH GUI 仍跳过，不能标为本批通过。

Tauri 已越过缺图标阶段，Android 专用身份写入路径暴露返回 `&str` 而非 `String` 的编译错误，已显式转换错误字符串。Flutter APK 构建成功，Heeler 逐字节核对也已通过，后续遍历 APK 原生对象时被未列入系统清单的 `libnativewindow.so` 拦截。原日志没有对象文件名，不能归因到 Heeler；现补充对象名诊断，并依据[Android 官方 NDK 库清单](https://developer.android.com/ndk/guides/stable_apis#android_native_application_apis)在固定 API 35 校验中允许此公开库。未知／私有库和缺少必需依赖仍拒绝，新增反例随本机原生包 10 项测试通过；APK 实际复验尚待执行。[第三轮完整记录](evidence/mobile-pair-gui/mobile-tabs-ci-third-20261106.json)

## 新包的手机验收步骤

以下步骤要使用本批来源匹配的新包；旧 `040eb26` 包不能代测。当前均没有物理手机结果。

1. 按[配对说明](14-mobile-pairing-workbench.md)连接自行准备的隔离测试主机，核对主机指纹、设备公钥和命名会话。先确认看板、pane 与持续更新画面一致。普通 herdr 0.9.5 保持只读；输入测试须使用明确的受保护扩展候选，不能靠版本号打开输入。
2. 为同一主机两个不同 pane 分别新建标签，核对显示的稳定 terminal ID。切到 B 后，A 必须标为暂停／旧画面；回到 A 不能自动恢复。主动恢复后取得新 full，输入仍需重新显式开启。记录服务端认证次数，确认正常切换没有重新认证。
3. 在 A 编写未发送草稿，切换后核对 B 草稿独立。输入候选中，让一笔请求等待回执时编辑新草稿：旧拒绝回执不能覆盖新内容；明确拒绝文本只能手动从只读找回区复制。未知结果锁定输入，不能出现自动重发或自动添加回车。
4. 关闭 A，确认 B 没有被关闭、激活或停止其共享节点；修改 B 所依赖的网络版本或身份，旧 B 视图必须要求关闭重开。创建到上限以及快速关闭重开时，尚在清理的连接继续占额，界面应明确拒绝超额连接。
5. 应用进入后台再回来，所有隐藏与可见连接均须已关闭，不能自动拨号。分别记录 Android 版本、设备、输入法、网络条件、源码 SHA、实际步骤和失败状态；验证后关闭测试应用。原生库能装包、设备能加载、节点入网和 overlay SSH 是四项独立结果。

## 手机优先的后续顺序

本批补查 [固定 Tailscale 源码与适配缺口](../validation/native/tailscale-adapter-audit.json)。Heeler 现有 libtailscale 的 Unix socketpair／文件描述符路径不能直接作为 Windows 桥；此前 tsnet 编译成功也不能证明该桥可用。后续需要可取消的 opaque stream 接口、独立节点生命周期，以及不会读取环境认证资料的显式授权流程。本机身份存储须实现完整 StateStore 契约，不能复用 EasyTier 的单份入网秘密作为 Tailscale 状态。

1. 本批两包与隔离链路已验收；下一批让手机看板持续接收会话／pane 状态变化。事件仅触发权威快照刷新，丢失或断流立即标为旧状态；隐藏退休订阅，显式恢复后在原 SSH 重建观察，不自动重放输入。
2. 将未知输入记录按主机、会话和稳定终端目标隔离；保留每个目标的未决锁定及人工核实入口，避免 A 的未决写入阻止 B 的独立输入。
3. 分别实现 Tailscale 和 ZeroTier 的身份、生命周期与字节流适配，再验证跨 provider 并发。设备条件具备时补 Android 原生加载、身份重启恢复及真实 EasyTier SSH；不以隔离 ABI 或 EasyTier 的成功外推到其他网络。
4. 根据手机结果完善 Penpot v2 的恢复、未知结果与组件状态，再进入桌面分屏和焦点适配。现有 30 画板本批未改；框架尚未定案。

未读取真实凭据、修改主机授权或安装本机完整 SDK。本批未打开本机 GUI 测试应用。
