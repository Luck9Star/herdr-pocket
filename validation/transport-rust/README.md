# M1a Rust 只读 SSH 适配器

状态：2026-10-30，本轮新增实验实现；`russh = 0.65.0`、`tokio = 1.54.1` 固定，依赖锁在本目录与 Tauri native crate 各自的 `Cargo.lock`。Tauri GUI 与 `remote-probe` CLI 使用同一个 `read_once`，没有第二条简化的“测试通过”实现。

`RemoteConfig` 对齐 [共享契约](../shared/remote-contract.json)。只支持用户显式审查后的未加密 OpenSSH Ed25519 临时私钥与完整 Ed25519 主机公钥 pin。适配器不读文件、不查 SSH agent、不读 `~/.ssh`、不持久化凭据，不输出原始错误、服务器数据或私钥。私钥字符串在 Rust config drop 时 zeroize；这不能保证 WebView/IPC/解析副本可靠擦除，也不是设备安全存储。

## 一次读取的边界

1. 校验配置和 pin 的 SSH 公钥结构；真实 SSH key exchange 回调匹配原始公钥后才开始认证。证书和其他算法不回退接受。拒绝所有服务器主动打开的 channel。
2. 一个 direct-streamlocal channel 只发送 `session.snapshot`。验证 response id、`result.type == session_snapshot` 与 `result.snapshot` 对象，拒绝 `ok:false`/error；再验证快照内 release `version == 0.9.5`、`protocol == 22`、唯一精确 `pane_id` 和 `terminal_id`。
3. 本轮只接受非 `default` 命名会话与 `/<config-root>/herdr/sessions/<session>/herdr.sock` 标准路径；拒绝空、`.`、`..` 段。由 socket 派生唯一 `XDG_CONFIG_HOME`，作为固定 `/usr/bin/env` 参数传给同一 release herdr。用户不能提供任意 env 或 command。
4. 固定命令是 `/usr/bin/env 'XDG_CONFIG_HOME=<派生根>' '<herdrPath>' --session '<session>' terminal session observe '<resolvedTerminalId>' --cols 80 --rows 24`。所有可变参数使用 POSIX shell 单参数 quote，terminal ID 限 `term_` 加小写十六进制、总长至多 128。没有 SSH PTY、terminal control、takeover、输入或 resize。
5. 仅接受首个 full ANSI、80×24、合法 seq/base64 的完整帧，然后关闭 channel 和 SSH。每个响应/观察行至多 1 MiB，观察总输出（含丢弃的 stderr）至多 2 MiB；SSH window 64 KiB、packet 32 KiB、channel queue 2。连接、认证、RPC、首帧各有固定超时。
6. 取消先失效 generation，再中断底层 TCP 的等待；不能只丢弃调用 future 而让 russh 后台连接继续运行。完成后再次检查取消，旧完成不能清除或替换新 attempt。没有重试、输入重放或断线自动恢复。

绑定局限必须保留：herdr 0.9.5 的 JSON snapshot/frame 没有可验证 session 身份字段。此实现依赖已核实的 release herdr 路径规则与 terminal ID 精确解析，不把路径或 terminal ID 宣称为加密身份。私钥/host pin 对应的 SSH 主机、账户、herdr binary 与远端文件系统仍是信任边界。`herdr-dev`、默认会话、非标准 socket、preview 版本在本轮明确不支持。

## 检查与 CI 入口

```sh
cargo test --locked --manifest-path validation/transport-rust/Cargo.toml
cargo check --locked --manifest-path validation/tauri/src-tauri/Cargo.toml
```

2026-10-30 本机 Mac 上 9 项 Rust unit tests 通过，Tauri native `cargo check --locked` 通过。包括真实自建 loopback TCP 的取消/EOF、pin 格式、目标路径/quote、帧结构和 generation 隔离。这些检查没有创建 SSH 授权文件、没有连接用户主机；不能代替 SSH/herdr CI 或设备运行结果。

