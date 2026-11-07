# 手机终端的阅读位置与连接恢复

2026-11-07。查看宽于手机的终端时，用户可以横滑阅读右侧列。从同一主机、会话和终端重新取得完整画面后，客户端恢复该目标的本地阅读位置；首次打开的目标从左侧开始。原版 herdr 的只读观察也能使用横滑。[原型实现](https://github.com/Luck9Star/herdr-pocket/commit/54bf6498ddda5cd86892e533e44ef8198e42a2be) · [逐场读数](evidence/mobile-pair-gui/viewport-recovery-20261107.json)

## 两条手机路径

下列固定 80 列是 11 月 7 日的基线。11 月 8 日的原型已加入三档观察画布和宽屏内容的手机阅读验收。[观察画布与共享 PTY 实测](47-mobile-observer-canvas.md)

- Flutter 的观察页在本地画出固定 80 列，支持横滑和拖动底部滚动条。每个标签按路由、主机指纹、账号、会话、socket、pane 和 terminal 分开保存最近 16 个位置。字号变化按字符列换算，宽屏下把位置限制在可见范围。隐藏期间收到的指纹不符或连接失败原因，切回时仍能看到。
- Tauri 新配对表单和已存主机标签均保存位置。每个视图在内存里保留最多 8 个目标，已保存主机的网络绑定和修订号参与区分。重连后先核对原终端并接收新全帧；隐藏、字体变化或宽度变化不会触发远端 resize。已存标签现在能分别解释主机密钥不符、设备认证失败、目标消失和观察中断。收到未知错误时显示固定的恢复提示。
- 两条路线都只保留本机的阅读位置。隐藏期间的输出历史、输入许可和未确认写入按各自原合同处理。用户仍须主动恢复观察，已发送或结果未知的输入不会重放。[目标与草稿恢复](24-target-input-recovery.md) · [手机标签](22-mobile-terminal-tabs.md)

## 交互与本地实测

Penpot v2 的 S02 和 S18 已接入 S46「原目标恢复阅读位置」，S47 演示首次进入另一目标。查看器实点验证 S46 → S47 → S46 → S02 → S46，以及 S18 → S46；S02/S18 原有 61 个对象的名称、位置、尺寸和跳转目的地经取整对照一致。编辑插件报告与站点的版本差异，已以保存后的读回和独立查看器确认结果。[打开 S46](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e8c46842cb06) · [交互和截图记录](../design/evidence/v2-mobile-horizontal-review-20261107.json)

Mac Chrome 156 使用真实 xterm 和触摸事件。320 × 820、390 × 820 两个视口各走两个入口。新配对表单横滑后返回主机列表，重新打开并审查原设备、连接、选择原终端、取得新全量帧。已存主机标签横滑后切换输入模式以重建滚动容器。四场均从 85 CSS 像素恢复到 85 CSS 像素，均为 0 次输入和 0 次远端 resize。SSH 和原生 IPC 使用测试替身；这里只证明客户端行为。[测量数据](evidence/mobile-pair-gui/viewport-recovery-20261107.json)

精确源码通过 247 项 Tauri 测试和 Vite 56 模块构建。Mac 的 Python 隔离环境通过 Flutter 驱动 59 项、共享远端驱动 36 项、打包工具 11 项和 POSIX helper 15 项。

## 发现的字体诊断错误

在固定的 Dart 3.11 与 terminal_view 0.5.0 候选核心上，初始环形缓冲区只分配 8 行时，从默认 24 行缩到 8 行会抛出异常。Flutter 诊断界面随即显示样例不可用。将初始容量改为 24 行，同一份 16 × 8 样例重新运行，八行右侧分隔符均在第 15 列。Mac Chrome 的八行也实际测到第 15 列。Android 测试分别采集 Flutter 的缓冲区列号和 Tauri 的 DOM 字形几何；手机实际使用的 fallback 字体与中文字形仍需另验。[共用样例](../validation/shared/terminal-font-diagnostics-v1.json) · [字体诊断设计](42-mobile-terminal-font-diagnostics.md)

## 复测步骤

1. 在隔离测试主机完成配对，核对原主机指纹、设备公钥和会话，主动连接并从看板选择 pane。待首帧后把 80 列终端横滑到右侧，记下左边可见的字符。
2. 切走标签再切回，要求使用者主动恢复。核对主机、会话、pane 和 terminal 身份，等待新全量帧，确认仍在原列附近。首次打开另一目标，应从左边开始。改变字号或旋转视口后，确认最右侧仍能访问，远端共享 PTY 尺寸不变。
3. 用独立测试资料制造指纹不符或失效认证。应停止连接并给出具体原因；切回保留原因，手工核对后才能重新连接。输入法收起、结果未知或恢复观察均不产生自动重发。

## 首批云验证与修复

源码 `54bf649` 的两份 arm64 安装包均已构建，已独立下载并核对归档、APK、来源、原生库、字体和诊断样例。Flutter analyzer 与 10 项绘制专项通过。Flutter 常规套件有 347 项通过、1 项跳过、5 项失败，包括三项字体诊断和键盘焦点、横向拖动各一项。四个 API 35 模拟器场景均未通过，旧的完整链路结果仍保留在[上一批验收记录](40-android-paired-dashboard-validation.md)。[首批运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/42372870417)

- Tauri 两场在诊断页检查输入和焦点时停止。Mac CDP 返回的真实字符串同样能复现：Python 按对象身份比较反序列化后的 `inputmode`。修复后逐字段比较类型和值，同一份 Mac 读数通过，布尔安全条件继续严格核对。
- Flutter 只读场景在本地字体诊断阶段超时；缓冲区容量错误已在固定 Dart 核心复现并修正。受保护输入场景在配对阶段超时，旧阶段码覆盖了勾选、单次点按创建设备和等待请求三个步骤。修订驱动在按钮居中、命中且位置连续稳定后只点一次，分别记录创建和等待阶段。
- 窄屏上的 Flutter 滚动控制改成独立 48 像素触控区，直接驱动终端的同一水平滚动控制器。内容可完整显示时保留全部终端高度。键盘测试现在核对收起后真实失焦、观察模式与按键零发送。修订源码为 `cb0fd1c`。[修订批运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/42374975205)

## 修订批 Android 实测

两套应用从同一提交 `cb0fd1c7ad3137a09dd92dbd72e2df168379ce88` 构建。八项云任务中五项通过，Flutter 源码检查任务和两套模拟器汇总任务失败。每个模拟器汇总任务包含两场，以下按各自的设备记录列出结果。[全部任务](https://github.com/Luck9Star/herdr-pocket/actions/runs/42374975205)

| API 35 x86_64 场景 | 手机设备公钥匹配 sshd 认证 | 观察／输入结果 | 共享 PTY 采样 |
| --- | --- | --- | --- |
| [Flutter · 原版 herdr](https://github.com/Luck9Star/herdr-pocket/actions/runs/42374975205/artifacts/13575638537) | 通过 | 配对、看板、首帧、增量、停止均通过。完整帧序号 1，后续读到序号 3；远端收到 0 字节 | 4,271 次，均为 119 × 40 |
| [Flutter · 受保护输入](https://github.com/Luck9Star/herdr-pocket/actions/runs/42374975205/artifacts/13575423976) | 通过 | 系统输入法目标核验失败，远端收到 0 字节 | 1,427 次，均为 119 × 40 |
| [Tauri · 原版 herdr](https://github.com/Luck9Star/herdr-pocket/actions/runs/42374975205/artifacts/13575498815) | 通过 | 系统输入法目标核验失败，远端收到 0 字节 | 770 次，均为 119 × 40 |
| [Tauri · 受保护输入](https://github.com/Luck9Star/herdr-pocket/actions/runs/42374975205/artifacts/13575896046) | 通过 | 系统输入法目标核验失败，远端收到 0 字节 | 798 次，均为 119 × 40 |

Flutter 只读场景使用应用自己的 AndroidKeyStore 包装种子和软件 Ed25519 签名。配对请求重新打开后复查原设备公钥，主机授权后进入看板。八行本地样例的缓冲区标记列均为 15，只读状态下系统键盘连续两次确认隐藏，应用的底部 inset 为 0。四场均确认主机撤销了本次测试公钥，停止临时进程并清除临时密钥。未使用个人授权文件。

其余三场的错误码均为 `android_system_ime_target_mismatch`，当场报告未保存足以区分焦点窗口与编辑器归属的字段。受保护输入、横向恢复和 Tauri Android 字形测量在本批均未完成验收。之前两种 GUI 在隔离主机通过完整配对和持续观察的证据仍对应源码 `1d604fa`。[上批四场通过的证据](40-android-paired-dashboard-validation.md)

Flutter analyzer 与 10 项组合重音绘制回归通过。常规套件 347 项通过、1 项跳过、5 项失败。两项横向视口测试的夹具缺少 Material，另三项字体测试在按钮操作后未找到诊断视图。后续提交修正 Material 祖先与尺寸定位，并将字体测试分拆为按钮命中、面板打开、资产加载、局部渲染四步，保留原有安全和列宽断言。修订后 widget 的执行结果待下一次云验收。[失败日志与绘制结果](https://github.com/Luck9Star/herdr-pocket/actions/runs/42374975205/artifacts/13575047541) · [后续测试修正](https://github.com/Luck9Star/herdr-pocket/commit/5aa797231aaacbe4ff20cd07ae917a479a2287f8)

同阶段还增加了独立的主机输入扩展构建及预检工具。固定上游提交已实际导出，补丁校验和应用通过，Mac 上 19 项工具测试通过；构建与套接字测试使用夹具。本批 Android 的受保护输入仍使用既有 dev 夹具，正式候选的 release 构建与真实会话预检待独立云任务验证。[主机工具与证据范围](../validation/herdr-input-extension/README.md)

### 可下载的同源安装包

| 路线 | arm64-v8a debug 归档 | 解压后 app.apk 的 SHA-256 |
| --- | --- | --- |
| Flutter | [下载测试包](https://github.com/Luck9Star/herdr-pocket/actions/runs/42374975205/artifacts/13575935931) | `ab0c06233be2c74e5ad591c6cafb5e90aa384e2f0785526641371bc542e70a96` |
| Tauri | [下载测试包](https://github.com/Luck9Star/herdr-pocket/actions/runs/42374975205/artifacts/13575986671) | `088b8bc6e562b02432bc9d87889f48eebdd95413bacaddf01b317d436f4950b4` |

登录 GitHub 后下载、解压，用 `shasum -a 256 app.apk` 对照上表。使用专用 Android 测试设备安装后，可按本文的手机复测步骤操作，最后退出测试应用并撤销临时配对。GitHub 显示归档于北京时间 2026-11-21 21:15（Flutter）和 21:16（Tauri）到期。已核对下载 ZIP 和 APK 哈希、唯一原生 ABI、构建提交、两份 .so 与同批 native manifest 的哈希，以及 APK 内字体和诊断样例字节。云模拟器实际运行使用 x86_64 构建，表中 arm64 APK 的真机安装和运行仍未验证。

下一批手机验证优先复核 IME 的应用／窗口归属，保留此前已完成步骤的脱敏读数，再复跑配对、看板和持续观察。物理手机可用后，用相同设备验证触控、中文组字和字体 fallback，再据结果收敛 Penpot、终端引擎和组件规格。三网连接与跨网并发继续逐平台验收。

### 输入法归属检查的后续修订

三场失败共用的驱动原先在整个系统输入法服务输出中搜索 `packageName`，可能把历史编辑器误算为当前目标。原报告只有错误码，无法据此反推这三场的具体原因。按 Android 15 源码，修订驱动只解析当前 `mInputEditorInfo` 的归属，要求默认显示屏上的前台应用及用户匹配。出现短暂无焦点时只读取状态，连续两次确认后才通过。若窗口属于其他应用、显示屏不唯一或归属不明，检查仍会失败。[InputMethodService](https://github.com/aosp-mirror/platform_frameworks_base/blob/android-15.0.0_r1/core/java/android/inputmethodservice/InputMethodService.java#L4479) · [EditorInfo](https://github.com/aosp-mirror/platform_frameworks_base/blob/android-15.0.0_r1/core/java/android/view/inputmethod/EditorInfo.java#L1243)

Tauri 驱动会保留已完成的看板、全帧、增量和字形检查；Flutter 会在键盘检查失败时立即保存当时的步骤及归属分类。两者共用脱敏白名单。隔离源码在 Mac 通过 47 项共享远端检查、62 项 Flutter Android 驱动检查和 15 项 Tauri 输入驱动检查，无跳过。修订只涉及测试驱动与夹具，应用包仍是上表的同源构建，新驱动在 API 35 上的结果留待下一批集中验收。
