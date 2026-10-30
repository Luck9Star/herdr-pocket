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
