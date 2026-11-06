# Flutter Android owned overlay bridge

2026-11-06，源码验证。此独立 crate 输出 `libherdr_flutter_network_runtime.so`，把 [MobileNodeService](../transport-rust/src/mobile_nodes.rs)、[JNI vault source](../android-network-source/README.md) 与真实 `OverlayDialer` 字节流接到 Flutter。默认不链接任何 overlay 库，也不读 vault；支持显式 EasyTier 和 Tailscale，不回退系统 TCP、DNS、localhost relay、其他 provider 或测试 fixture。本批未安装 SDK/NDK、未触发 CI、未启动真实节点或读取真实身份；Android 编译和设备运行另验。

## Native packaging

`network-easytier` 和 `network-tailscale` 分别显式转发既有的 provider 链接特性；受控候选库目录继续使用 `HEELER_ET_LIB_DIR`。依赖固定在本目录 Cargo.lock，直接依赖沿用 `jni 0.21.1 / tokio 1.54.1 / serde 1.0.229 / serde_json 1.0.154 / zeroize 1.9.1`。Android source 以 rlib 链入本 cdylib，不加载独立 source cdylib。

Android API 35+ 的 Kotlin channel 尝试加载各 provider 的 `heeler_easytier` / `hp_tailscale`，加载 `herdr_flutter_network_runtime` 后分别绑定 `AndroidEasyTierConfig` / `AndroidTailscaleConfig` 与 applicationContext，再创建 scope。provider capability 还须同时具备对应编译特性及 Context 绑定。**单个 runtime 的所有 DT_NEEDED 都是加载前提**：双 provider runtime 缺任一必需 so 时整个 runtime 不可用；不承诺损坏包中另一个 provider 可继续运行。单 provider 构建可独立装配，不回退。两个库的架构、同源 manifest、SHA、其余 `DT_NEEDED` 和打包证据须由构建层验证。显式 `native-fixture` 只链接 Unix 合成 C ABI；若用于 Android target，编译直接拒绝。

## MethodChannel contract

通道为 `dev.herdr/network-runtime`。Kotlin 每个 Flutter engine 私有一个 native scope，Dart 不接收、不指定 scope。所有方法参数为严格 key 的 map；所有错误为脱敏 `PlatformException.code`。ET 的 `Binding` 恰为 `{profileId, profileRevision, networkName, identityRef}`，TS 增加 `provider:"tailscale"`：ID 为目录 32 位小写十六进制，revision 为正 int32，identityRef 为 vault UUIDv4 handle。它不是 instanceId 或原生 node ID。

| Method | Arguments | Success result |
| --- | --- | --- |
| `available` | none / `{}`（ET），TS 为 `{provider:"tailscale"}` | `{available:bool, reason:String|null}` |
| `nodeStatus` | `{profileId}`；TS 为 `{profileId,provider:"tailscale"}` | `{state,binding:Binding|null}` |
| `nodeStart` | ET `{binding,peers:List<String>}`；TS `{binding,settings:{controlUrl,hostname}}` | `{state,binding}` |
| `nodeStop` | `{binding}` | `{state,binding}` |
| `nodeLogin` / `nodeLoginStatus` | `{binding}`（TS） | `{state,binding,authUrl,reviewToken}` |
| `openLogin` | `{binding,url,reviewToken}`（TS，显式用户动作） | `{opened:true}` |
| `streamOpen` | `{binding,host,port,openId:String}` | `{streamId,route}` |
| `cancelOpen` | `{openId:String}` | `{cancelled:true}` |
| `streamRead` | `{streamId,maxBytes:1..65536}` | `{bytes:Uint8List,eof:bool}` |
| `streamWrite` | `{streamId,bytes:Uint8List(1..65536)}` | `{accepted:1..submittedLength}` |
| `streamFlush` | `{streamId}` | `{flushed:true}` |
| `streamShutdown` | `{streamId}` | `{shutdown:true}` |
| `streamClose` | `{streamId}` | `{closed:true}` |

节点 state 为 `unavailable / starting / engine-started / needs-login / needs-machine-auth / running / closing / stopped`。TS 只有 Running 可拨号。只有 stop 返回 `stopped` 才是原节点清理确认；错误、超时或 Closing 不能当成功。EngineStarted 只代表引擎接受启动，不表示入网、peer 可达或 SSH 准备好。nodeStart 的 Java vault config builder 和 Kotlin 入口均明确拒绝 PUBLIC_NO_SECRET，不隐式改变模式。

