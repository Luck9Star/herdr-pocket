# 前台 overlay 字节流核心实验

2026-11-06。这个独立 Rust crate 实现 owner 绑定的 overlay 流，以及 profile revision 绑定的 managed node start/status/stop 入口。EasyTier 与新增 Tailscale 候选复用同一 NodeEntry 生命周期；默认构建没有原生 backend，必须显式 feature 与库目录。本轮实际只执行合成 C ABI 与 fake-engine 测试，没有启动真实 EasyTier 节点或读取真实身份；GUI、系统安全存储与实际 overlay TCP 仍未接通。

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

第二条实际包含原 8 项 portable 测试与 4 项精确 `nodes.txt` fake-engine FFI 测试。fake engine 不创建网络节点、socket、DNS 或身份文件；它验证新 Rust 源模板的 epoch、selector、drain、timeout 配额、拒绝文件凭据与错误脱敏。旧 8 项中的自有 loopback 测试需要允许 localhost bind；本轮默认 sandbox 禁止 bind，已在授权的 sandbox 外复跑通过。不能把 fake engine 或 C fixture 通过当成真实 Heeler 新四符号已编译/链接；离线检查时尚未执行真实云构建；随后三桌面固定源码 check/link/load 已通过，详见[网络批次验收](../../docs/18-mobile-network-profiles.md)，不代表真实节点运行。新增 race 回归以屏障固定 secure-load/native-start 与 detach 的交错，核对撤销后不能激活原 revision、迟到清理失败仍占配额、activation 先完成时仍保持 admission 关闭，以及 managed revision 不会打开同 key 的 legacy 替换。

## 当前边界

| 层 | 本段结果 |
| --- | --- |
| owner/profile/revision、C ABI 调用、取消与资源回收 | 23 项 Mac C fixture 与 1 项默认门禁测试通过；不含真实 engine/网络 |
| EasyTier managed backend | 已实现九个 ABI 调用与 node lease；更新补丁的真实来源 check/link 仍待执行 |
| Tailscale backend | 新增固定 `hp_ts` ABI 候选与独立 C fixture，见下节；不等于真实 tsnet 节点或网络验证 |
| ZeroTier backend | 此历史批次未接入；2026-11-07 新源码见下节，缺库仍 `ProviderUnavailable` |
| GUI/SSHSocket、系统安全存储、稳定 node identity、真实 overlay TCP | 未接入／未验证；默认入口拒绝启动 |
| iOS、Android、Windows、Linux 的本段运行 | 未验证；C fixture 当前仅 Unix 构建 |
| 15 格单网络、20 格前台并发矩阵 | 本段不新增任何通过格，继续按[原矩阵](../../docs/09-prototype-validation.md)验收 |

现有 [native 候选三桌面结果](../../docs/10-blocker-repair.md)与这里的新 runtime 分层记录；历史库链接通过不能代替本段集成，fixture 跨 provider 隔离不能代替 Tailscale + EasyTier 真并发。

## Rust SSH byte adapter（2026-11-06）

