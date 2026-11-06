# Tailscale managed runtime（候选）

本目录提供 `hp_ts_*` C ABI、Go 生命周期管理器和实际 `tsnet.Server` adapter。使用固定 Tailscale v1.104.1 源码及父目录记录的 `ExplicitAuthOnly` 补丁；未打补丁的 stock tsnet 不满足构建要求。它是产品接入候选，隔离测试、编译与动态库加载不证明真实 tailnet、手机设备或分发可用。

公开签名和结果码以 [hp_ts.h](hp_ts.h) 为准。输出库名为 `libhp_tailscale`。调用方保存所有节点与流句柄，先 close、再 release；只有 release 返回 `HP_TS_OK` 才可释放其所有权。存储回调及 opaque `uint64_t context` 必须保持到 node release 成功，超时、取消、Rust Drop 或 Start 失败均不能提前释放。

- 全进程最多 8 个节点、32 个流；句柄使用单调 u64，不复用。迟到 Start/Dial、阻塞或失败的 Close/IO 和未 release 句柄继续占配额。Close 报 IO 后对象与存储 context 仍保留，仅显式 close 重试原对象；cancel 不自动重试。迟到 Dial 的 orphan 关闭失败也保留，由显式 node close 重试并成功后清理。
- `node_new` 只预留资源。Start 无法取消：等待超时会请求退休，实际 engine.Close 等 Start 返回后执行。对未启动节点直接关闭不会调用 engine.Close。
- 状态为 Starting、NeedsLogin、NeedsMachineAuth、Running、Closing、Stopped。Start 成功不等于 Running；仅结构化状态为 Running 才可发起 TCP Dial。Status/Login 使用受控 LocalClient API，互斥且保留迟到操作的所有权。
- 登录只由 `node_begin_login` 发起。不自动打开浏览器，不从日志提取 URL。只有显式登录后的 Status 可给出 HTTPS、无 userinfo/fragment、最多 4096 字节的 auth URL；完整 Status JSON 最多 8192 字节。上层仍需自己的 URL 确认策略。
- 实际 adapter 固定 `ExplicitAuthOnly: true`、默认官方 ControlURL、默认 hostname `herdr-pocket`，并在构造 Server 前调用 `envknob.SetNoLogsNoSupport()` 与 `logtail.Disable()`。Logf/UserLogf 丢弃，不打印授权 URL。没有 AuthKey 配置入口。
- 每个原生 profile 提供独立、规范化绝对 app-private Dir；调用方负责目录权限和防止 symlink 别名。相同规范路径在旧节点 release 前不能重复占用。自定义 StateStore 仍不省略 tsnet.Dir。
- 全部 StateStore 键原样传给原生回调（含空键），最多 1024 字节，值最多 262144 字节。missing、存在的空值、null-delete 分离；任何读取/写入错误直接失败，无 Go 明文状态存储回退。回调须线程安全且同步完成，不能保留借用指针；read 返回非空分配即使同时报错也会调用 release。manager 对每个 node 包装独立访问门，回调及 read 分配释放都持共享 lease；只有 engine Close 成功、API/流收敛且所有 lease 返回后，才关闭门并允许 node release。Close 失败保持存储与 context；门关闭后的迟到访问直接报 IO，不调用宿主回调，不依赖上游后台 goroutine 已全部 join。
- opaque net.Conn 不是 Unix fd。每次 IO 最多 64 KiB，deadline 为 1..60000 ms；读和写可并行，同方向只允许一个操作。取消唤醒调用者并退休流，底层工作仍保留所有权。写入派发后中断返回 UNKNOWN_WRITE，不重放。
- Read 的可重试 TIMEOUT 仅在底层已返回、读到零字节时产生。等待超时但 Read 仍未结束时返回 CANCELLED 并退休流，避免新 Read 吞掉迟到字节。CloseWrite 使用连接的真实半关闭能力；不支持则明确 UNSUPPORTED，绝不以 full close 伪装。

## 隔离验证

核心测试可完全绕过第三方包，仅使用 fake engine、net.Pipe 和自建 `127.0.0.1` listener：

```sh
GO111MODULE=off go test -race -count=20 -v \
  validation/native/tailscale-runtime/core.go \
  validation/native/tailscale-runtime/core_test.go
```

完整验证使用父目录工具创建的固定源码临时构建树，`go test -race -tags hp_ts_test ./...` 包含真实 cgo StateStore 回调测试。`hp_ts_test` 仅启用 C 内存回调 fixture，不启动 tsnet。候选构建工具另验证上游显式认证补丁、构建 c-shared 库，并在子进程中核验 ABI version 与有限的未启动节点生命周期：node_new → Stopped → login/dial 拒绝 → close/release。该检查不调用 node_start，不执行存储回调或建立网络连接。

尚未验证真实 Tailscale 节点、登录/审批、tailnet 流量、Android/iOS/Windows ABI、设备存储桥及发布安装。Go 代码不单独证明这些能力。
