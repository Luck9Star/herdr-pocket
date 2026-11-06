# 手机节点生命周期与显式 SSH 路由

2026-11-06，延续 [本机入网资料批次](19-mobile-network-identity.md)。本批把 Android vault 内部配置读取、共享 Rust 节点服务和 Tauri 手机连接路径接在一起。**这是源码集成和隔离验证；没有启动真实 EasyTier 节点、重建 APK 或触发 Actions。默认应用缺少已验证的 Android 原生库时仍拒绝组网连接。** [现有下载](18-mobile-network-profiles.md#android-下载与实际结果)继续对应 `040eb26`，不包含本批。

## 从本机资料到节点

Android 新增 JNI 专用配置入口，在同一次加锁、认证解密中核验 profile、handle、模式和稳定 instanceId。只接受已审查的网络名称和 peers，构建固定 TOML：instance_id、DHCP、空 listeners、network_identity、peer URI 和 no_tun。没有任意 TOML、秘密读取或导出到 Dart／JS 的接口。

共享 [Rust Android source](../validation/android-network-source/README.md)缓存 JavaVM、应用 Context 和类引用；生命周期 worker 通过 JNI 读取短寿命配置。它校验保存的 profile revision、网络名和身份 handle，清理 Java 数组与自有临时字节，不打印 Java 异常内容。没有重新生成身份、明文存储或系统网络回退。引擎、虚拟机内部副本仍不能保证完全擦除。

固定 Heeler `6a2817f` 的 outbound-only 策略拒绝空秘密，因此 **`PUBLIC_NO_SECRET` 可以作为明确的本机资料模式保存，但当前候选不能启动它**。Tauri 页面显示原因，后端按认证后的公开元数据再次拒绝；没有擅改网络模式或填入替代秘密。

## 启动编号与配置版本分别绑定

共享 `MobileNodeService` 的公开 Binding 保存 profile ID、持久配置 revision、网络名、身份 handle。每次显式启动另分配单调递增的内部 attempt。重新启动同一配置不改变输入恢复标记中的配置版本；旧 NodeLease／旧 dialer 只能指向原 attempt，不能接到新节点。

同配置的身份删除后重建会产生新的 handle；原节点彻底停止并回收后，才能显式启动新身份。旧身份的未知发送记录不会被新身份清除。调用方必须保证同 revision 的公开 peers 不变，service 本身不读取目录或复制秘密。

状态限于 Starting、EngineStarted、Closing、Stopped。**EngineStarted 只代表本机引擎接受启动，不代表入网、peer 可达或 SSH 认证。** 启动失败、取消、迟到完成与停止失败继续保留资源占额；不会自动再次启动。停止与状态回执都核对原 attempt，关闭中的节点不能被旧状态回复重新激活。

同一 service 最多保留 8 个未清理节点及 32 个配置 ID 历史；停止后的历史不自动淘汰，以保留版本检查。反复删除、新建超过历史上限需重建应用 runtime，现阶段没有后台自动清理策略。

## Tauri 手机接线与默认门禁

手机网络页增加节点状态、刷新、显式启动与停止，并在操作前核对目录版本、配置版本、身份和影响主机集合。修改网络／身份先撤销相关 SSH，再等待节点停止；停止结果不确定时不继续写入。单个主机解绑或删除只撤销该主机连接，保留其他主机共享的节点。

持续观察通过实际 `OverlayDialer` 进入共享 SSH host key 校验、设备签名、看板、选 pane 和 full/delta 流程。显式绑定网络时没有系统 TCP fallback；没有网络绑定才沿用 SystemDialer。原实验性单次读取入口仍是无 profile 的显式系统读取，不属于组网入口。

`network-easytier` 是显式 Cargo feature，继续要求已审阅、按目标平台构建的原生库与 `HEELER_ET_LIB_DIR`。默认关闭；桌面及未接入的 provider 返回不可用。Android JNI 初始化失败也不能显示可启动。Flutter 本批只更新共享 Java 来源记录，**平台流和节点 GUI 尚未接入**；两路线不因此收敛选型。

## 验证边界

本批检查、源码摘要与未验证项归档于 [node-routing-source-20261106.json](evidence/mobile-pair-gui/node-routing-source-20261106.json)。Java vault 38 项、配置构建 33 项、Python TOML 独立解析，以及 JNI Rust 2 项与桌面 JVM 52 项通过。JVM 使用合成 Context／配置类并启用 `-Xcheck:jni`，不能算 AndroidKeyStore 或 Android 设备结果。独立审查另外覆盖控制字符、补充 Unicode、伪造 TOML 片段和畸形 UTF-8。

共享 service、runtime、Tauri 和打包工具的最终检查数量以 JSON 逐项记录为准。Android feature、Kotlin／Gradle、实际 native parser、设备锁定、前后台、真实组网拨号及 SSH 端到端尚未执行。现有五端 × 三网及并发验收矩阵没有新增通过格。本批仅运行隔离命令行测试，未打开 GUI 测试应用。

## 下一步

1. 为 Android 固定来源原生库补齐可审阅的构建、打包和来源关联，再把 Flutter 平台字节流接入同一节点契约；集中构建时一并复验此前 Flutter 回归与驱动修正。
2. 在授权的隔离组网环境中验证实际节点 → SSH → 配对接入／看板／持续观察，保留入网、连通、host key 和 session 绑定的分层证据；先只读，再输入。
3. 推进手机跨网络标签与互不影响的停止／恢复，分别接入 Tailscale 和 ZeroTier。本机损坏身份恢复、真机 IME／触控／相机和 iOS 签名继续单列；桌面分屏与焦点在手机闭环后。

## 固定来源核对

- [Heeler outbound-only 策略](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/native/easytier/src/lib.rs)与既有 managed-node 补丁保持不变。
- [EasyTier TOML 模型](https://github.com/EasyTier/EasyTier/blob/728ba94b5029240add6204eed591f22e4e039e6b/easytier-core/src/config/toml.rs)核对了 UUID instance_id、dhcp、peer 和 flags；固定 blob `81692860334e6e1547d6953d2b9df9e197a56382`。这属于源码核对，不是运行解析器的结果。
- JNI 固定 `0.21.1`。Context7 返回的泛版本示例不适用时，改以固定源码和 [0.21.1 JavaVM 文档](https://docs.rs/jni/0.21.1/jni/struct.JavaVM.html)核对，不混用新版 API。