首轮真实 [SSH/herdr CI 41046472357](https://github.com/Luck9Star/herdr-pocket/actions/runs/41046472357) 在 `b88a0ad` 失败：wrong-pin 真实拒绝通过；其余 Rust case 已完成 pin/auth/snapshot，但错误地读取扁平 `result.version`，报告 `unsupported_protocol`。已依据固定源码修正 `result.snapshot` envelope，并在原 unit 中加入旧扁平形状、错误 type、版本/protocol 与 `ok:false` 的拒绝断言；第二轮 [CI 41047398465](https://github.com/Luck9Star/herdr-pocket/actions/runs/41047398465)（`4b78b6b`）的 Rust 路线 6/6 通过：positive/reconnect 得到 full，wrong-pin 在认证前拒绝，missing/cross-session 在真实 snapshot 后拒绝绑定，cancel 在 snapshot 后取消；接收端输入总数 0，临时进程/密钥清理通过。该 run 整体仍因 Dart 路线失败，不能将整条工作流写成通过；[按来源归档的证据](../../docs/evidence/mobile-remote/41047398465/README.md)区分两条路线。结果只覆盖 Ubuntu loopback SSH/herdr，不代表 GUI 操作或手机实测。固定 observe CLI 仅输出 `terminal.frame` 或 `terminal.closed` JSON，其他协议消息在 CLI 内忽略，因此适配器不跳过任意 stdout 前导行。

第三轮 [CI 41048094519](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094519)（`d15da12`）中 Rust 与 Dart 各 6/6、整体 12/12 通过，接收端输入 0，清理通过；[第三轮证据](../../docs/evidence/mobile-remote/41048094519/README.md)单独归档。该轮 Rust adapter 源文件与 Tauri 测试包的 `4b78b6b` 完全一致；Tauri 平台包仍按自己的源 SHA 与构建记录验收。

第三代理负责的 [隔离 CI driver](../remote-harness/README.md) 调用：

```sh
cargo run --locked --manifest-path validation/transport-rust/Cargo.toml --bin remote-probe -- \
  --config TEMP_CONFIG_PATH --case positive --output SAFE_REPORT_PATH
```

CLI 仅接受 `GITHUB_ACTIONS=true`、非特权端口 `127.0.0.1` 及显式临时配置/报告文件，配置最大 32 KiB。四个 case 为 `positive`、`wrong-pin`、`missing-session`、`cancel`；driver 自己构建负向配置。取消发生在真实认证和 snapshot 之后；迟到回调隔离是单独 unit test，报告不会把模拟 late callback 冒充网络收到的帧。stdout/stderr 不打印配置或服务端输出，报告仅共享契约的十个安全字段。实际云端 run/结果由仓库 evidence 记录；此 README 不把尚未执行的 CI 标为通过。

## API 与协议来源

本轮先运行 Context7 `library russh` → `/eugeny/russh` → `docs`，查询 0.65.0 的 host-key handler、内存密钥、connect_stream、direct-streamlocal、exec/cancel 和 channel backpressure；随后核对本机 Cargo registry 的固定 0.65.0 源码，因 Context7 结果不保证版本专属。未出现 quota 错误。

- [russh 0.65.0 client API](https://docs.rs/russh/0.65.0/russh/client/index.html)、[keys API](https://docs.rs/russh/0.65.0/russh/keys/index.html)。`decode_secret_key` 不读文件；`connect_stream` 有后台会话，因此提供可取消的 TCP wrapper。
- herdr 固定提交 `2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01`：[snapshot 构造](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/app/api/session.rs)、[版本](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/build_info.rs)、[protocol 22](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/protocol/wire.rs)。
- [响应 envelope](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/schema/response.rs)：`ResponseResult` 是 `#[serde(tag = "type", rename_all = "snake_case")]` 枚举，`SessionSnapshot` variant 包含 `snapshot` 字段；不能只读内层 struct 后假定平铺到 result。
- [配置根规则](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/config/io.rs)、[命名 session 路径](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/session.rs)、[精确 terminal target 解析](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/app/terminal_targets.rs)、[observe JSON 字段](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/client/terminal_sessions.rs)。

## M1b 持续只读候选（本地测试范围）

`observe` 在同一 SSH 连接内读取唯一命名会话快照，以 pane ID 和 terminal ID 显示看板，明确选择后再执行固定观察命令；空 pane ID 仅允许看板发现，`read_once` 原校验不变。快照最多 256 pane，重复 pane 或 terminal ID 拒绝。首帧 10 秒内须为 full，后续 full/delta 均要求 seq 恰好递增；不完整、非法、超限或乱序即终止，停止后原画面为陈旧。观察期间无输出不视为失败。单行上限 1 MiB、解码帧 64 KiB、stderr 总量 64 KiB；回调逐帧完成后才读取下一帧。取消中断选择、渲染等待和真实 SSH TCP；没有自动重连、输入、远端 PTY 或 resize。

CI-only probe 增加 `observe-positive`（至少三帧及一个 delta）、`observe-cancel`（首帧后取消）和 `observe-reconnect`（主动发起两次独立观察，各 full + delta）。报告仅输出聚合计数，不记录终端数据；未运行的新云端用例不能作为真实 SSH 或手机验证结果。

## 显式 overlay byte transport（2026-11-06）

`transport::Dialer` 返回真正可交给 `russh::client::connect_stream` 的 `ByteStream`；旧 `read_once`、`observe`、device signer 和 guarded input API 继续使用 `SystemDialer`。需要 overlay 时明确调用 `read_once_with_dialer`、`observe_with_dialer`、`observe_with_device_signer_and_dialer` 或 `observe_interactive_with_dialer`，传入 `overlay::OverlayDialer`。所有入口共用 `connect_pinned`，继续使用同一个 host-key handler、认证、device signer、snapshot/session/terminal 校验和原 `LiveInput`；不会另建简化的 SSH 信任路径。

`OverlayDialer::new(Arc<OverlayRuntime>, NodeLease, Duration)` 只绑定实际 app-owned node lease。runtime 的 `open_node` 先验证 node 来自同一个 runtime，再调用 `open_revision`；同名 profile、同 revision 或同虚拟地址不能跨 runtime 借用。每次 dial 新建 owner，取消或丢弃待完成 open 后，原迟到 native handle 仍由 runtime 清理。stream 持有原 owner/profile/revision，不会随 profile 替换而转向新节点。默认构建没有 bridge：缺桥严格拒绝，没有系统 DNS、普通 TCP、localhost listener 或其他 provider fallback。

- `OverlayStream` 直接 poll runtime 的 `Operation` Future；同步 FFI 仍只在 runtime 的独立 worker。读写各最多一个 operation，单次至多 64 KiB；改变下次读缓冲大小时保留已读取的剩余字节。
- 正数 write 只确认本地接受前缀。适配器仅返回该前缀长度，随后由原 SSH writer 推进；UNKNOWN、取消、错误或丢弃 pending write 后更换 buffer 都会关闭该流，不重发。`flush` 没有远端送达保证，ABI 没有额外 flush primitive。
- 原生 read 的 `-2` 明确映射 `ReadTimedOut`，只在同步 FFI 已返回、原 read slot 已释放后，以 Tokio timer 至少间隔 10 ms 再提交 read。正常空闲保持 pending；迟到 read 未返回时不再提交。这里依据固定 portable `Registry::read` 对 cancel-safe Tokio `read` 的 timeout；其他 read 错误仍关闭。write timeout 不走这条继续路径。SSH 握手的整体 8 秒限时和首帧限时继续由共享上层执行。
- `shutdown` 是异步半关闭，保留读取；`close`、取消和 Drop 请求退休本 owner 的流。它们不是 cleanup 成功凭据：宿主保留 runtime，通过 `reserved_streams()` 及节点 cleanup 状态观察尚未返回/清理失败的配额，需要时显式重试原 revision 的 cleanup。

recovery marker 现在绑定**实际连接 stream**提供的 `provider/profile_id/profile_revision/identity_ref`，并继续比较原 SSH host/key/user/socket/session/pane/terminal。没有让 GUI caller 自行传 `None`。旧 marker 缺少 `route` 字段时只表示 legacy/system，overlay 不能清除它；不同 provider、profile、revision 或设备安全存储引用均不能确认同一未知输入。持久 route 不含仅本进程有效的 node epoch/owner；公开网络设置改变必须提升持久 revision，独立 vault 身份换代由新的 `identity_ref` 区分。

feature `overlay-linked-easytier` 明确链接既定候选库；`overlay-native-fixture` 明确启用合成 C ABI，不能作为真实网络证据或缺桥 fallback。`OverlayDialer` 不能在未启用 fixture feature 时接收 `SyntheticNativeFixture` node。路径依赖 `herdr-overlay-runtime-probe = 0.1.0` 固定在本仓库，未新增外部依赖版本。

本轮先完成 Context7 `library russh` → `/eugeny/russh` → `docs`，再核对本机锁定 russh 0.65.0 的 `connect_stream` 约束及 Tokio 1.54.1 `read` 的 cancel-safety。固定 Heeler 原源 SHA-256 `34bca319f85822ae410cea3c3d108024611d9bb26f9b0f98796b0ceee1eef537` 已与 [managed source audit](../native/managed-source-audit.json) 重算比对，`HEELER_ET_ERR_TIMEOUT == -2`；[portable read](../native/portable-stream/src/lib.rs) 和 [FFI mapping](../native/portable-stream/ffi.txt) 是读超时语义的直接依据。

本轮最终本地结果：transport 完整 suite 为 42 项 library tests + 1 项 CLI report test 通过，其中 11 项为新 overlay adapter 测试；runtime 合成 native fixture 为 24 项通过，默认缺桥/安全存储门禁 1 项通过；默认 transport `cargo check --locked --offline` 通过。没有运行 CI 或安装平台 SDK。

验证命令（target 产物只写临时目录）：

```sh
CARGO_TARGET_DIR=/private/tmp/herdr-transport-overlay-target cargo test --locked --offline --manifest-path validation/transport-rust/Cargo.toml --features overlay-native-fixture
CARGO_TARGET_DIR=/private/tmp/herdr-transport-overlay-target cargo check --locked --offline --manifest-path validation/transport-rust/Cargo.toml
CARGO_TARGET_DIR=/private/tmp/herdr-overlay-runtime-target cargo test --locked --offline --manifest-path validation/overlay-runtime/Cargo.toml --features native-fixture
```

新增测试只使用合成 Backend、受控 C ABI、Unix socketpair 及原有自建 loopback SSH fixture。Unix socketpair 测试经过真正的 `OverlayStream → russh` key exchange，分别证明只读和 guarded 入口在错 pin 时认证计数为零。它们没有启动真实 overlay node、访问真实凭据或连接用户主机，不新增任何设备/真实组网矩阵通过格。GUI 的实际 native packaging、系统安全存储和 node identity 仍由各宿主另行验收。

严格 `cargo clippy --all-targets --features overlay-native-fixture -- -D warnings` 本轮没有通过：剩余诊断位于原有 config transfer、input、legacy API 和 loopback test 的 `collapsible_if`、`nonminimal_bool`、`result_unit_err`、`too_many_arguments`、`type_complexity`、`field_reassign_with_default`。本批没有把它写成无警告结果。

## 手机 managed-node 生命周期服务（2026-11-06，后续源码批次）

`mobile_nodes::MobileNodeService::new()` 为 app 创建独立 runtime；可供 Tauri Rust 与后续 Flutter native 接线共用。`start(binding, source, deadline, cancellation)` 每次显式注入 `Arc<dyn SecureConfigSource>`，`status(&binding)`、`status_profile(profile_id)`、`stop(&binding, deadline)` 为异步入口，`dialer(&binding, deadline)` 只捕获成功领取的精确 `NodeLease`。没有默认 source、秘密读取 GUI API、启动重试或普通 TCP fallback；默认缺桥在读取 source 前拒绝。

不可变 `Binding` 只含 `profileId / profileRevision:u32 / networkName / identityRef`。`NodeSpec.profile_revision` 是持久目录 revision；`NodeSpec.revision:u64` 仅为 runtime 内单调递增的启动 attempt。停止再启动同一配置保留 recovery route 的持久 revision 与身份引用，同时获得新的 attempt；旧 dialer/lease 不能转向重启节点。网络名或其他公开网络设置变化必须提升目录 revision。独立 vault 删除／重建生成新 `identityRef`，在旧节点明确 Stopped 且清理完成后，可用相同目录 revision 显式启动；两种身份不能互相清除未知输入标记。

**可信调用方契约：** service 的 Binding 不含 peers，不能识别调用方在相同 revision 下偷换 peers。宿主须在取得目录 CAS 审核的不可变配置后创建本次 source；任何公开 peers 变化必须提升持久 revision。source 在 worker 内核对 `profile.id / profile_revision / network / identity_ref`，按该绑定载入本机安全资料与已固定 peers，不能把临时 `spec.revision` 当目录 revision。source 失败只返回脱敏错误，不降级为其他身份、文件或配置。

Starting、EngineStarted、Closing、Stopped 只描述本机生命周期；EngineStarted 不表示入网、peer 可达或 SSH 可用。取消或丢弃 pending start 会退休其原 attempt，迟到结果不能附着；未返回的 start、失败清理与 drain 都占原 runtime 的 8 个 node 配额。失败 stop 只能由宿主显式调用同 Binding 的 stop 重试；不能把 Closing 当 Stopped 或重试 start。`status_profile` 返回 service 实际保留的旧 Binding，供 vault 已删除／换代时先撤销其 SSH 再停止原节点。service 自身立即关闭 node admission；SSH 页面状态与取消仍须宿主同步撤销。

每个 service 最多保留 32 个不同 profile ID（含 Stopped 历史），以保留本 runtime 的 revision／网络名防降级检查；第 33 个新 ID 在读取 source 前返回 `mobile_node_history_capacity`，已知 ID 仍可重启。不会静默淘汰历史。清空历史须在旧 runtime 资源明确清理后，由 app 重建 service/runtime；这不是自动恢复或真实安全存储防回滚保证。

本批复验仅使用显式 `overlay-native-fixture` 的合成 C ABI、自建临时 recovery 目录与已有隔离 SSH fixture；没有新 CI 构建、平台 SDK 安装、真实凭据读取、socket 转发或真实节点启动。测试命令沿用上面的 `/private/tmp/herdr-transport-overlay-target` 与 `/private/tmp/herdr-overlay-runtime-target`；GUI、真实 engine 与设备验收分别记录。

## 保留 SSH 的暂停与显式恢复（2026-11-06）

新增 `observe_interactive_controlled_with_dialer` 供宿主为每个连接创建独立的 `ObservationControl`；旧入口保持原语义。参数沿用 config、device signer、整连接 cancellation、audit、progress、pane selection、frame callback 和 dialer，增加 `Option<ControlledInputHooks>` 与 control。`frame(epoch, StreamFrame)` 的 Future 是本帧消费确认；`ControlledInputHooks` 提供共享 recovery、`ready(epoch, Arc<LiveInput>)` 和 `state(ObservationSnapshot)`。只读调用传 `None` 仍可暂停／恢复。

`control.snapshot()` 返回 `{ epoch:u64, phase }`；phase 为 `starting / active / pausing / paused / resuming / closed`。`pause()`、`resume()` 同步返回 `Result<ObservationAck>`，宿主必须继续 await 该 Future。每个 control 只接纳一个命令；忙时返回 `control_busy`，`resume` 仅接受 Paused 状态。Pause 可覆盖正在执行的 Resume：先同步退休旧 epoch 和输入权限，原恢复 ACK 返回 `control_superseded`，旧 frame／ready／receipt 不能激活新 epoch。宿主处理所有 callback 时仍须匹配连接 ID 与 epoch，并同步清除自己的未发送输入队列；core 不持有 GUI 队列。

暂停先同步撤销原 `LiveInput`，再关闭本地 observation channel，成功 ACK 后进入 Paused，保留原 SSH、实际 route、host pin、用户、session、pane 和 terminal。ACK 表示**本地 channel sender 已退休、Close 请求已处理**；它不证明对端收到 Close 或观察进程退出。暂停没有持续 frame 缓冲，也不依赖悬挂 frame ACK。恢复只在同一 SSH 上重新 snapshot，核对原 pane 仍对应同 terminal，再创建新的 observe channel；首帧必须 seq=1/full，且其 callback 完成后才进入 Active／发布新 `LiveInput`。新输入仍从 observe 模式开始，没有自动 dial、重连、resize 或输入重放。初次 pane 选择可一直等待用户，取消或 control epoch 变化仍可打断。

未决输入在暂停后失去资格，保留 durable unknown marker；迟到的成功 receipt 不能清除它。observation epoch 的取消只退休原输入，整连接 cancellation 仍中断网络和输入。Recovery 本轮继续只有一个全局 marker：A 的未知结果可能阻止 B 发送，B 的独立观察和暂停／恢复继续工作；不同目标不能清除 A 的标记。恢复 marker 的持久 route 不增加 observation epoch，也不弱化原有身份校验。

单次本地 Close 处理最多 5 秒，snapshot／capability RPC 同样显式退休自己的 channel；EOF 单独不算退休。关闭错误、超限或超时会取消原 SSH。`ObservationAck` 从创建起设 10 秒截止时间，等待时到期或丢弃当前未完成 ACK 会撤销整连接；被覆盖旧 ACK 的迟到 Drop 不影响新命令。宿主必须 await ACK 并处理错误，不能丢弃 Pause 后继续使用原输入。连接入口正常返回前会取消网络并等待其 pending dial Future 与 SSH driver 所拥有的实际 ByteStream 完成 Drop；宿主的连接额度必须保留到入口结束，不能以收到 Closed 状态代替释放。overlay 的迟到 native open／failed cleanup 另受 runtime 的 32 stream 预算约束；宿主的 8 个 SSH 额度不表示 native reservation 已全部归零。

### 固定 russh 的局部候选修补

官方 0.65.0 本地主动 Close 删除 encrypted channel 后，后续 peer Close 被 established-channel 检查跳过，独立 client sender 索引仍残留。候选在原 Close 分支退休 sender；若该分支发现 encrypted pending data，则保守断开本 SSH。驱动遇 zero-window 时可能先停止读取普通 outbound 队列，让 Close 尚未进入此分支；此时由上面的 5 秒关闭限时取消原 SSH。zero-window 回归证明的是这条超时／撤销路径，没有声称动态执行了 defensive pending guard。服务端不响应 Close 时，成功的本地退休也不能证明远端进程退出。

三个消费根 `transport-rust`、`tauri/src-tauri`、`flutter-network-runtime` 的 patch 和锁均指向同一个本地 0.65.0；独立 `validation/ssh` 保留原 registry 版本作对照。完整官方 90 文件、唯一修改 `src/client/mod.rs` 的补丁、源码／archive hash 和补充 Apache 许可证见 [source manifest](../vendor/russh-0.65.0-source.json) 与 [NOTICE](../vendor/RUSSH-NOTICE.md)。离线校验会反向应用精确补丁，逐文件还原官方 hash；提供已缓存 archive 时还会独立核对每个成员，不写 Cargo registry。

```sh
python3 validation/vendor/verify-russh.py --metadata
# archive 参数是已取得的官方 .crate 本地路径；本机本轮为以下临时文件。
python3 validation/vendor/verify-russh.py --archive /private/tmp/herdr-russh-0.65.0.crate --metadata
python3 validation/vendor/reproduce-local-close.py --archive /private/tmp/herdr-russh-0.65.0.crate --log-dir /private/tmp/herdr-russh-local-close-evidence --output /private/tmp/herdr-russh-local-close-evidence.json
```

本轮最终本机结果：默认完整 suite **51 项 library + 1 项 CLI report test**，`overlay-native-fixture` 完整 suite **60 项 library + 1 项 CLI report test** 全通过。新增 8 项 controlled loopback 回归覆盖同 SSH 连续 8 次暂停／恢复且 dial/auth 各一次、两条连接隔离、恢复目标替换拒绝、pending frame ACK 可暂停／取消及覆盖恢复、未决输入 unknown 与迟到 ACK 隔离、peer 不读 Close 时本地退休、zero-window pending 后 5 秒超时断开原连接、用户选择超过 8 秒与迟到 I/O Drop 收敛。

独立源码重建对照以同一正常 pause/resume 测试取得官方 upstream 预期关闭超时（exit 101），候选通过（exit 0）；来源校验还证明三根各只有一个 russh 候选实例。vendor 新增的两个内部单测因本机缺少其锁定 dev 依赖没有运行，不计入上述通过数。严格 Clippy 仍有原有 12 个诊断，新 controlled 模块没有诊断；依赖自身另有原始 unused-variable/dead-code warning。没有运行本批 CI、真实 herdr／overlay 节点、真实凭据或设备测试。