`route` 只取自实际连接的 `ByteStream::route_identity()`，恰为 `{provider,profile_id,profile_revision,identity_ref}`；不加入 caller 提供的 instanceId、临时 attempt 或 owner。复用同一保存配置重启时 route 保持稳定，换 vault handle 后 route 改变；未知输入恢复必须与实际 route 精确比较。公开 peers 不在 Binding 中，由可信 GUI 目录 CAS 保证相同 revision 不变；本服务不能识别同 revision 偷换 peers。资料只在 Java vault → Rust source → native engine 内部流动，不回 Dart。

TS 设置先经共享 `TailscaleSettings` 验证、填充默认值并计算配置 hash；
只有 hash 与 binding 的 networkName 完全一致才允许创建身份源。TS 身份
channel 的 create 仅接收 profileId/provider，公开 mode 为 DEVICE_STATE；
status 返回引用，delete 和 nodeStart 精确核对 handle，state 字节从不经 GUI。
登录只有显式 `nodeLogin` 发起；`nodeLoginStatus` 只读。授权 URL 与一次性
reviewToken 成对返回，native 保存原 attempt，并在 `openLogin` 前再次核对原
attempt、URL 与 token。前后台切换、其他登录请求、start/stop 或 scope 关闭会
撤销 Kotlin 的待打开资格；仅用户点击时通过 ACTION_VIEW 打开已核对 URL。
旧 token 不在相同持久 binding 的新节点上复用。

## Bounded ownership and I/O

全 app 共享一个 service，但每个活动 profile 只属于一个 engine scope，其他 scope 不能启动、停止或拨用它。streamId 为本进程从不复用的 opaque token，须同时匹配私有 scope；它不是 native handle。detach 立即退休自己 scope 的 open/start admission、取消自己的 pending operation、abort 自己的 stream，然后异步停止自己拥有的节点，不停止其他 engine 或同 provider 的其他 profile。

延迟 cleanup 在 owner 锁内先取消 pending start，再捕获 service 的 opaque `NodeAttempt`；`stop_attempt / status_attempt` 在 service registry 锁内比对原 attempt 后才退休或查询，不能跟随相同持久 Binding 的重启节点。尚未 admit 的 owner 保留 Starting，不能被旧 Stopped history 清除；不同 Binding 的 Stopped history 不当作新 attempt。`NodeAttempt` 不序列化、不暴露 attempt 数字，不改变持久 recovery route。

总计最多 4 个 scope（含尚未确认清理的 retired scope）、8 个 node、32 个 stream admission slot。32 slot 同时计入 queued reservation、pending native open、活动流、取消迟到结果及失败清理。单次 cancel/close 回执只表示 admission 退休。为避免无证据释放，retired stream ledger 只有在 runtime `reserved_streams()==0` 时才回收；因此另一个长期活动流可能让已物理关闭的 slot 保守占用更久。失败 node 清理保留 node 与 scope 配额；只有显式 stop/close-scope 重试，背景仅观察原 worker 的 status。底层 service 的 32 个 profile 历史 ID 上限同样保留。

openId 为每个 Dart channel 严格递增、不复用的正十进制字符串。Kotlin fast lane 先调用 `nativeReserveOpen` 顺序登记，再将阻塞 open 投到独立 pool。`cancelOpen` 可以先到，只记该 ID，不误杀其他并发 open。每 scope 最多 4096 个未来取消 tombstone；超额明确拒绝，不静默遗忘。高水位前的 ID 永久拒绝重用；越过的取消 ID 由高水位拒绝保证，不再占 tombstone。

每个 stream 每方向最多一个请求，read 与 write 独立 admission。stream 共享 mutex 只包单次 `poll_*` 或 `abort`，不跨 await；只接收已审查的 OverlayStream，poll 不跑阻塞 FFI。native FFI 仍在原 runtime worker。Kotlin 为 fast control、start、status、stop、open、read、write 分池和设置有限队列；挂起 read/start 不占写入、关闭或停止 lane。

