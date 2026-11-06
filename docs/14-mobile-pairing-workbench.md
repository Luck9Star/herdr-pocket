# 手机配对、主机看板与终端工作台

2026-11-06 最新结果：Flutter 和 Tauri 同一提交的 Android API 35 配对与持续观察均已通过。下载两份当前 APK 请到[手机 GUI 验证记录](15-mobile-gui-validation.md#当前可下载的手机测试包)。下文保留基线包与中间失败版本的来源。

2026-11-05。`main` 首页已更新，公开实现位于 `codex/core-prototype-validation`。先重建了 10 月 30 日已验证源码的两份 Android 基线 APK，随后在原型分支开发设备配对、主机管理、多标签终端和安全输入。项目仍处于原型阶段。[公开首页提交](https://github.com/Luck9Star/herdr-pocket/commit/fb6d39035920064e2dded62bb8a1d4e2df061a40) · [上一阶段的传输与设计证据](13-mobile-dashboard-observe.md)

## Android 基线包

构建分支 `codex/android-baseline-20261105` 的 `b086299` 只收窄云构建矩阵，应用源码与 `221a37a` 一致。两个包均已下载，核对来源、随包清单、哈希和实际 APK。它们展示既有只读看板。配对、相机和远端输入属于后续功能批次。

| 路线 | 应用包 | APK SHA-256 |
| --- | --- | --- |
| Flutter 修补候选 | [Android 测试包](https://github.com/Luck9Star/herdr-pocket/actions/runs/42034838601/artifacts/13417443481) | `642bfad0224591f52ad0639668acdbdf34929f6ce4a4749349edb8930b6f62d7` |
| Tauri | [Android arm64 测试包](https://github.com/Luck9Star/herdr-pocket/actions/runs/42034838719/artifacts/13417169114) | `52c6cdd8ccd1cf90ebda442ac10e9bd138d2fdb9d5e28d9cc6ffe2d22da6290a` |

本地 APK 位于忽略的 `tmp-probe/android-20261105/baseline/`，具体路径、run 与 artifact ID 见[下载记录](evidence/mobile-pair-gui/baseline-builds.json)。GitHub 测试产物有保留期限。

## 手机流程

从主机看板新增资料，核验账号、命名会话、主机公钥及路径，明确创建设备身份。手机展示公开请求，主机操作者使用一次性 helper 核对账号和设备指纹，明确授权后返回公开响应。手机可粘贴文本或请求打开相机扫码，再核对来源、两端指纹及期限。接受后进入“已授权、尚待连通验证”，用户再主动发起 SSH。实际主机公钥匹配、设备私钥签名、认证与 snapshot 成功后，用户从当前会话选择 pane，看到 full 和持续 delta。

Android 两壳共用本机 Keystore 的 AES 封装密钥和 Ed25519 软件签名实现，设备签名路径要求 API 35。Flutter 在 iOS/macOS 接入 CryptoKit 与 ThisDeviceOnly Keychain。Tauri 的 Linux/Mac 签名身份只保存在当前进程；Tauri iOS/Windows 的设备签名入口仍有平台缺口。桌面临时身份和 widget 内存 double 必须与手机系统存储运行分别验收。[Android 来源和存储机制](../validation/pairing/native/android/README.md) · [相机来源及边界](../validation/pairing/native/camera/README.md)

主机目录保存有界的本地资料、引用及状态。再次进入须核验原 handle 对应的公钥，并重新审查连接。停用资料、删除本机身份、撤销主机授权是三个独立动作。标签切换先撤销旧视图的观察／输入许可，返回须主动取得新 full。设备身份、草稿和未知发送正文不进入可移植资料。

## 主机辅助命令

[POSIX helper](../helper/README.md)按当前登录账号解析 home，接受 `preview`、`authorize`、`revoke`。写操作要求主机操作者在控制终端输入与请求 ID 绑定的确认短语。公开响应可输出为 JSON 或 SVG 二维码。收据先记录意图，再修改确切授权行，支持中断后核查。既有公钥、被外部编辑的条目和重复条目会保留给操作者处理。工具仅覆盖非 root 的 POSIX/OpenSSH 默认授权路径。仓库测试只用了自建临时 home，没有访问用户主机的授权文件。

## 为什么原版主机只读

固定 herdr 0.9.5 的 `pane.send_*` 通过 pane 编号查找目标，不能在同一服务端操作中校验期望的稳定 terminal ID。`terminal session control` 可以绑定稳定 terminal，但附着时会调整共享 PTY 尺寸，输入也缺少逐笔受理回执。[目标解析](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/app/ids.rs) · [固定版本服务端](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/server/headless.rs)

[隔离候选补丁](../validation/herdr-input-extension/README.md)新增独立能力查询及稳定目标写入 RPC。服务端在同一事件中核对 pane/terminal，限制 1–4096 bytes，受理后回显请求 ID、目标和字节数。普通 0.9.5 继续只读。扩展主机在 fresh full、活动焦点、显式逐键或草稿模式满足后才允许发送。入队回执与远端命令执行分别显示。发送前持久记录目标与请求 ID，连接丢失或结束前标记未清除时保持“待核实”，重新获取原目标 full 并由用户确认后才可继续。不会重放旧输入，不更改共享 PTY 尺寸。补丁只应用到临时 checkout，未修改真实主机或上游仓库。

## 验证与缺项

首轮集成源码 `3df3e64` 的[配对云任务](https://github.com/Luck9Star/herdr-pocket/actions/runs/42036313680)和[原有 SSH 对照](https://github.com/Luck9Star/herdr-pocket/actions/runs/42036313863)成功。Flutter 首轮 analyzer 因两项冗余 import 停止。Tauri 初次 Android 编译发现 Java/Kotlin 字节码目标不一致，另外四个平台的包构建成功。Linux 原生 GUI 探针进入 pane 选择后，未读到预期屏幕文本，报告 `full_screen_missing`；该轮没有完成闭环验收。对应修正已纳入后续代码：清理 import、沿用各应用模板的编译目标、用 xterm 渲染回调的逐帧计数核验消费情况。渲染计数不能作为字体绘制或真机视觉证据。[首轮 GUI 记录](evidence/mobile-pair-gui/first-attempt/tauri-gui.json)

本机隔离检查包含生产 helper 7 项、v2 配对 21 项、原 helper 15 项、SSH harness 门禁 11 项和 Flutter 包装工具 7 项。Rust/JS、Swift 文件机制及 Android 纯 JVM 的专项检查见各验证目录。手机实机触控、中文 IME、扫码识别、系统锁屏／备份恢复、三网络 15 格和并发 20 格尚需独立运行验收。

后续按[批次策略](07-build-and-release.md)从同一提交运行手机优先验收，按实际 run 和产物更新此页。完整桌面分屏、可移植配置和三网接入继续按设计推进，最后比较正确性合格路线的性能与维护成本。

### 手机工作台集中验证 4c475b2

[批次 42050012843](https://github.com/Luck9Star/herdr-pocket/actions/runs/42050012843) 已产出含配对和持续观察实现的 [Tauri Android debug APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42050012843/artifacts/13425823518)，APK SHA-256 为 `118a80d49a9d933a5ba6d688970866ed4a155fbde7f472a0b9242a2cbf1099d4`。已独立核对 APK、随包 SHA 清单和三份原生库声明。[产物及失败记录](evidence/mobile-pair-gui/paired-builds.json)

- Linux/macOS 的 helper 与配对契约、Android 密钥桥编译通过。Flutter 因可空 SSH channel 和未导入的 `ValueListenable` 停在 analyzer，此提交没有 Flutter APK。
- API 35 x86_64 APK 编译通过。云 runner 缺少 `libpulse.so.0`，模拟器未启动。Linux Tauri GUI 在从主机看板进入异步加载的表单时，驱动过早清空不可交互的输入框，未抵达 SSH 认证。
- 扩展主机源码的 Ghostty 构建需要 Zig 0.16.0，首次未配置该编译器。原版和扩展主机的结果单独记录。

手机修复批次集中处理上述错误，并增加待授权恢复。切后台取响应或切回已保存主机时，两端沿用原设备公钥与未过期的请求，重新核验来源后才可接受响应。Flutter 的真实 SSH widget 探针从主机目录开始，离开后需重新打开相同待处理请求。涉及平台密钥、系统杀进程和真实相机的路径继续独立验收。

### 测试包怎么试

1. 从对应 run 的 artifact 解压，核对 `SHA256SUMS` 和 manifest 的源码 SHA。Flutter artifact 的 `flutter-android-debug.zip` 内有 APK；Tauri artifact 的 APK 位于顶层。基线包可用于比较旧版只读看板。
2. 在授权使用的 Android 测试设备或一次性模拟器上安装相应 APK；当前设备签名实验要求 **API 35 或更高**。从首页新增主机，仅填写测试目标。出现公开请求后切到后台再返回，核对请求 ID 与设备指纹仍相同。
3. 可在没有任何主机授权的条件下检查取消、待授权恢复、过期响应、指纹不符及手动输入兜底。SSH 正向路径由隔离 harness 提供自建临时主机、helper 和测试公钥，使用 Actions 记录核对；扫码、审查或存入主机资料均不会自行连接。
4. 观察挂起时保留旧画面。恢复应要求主动连接、重新选中或核验目标、收到新 full，之后才继续消费 delta。原版 herdr 保持只读；布局变化不改变共享 PTY 尺寸。用完退出测试应用。

EasyTier 的进程内字节流核心已有独立实现。本机的 12 项 C ABI 故障 fixture 覆盖同虚拟 IP 的不同归属、并行读写、取消后迟到句柄关闭及写后结果未知。这里没有运行真实节点，五平台三网络与并发矩阵仍需逐格验收。[复验步骤及 ABI 边界](../validation/overlay-runtime/README.md)
