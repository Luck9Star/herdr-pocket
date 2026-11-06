# 前台 overlay 字节流核心实验

2026-11-06。这个独立 Rust crate 实现 owner 绑定的 overlay 流，以及 profile revision 绑定的 EasyTier node start/status/stop 入口。默认构建没有原生 backend；显式链接更新后的候选库才调用五个 stream 和四个 managed-node 符号。本轮实际只执行合成 C ABI 与 fake-engine 测试，没有启动真实 EasyTier 节点或读取真实身份；GUI、系统安全存储与实际 overlay TCP 仍未接通。

本轮精确检查记录见 [offline evidence](../native/evidence/2026-11-06-managed-node-offline.json)。维护者先运行下面的离线复验。它调用单独编译的 C ABI 故障 fixture，**不是真实 EasyTier 节点或组网结果**。

## 离线复验

前提：已有 Rust 1.95+、Unix C 编译器、`ar` 和 pthread。本机实际使用 macOS arm64 / rustc 1.96.0；没有安装新 SDK，也没有启动网络节点。此 crate 没有第三方 Cargo 依赖，锁文件只有本包。

从仓库根目录运行：

```sh
CARGO_TARGET_DIR=/private/tmp/herdr-overlay-runtime-target cargo test --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml --features native-fixture
CARGO_TARGET_DIR=/private/tmp/herdr-overlay-runtime-target cargo clippy --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml --all-targets --features native-fixture -- -D warnings
CARGO_TARGET_DIR=/private/tmp/herdr-overlay-runtime-target cargo clippy --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml --all-targets -- -D warnings
```

本轮实际：23 项 native fixture 测试通过（原 12 项流测试加 11 项节点测试）；两种 feature 配置的 Clippy 无警告。默认无桥配置另有 1 项门禁测试通过。C fixture 的 `.o`、`.a` 与 Rust 产物只进入指定临时 target。`native-fixture` 是显式测试 feature，不会被生产缺桥路径自动选择。

测试实际覆盖：

- read 阻塞时 write 与 close 可独立运行，半关闭后仍能读取 EOF；同方向并发返回 `Busy`。
- provider/profile/owner/runtime 不串用；相同虚拟 IP 仍传入各自固定的 native instance key 和 network selector。
- 取消 pending open 后保留 32 个配额，迟到 handle 由原 owner 关闭一次；未消费的 ready open 和 runtime 释放也清理自己的流。
- write 只返回已接受的前缀；部分写后返回 UNKNOWN、取消中写入或异常返回不重放，并关闭该流。
- native close 失败保留 handle 与配额；仅显式重试 close。profile 替换等待旧资源关闭，旧 lease 不能转向新 backend。
- Future 取消会唤醒调用方，不等 native open 返回；原生缓冲与配额仍保持到所有 FFI 返回。

fixture 不创建 socket、不调用系统 DNS、节点或身份 API。跨 provider 测试的第二 provider 是明确标记的 C fixture 适配器，只验证路由隔离；它没有实现 Tailscale。

## 接入真实候选 ABI

真实 backend 是 [`src/easytier.rs`](src/easytier.rs)，固定依据为：

| 来源 | 固定值 |
| --- | --- |
| Heeler natives | `6a2817fc02aeb552df251d9478753c22fd4738bb` |
| EasyTier 开发提交 | `728ba94b5029240add6204eed591f22e4e039e6b` |
| 本项目 portable patch SHA-256 | `98897e41300496ad20b4708172c1c111f8ecab08e7cb279530b5a10f0e3620d7` |
| portable module SHA-256 | `2fa47339bacac80d6b4a16af56b500e89fcabe560e5ccddfdb0eb2e418e07c36` |
| C ABI | 原 `HEELER_ET_STREAM_ABI_VERSION 1` 五符号保留；新增 `HEELER_ET_NODE_ABI_VERSION 1` 四符号 |