一次 JNI read 最多等 250 ms。超时只丢弃 `poll_fn` 等待，原 Operation 留在 OverlayStream，下次 pull 继续等它；没有第二个未回收 native read。空数组且 `eof:false` 表示 idle/pending，Dart 须 await 小退避后继续 pull；只有 `eof:true` 是 EOF。原 ABI 的 read deadline 仍为 10 秒，挂起 FFI 不占 Kotlin read lane。换 read buffer 大小保留原适配器的剩余字节。

write 只报告已接受前缀；调用方仅推进 accepted，不重发已接受部分。UNKNOWN、write error 或 10 秒外层超时均 abort 原流并报 `overlay_unknown_write`，不会重试。flush 只确认本地适配器状态，不能代表远端送达；shutdown 仅半关闭写入，可继续读。close/cancel 可在 read/write pending 时独立退休原流，迟到 native handle 仍占原预算直到清理。

## JNI wire

Kotlin `dev.herdr.pocket.NetworkRuntimeChannel` 的 companion `@JvmStatic external` 方法为：

```kotlin
nativeCreateScope(): Long
nativeReserveOpen(scope: Long, openId: String): String
nativeCall(scope: Long, method: String, argsJson: String, payload: ByteArray?): Array<Any?>
nativeCloseScope(scope: Long): String
```

创建失败返回 0。reserve/close-scope 返回 JSON envelope：`{"ok":true,"value":...}` 或 `{"ok":false,"error":"safe_code"}`。call 返回恰为 2 元素的 Object array，元素 0 是同一 envelope String，元素 1 仅 read 成功时为 byte[]，其余为 null；Kotlin 再把 bytes 放入 MethodChannel result。streamWrite payload 单独传 byte[]，不进 JSON。native 校验 metadata 40,000 UTF-8 bytes 与 payload 65,536 bytes 上限，清除 JNI exception 而不 describe/log。Rust 输入副本、Java config array 及 Kotlin write queue 可变缓冲区尽力清零，不保证 Dart/平台/engine 内所有副本擦除。

预 admission 错误包括 `invalid_network_request / invalid_network_binding / overlay_provider_unavailable / network_native_context_unavailable / network_scope_unavailable / network_scope_mismatch / network_capacity / network_scope_capacity / network_cancel_capacity / network_open_id_invalid / network_open_id_reused / network_open_not_reserved / network_stream_busy`。service 保留 `mobile_node_* / overlay_stale_revision` 等固定错误。`cancelled / network_start_unknown / network_open_unknown / mobile_node_cleanup_pending / overlay_unknown_write` 均须保守处理，不自动重试 start 或输入。任何不明确的 channel 异常都不能推导“没有执行”。

## Offline checks

```sh
CARGO_TARGET_DIR=/private/tmp/herdr-flutter-network-runtime-target cargo test --locked --offline --manifest-path validation/flutter-network-runtime/Cargo.toml
CARGO_TARGET_DIR=/private/tmp/herdr-flutter-network-runtime-target cargo test --locked --offline --manifest-path validation/flutter-network-runtime/Cargo.toml --features native-fixture,tailscale-fixture
CARGO_TARGET_DIR=/private/tmp/herdr-flutter-network-runtime-target cargo clippy --locked --offline --manifest-path validation/flutter-network-runtime/Cargo.toml --all-targets --features native-fixture --no-deps -- -D warnings
sh validation/flutter-network-runtime/tests/run-jvm.sh
```

默认测试验证缺桥与 scope/open admission；显式 C ABI 测试验证 actual service/dialer route、空闲读继续、读写并发、partial/UNKNOWN、半关闭/EOF、取消先到及迟到 open、32 个失败 close 的预算、retired scope 配额和 detach 只影响自己的节点。JVM 测试用桌面 JDK、self-created Java fixture 和 `-Xcheck:jni`，不加载 Android 类或 vault；它验证 JNI envelope、边界、null、scope、高水位与默认门禁。以上不是 Android SDK/Kotlin 编译、Flutter widget、真实 EasyTier 或设备证明。

本批离线结果以实际测试日志为准；双 C fixture、桌面 JVM 和 Kotlin stub 不代表 Android 真机或真实组网。fixture 含停住旧 cleanup executor 后新 scope 以同 Binding 重启的回归，以及 4 种 pre-admission 状态；shared service 的 10 项聚焦测试通过。`--no-deps` 不代表既有 transport crate 的 12 项严格 Clippy 诊断已修复。
