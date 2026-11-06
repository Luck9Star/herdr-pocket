# 手机本机入网资料与 SSH 网络流接线

2026-11-06，后续源码批次。本批接入两套手机 GUI 的 EasyTier 本机秘密管理，并为 Rust SSH 传输增加显式 overlay 字节流适配。**没有重建 Android 包或触发 Actions；[上一批下载和设备证据](18-mobile-network-profiles.md)仍对应 `040eb26`。本批尚未把 Android vault、原生节点启动和 GUI SSH 连成可运行的组网闭环。**

后续源码已增加 JNI 配置源、共享节点服务和 Tauri 手机显式路由，Android 构建与真实组网仍待验收；最新状态见 [节点接线记录](20-mobile-node-routing.md)。以下保留本批次原验证边界。

## 手机入口与本机资料

Flutter 和 Tauri 的网络管理页在公开配置之外提供本机入网资料入口。Android API 35 起使用同一份 [Java vault](../validation/network-profiles/native/android/README.md)；其他平台或 provider 明确显示尚未接入。资料保存不表示节点启动、加入网络或连接成功。

- 模式由用户明确选择：`PRIVATE` 接受 1–1024 个有效 UTF-8 字节且禁止 NUL；`PUBLIC_NO_SECRET` 只接受空秘密。空输入不能隐式转成无密码网络。
- native 为每份 profile 生成独立 UUIDv4 handle 和固定 instanceId。profile/provider 唯一，重复创建拒绝，不覆盖已有身份。`status` 验证记录与密钥后只返回公开资料；找不到文件才是未配置，锁定、损坏或丢 key 均为不可读取。
- 原生 `create / status / delete` 在后台线程运行；GUI 没有读取秘密、导出身份或任意 TOML 的 API。SSH 配对密钥使用另一个目录和 alias，不会随网络资料删除。
- 保存／移除前核对配置版本和受影响主机，停止这些本地标签；未知结果只重新读取，不重发、反向删除或自动连接。删除公开配置前，Android 必须确认对应本机资料已明确移除。
- 秘密字段提交或离开时清空，不进入 HostCatalog、配置迁移 v2 或日志。可变字节缓冲区尽力清零；Dart/JS/Java String、平台编码器与引擎副本不能承诺完全擦除。

存储为 app `noBackupFilesDir` 下的有界 AES-GCM envelope；AAD 绑定版本、profileId、provider、handle。AndroidKeyStore 的 AES key 要求设备解锁，读取失败不重新生成，不降级明文。纯 JVM 测试注入内存 backend，不操作真实设备密钥。

## 显式网络流到共享 SSH

新增 Rust `ByteStream / Dialer / SystemDialer` 和 `OverlayDialer / OverlayStream`，由同一个 `connect_pinned` 执行 SSH host key 检查；只读和受保护输入入口共用认证、目标绑定和取消逻辑。原系统路径保持原行为，指定 overlay 不会转去系统 DNS/TCP，也不使用 localhost relay。

`OverlayDialer` 捕获实际 app-owned `NodeLease`，每次连接创建新 owner；原 runtime、provider、profile 和 revision 必须匹配。Read/Write await 现有 native worker operation，Tokio poll 不执行阻塞 FFI。部分写只推进已受理前缀，UNKNOWN 或取消后关闭该流且不重放。关闭只发起清理，未返回或失败的资源仍占原 runtime 配额。

正常空闲的 read timeout 与连接错误分开；只有固定 ABI 明确返回、且原 read 已回收的超时才能重新等待读取。写超时不重试。持久输入恢复标记绑定实际连接流的 provider/profile/revision/本机 identity reference；缺字段的旧标记只代表原系统路由，不得由同 IP 的另一网络清除。

这层适配器可供 Tauri 后端连接。Flutter 的平台网络流以及两套 GUI 到真实 node 的生命周期接线仍未完成。native fixture 仅用于测试；缺库时不能选择合成 backend 作为 fallback。

## 证据范围

| 检查 | 本批可证事实 | 不涵盖 |
| --- | --- | --- |
| Android vault JVM | 38 项离线断言通过（含元数据不可读取和实际 POSIX 拒绝）；独立 8 JVM 同 profile 竞争仅 1 次创建成功；失败清理反例通过 | AndroidKeyStore、真实设备锁定、Android 文件系统耐久性 |
| Android Java API stub | 共享 Java 通过临时 stub 编译 | 实际 Android SDK / Gradle 编译、平台运行 |
| Flutter | 新增状态、平台通道与目录竞态测试；53 个 Dart 文件语法、8 项 Python 工具及隔离 scaffold 检查通过 | Dart analyzer、Flutter/widget 与 AVD 尚未执行 |
| Tauri | JS 65 项、Rust 20 项与前端构建通过；Android scaffold 接入检查通过 | Kotlin / Gradle 构建、手机实际 UI 与安全存储 |
| overlay→SSH | transport 42 项 library + 1 项 CLI、runtime 24 项 fixture + 1 项默认门禁通过；含真实 russh 握手拒绝错 pin | 真实 EasyTier 拨号、跨网并发与真机 |

父代理独立复跑 JVM 38 项、整合后 Tauri Rust 20 项、网络 UI 9 项和 overlay adapter 11 项，全部通过。完整 transport 与 runtime 的结果由子代理执行，并结合源码复核。[本批源码与检查记录](evidence/mobile-pair-gui/network-identity-source-20261106.json) · [Rust 命令与范围](../validation/transport-rust/README.md)。

严格 transport Clippy 未通过，剩余 12 个诊断位于既有迁移、input、旧 API 和 loopback 测试；没有将该检查算作通过。编译、测试替身、原型画面和设备结果分别计数，五平台 × 三网矩阵仍保留原未验证项。本批没有启动测试应用或真实网络节点。

## 仍需实现与下一步

1. 将已保护的本机资料通过 native 内部回调转换成固定 EasyTier 配置并启动真实 managed node，验证稳定 instanceId 与 no-TUN 路由；秘密不得绕回 GUI。把有限状态映射到手机配对、看板和持续观察。
2. 接入 Flutter 平台流与两套 GUI 的真实 overlay SSH 路由、前台跨网标签，验证取消、停用和恢复不影响其他 provider。Tailscale 与 ZeroTier 分别实现身份和运行时，不能将 EasyTier 成功外推。
3. 完成损坏／缺 key 后的明确本机恢复策略。当前普通删除会先验证记录，因此无法删除这些异常记录；崩溃也可能留下 orphan alias 或 pending 文件。没有自动清理、rollback 防护或保证所有进程内秘密副本被擦除。
4. 积累上述集成后集中云构建，同时复验上一批 Flutter 的驱动与回归修正；有真机条件后单列触控、IME、相机、锁屏、跨重启和 iOS 安装。桌面分屏与独立焦点排在手机接入闭环之后。

## 来源

库版本继续固定为 `russh 0.65.0`、`Tokio 1.54.1`、`zeroize 1.9.1`，没有引入新的第三方 Android vault 依赖。固定 Heeler/EasyTier 来源沿用 [native source audit](../validation/native/managed-source-audit.json)；适配器不得用新 main API 替换该来源。

本批按 Context7 library → docs 核对 [Flutter 平台通道](https://github.com/flutter/website/blob/main/sites/www/content/blog/flutter-platform-channels/index.md)、[Android unlocked-device key 配置](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec.Builder#setUnlockedDeviceRequired(boolean))。版本相关行为还须依固定源码和实际构建验证。
