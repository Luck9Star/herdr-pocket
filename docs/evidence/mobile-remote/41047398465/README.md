# 第二轮 M1a：Rust 6/6，Dart 认证后异步失败

2026-10-30，[run41047398465](https://github.com/Luck9Star/herdr-pocket/actions/runs/41047398465)，源码 `4b78b6b81a6761a248952e1fc5ec8f0e49f3d21b`，总体 **failure**。[artifact12972204179](https://github.com/Luck9Star/herdr-pocket/actions/runs/41047398465/artifacts/12972204179) 已下载并逐条重算顶层 7 个、probe 内 4 个 SHA 条目，均一致；[下载核验](download-verification.json)保存逐文件摘要。

Rust build/test、Flutter 解析锁定、Dart CLI analyze 与本机架构编译均通过，随后实际执行 12 项，**7 通过／5 失败**。凭据生成前的 CLI 编译成功与运行时错误分开记录，见[阶段结果](stage-outcomes.json)。

| 路线 | 实际结果 |
| --- | --- |
| Rust/russh | **6/6 通过**：正确 pin／认证／snapshot／full，错误 pin 认证前拒绝，缺失 session、真实第二 session 的相同 pane ID 错配拒绝，snapshot 后取消，显式重新连接取得新 full |
| Dart/DartSSH2 | 错误 pin 拒绝通过。其余 5 项均已生成安全报告：正确 pin 与认证开始为 true，snapshotReceived/fullFrameReceived 为 false，进程 exit 1，`async_state_error`，lateEventsIgnored=1 |

两实际 session 的 readiness 诊断确认：`result.type=session_snapshot`、`result.snapshot.version=0.9.5`、`result.snapshot.protocol=22`；flat version/protocol 不存在。Rust 首轮 envelope 误读已经由本轮真实正向验证修复。Dart 的失败位于认证后、收到 snapshot 前的异步 StateError，尚不能仅凭此断言具体根因；不把错误区捕获本身当成功。

合成接收器仍为 **0 bytes**；自有进程停止、临时 keys 删除，未操作用户授权文件或上传原始输出。[原始脱敏 manifest](probe/manifest.json)保留全部布尔证据和退出码。elapsedMs 包含 CLI 启动／JIT 等开销，不用于 Rust/Dart 性能排名。

这里只证明 Ubuntu loopback 中的共享适配代码行为。手机 GUI、真实 IME／触控、扫码、设备密钥存储、overlay、连续观察及远端输入仍未验证；不据此确定最终框架。
