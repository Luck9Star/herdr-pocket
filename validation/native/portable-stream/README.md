# Portable stream candidate

这是固定 Heeler EasyTier 来源的实验补丁，不是已可用于产品的组网 SDK。原始来源／失败矩阵保留于上级目录。没有启动真实 EasyTier 节点或读取真实身份。本轮新增 managed-node ABI 源码与隔离测试；2026-10-30 的真实三桌面候选结果仅对应当时补丁，不能覆盖更新后的 node 扩展。

## 来源与接口

- Heeler `6a2817fc02aeb552df251d9478753c22fd4738bb`，EasyTier `728ba94b5029240add6204eed591f22e4e039e6b` 与原始 3 补丁不变。
- 2026-10-30 只读检查当时 Heeler HEAD `b779bdc4930a221fe1cd5cc534af6c3e8b1f67f2`：`native/easytier/src/lib.rs` 与 header 相对固定来源没有 portable 修复，不把更新其它 provider 的提交替换成本候选来源。
- 独立模块精确 `tokio = 1.53.1`、`libc = 0.2.189` 与 Cargo.lock。实际 Heeler 锁也为 Tokio 1.53.1／libc 0.2.189，但两锁的传递依赖可能不同，独立测试不能替代嵌入后的真实 Heeler 编译与测试。
- Context7 按 `library Tokio` → `/tokio-rs/tokio` → `docs` 核查 UnixStream、copy_bidirectional 与半关行为；完整来源、补丁、复制模块 SHA 由 [`portable-manifest.json`](../patches/portable-manifest.json) 固定。

[`header.txt`](header.txt) 是生成补丁时加入原始 C header 的合同；[`ffi.txt`](ffi.txt) 是流适配代码，[`nodes.txt`](nodes.txt) 是 additive managed-node 适配代码。实际构建应用 [`0001-portable-stream-handles.patch`](../patches/0001-portable-stream-handles.patch)，再把本目录 `src/lib.rs` 与 `src/tests.rs` 按已锁 SHA 原样复制进 Heeler，不从不同实现复制“类似测试”。

旧 Unix `int fd` 保留；Apple 使用 `SO_NOSIGPIPE`，Linux 旧调用端必须使用 `MSG_NOSIGNAL` 或等价安全写入，裸 POSIX write 仍有风险。Windows 旧入口明确报 unsupported，绝不把 SOCKET 截为 int。这个残余调用端合同未被平台 cfg 自动解决。

新 `heeler_et_stream_*` ABI 使用 opaque `uint64_t`：

- 至多 32 个 handle，包含 pending 与失败连接；失败后仍需 close。ID 单调、不重用、溢出拒绝。
- 每方向 64 KiB duplex 队列，pump 每方向另有固定 8 KiB；每次 read/write 最多 64 KiB。没有外部 listener、SOCKS 服务、TUN 或系统 VPN 依赖。
- connect 立即返回 pending handle；read/write 有截止时间。正数 write 只证明本地队列接受的前缀，不证明远端收到或执行。超时／取消／错误可为 UNKNOWN，禁止自动重放。
- read/write 分锁，close 不等待这些锁，先移除 capability，再取消并回收 dial/pump。迟到完成释放它拥有的 stream，重复 close 和旧 ID 返回错误。shutdown_write 半关而保留接收方向。
- C 调用必须在独立非 UI、非 Tokio runtime 线程。检测到已有 Tokio runtime 会返回 `-10`，不嵌套 block_on。调用方须维持 buffer 有效直到同步返回；不能复制 handle 并建立第二个关闭 owner。

## 验证分层

已有 Mac 使用 rustc 1.96.0 执行 `cargo test --locked --manifest-path validation/native/portable-stream/Cargo.toml`，8/8 通过，独立 reviewer 也复跑。Unix SIGPIPE 测试先在子进程恢复 default，再证明原始 send 的阳性对照确实被 SIGPIPE 终止；portable peer-close 子进程正常返回。不会改变父进程的信号策略。