[transport-rust](../transport-rust/README.md#显式-overlay-byte-transport2026-11-06) 已新增真正的 Tokio `AsyncRead + AsyncWrite` adapter，使用本 runtime 的 Future 和精确 `open_node` → `open_revision`；`open_node` 另检查 NodeLease 的原 runtime。`NodeLease::identity_ref()` 只公开安全存储引用，供实际 stream 的持久 recovery route 绑定。它不公开 native epoch，也不表示身份已实现持久稳定。默认仍缺桥拒绝；本段不新增真实节点、GUI overlay 或设备验证。

`Failure::ReadTimedOut` 只表示同步 read 已返回、没有读取任何字节且没有迟到 read。EasyTier 固定 ABI 的 read `-2` 映射到此值；transport 在原 Operation 完成后以有界 timer 继续读取，正常空闲不关闭连接，write 仍不自动重试。本轮 native fixture 24 项和默认门禁 1 项通过，新增 timeout 回归证明之后可写入并读到同一流的数据。其余历史测试与真实网络边界继续按上文和 transport README 区分。


## Tailscale managed backend 候选（2026-11-06）

[`tailscale.rs`](src/tailscale.rs) 使用 [`hp_ts.h`](../native/tailscale-runtime/hp_ts.h) 的固定 ABI v1。`linked-tailscale` 必须给出绝对 `HP_TS_LIB_DIR`，库名为 `libhp_tailscale`；没有自动下载、系统库发现、系统 TCP／DNS、文件 StateStore 或合成 fixture fallback。`tailscale-fixture` 只链接独立 C ABI 故障 fixture，不是 Go engine。两 provider 的 NodeEntry 共用原 admission、owner／revision、取消、迟到清理、8 node／32 stream 配额及显式 cleanup 重试；没有平行 lifecycle manager。

`NativeStateSource::load(&NodeSpec)` 在原 lifecycle worker 上为完整不可变 spec 提供 `NativeNodeConfig`。配置携带原 spec、宿主已核验的独立 app-private 目录、公共 hostname／HTTPS control URL，以及 `Arc<dyn NativeStateStore>`；backend 再次比较完整 spec。`NativeVettedDirectory` 只核对绝对／干净路径，权限、所有权、symlink 与独立目录的原生验证由宿主负责，不能把此构造器当系统安全证明。当前 hostname 取单个 ASCII DNS label，URL 采用较严格 ASCII HTTPS authority 策略，不支持 IPv6 literal；control URL 不允许 query。没有 auth key 或环境凭据入口。

StateStore 接口只传 key/value bytes：key 0–1024 bytes、value 0–262144 bytes，完整任意 key（包括空、NUL、非 UTF-8）不改写；`Missing` 与 `Unavailable` 区分，present-empty 与 absent、`write(None)` 删除与 `write(Some(empty))` 存空区分。值、配置与 store 没有 Debug／Clone／serde。read 返回的原 Rust allocation 一直持有到 Go 的精确 release 回调，随后尽力覆写；write 借用原 buffer，不额外留副本。每个 context 最多 32 个未归还 read buffer。宿主 store 必须线程安全、不得 panic 或记录 key/value；JNI/系统错误必须转 `Unavailable`，不能伪装 Missing 或建新身份。

callback context 与函数表由进程级单调 ID registry 持有，只有 `hp_ts_node_release == OK` 证明真实 close、原调用与回调已收敛后才释放。此契约要求 Go bridge 在每个 node 的 StateStore 上显式设门：engine close 成功后拒绝新的 host callback，等待已进入的 callback 返回，才允许 closeDone／release OK；不假设上游 tsnet.Close 已隐式 join 所有后台 StateStore 使用者。旧 engine 对已退休 store 的迟到调用必须在 Go gate 内返回 unavailable，不能再次进入已释放 Rust/JNI context。close timeout／IO、取消、失败 start 和 Rust runtime Drop 都不能提前释放 store；无法收敛的 owner 保守保留并占最多 8 个 context，不把泄漏当成功回收。宿主需保留 runtime 以执行原 revision 的显式 cleanup；这不提供强制擦除或失败后无限开节点能力。

状态区分 `Starting / NeedsLogin / NeedsMachineAuth / Running / Closing / Stopped`。EngineStarted 不代表可用网络；mobile 层只有 Tailscale Running 才提供 dialer，最终仍由该原 node 的 native dial 决定是否能连接。`begin_node_login`／mobile `begin_login` 是显式动作，返回粗粒度状态与仅经审查的 HTTPS auth URL，不返回原始日志；URL 的 Debug 被隐藏，也不自动打开浏览器。Running 仍不是设备、peer、route 或 SSH 验证。read TIMEOUT 仅映射原 read 已结束且 0 bytes 的可重试空闲；其他未收敛错误关闭原流，write UNKNOWN 不重放。半关闭必须保留读方向，底层不支持时拒绝而不伪造 full close。

离线 C ABI 复验（不启动真实节点）：

```sh
CARGO_TARGET_DIR=/private/tmp/herdr-overlay-runtime-ts-target cargo test --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml --features tailscale-fixture
CARGO_TARGET_DIR=/private/tmp/herdr-overlay-runtime-both-target cargo test --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml --features native-fixture,tailscale-fixture
CARGO_TARGET_DIR=/private/tmp/herdr-overlay-runtime-both-target cargo clippy --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml --all-targets --features native-fixture,tailscale-fixture -- -D warnings
CARGO_TARGET_DIR=/private/tmp/herdr-transport-overlay-target cargo test --locked --offline --manifest-path validation/transport-rust/Cargo.toml mobile_nodes --features overlay-native-fixture,overlay-tailscale-fixture
```

本批 C fixture 实际验证 store key／missing／empty／delete、取消迟到 start、stop 失败持有原 store、原 spec 不能换绑、身份不可用和超限不变 Missing、显式 login／状态、半关闭、read idle timeout，以及相同目标地址下两 provider 流与 stop 隔离。它没有创建 socket、读取真实身份或运行 tsnet。mobile Binding 新增可选 `provider`；旧 JSON 缺省仍 EasyTier，Tailscale 用明确的 `with_provider` 和 `start_tailscale`，不会经旧 EasyTier 入口加载别的 provider 身份。进程 attempt 不进入持久 route，旧 attempt／dialer 无法跟随新节点。

已有受控 Go 候选库时，可只链接并运行不启动节点的 ABI probe：

```sh
HP_TS_LIB_DIR=/absolute/verified/library/directory CARGO_TARGET_DIR=/private/tmp/herdr-overlay-runtime-ts-linked cargo build --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml --features linked-tailscale --example tailscale_abi_presence
# macOS: run the built binary directly; cargo run can rewrite loader variables.
DYLD_LIBRARY_PATH=/absolute/verified/library/directory /private/tmp/herdr-overlay-runtime-ts-linked/debug/examples/tailscale_abi_presence
# Linux uses LD_LIBRARY_PATH instead; Windows requires its explicit DLL search path.
```

build 只证明本 adapter 所用符号能链接；动态库能否找到与加载必须由目标平台 loader 路径和直接运行的独立结果确认。直接运行只读 ABI version 与无效 node 0 的 status，不调用 new/start/login/dial/StateStore。cargo run 的 loader discovery 失败不能冒充加载成功，也不要求把库复制进仓库或修改系统搜索路径。真实库来源、补丁、SHA 与加载结果由上层交付记录另记；C fixture 或 link/load 不能替代真实登录、加密身份重启、手机、overlay TCP、15 格单网和 20 格前台并发矩阵。

## ZeroTier managed backend（2026-11-07）

[`zerotier.rs`](src/zerotier.rs) 接固定 manager/stream ABI v1。`linked-zerotier` 要求显式绝对 `HP_ZT_LIB_DIR`；`zerotier-fixture` 是独立内存 C 替身，不能进入 App 或缺库回退。没有系统 TCP／DNS 路径；目标只接受 numeric IPv4／IPv6，network ID 只接受 16 位非零小写十六进制。

每个 profile 的 `NodeEntry` 保留一份 `NativeDeviceSession` 与独立网络 lease，同一设备可共享 native owner。设备租约的取得放在原 start worker 内，先由 backend 保留结果，再核对取消和同一个 deadline 的剩余时间；不能在会被丢弃的 load 阶段创建设备。已有原生副作用的失败必须携带原 session，不能只返回错误。stop 顺序为原 stream close/release、network leave、session retire；最后一个设备 session 才能 stop/release 设备和退休 vault。任一步失败保留原对象和配额，后续显式 stop 重试。

`NodeStatus::ZeroTier { phase, online }` 分别表示控制器网络配置和设备在线。Configured 不等于目标路由或 SSH 可用；mobile service 仅在 Configured＋online 时提供 dialer，native open 仍核查原 netif 与 generation。未知 write 不重放；read timeout 仅限原同步 read 已返回且消费 0 bytes。失败 open 的未退休原生句柄由原 backend 有界保留，不能因调用方收到 Err 而遗失。

```sh
cargo test --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml
cargo test --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml --features native-fixture,tailscale-fixture,zerotier-fixture
cargo clippy --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml --features native-fixture,tailscale-fixture,zerotier-fixture --lib -- -D warnings
```

本机默认 5 项、三 fixture 43 项及上述 Clippy 通过。覆盖双网独立退休、IPv6 字节、原租约、取消后的迟到 acquire/join、deadline 后禁止新 join、32 个失败 open 保持配额、未知写入一次、网络和 vault 清理失败可重试。没有真实 ZeroTier 节点、手机安装或三网并发结果。
