# 手机优先 M1a：两条真实只读适配器对照

此目录把 Flutter/DartSSH2 与 Tauri/russh 所用适配代码放进同一个临时 OpenSSH + herdr 目标验证。它不是 UI 自动点击或手机运行证据；工作流结果、源码 SHA 和下载 manifest 必须对应后，才能记实际通过。

范围：手动资料审查／预期 host key → SSH 公钥认证 → 每请求一个 streamlocal `session.snapshot` → 明确 session/pane 的首个 full → 关闭。远端输入、连续观察、扫码、受保护凭据存储、三网和手机 IME 均不在本轮通过范围。

## 隔离边界

- `run-ci.py` 在 fixture 创建前检查 `GITHUB_ACTIONS=true`、数字 run ID 与 `refs/heads/codex/`。本机只运行下面的纯逻辑测试，不启动 sshd/herdr。
- 同一新建 `/tmp/hp-mobile-*` 包含临时 Ed25519 host/wrong/client keys、专用授权文件、独立 XDG 目录和两个命名 session。sshd 只监听 `127.0.0.1` 高端口，禁止 SSH PTY、密码／交互认证和 agent forwarding。它不读取或修改用户 `~/.ssh`、真实授权或组网身份。
- fixture setup 可创建自己的 herdr pane 并运行合成画面／输入计数器；这与两个只读客户端分开。客户端过程期间计数器必须仍在运行，接收字节必须保持 0。
- `herdrPath` 是校验过的真实二进制，不使用 wrapper 覆盖 XDG。客户端从已审查的命名 session socket 路径推导 XDG 根，并用 snapshot 里 pane 对应的 `terminal_id` 建立观察，不能以多个 session 都有 `w1:p1` 推断同一目标。
- 每个 CLI 配置只在私有临时目录保存，结束即删除。stdout/stderr 不上传；原始 sshd/herdr 日志只留临时目录。artifact 从严格的报告字段／类型白名单重建，不复制私钥、配置、远端文本或任意异常消息。
- 只终止本次记录的进程组、清除本次生成的 keys，不停止系统服务或递归删除用户目录。cleanup 状态单独报告。

## 同条件用例

两适配器依次使用同一 sshd、host key、合成 pane 内容与 80×24 目标，每条最多 60 秒。某条失败仍尝试其余用例，并增量保存结果。

| 用例 | 必须取得的实际证据 |
| --- | --- |
| positive | host key 比对、认证、snapshot 与 full 均真实完成 |
| wrong-pin | 实际 key 回调执行，匹配为 false，认证未开始；TCP 拒绝／超时不能通过 |
| missing-session | 有效 socket 返回 snapshot 后，错误 session 被拒绝，无 full；可以在绑定检查时拒绝，不能称已执行 observe |
| cross-session | 第二个真实 session 确有相同 pane ID，socket/session 错配仍被拒绝，不发布其他 session 的画面 |
| cancel | 实际 SSH 已完成 snapshot 后取消，无 full；开始前取消不能代替本项。迟到结果发布另由适配器单测检查 |
| reconnect | 显式再次执行 positive，取得新 full；输入计数仍为 0，没有自动重试或重放 |

## 执行与产物

本机允许的轻量检查：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s validation/remote-harness -p 'test_*.py' -v
```

2026-10-30 首版 7 项 guard 测试通过，加入有限协议诊断后为 8 项全部通过；3 个 Python 文件语法解析通过。这些只证明隔离门禁和结果分类，不证明 SSH 用例已经执行。

云端工作流：[mobile-remote-validation.yml](../../.github/workflows/mobile-remote-validation.yml)。它使用 Rust 1.96.0 和已有固定 Flutter 3.47.9/c197ca5 来源，在 runner 构建两适配器。候选 terminal 包首次 hosted→path 转换按既有 `pub get` + `candidate.py verify-lock` 执行，除候选本体外不得漂移。源锁与实际阶段结果在编译失败时也上传，实际协议结果在 `probe/manifest.json`；缺失该文件表示未进入完整协议探针，不能算通过。

真实协议来源仍固定 herdr v0.9.5 / `2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01`，Linux x86_64 二进制 SHA256 `14d9e8bc8b4a9e0118d77c32266f76d461f09b40342eb23752960bd89f59929d`。新 workflow 保留 14 天测试 artifact，不创建 Release、不提交商店、不合并主分支。

2026-10-30 已按 Context7 `library OpenSSH` → `docs /openssh/openssh-portable` 核查 `AuthorizedKeysFile`、`AllowStreamLocalForwarding local`、`AllowTcpForwarding local` 与 `PermitTTY no`。依据[官方 sshd_config 文档](https://github.com/openssh/openssh-portable/blob/master/sshd_config.5)及 [streamlocal 服务端处理](https://github.com/openssh/openssh-portable/blob/master/serverloop.c)；固定 runner 的实际 OpenSSH 版本应随云端执行记录核对。

首轮实际 [41046472357](../../docs/evidence/mobile-remote/41046472357/README.md) 为 2/12 通过、10/12 失败；仅两端错误 pin 拒绝通过。后续增加 readiness snapshot 的 version/protocol 类型与受限值诊断、CLI 退出码和报告长度，仍不输出原始响应或错误。实际版本记录为 OpenSSH 9.6p1 Ubuntu-3ubuntu13.20。

第二轮 [41047398465](../../docs/evidence/mobile-remote/41047398465/README.md) 为 7/12 通过：Rust 6/6；Dart 仅错误 pin 通过，其余认证后、snapshot 前发生安全报告中的 `async_state_error`。真实 readiness 确认 tagged `result.snapshot` 与 0.9.5 / protocol 22。接收器 0 bytes，cleanup 通过；Dart 修复仍需后续实际 run。

第三轮 [41048094519](../../docs/evidence/mobile-remote/41048094519/README.md) 在源码 `d15da12` 上 **12/12 通过**，Rust、Dart 各 6/6；移除 Dart channel 的竞争 `flush()` 后，实际正向 full、snapshot 后取消和显式重连均通过。接收器 0 bytes，cleanup 通过；脱敏 artifact 的两层 SHA 已下载复核。这里的 reconnect 是新 CLI 调用，missing-session 是有效 socket 返回 snapshot 后的名称绑定拒绝；不外推到 GUI 连续恢复或真正不存在 socket 的观察命令。elapsedMs 包含进程启动／JIT，不作为公平性能排名。
