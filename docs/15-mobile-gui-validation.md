# 手机主机看板与配对的集中验证

2026-11-06。用户从主机页新增目标，核对主机身份和设备公钥，将公开请求交给 helper。在手机上粘贴或扫描响应并再次审查，主动连接后才能查看该命名会话的 pane。看板支持恢复同一台设备的待授权请求，终端页要求用户选定 pane 才开始持续观察。[配对工作台和测试步骤](14-mobile-pairing-workbench.md) · [Penpot 文件与覆盖清单](../design/README.md)

## 已有云端记录

| 源码和运行 | 可复核的结果 |
| --- | --- |
| [基线 b086299](evidence/mobile-pair-gui/baseline-builds.json) | 已重建并下载 Flutter 和 Tauri 两份只读测试包；均已核验 SHA。 |
| [工作台 4c475b2](evidence/mobile-pair-gui/paired-builds.json) | Tauri Android 包含 GUI 配对和观察代码。Flutter 分析失败。Linux GUI 驱动到表单时停止；Android 模拟器缺少系统库，未启动。 |
| [待授权恢复 988f362](evidence/mobile-pair-gui/recovery-builds.json) | 新版 [Tauri Android APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42052516810/artifacts/13426803591) 已验 SHA 和三份随包声明。Linux 上 18/18 项隔离 SSH 对照通过；输入扩展候选服务端编译及目标绑定测试通过。Flutter Android 编译遇到未公开的 `O_DIRECTORY`；Flutter GUI 被静态检查一条多余 import 拦住。Android AVD 已实际启动，两条 Tauri GUI 探针在表单处停止，候选输入服务的 socket readiness 超时。 |

988f362 的 Tauri APK SHA-256 为 `8ef2958ff0aaa3eeddbe13c4c1807907440fec215d7027dc59873daa84939d1c`。该批次未完成“GUI 审查的设备公钥被 sshd 接受 → 选中 pane → 首帧和增量”的整段验收。[Actions 运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/42052516810)

## 面向手机的改动

- 主机首页先初始化可操作的表单；离线实验室仅在打开时初始化。隐藏实验室暂停其模拟终端。已在隔离标识的 macOS 原生包中通过首页按钮进入表单并输入 `fixture.invalid`，未发起连接，测试进程已关闭。Chrome 独立预览也验证了同一入口，测试浏览器和临时服务已关闭。
- 两端按同一 herdr 0.9.5 / protocol 22 快照解释 pane 的标签、agent、工作状态和 workspace/tab。未知状态显示“状态未知”；展示文字不参与目标选择。只接收有界可打印的说明字段，继续以唯一 pane ID 和稳定 terminal ID 绑定目标。云场景仅验证的字段仍应按实际结果报告。[固定 PaneInfo](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/schema/panes.rs) · [共享快照](../validation/shared/dashboard-snapshot.json)
- Flutter 在 Android 公开 API 上以只读且拒绝跟随符号链接的方式打开目录，通过 `fstat` 检查实际类型并在原子替换后同步。单独的 Flutter AVD 入口使用正式主机目录、Android 受保护密钥和 SSH 适配器。runner 只能交换这次测试的公开请求与响应。[Android Os](https://developer.android.com/reference/android/system/Os) · [OsConstants](https://developer.android.com/reference/android/system/OsConstants) · [Flutter AVD 步骤](../validation/flutter/integration_test/README.md)
- Tauri iOS 接入共用的 CryptoKit 签名、ThisDeviceOnly Keychain 后端及相机授权响应入口。本机 3 项 Swift 接线及内存替身测试通过，系统 Keychain 调用数为 0，iPhone 签名安装、相机、锁屏和重启仍待验。[iOS 插件实现](../validation/tauri/ios/PocketPlugin.swift)

## 下一步验收

1. 从同一来源验证两份 Android 应用包和两种模拟器 GUI。核对 helper 接受的设备公钥指纹、sshd 的实际记录、已选 pane 的 full/delta、主动停止及设备进程关闭。原版只读用例要求接收端输入为 0。
2. 将带保护输入的隔离候选主机单独验证。需要匹配请求 ID 的队列受理回执和精确的终端接收字节；网络结果未知时保持锁定，人工核实原目标再恢复，不重放。
3. 在能取得真机时补扫码、中文 IME、触控、键盘变化、锁屏与长期运行。三网与跨网并发仍待逐端验证；确认正确性后再定框架并回写高保真页面。
