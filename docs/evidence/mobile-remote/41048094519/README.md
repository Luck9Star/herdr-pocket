# 第三轮 M1a：两条只读适配器各 6/6 通过

2026-10-30，[run41048094519](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094519)，源码 `d15da12a4fc7d60313b3c253a315c001e7290b5e`，总体 **success**。[artifact12973068771](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094519/artifacts/12973068771) 已下载并逐条重算顶层 7 个、probe 内 4 个 SHA 条目，均一致；[下载核验](download-verification.json)保存逐文件摘要。该测试 artifact 预计 2026-11-13 到期，本目录保留原始脱敏内容。

Rust build/test、Flutter 依赖解析与候选锁审查、Dart CLI analyze/编译均通过，实际协议用例 **12/12 通过**。这是两条 GUI 使用的共享适配代码在 Ubuntu 24.04 x86_64、同一个临时 loopback OpenSSH + herdr 0.9.5 fixture 下的结果，见[阶段结果](stage-outcomes.json)及[完整脱敏 manifest](probe/manifest.json)。

| 用例 | Rust/russh | Dart/DartSSH2 | 实际证明范围 |
| --- | --- | --- | --- |
| positive | 通过 | 通过 | pin 匹配、认证开始、真实 snapshot、明确目标的首个 80×24 full |
| wrong-pin | 通过 | 通过 | 真实 key 回调发生、pin 不匹配，认证未开始 |
| missing-session | 通过 | 通过 | 有效 socket 返回 snapshot 后，配置中的不存在 session 名与 socket 路径不一致，`session_mismatch` 拒绝；未运行该不存在 session 的 observe |
| cross-session | 通过 | 通过 | 两个真实 session 均存在且 pane ID 相同，socket/session 错配仍被拒绝，无 full |
| cancel | 通过 | 通过 | 已完成 pin、认证和 snapshot 后取消，无 full，`cancelled`；不是取消前连接失败 |
| reconnect | 通过 | 通过 | 新 CLI 调用显式再次连接同一目标，取得新 full；未验证同一 GUI 实例的连续恢复 |

取消结果中，Dart `generation=2`、`lateEventsIgnored=1`；Rust 报告本次 attempt 的 `generation=1`、`lateEventsIgnored=0`。两者实际 SSH 取消条件均满足；不能由 Rust 的本轮计数声称已注入迟到事件。代际失效与迟到发布拒绝另由适配层单测覆盖，本轮不等同于长连接流中断／后台恢复验证。

两实际 session 的 readiness 均确认 `result.type=session_snapshot`、`result.snapshot.version=0.9.5`、`result.snapshot.protocol=22`。此前两轮失败均保留：[首轮 2/12](../41046472357/README.md)、[第二轮 7/12](../41047398465/README.md)。本轮在移除 Dart streamlocal channel 的竞争 `flush()` 后，之前认证后的 `async_state_error` 不再复现，正向与取消均取得预期实际证据。

合成接收器全过程 **0 bytes**；自有进程停止、临时 keys 删除，未操作用户授权文件或上传原始输出。elapsedMs 包含 CLI 启动／JIT 等开销，不用于两路线性能比较。

手机 GUI 的有效 SSH 接入、真实手机 IME／触控、扫码、受保护密钥存储、三网、连续观察、远端输入及五平台运行仍未验证；本轮不确定最终框架，也不授予操作真实主机的权限。
