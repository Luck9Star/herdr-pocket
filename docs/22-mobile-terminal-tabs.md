# 手机独立终端标签与保留连接

2026-11-06，延续 [Flutter 原生网络通道](21-flutter-native-network.md)。本批推进手机从配对、看板进入多个独立终端视图：同一主机可打开不同 pane，隐藏视图撤销输入并暂停观察，回到前台后由用户显式恢复。**首轮集中云构建已执行并失败，未生成新 APK；修复后的复验待执行。** 此前 Android 测试包仍对应 `040eb26`，不能用来验收本批代码。[上一批包与失败记录](18-mobile-network-profiles.md)

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

## 新包的手机验收步骤

以下步骤要使用本批来源匹配的新包；旧 `040eb26` 包不能代测。当前均没有物理手机结果。

1. 按[配对说明](14-mobile-pairing-workbench.md)连接自行准备的隔离测试主机，核对主机指纹、设备公钥和命名会话。先确认看板、pane 与持续更新画面一致。普通 herdr 0.9.5 保持只读；输入测试须使用明确的受保护扩展候选，不能靠版本号打开输入。
2. 为同一主机两个不同 pane 分别新建标签，核对显示的稳定 terminal ID。切到 B 后，A 必须标为暂停／旧画面；回到 A 不能自动恢复。主动恢复后取得新 full，输入仍需重新显式开启。记录服务端认证次数，确认正常切换没有重新认证。
3. 在 A 编写未发送草稿，切换后核对 B 草稿独立。输入候选中，让一笔请求等待回执时编辑新草稿：旧拒绝回执不能覆盖新内容；明确拒绝文本只能手动从只读找回区复制。未知结果锁定输入，不能出现自动重发或自动添加回车。
4. 关闭 A，确认 B 没有被关闭、激活或停止其共享节点；修改 B 所依赖的网络版本或身份，旧 B 视图必须要求关闭重开。创建到上限以及快速关闭重开时，尚在清理的连接继续占额，界面应明确拒绝超额连接。
5. 应用进入后台再回来，所有隐藏与可见连接均须已关闭，不能自动拨号。分别记录 Android 版本、设备、输入法、网络条件、源码 SHA、实际步骤和失败状态；验证后关闭测试应用。原生库能装包、设备能加载、节点入网和 overlay SSH 是四项独立结果。

## 三网络的后续顺序

本批补查 [固定 Tailscale 源码与适配缺口](../validation/native/tailscale-adapter-audit.json)。Heeler 现有 libtailscale 的 Unix socketpair／文件描述符路径不能直接作为 Windows 桥；此前 tsnet 编译成功也不能证明该桥可用。后续需要可取消的 opaque stream 接口、独立节点生命周期，以及不会读取环境认证资料的显式授权流程。本机身份存储须实现完整 StateStore 契约，不能复用 EasyTier 的单份入网秘密作为 Tailscale 状态。

1. 完成本批两包与隔离链路集中验收，保留失败，先修手机配对 → 看板 → 观察／输入 → 多标签恢复。
2. 验证 Android 原生加载、设备身份重启恢复及真实 EasyTier SSH；现有隔离 ABI 或构建检查不新增真实组网通过项。
3. 分别实现 Tailscale 和 ZeroTier 的身份、生命周期与字节流适配，再验证跨 provider 并发。没有将 EasyTier 的成功外推到其他网络。
4. 根据手机结果完善 Penpot v2 的恢复、未知结果与组件状态，再进入桌面分屏和焦点适配。现有 30 画板本批未改；框架尚未定案。

未读取真实凭据、修改主机授权或安装本机完整 SDK。本批未打开本机 GUI 测试应用。
