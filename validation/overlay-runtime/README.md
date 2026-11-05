# 前台 overlay 字节流核心实验

2026-11-05。这个独立 Rust crate 把已有 EasyTier portable ABI 接入 owner 绑定的 open/read/write/half-close/close，供后续 Flutter/Tauri 传输桥使用。默认构建没有可用原生 backend；显式链接候选库后才调用其五个真实 C 符号。这里没有 GUI 接线、节点启动、身份读取或普通 TCP/DNS 回退。

维护者先运行下面的离线复验。它调用单独编译的 C ABI 故障 fixture，**不是真实 EasyTier 节点或组网结果**。

## 离线复验

前提：已有 Rust 1.95+、Unix C 编译器、`ar` 和 pthread。本机实际使用 macOS arm64 / rustc 1.96.0；没有安装新 SDK，也没有启动网络节点。此 crate 没有第三方 Cargo 依赖，锁文件只有本包。

从仓库根目录运行：

```sh
CARGO_TARGET_DIR=/private/tmp/herdr-overlay-runtime-target cargo test --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml --features native-fixture
CARGO_TARGET_DIR=/private/tmp/herdr-overlay-runtime-target cargo clippy --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml --all-targets --features native-fixture -- -D warnings
CARGO_TARGET_DIR=/private/tmp/herdr-overlay-runtime-target cargo clippy --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml --all-targets -- -D warnings
```

预期：12 项 native fixture 测试全部通过；两种 feature 配置的 Clippy 无警告。C fixture 的 `.o`、`.a` 与 Rust 产物只进入指定临时 target。`native-fixture` 是显式测试 feature，不会被生产缺桥路径自动选择。

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
| 本项目 portable patch SHA-256 | `c6cf73a5e26bab665c226f37c81d55671f801e84d67d340bd18dc670529b06a4` |
| portable module SHA-256 | `2fa47339bacac80d6b4a16af56b500e89fcabe560e5ccddfdb0eb2e418e07c36` |
| C ABI | `HEELER_ET_STREAM_ABI_VERSION 1`，五个 `heeler_et_stream_*` 符号 |

本轮重算了 patch、portable module 和测试模块的 SHA，均匹配现有 [portable manifest](../native/patches/portable-manifest.json)。固定上游的 [instance key/slot](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/native/easytier/src/lib.rs#L50-L170) 与 [按 instance 路由、内部解析、data-plane TCP](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/native/easytier/src/lib.rs#L410-L569) 已核对；新增签名与行为依据是本仓库 [portable header](../native/portable-stream/header.txt) 和 [FFI 实现](../native/portable-stream/ffi.txt)。当前 Context7 文档只作背景，没有拿新 main 的 API 替换固定来源。

先按 [native 构建说明](../native/portable-stream/README.md)取得对应平台的真实候选库，并核对来源、补丁、架构、库 SHA 与适用许可。库应来自受控构建目录；本 crate 不自动下载、发现或认证任意同名库，也没有 ABI 版本查询函数可替代来源核验。默认 feature 不会链接系统中偶然存在的同名库。

在已有候选库的构建环境中，明确指定其目录：

```sh
HEELER_ET_LIB_DIR=/absolute/path/to/verified/candidate-library CARGO_TARGET_DIR=/private/tmp/herdr-overlay-runtime-linked cargo build --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml --features linked-easytier --example abi_presence
```

`/absolute/path/to/verified/candidate-library` 是待替换路径。目标库名是 `libheeler_easytier`（对应平台的 `.a`、`.so`、`.dylib`）或 Windows `heeler_easytier.lib` 等匹配链接产物；动态加载路径及平台链接依赖仍由宿主构建负责。构建 `abi_presence` 会要求真实五个符号；运行这个 CLI 只调用 `close(0)`，允许 bridge 初始化进程内 runtime，但不启动节点、join、dial 或读身份。本机没有真实候选库，因此本轮没有执行这条真实库链接/调用，不把 C fixture 结果算给它。

`linked-easytier` 使用真实候选 ABI；`native-fixture` 使用合成 C ABI，二者不能同时作为发行证据。EasyTier 上游/glue 的 LGPL 条件和对应源码、补丁、重链接材料继续按 native 来源处理，本段不裁定项目最终许可证。

## 调用与所有权

1. 为一次 Host/route 连接尝试创建 `Owner`；重新连接创建新 owner，不恢复旧 token。
2. `attach_profile` 绑定 `(Provider, profileId)` 与不可变 backend。EasyTier backend 明确携带 app 所拥有的 instance key 和必填 network selector；不从 IP 推断网络。
3. `open` 返回可 await 的 `Operation<StreamLease>`。它只表示获得 pending native handle，**不表示 overlay TCP 已就绪**。SSH 的 host key、认证、session/socket/terminal 身份校验仍归上层。
4. 用同一 owner 和 lease 调用 `read`、`write`、`shutdown_write`；每条流最多一个 reader 与一个 writer。所有同步 FFI 都在独立非 UI、非 Tokio worker 上运行，64 KiB 上限和 deadline 有效至返回。生产调用方应 await Future；`wait` 仅供非 UI 调用方和测试。
5. 正数 write 是本地队列已接受的前缀。调用方若继续，只能推进这个前缀后的剩余部分；UNKNOWN、取消或错误不能重发整段。这里不做自动 `write_all`、离线排队或重连。
6. `close` 幂等地退休该流；`cancel_owner` 只退休该 owner 的流；`detach_profile` 只退休该 profile 的流。它们不停止共享节点、不离网、不删除身份，也不影响其他 provider/profile。native close 失败或原生调用尚未返回时，`reserved_streams()` 保留配额，不无限开新连接。

节点生命周期是明确缺口：ABI v1 没有 node epoch 或 ready 查询。调用方必须独占 instance key 的 start/stop/replacement；不能把任意外部节点的可复用 key 当成已经认证的本项目 node lease。本段不调用 start/stop，因此不能证明节点身份或同网运行。后续应由本项目节点 registry 独占这些操作，或扩展上游 epoch guard，再接产品节点管理。

## 当前边界

| 层 | 本段结果 |
| --- | --- |
| owner/profile 路由、真实 C ABI 调用、取消与资源回收 | 12 项 Mac native fixture 测试通过；不含真实网络 |
| EasyTier backend | 已实现五个真实 ABI 调用；需要显式链接已核验候选库及由 app 拥有的运行实例 |
| Tailscale / ZeroTier backend | 明确 `ProviderUnavailable`，没有替代路径 |
| GUI/SSHSocket、节点启用、身份存储、真实 overlay TCP | 未接入／未验证 |
| iOS、Android、Windows、Linux 的本段运行 | 未验证；C fixture 当前仅 Unix 构建 |
| 15 格单网络、20 格前台并发矩阵 | 本段不新增任何通过格，继续按[原矩阵](../../docs/09-prototype-validation.md)验收 |

现有 [native 候选三桌面结果](../../docs/10-blocker-repair.md)与这里的新 runtime 分层记录；历史库链接通过不能代替本段集成，fixture 跨 provider 隔离不能代替 Tailscale + EasyTier 真并发。
