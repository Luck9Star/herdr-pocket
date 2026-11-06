# 手机网络配置与迁移契约

2026-11-06。两套 GUI 使用独立网络配置和显式主机引用。公开配置描述、设备节点身份、SSH 身份和活动连接分别绑定；连接时固定配置 ID 与 revision，目录或绑定变化会撤销相关连接许可。当前实现与设备结果随本批验收更新。

## 公开记录

`NetworkProfile` 精确包含 `id`、`label`、`provider`、`enabled`、`revision`、`settings`。ID 为本机生成的 32 位小写十六进制；label 非空、UTF-8 最多 96 bytes，拒绝 C0／C1 控制字符。revision 为 1 至 2147483647 的整数，新建为 1，每次修改递增，达到上限后拒绝修改。本机最多保存 32 个配置。

| provider | settings 字段 | 校验 |
| --- | --- | --- |
| tailscale | controlUrl、hostname | controlUrl 空串采用原生默认值，其他值为 HTTPS 绝对 URL。hostname 允许空串，指定时为 1–63 位 ASCII 字母数字或连字符，首尾字母数字 |
| easytier | networkName、peers | 名称非空、UTF-8 最多 64 bytes、拒绝 C0／C1。peers 为 1–16 个唯一地址，支持 tcp、udp、ws、wss；tcp／udp 必须给出 1–65535 端口，路径为空或 `/` |
| zerotier | networkId | 16 位小写十六进制，拒绝全零 |

上述 URL 最多 2048 个 ASCII 字符，必须有 host，拒绝空白、反斜杠、userinfo、query 和 fragment。WebSocket 可带路径和默认端口；任何显式端口必须在 1–65535 内。settings、profile 与迁移载荷拒绝未知字段、重复键及类型转换。表单可以在提交前提示并规范用户输入，持久化与解密后的验证采用严格格式。

网络秘密、认证 token、节点状态与身份目录由后续设备安全存储接口处理。公开表单仅收集本表字段，界面显示配置保存状态和当前连接组件的真实可用性。

## 连接与修改

主机记录增加可空的 `networkProfileId`。旧文件缺失此字段时归一化为 null，沿用原来的系统连接路径，原 `provider` 标签继续保留其历史描述用途。新显式绑定必须指向已存在的网络记录；用户解除绑定时审查改用系统路径的影响。

修改、停用和解除绑定前展示受影响主机。保存采用目录整体 CAS，并在提交前撤销受影响标签的输入与连接许可。停用保留引用并阻止连接。被引用的网络删除返回 `network_in_use`，由用户先处理引用。目录重读或保存结果未知时，旧许可失效；晚到结果必须匹配原目标、网络 revision 和连接 generation。

网络接入入口位于连接所需的设备凭据读取、签名和 SSH 拨号之前。缺少真实 bridge、安全存储或节点授权时，按具体缺项阻止连接；本地配对审查、公钥生成与待授权请求恢复仍可单独操作。配置记录与页面标签本身不能产生网络可达状态。隐藏标签仍按既有规则等待原目标新 full，输入恢复须显式操作；本地字号与布局调整沿用共享 PTY 尺寸约束。

## 迁移 v2 与终端字号

加密 envelope 沿用 `HPKT` v1／suite 1。v2 plaintext 精确包含 `version`、`hosts`、`networks`、`preferences`。旧 v1 plaintext 保留原有解密与导入路径。

- `hosts` 最多 16 项，每项为 `label`、`provider`、`target`、`networkKey`。networkKey 必须出现，可为 null；有值时必须引用本档案中的网络，provider 与所引用网络一致。
- `networks` 最多 16 项，每项为 `key`、`label`、`provider`、`settings`。key 是档案内的唯一引用，格式 `[A-Za-z0-9_-]{1,32}`。本机 ID、revision、enabled 与身份材料均不进入档案。
- `preferences` 必须出现，可为 null，或精确为 `{ "terminalFontSize": 14 }` 形式，字号整数范围 10–28。本机旧目录默认 14。导入偏好需要用户显式勾选。
- hosts 与 networks 均可为空，整个包至少有一项主机、网络或非空 preferences。大小继续受 65536-byte plaintext 上限约束。

导出所选主机时带入其依赖网络，也允许显式选择独立网络和字号偏好。导入预览列出网络参数及主机绑定，同名配置明确显示将新建；用户可以取消整个操作。实际导入网络生成新本机 ID，revision 为 1，初始停用，等待本设备独立配置授权。只有实际应用主机需要的网络及用户显式选入的网络才创建。保留主机的选项沿用其原绑定。

主机新增／保留／替换、网络新建和偏好修改组成一次目录事务，整批容量、引用和 revision 校验完成后才撤销受影响连接。替换主机继续保留退役的原设备身份供撤销核查。字号只影响本机呈现。

## 共享证据

[network-profiles-v1.json](../shared/network-profiles-v1.json) 包含 4 个有效记录与 41 个拒绝样例；[config-transfer-v2.json](../shared/config-transfer-v2.json) 包含独立 Python PBKDF2／AES-GCM 生成的 829-byte plaintext、879-byte archive，以及 3 个有效与 20 个拒绝 plaintext。Rust 与 Dart 分别消费相同字节。旧 [v1 黄金样例](../shared/config-transfer-v1.json) 继续覆盖历史档案。SHA 记录在 [共享校验和](../shared/SHA256SUMS)。

样例使用虚构地址和公开测试材料。实现的编译、单元／widget、原生 GUI、真实组网和设备体验分别记录；三网平台与并发矩阵仍见[总验证记录](../../docs/09-prototype-validation.md)。

2026-11-06 按 Context7 的 library → docs 查询官方 EasyTier、Tailscale 和 ZeroTier 文档。当前官方资料用于字段含义核对，原生实现继续依据 [sources.json](../native/sources.json) 的固定版本。EasyTier 的共享网络名称与秘密由节点匹配，tsnet 的服务器配置与本机身份状态分开，ZeroTier 网络 ID 使用 16 位十六进制并经 node join 处理。[EasyTier 官方配置](https://github.com/easytier/easytier/blob/main/README.md) · [tsnet 官方说明](https://github.com/tailscale/tailscale/blob/main/tsnet/README.md) · [ZeroTier Sockets](https://github.com/zerotier/docs/blob/main/docs/sockets.md)

## ZeroTier 设备级身份基础（2026-11-07）

`native/android/ZeroTierDeviceStoreCore.java` 是独立设备 namespace 的托管核心，151 个临时 JCE／JVM 检查通过。它保留跨进程 owner 租约、原生退休证明接口及明确的创建／删除恢复；不复用首个 profile 作为全局身份。不可读身份的两步丢弃仅针对同实例此前认证过的 handle；跨重启缺少可信引用仍阻断。尚未接 AndroidKeyStore、JNI、network manager 或 GUI，不在当前测试包中。[实现与完整边界](../../docs/28-zerotier-native-foundation.md)