本轮重算 patch、原 portable module、测试模块与新增 node/template 的 SHA，均匹配更新后的 [portable manifest](../native/patches/portable-manifest.json)。固定上游的 [instance key/slot](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/native/easytier/src/lib.rs#L50-L170) 与 [按 instance 路由、内部解析、data-plane TCP](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/native/easytier/src/lib.rs#L410-L569) 已核对；新增签名与行为依据是本仓库 [portable header](../native/portable-stream/header.txt) 和 [FFI 实现](../native/portable-stream/ffi.txt)。当前 Context7 文档只作背景，没有拿新 main 的 API 替换固定来源。

先按 [native 构建说明](../native/portable-stream/README.md)取得对应平台的真实候选库，并核对来源、补丁、架构、库 SHA 与适用许可。库应来自受控构建目录；本 crate 不自动下载、发现或认证任意同名库，也没有 ABI 版本查询函数可替代来源核验。默认 feature 不会链接系统中偶然存在的同名库。

在已有候选库的构建环境中，明确指定其目录：

```sh
HEELER_ET_LIB_DIR=/absolute/path/to/verified/candidate-library CARGO_TARGET_DIR=/private/tmp/herdr-overlay-runtime-linked cargo build --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml --features linked-easytier --example abi_presence
```

`/absolute/path/to/verified/candidate-library` 是待替换路径。目标库名是 `libheeler_easytier`（对应平台的 `.a`、`.so`、`.dylib`）或 Windows `heeler_easytier.lib` 等匹配链接产物；动态加载路径及平台链接依赖仍由宿主构建负责。构建 `abi_presence` 会要求五个 stream 与四个 managed-node 符号；运行只调用 `close(0)` 与 `node_status(0)`，允许初始化进程内 runtime，不启动节点、join、dial 或读身份。本机没有真实候选库，因此本轮没有执行这条真实库链接/调用，不把 C fixture 结果算给它。

`linked-easytier` 使用真实候选 ABI；`native-fixture` 使用合成 C ABI，二者不能同时作为发行证据。EasyTier 上游/glue 的 LGPL 条件和对应源码、补丁、重链接材料继续按 native 来源处理，本段不裁定项目最终许可证。

## 调用与所有权

1. 为一次 Host/route 连接尝试创建 `Owner`；重新连接创建新 owner，不恢复旧 token。
2. 旧 `attach_profile` / `EasyTierBackend::linked` 保留给 key ABI 实验，revision 为 0。产品节点使用下面的 managed API，不能把任意外部 key 当成 app 所有的 node lease。
3. `open` 返回可 await 的 `Operation<StreamLease>`。它只表示获得 pending native handle，**不表示 overlay TCP 已就绪**。SSH 的 host key、认证、session/socket/terminal 身份校验仍归上层。
4. 用同一 owner 和 lease 调用 `read`、`write`、`shutdown_write`；每条流最多一个 reader 与一个 writer。所有同步 FFI 都在独立非 UI、非 Tokio worker 上运行，64 KiB 上限和 deadline 有效至返回。生产调用方应 await Future；`wait` 仅供非 UI 调用方和测试。
5. 正数 write 是本地队列已接受的前缀。调用方若继续，只能推进这个前缀后的剩余部分；UNKNOWN、取消或错误不能重发整段。这里不做自动 `write_all`、离线排队或重连。
6. `close` 幂等地退休该流；`cancel_owner` 只退休该 owner 的流。`detach_profile` 永久撤销当前 revision 的 admission；若 managed start 仍 pending，它会唤醒 start Future 返回 `Cancelled`，并在原加载/start 返回后清理该迟到节点。已完成的节点保留给 status/显式 stop。这些操作不删除身份，也不影响其他 provider/profile。native close 失败或原生调用尚未返回时，`reserved_streams()` 保留配额，不无限开新连接。

## Managed node 调用与门禁

固定 Heeler 的真实入口是 `heeler_et_start(key,toml,timeout_ms,err,errlen)`、`heeler_et_status_json(key,buf,len)` 和无返回值的 `heeler_et_stop(key)`。start 可以替换同 key；原 stop 先移除 slot，再忽略 5 秒 stop timeout。因此新节点没有复用这条可替换 key 路径：新增 native registry 直接持有 `create_native_instance(config)` 返回的固定 instance，以进程内单调、不复用、溢出拒绝的 `uint64_t` lease 标识，完全不进入旧 `SLOTS`。旧 start/stop/stop_all 无法替换或停止这些 managed 节点。

四个新增符号在 [header](../native/portable-stream/header.txt) 和精确 [node 源模板](../native/portable-stream/nodes.txt)：`heeler_et_node_start`、`heeler_et_node_status`、`heeler_et_node_stop`、`heeler_et_node_stream_connect`。最后一个从不可变 node lease 捕获 instance，再使用固定来源的 no-TUN data-plane TCP；原五个流符号不改签名。stream close 同时释放对应 node 的 stream 归属。

应用调用顺序：

1. 创建 `NodeSpec { profile: ProfileKey, revision, network, identity_ref }`；revision 必须大于 0，重启/修改后增加，失败尝试也不能重用旧 revision。公开元数据只含本设备安全存储引用，不能含 TOML、network secret 或 identity state。
2. 调用 `start_easytier_profile(spec, source, deadline)`，从 UI executor await `NodeOperation<NodeLease>`。`SecureConfigSource::load` 只在独立 lifecycle worker 上取得短期 `SecretConfig`；本项目没有五平台生产 source 实现。source 缺失立即 `IdentityUnavailable`；bridge 缺失 `ProviderUnavailable`，均不读取身份。禁止明文文件 fallback。
3. `node_status(&lease)` 只返回 `Starting / EngineStarted / Closing / Stopped`。`EngineStarted` 仅表示固定 engine `instance.start()` 返回成功及运行状态，不能作为 join、IP、route、peer 或 TCP ready 证据。status 不返回原始 TOML、secret、IP、peer 列表或上游错误文本。
4. 用 `open_revision(owner, profile, revision, host, port, deadline)` 打开流。managed profile 的旧 `open` 或错误 revision 立即 `StaleRevision`；显式请求的 revision 始终与当前 profile 比对，即使同 key 后来接入 legacy revision 0 也会拒绝旧 managed 请求；每个 `StreamLease::profile_revision()` 保留原 revision，旧 owner/late handle 不能转向替换后的节点。
5. `stop_node(&lease, deadline)` 先关 admission，取消并等待原 profile 的 pending open、read/write 与 close 全部 drain，然后才调用 native node stop。8 个 runtime node 配额与 32 个 stream 配额均包含 pending、失败和清理未完成的资源。native registry 另有 32 个 managed node 上限。
6. 取消/丢弃未领取的 start 会停止原 revision 的迟到节点；不重试 start。start 失败也可能得到非零 native lease，仍由 registry 保留并执行一次 cleanup。stop timeout、UNKNOWN 或 stream close 失败保留 lease/配额；仅显式 `stop_node` 或 `retry_node_cleanup(profile, exact_revision, deadline)` 重试清理。旧 lease 的重复 stop 不影响新 revision。runtime Drop 尝试 drain/stop；需要观察和重试失败时，宿主应保留 runtime，不能把 Drop 当作成功凭据。

`SecretConfig` 没有 Debug/Clone/序列化，临时输入 drop 时尽力覆写；engine 仍可在其内存配置中持有 secret，不能宣称内存所有副本已抹除。固定 native features 没有 `management`，其 credential-file storage adapter 为 None；新 native start 另拒绝 `credential_file` 和 `managed_credentials`。这项静态核查只说明本路径没有接通持久身份文件，并不完成 Keychain/Keystore/DPAPI/libsecret 等安全存储或稳定 node identity 验证。来源与限制见 [source audit](../native/managed-source-audit.json)。

额外离线复验：

```sh
CARGO_TARGET_DIR=/private/tmp/herdr-overlay-runtime-target cargo test --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml
CARGO_TARGET_DIR=/private/tmp/herdr-portable-stream-target cargo test --locked --offline --manifest-path validation/native/portable-stream/Cargo.toml
```

第二条实际包含原 8 项 portable 测试与 4 项精确 `nodes.txt` fake-engine FFI 测试。fake engine 不创建网络节点、socket、DNS 或身份文件；它验证新 Rust 源模板的 epoch、selector、drain、timeout 配额、拒绝文件凭据与错误脱敏。旧 8 项中的自有 loopback 测试需要允许 localhost bind；本轮默认 sandbox 禁止 bind，已在授权的 sandbox 外复跑通过。不能把 fake engine 或 C fixture 通过当成真实 Heeler 新四符号已编译/链接；更新后补丁的真实云构建尚未执行。新增 race 回归以屏障固定 secure-load/native-start 与 detach 的交错，核对撤销后不能激活原 revision、迟到清理失败仍占配额、activation 先完成时仍保持 admission 关闭，以及 managed revision 不会打开同 key 的 legacy 替换。

## 当前边界

| 层 | 本段结果 |
| --- | --- |
| owner/profile/revision、C ABI 调用、取消与资源回收 | 23 项 Mac C fixture 与 1 项默认门禁测试通过；不含真实 engine/网络 |
| EasyTier managed backend | 已实现九个 ABI 调用与 node lease；更新补丁的真实来源 check/link 仍待执行 |
| Tailscale / ZeroTier backend | 明确 `ProviderUnavailable`，没有替代路径 |
| GUI/SSHSocket、系统安全存储、稳定 node identity、真实 overlay TCP | 未接入／未验证；默认入口拒绝启动 |
| iOS、Android、Windows、Linux 的本段运行 | 未验证；C fixture 当前仅 Unix 构建 |
| 15 格单网络、20 格前台并发矩阵 | 本段不新增任何通过格，继续按[原矩阵](../../docs/09-prototype-validation.md)验收 |

现有 [native 候选三桌面结果](../../docs/10-blocker-repair.md)与这里的新 runtime 分层记录；历史库链接通过不能代替本段集成，fixture 跨 provider 隔离不能代替 Tailscale + EasyTier 真并发。