三桌面 CI 用 Rust 1.95.0：先独立模块 tests，再对固定 Heeler 加补丁做 `cargo check --locked --lib`、仅选择 `pocket` 的嵌入模块与 FFI tests、真实 cdylib 链接与子进程 ctypes 加载新符号／无效 handle 拒绝。Unix 是 8 个核心测试，Windows 不运行 POSIX SIGPIPE 项。每一层单列结果，任意失败保留非零退出码。

loopback TCP 只在测试中构造自有两端，并核对两侧地址，作为 synthetic remote；生产候选 ABI 使用内存 duplex，不打开该测试 listener。测试覆盖双向字节、半关／EOF、背压、超时 UNKNOWN、取消锁等待、pending/late connect、32 上限／ID 溢出及多连接隔离。没有以这些测试冒充 EasyTier overlay dial、真实网络恢复或五端并发验证。

## 已取得的候选结果

[run 40993901952](https://github.com/Luck9Star/herdr-pocket/actions/runs/40993901952)，源码 `d60b8d0a5def48a4af27b6544c48baea1bbf810f`：三桌面独立模块测试通过；真实固定 Heeler 加补丁后 check、嵌入测试、cdylib 链接、加载均通过。Linux/macOS 各 9 项嵌入测试，Windows 8 项（没有 POSIX SIGPIPE 项）；均含新 FFI 的已有 runtime 返回 `-10`。加载检查解析 5 个新符号并验证无效 close 返回 `-6`。

三份 artifact 已实际下载并逐项核验 SHA256SUMS。原始结果、补丁／模块来源与库 hash 见 [三桌面结果](../../../docs/evidence/native/2026-10-30-portable-candidate.json)。Windows 清单使用反斜杠；在 Mac 校验时仅规范化查找路径，原始字节与 hash 保留。

这些结果解除本候选的 Linux／Windows 编译阻断并证明选定的本地字节流与生命周期合同。GUI 调用方适配、overlay 实际拨号、系统后台、Android/iOS、15 格单网络及 20 格并发矩阵仍未验证。候选代码遵循 Heeler glue 的 LGPL-3.0-or-later 来源边界，最终项目许可证与分发义务另行审查。

## 2026-11-06 managed-node 扩展

原五符号与 stream ABI v1 保留；新增 node ABI v1 四符号：start/status/stop/node_stream_connect。节点不进入可被替换的旧 key `SLOTS`，由专用 registry 直接持有固定 engine instance，node lease 单调不复用、溢出拒绝。connect 从该 lease 捕获 instance，network selector 必须相等；旧 start/stop/stop_all 无法影响它。start 成功只表示 engine-started，不证明 join、地址或路由。status 只输出三值 whitelist，不返回配置或上游错误文本。

start 返回负数时可能仍输出非零 lease，调用端必须保留并 stop。stop 先关闭 admission，必须先关闭/drain所有归属流并等待 active I/O 返回；native stop timeout 保留 node/instance 与容量，成功实际返回才释放，显式 retry 清理。managed node 上限 32；OverlayRuntime 另限 8。配置只借用短期内存，拒绝 `credential_file` 与 `managed_credentials`；并未实现系统安全存储和稳定 device identity。固定源码追踪见 [source audit](../managed-source-audit.json)，runtime 约定见 [调用说明](../../overlay-runtime/README.md)。

新增 [`tests/managed_nodes.rs`](tests/managed_nodes.rs) 把精确 `nodes.txt` 编译到 fake engine 中，本机 4/4 通过；原 8/8 portable tests 保持通过。fake engine 不运行 EasyTier，不打开 socket/DNS/identity，仅测试新增 FFI 的 epoch、selector、drain、容量、start/stop timeout与错误脱敏。新补丁/模板 SHA 已更新至 manifest，并在固定原文件上实际执行 `git apply --check` 与全部 patched-file SHA 核对。更新后真实 Heeler check/link、九符号加载与任何设备/真实网络测试均未运行，留给同批 cloud 验证。
