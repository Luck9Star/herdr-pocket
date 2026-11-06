# 加密配置迁移

本实现供两条手机候选使用。导入界面先显示目标、冲突和所需新授权，确认后提交一次本机目录更新。正在使用的被替换目标先停止输入与观察。配对身份保留在停用的旧记录中，新记录取得新的本机 ID 并重新配对。

2026-11-06 增加 plaintext v2，包含公开网络配置与可选字号；加密 envelope 继续沿用下述 v1 格式。旧 v1 plaintext 可读取，新 GUI 默认导出 v2。网络引用、导入停用及单次目录事务见[网络迁移契约](../network-profiles/README.md)，当前验收见[手机网络记录](../../docs/18-mobile-network-profiles.md)。

## 版本 1 格式

文件依次为 4-byte ASCII `HPKT`、版本 `01`、套件 `01`、16-byte salt、12-byte nonce，以及 AES-256-GCM 密文和末尾 16-byte tag。完整的 34-byte 头部作为 AAD。PBKDF2-HMAC-SHA256 固定迭代 600,000 次，派生 32-byte key。每次导出以系统安全随机源生成 salt 和 nonce。格式选择为本轮实现默认值，移动设备上的耗时仍需实测。

口令原样以 UTF-8 编码，保留空格与 Unicode 形式。新口令至少 12 个 Unicode 标量，最大 1,024 UTF-8 bytes。读取支持 1–1,024 bytes。明文最大 65,536 bytes，文件最大 65,586 bytes。格式、长度、版本、套件及口令边界先于 KDF 检查，错误口令与认证失败均拒绝预览和写入。KDF 在后台运行，Tauri 限制同一时刻只能处理一项。

Rust 使用锁定的 `ring 0.17.14`，Dart 使用 `pointycastle 4.0.0`。两者分别调用成熟库的 PBKDF2 和 GCM 实现。[ring PBKDF2](https://docs.rs/ring/0.17.14/ring/pbkdf2/fn.derive.html) · [ring AEAD](https://docs.rs/ring/0.17.14/ring/aead/struct.LessSafeKey.html) · [PointyCastle 4.0.0](https://pub.dev/documentation/pointycastle/4.0.0/)

v1 明文采用严格 JSON schema，每份包含 1–16 个 `hosts`。字段为 `label`、`provider`，以及 `target` 中的 `host`、`port`、`username`、`expectedHostKey`、`socketPath`、`herdrPath`、`session`。v1 范围为主机定位与网络类型元数据；v2 扩展上述网络模型与偏好。两个版本均由白名单排除设备身份、秘密、输入与终端运行状态。

## 审查与事务

- 预览绑定完整候选资料和当前目录 revision。重新读取文件、目录变化、离开预览或票据失效均须重新审查。
- 每项明确选择添加、保留或替换。替换必须覆盖预览列出的对应冲突，重复消费同一旧记录和容量不足在提交前拒绝。
- 新记录无配对身份。被替换的已配对记录保持原 ID、目标与密钥引用，并标记退役停用，供用户在原主机核查撤销或明确删除本机身份。
- 所有资料在单次原子提交中更新。若原生保存已开始而结果未确认，需要重新读取目录核实；不自动重试写入。

## 文件通道

Android 使用系统 Storage Access Framework 选定的 `content:` URI，后台读写有界字节。Flutter Android、iOS 和 macOS 已接入同名文件通道；Tauri Android/iOS/macOS 各接入原生选择器。其他桌面平台保留显式文件控件路径，实际下载与安装环境需要独立验证。[Android 文件选择](https://developer.android.com/guide/components/intents-common#OpenFile) · [Apple 文档选择器](https://developer.apple.com/documentation/uikit/uidocumentpickerviewcontroller)

系统取消返回独立取消结果。文件写入已经开始时要等待其结果，写出失败需用户核查目标文件。Tauri 的 macOS 测试包最低版本设为 11.0，与本轮 Swift 桥的编译目标一致。iOS 临时导出采用设备保护的临时文件，正常成功、取消与结束会清理；强杀或崩溃后的残留清理仍待完成。

## 现有验证

`../shared/config-transfer-v1.json` 是公开合成样例，包含测试口令、固定随机材料、明文和加密字节。它由 Python 的 `hashlib.pbkdf2_hmac` 与 `cryptography` 的 `AESGCM` 独立生成并解回，摘要纳入共享 `SHA256SUMS`。Rust 已得到相同加密字节。Dart 对该样例的双向测试将在相同源码的云批次运行。

Mac 已运行 Rust 认证失败、长度、严格 schema、目录冲突与原子失败回归，完成 Swift 静态库及 Tauri 完整链接。自建临时文件验证了 Apple 协调读写、线程与取消门禁。系统选择器的实际点选、Android/iOS 文件提供方、跨设备实际搬运及所有平台的耗时均需要对应运行证据。完整批次结果统一记录在手机 GUI 验证文档。
