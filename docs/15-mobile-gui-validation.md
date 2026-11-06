# 手机主机看板与配对的集中验证

2026-11-06。用户从主机页新增目标，核对主机身份和设备公钥，将公开请求交给 helper。在手机上粘贴或扫描响应并再次审查，主动连接后才能查看该命名会话的 pane。看板支持恢复同一台设备的待授权请求，终端页要求用户选定 pane 才开始持续观察。[配对工作台和测试步骤](14-mobile-pairing-workbench.md) · [Penpot 文件与覆盖清单](../design/README.md)

## 当前可下载的手机测试包

本批已接入主机受理回执、组合键、隐藏恢复与加密主机资料迁移。Tauri `8daf1bc` 的 API 35 原版与受保护用例通过；Flutter `007e20d` 普通包已构建，100 项单元／widget、10 项渲染回归通过，Android GUI 仍未通过。

| 应用 | 最新测试包 | 验证范围 |
| --- | --- | --- |
| Flutter `007e20d` | [debug APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42147341123/artifacts/13472225200) | 构建和回归通过。原版 AVD 停在手机授权确认，受保护 lane 被既有设备保护拦截、未进入 GUI 测试 |
| Tauri `8daf1bc` | [arm64 debug APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42141054727/artifacts/13466854945) | API 35 配对、观察、单键、草稿和隐藏后恢复通过，接收端精确收到 10 bytes |

两包源码分别记录。解包步骤、完整 SHA 与失败边界见[本批验证](16-mobile-input-and-config.md)，原始产物核验见[集中记录](evidence/mobile-pair-gui/input-config-builds.json)。真机 IME、相机和三网并发继续单列。

### 已通过只读闭环的同源基线

