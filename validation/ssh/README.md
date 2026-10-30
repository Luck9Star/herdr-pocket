# 隔离 SSH / herdr 验证

本目录提供独立 Linux 协议探针，**尚未接入 Flutter/Tauri GUI**。实际状态以 [SSH Actions](https://github.com/Luck9Star/herdr-pocket/actions/workflows/ssh-validation.yml) 的源提交与 artifact 为准，不把编译或模型测试当真实链路通过。

第四轮 [40985722900](https://github.com/Luck9Star/herdr-pocket/actions/runs/40985722900)，源 `ed35d84046c269169f1b72176ab769b398e6cca5`：以下 7 项真实协议检查全部通过，[artifact](https://github.com/Luck9Star/herdr-pocket/actions/runs/40985722900/artifacts/12946711960) 已下载并逐一核验全部 SHA256SUMS。目标 `w1:p1` 接收 `41e4b8ade696871b5b41030d` 共 12 bytes，重连后接收器仍活且字节未增加。保存的 [manifest、分项结果与收件记录](../../docs/evidence/tauri/2026-10-30-ssh-results.json) 只证明该隔离 harness，不延伸为 GUI 输入或组网通过。下面保留前三轮失败，方便复现边界。

`run-ci.py` 仅允许在 GitHub runner 执行。它在新建 `/tmp/hp-ssh-RUN_ID` 内生成一次性 Ed25519 host/client keys、配置和专用授权文件，只启动 `127.0.0.1` 的临时 sshd；不读取 SSH agent、`~/.ssh`、真实节点身份或真实主机。herdr 通过独立 XDG 目录运行 `pocket-probe` session；测试结束只终止本次启动的进程组和删除已知临时keys，不修改 runner 用户授权或系统 sshd 配置。

固定来源：

- `russh = 0.65.0`，关闭默认特性，显式 `ring`；`tokio = 1.54.1`，`serde_json = 1.0.154`，`Cargo.lock` 固定传递依赖。
- herdr 官方 `v0.9.5` Linux x86_64 发布文件，SHA-256 `14d9e8bc8b4a9e0118d77c32266f76d461f09b40342eb23752960bd89f59929d`；tag 解引用到 `2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01`，不同于设计文档当时浏览的仓库快照。
- API 按该固定提交的 [pane schema](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/schema/panes.rs) 与 [raw send_text 实现](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/app/api/panes.rs) 核查；CI另存真实二进制导出的schema。

Context7 已执行 russh `library` → `/eugeny/russh` → `docs`，核查 `check_server_key`、`connect_stream`、`authenticate_publickey`、streamlocal 与 exec；固定 0.65.0 示例源码再次核对接口。源码示例的无条件 `Ok(true)` **没有**被采用。错误 pin 必须实际进入 key 回调并明确不匹配，再确认连接失败；TCP拒绝或超时不会被计作负向通过。

## 验证内容

1. 错误 host key 在认证前拒绝；正确 pin + 临时私钥完成实际SSH认证。
2. 每RPC单独打开 `direct-streamlocal` channel，读取真实 `session.snapshot`；目标socket绑定显式命名session。
3. 在临时pane运行raw PTY字节接收器。经真实RPC发送 `A中文` 与 `up`、`ctrl+c`、`enter`，收件端应为12 bytes：`41e4b8ade696871b5b41030d`，没有额外提交或隐式重试。
4. `exec` 显式 `--session pocket-probe ... observe`，不申请SSH PTY、不control/takeover，核对首帧full和80×24。不存在session必须失败，不能返回默认session帧。
5. 取消连接与generation，重新pin/认证并取得新full；接收器仍存活，核对重连后收件字节未增加。这里只证明该探针没有重放，不替代GUI输入队列/手机生命周期测试。

每通过一项写增量 `ssh-results.json`，后续失败不抹去已执行事实。最终 `manifest.json` 的总体状态、日志和 `received-bytes.json` 与 partial checks 一起读取。所有keys/fixture认证配置均不上传；只保存合成输入接收结果、schema、锁和构建来源。

本机轻量检查仅 `cargo check --locked --manifest-path validation/ssh/Cargo.toml`（已执行通过）与Python语法，不本机启动sshd或herdr。工作流只在codex分支，构建与测试产物不发布Release/商店。移动端、overlay、GUI绑定、真实用户凭据与设备结果继续标未验证。

## 实际运行记录

[首轮 40984387108](https://github.com/Luck9Star/herdr-pocket/actions/runs/40984387108)，源 `be3a585186eb06b6557a83ae75f9b1d85cbe73e4`：固定客户端编译成功，错误 host key 确实进入比较回调并被拒绝；随后临时公钥认证失败，streamlocal、输入、observe、重连均未执行。ERROR 级 sshd 日志未给出原因。下一轮临时 sshd 使用 PAM account/session 检查并提高到 VERBOSE，以核查 CI 系统账户认证；密码与交互认证仍关闭，授权文件仍为本次临时文件。不把这一配置调整当根因已经确认。

[第二轮 40985036883](https://github.com/Luck9Star/herdr-pocket/actions/runs/40985036883)，源 `e254d6d3fa71783325925bfa25c9a8c12f6965e6`：错误 key 拒绝和正确 pin + 临时公钥认证通过；Unix socket channel 被 sshd 拒绝，未发输入。Context7 `library OpenSSH` → `/openssh/openssh-portable` → `docs` 查明 [session.c](https://github.com/openssh/openssh-portable/blob/master/session.c) 的 `AllowTcpForwarding no` 会关闭 local admin permission，[channels.c](https://github.com/openssh/openssh-portable/blob/master/channels.c) 的 `channel_connect_to_path` 同样检查它。下一轮只在临时 loopback sshd 改 `AllowTcpForwarding local`，客户端仍只使用显式 fixture Unix socket，没有 TCP 转发调用；不修改系统 sshd 配置。

[第三轮 40985445226](https://github.com/Luck9Star/herdr-pocket/actions/runs/40985445226)，源 `bf0f2557f3593b899048e01f6fc507d841af30ad`：herdr socket 路径已出现，但紧随的 workspace create 返回 `server_not_running`，尚未进入 SSH 客户端。修复 fixture 启动竞态：用有界、只读的 `session.snapshot` 等待可接受连接，workspace create 与所有输入仍只发送一次，不做写重试。