两包来自同一提交 `307c863baf568af0b154d4ff6d414a69f3cf4274`，对应的 Flutter 与 Tauri 应用路径都在 API 35 云模拟器通过配对和只读观察。下载的是供试用的 debug APK；自动化另行构建了同源的 AVD 测试变体。[成功运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/42132730593) · [安装与手动验收步骤](14-mobile-pairing-workbench.md#测试包怎么试)

| 应用 | 下载与解包 | 实际 APK SHA-256 |
| --- | --- | --- |
| Flutter | [Android debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42132730593/artifacts/13464856670)；解压 artifact，再解压 `flutter-android-debug.zip` 取得 `app-debug.apk`。 | `c5c1c5452b23e5fd0cf6cdbee4cfc94bc35884c04f86ee12a3e9cd4c5425eb7f` |
| Tauri | [Android arm64 debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42132730593/artifacts/13463534127)；artifact 顶层为 `app-universal-debug.apk`。 | `77921d9b8648b448fb329b4d3dc85b907d7db32eb1485af4aa28da92ba721daa` |

两份 APK 均已在本机解包核对 SHA-256、随包清单和三份原生库声明。GitHub 测试 artifact 有保留期限，记录中保留了可复跑的分支、提交与产物名称。[两包来源及实测记录](evidence/mobile-pair-gui/storage-builds.json)

## 已有云端记录

| 源码和运行 | 可复核的结果 |
| --- | --- |
| [基线 b086299](evidence/mobile-pair-gui/baseline-builds.json) | 已重建并下载 Flutter 和 Tauri 两份只读测试包；均已核验 SHA。 |
| [工作台 4c475b2](evidence/mobile-pair-gui/paired-builds.json) | Tauri Android 包含 GUI 配对和观察代码。Flutter 分析失败。Linux GUI 驱动到表单时停止；Android 模拟器缺少系统库，未启动。 |
| [待授权恢复 988f362](evidence/mobile-pair-gui/recovery-builds.json) | 新版 [Tauri Android APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42052516810/artifacts/13426803591) 已验 SHA 和三份随包声明。Linux 上 18/18 项隔离 SSH 对照通过；输入扩展候选服务端编译及目标绑定测试通过。Flutter Android 编译遇到未公开的 `O_DIRECTORY`；Flutter GUI 被静态检查一条多余 import 拦住。Android AVD 已实际启动，两条 Tauri GUI 探针在表单处停止，候选输入服务的 socket readiness 超时。 |

988f362 的 Tauri APK SHA-256 为 `8ef2958ff0aaa3eeddbe13c4c1807907440fec215d7027dc59873daa84939d1c`。该批次未完成“GUI 审查的设备公钥被 sshd 接受 → 选中 pane → 首帧和增量”的整段验收。[Actions 运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/42052516810)

## 面向手机的改动

- 主机首页先初始化可操作的表单；离线实验室仅在打开时初始化。隐藏实验室暂停其模拟终端。已在隔离标识的 macOS 原生包中通过首页按钮进入表单并输入 `fixture.invalid`，未发起连接，测试进程已关闭。Chrome 独立预览也验证了同一入口，测试浏览器和临时服务已关闭。[Mac 检查记录](evidence/mobile-pair-gui/macos-host-board.json)
- 两端按同一 herdr 0.9.5 / protocol 22 快照解释 pane 的标签、agent、工作状态和 workspace/tab。未知状态显示“状态未知”；展示文字不参与目标选择。只接收有界可打印的说明字段，继续以唯一 pane ID 和稳定 terminal ID 绑定目标。云场景仅验证的字段仍应按实际结果报告。[固定 PaneInfo](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/schema/panes.rs) · [共享快照](../validation/shared/dashboard-snapshot.json)
- Flutter 在 Android 公开 API 上以只读且拒绝跟随符号链接的方式打开目录，通过 `fstat` 检查实际类型并在原子替换后同步。单独的 Flutter AVD 入口使用正式主机目录、Android 受保护密钥和 SSH 适配器。runner 只能交换这次测试的公开请求与响应。[Android Os](https://developer.android.com/reference/android/system/Os) · [OsConstants](https://developer.android.com/reference/android/system/OsConstants) · [Flutter AVD 步骤](../validation/flutter/integration_test/README.md)
- Tauri iOS 接入共用的 CryptoKit 签名、ThisDeviceOnly Keychain 后端及相机授权响应入口。本机 3 项 Swift 接线及内存替身测试通过，系统 Keychain 调用数为 0，iPhone 签名安装、相机、锁屏和重启仍待验。[iOS 插件实现](../validation/tauri/ios/PocketPlugin.swift)

## 下一步验收

1. 从同一来源验证两份 Android 应用包和两种模拟器 GUI。核对 helper 接受的设备公钥指纹、sshd 的实际记录、已选 pane 的 full/delta、主动停止及设备进程关闭。原版只读用例要求接收端输入为 0。
2. 将带保护输入的隔离候选主机单独验证。需要匹配请求 ID 的队列受理回执和精确的终端接收字节；网络结果未知时保持锁定，人工核实原目标再恢复，不重放。
3. 在能取得真机时补扫码、中文 IME、触控、键盘变化、锁屏与长期运行。三网与跨网并发仍待逐端验证；确认正确性后再定框架并回写高保真页面。

### 双手机候选 de86b33

[集中运行 42128042321](https://github.com/Luck9Star/herdr-pocket/actions/runs/42128042321) 同源产出 [Flutter Android APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42128042321/artifacts/13462820378)、[Tauri Android APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42128042321/artifacts/13461308993)、[Tauri iOS 模拟器包](https://github.com/Luck9Star/herdr-pocket/actions/runs/42128042321/artifacts/13462935479)与[一次性 POSIX helper 源码包](https://github.com/Luck9Star/herdr-pocket/actions/runs/42128042321/artifacts/13461532833)。Tauri 的 iOS 新插件已在模拟器包中完成编译链接。Flutter iOS 任务因 GitHub 当时不支持请求的 macOS 14 runner 配置，在零步骤执行时取消。整个 run 显示 cancelled；各 job 的 build、failure 和 cancelled 分开记录。

Flutter 分析通过，12 项目录／widget 用例失败，其中 7 项追到同一嵌套 Map 类型错误，阻断原生设备句柄写入。Linux Flutter GUI 停在公开请求之前。Linux Tauri 进入表单，在编辑 herdr 可执行路径时触发 WebDriver 不可交互错误；API 35 Tauri 在创建请求阶段停止。Flutter API 35 清理记录确认应用、ADB 转发和测试工具都已退出，未完成 GUI 正向用例。原版隔离 SSH 再次通过 18/18，扩展主机的 socket、snapshot 与能力查询自检通过。手机闭环修复集中验证目录写入、公开交换的 ADB 退出状态，以及正常表单的滚动与焦点。

两份 APK 已解包，实际字节、来源 SHA、随包校验和以及 BC、QR、ZXing 三份声明都已核对。Flutter 的 APK SHA-256 是 `f2388234ee265c6c4179ba2ad97d512628d16974650fde8eb826c9604c15215b`，Tauri 的是 `a60dfac6f2a981f8eb917b927e3f981e74e1d9311fd9c957ed4f589b23ccd615`。Flutter 这一版仍含上文的目录错误，下载时请区分构建成功与配对可用。[完整结果、产物与清理记录](evidence/mobile-pair-gui/phone-builds.json)

### Android 目录锁和持续观察

在聚焦复验 `f2d5594` 中，Flutter analyzer、76 项单元／widget 测试及 10 项终端渲染回归通过；1 项真实 SSH widget 用例由独立 job 运行。Flutter iOS 使用 macOS 15 runner 完成无签名构建。真实 Flutter GUI 探针在公开请求后超时，API 35 Flutter 在公开请求阶段退出。Tauri 的 API 35 报告将错误定位到保存主机目录，尚未创建设备身份。[聚焦复验](https://github.com/Luck9Star/herdr-pocket/actions/runs/42129682652) · [该批产物与失败阶段](evidence/mobile-pair-gui/observe-builds.json)

Rust 1.96 的标准库对 Android 的 `File::try_lock` 固定返回 Unsupported；此前目录初始化错误被 UI 丢弃，后续保存只报告资料不可用。实现已改用非阻塞 `flock`，仍持有原文件描述符至仓库关闭，并同步修复未知输入记录使用的锁。桌面实测两个独立文件描述符会竞争，释放后能重新获取；Android 运行需修复后的 APK 独立验收。[固定 Rust 源码](https://github.com/rust-lang/rust/blob/1.96.0/library/std/src/sys/fs/unix.rs#L1529-L1590)

看板将主机明确报告为 blocked 的窗格稳定置顶，同组保留快照顺序；陈旧数据单独标注。后续验收在临时测试 PTY 采样真实行列数，并分别记录 GUI、独立 Android 签名挑战与本地窗口尺寸变化，单项通过不能替代另一项。

### 设备签名与主机看板 307c863

Flutter Linux widget 已走通“主机列表 → 生成公开请求 → 返回并重开原请求 → 审查 helper 响应 → 主动连接 → 选定 pane → 持续观察 → 手动停止”。隔离 sshd 日志核对了本次批准的设备公钥；测试签名器调用 1 次，收到 1 个 full 与 3 个 delta，接收端输入为 0 字节。两次本地窗口尺寸变化期间，真实远端共享 PTY 的 407 次取样始终为 119 列 × 40 行，未观测到尺寸变化；最大采样间隔 54 ms。已撤销 fixture 公钥、关闭进程并清理临时身份。此项检查使用测试签名器，终端帧证据来自 widget 状态与 parser；字体像素、Android 系统存储及真机体验分别验收。[已核验的 GUI 记录](evidence/mobile-pair-gui/gui-307c863/flutter-widget.json) · [实际 job](https://github.com/Luck9Star/herdr-pocket/actions/runs/42132730593/job/127613103511)

该批 Flutter analyzer 通过，79 项常规测试及 10 项渲染回归通过，1 项 opt-in SSH 测试由上面的独立 job 执行。[Android 聚焦运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/42132730593)

同一主流程也已在 Tauri Linux 原生 GTK/WebKit 应用走通。使用该进程新建的临时设备身份，sshd 确认接受了已审查的公钥；用户选择的 pane 产生 1 个 full 和 1 个 delta，均收到 xterm parser 回调。停止后保留陈旧画面，输入 0 字节，fixture 公钥已撤销、测试进程已关闭。此次源码为 `f2d5594`，并非与 Flutter 同 SHA 的性能对照。[Tauri 原生 GUI 记录](evidence/mobile-pair-gui/gui-f2d5594/tauri-linux.json) · [实际 job](https://github.com/Luck9Star/herdr-pocket/actions/runs/42129682652/job/127602837581)

**Flutter Android API 35 通过手机闭环。** 一次性云 AVD 运行正式 `app.main`、主机目录与原生设备密钥桥。页面重新打开同一待授权请求并核验原公钥，用户审查响应后主动连接；隔离 sshd 匹配已批准的设备指纹。选定 pane 的 full 和增量在同一终端对象上将显示序号从 2 推进到 3，停止后显示陈旧状态。接收端收到 0 字节，测试没有注入 key store、签名器或帧。独立临时身份完成 Ed25519 挑战验签、删除并拒绝再次读取。GUI 本机身份已删除，主机 fixture 授权已撤销，应用进程、测试包与专用 ADB 转发均已清理。此处通过的是 API 35 模拟器与手动输入公开响应的路径；实机摄像头、真实 IME、强硬件密钥等级及三网仍待验证。[Android GUI 报告](evidence/mobile-pair-gui/gui-307c863/flutter-android.json) · [独立签名报告](evidence/mobile-pair-gui/gui-307c863/flutter-android-signer-probe.json) · [清理记录](evidence/mobile-pair-gui/gui-307c863/flutter-android-device-cleanup.json)

**Tauri Android API 35 同样通过。** 原生应用在 WebView 内完成公开请求及响应审查，临时主机接受了 GUI 对应的 Android 设备公钥。选定 pane 后，xterm parser 回调确认消费了 1 个 full、1 个 delta；手动停止后画面标为陈旧，接收端输入为 0。该次设备观察期间的 837 次采样均为 119 × 40，未观测到共享 PTY 尺寸变化。fixture 公钥已撤销，自建测试进程已关闭。[Android GUI 报告](evidence/mobile-pair-gui/gui-307c863/tauri-android.json)

两条路线的手机第一闭环因此有同版本、同 API 级别的实证。下一步优先验证**受保护的逐键／草稿输入、断线后结果核实、隐藏标签恢复**，再做手机真机相机、IME 与三网并发测试；完成正确性对照后决定框架。原型的配色与信息模型继续沿用当前版本。

下一批实现与本地回归见[手机输入、恢复与配置迁移](16-mobile-input-and-config.md)，其云端与设备结果另行记录。
