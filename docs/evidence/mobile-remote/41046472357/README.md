# 首轮 M1a 适配器实际 SSH 验证：失败记录

2026-10-30，[run41046472357](https://github.com/Luck9Star/herdr-pocket/actions/runs/41046472357)，源码 `b88a0ad9b2a173ac743568ec5ce479f22b6844ca`，总体 **failure**。[artifact12973360512](https://github.com/Luck9Star/herdr-pocket/actions/runs/41046472357/artifacts/12973360512) 已实际下载；顶层 7 个、probe 内 4 个 manifest 条目全部重算 SHA256 一致，见[下载核验](download-verification.json)。保留原始脱敏 manifest，不以修复后的推断覆盖失败事实。

Rust build/test、Flutter 准备与依赖锁核验均成功，真实探针执行完 12 项，**2 通过／10 失败**。唯一通过的是两适配器各自的错误 host key：实际 key callback 执行、比对失败且未开始认证。

| 适配器 | 其他 5 项的实际结果 |
| --- | --- |
| Rust | positive、missing-session、cross-session、cancel、reconnect 均 `unsupported_protocol`。已完成正确 pin、认证及收到 snapshot，未收到 full；没有把它们计为绑定或取消通过 |
| Dart | 相同 5 项没有生成 safe report（`adapter_report_missing_or_large`）。wrong-pin 的实际运行排除了“整个 CLI 不能编译”这一解释，但尚不能据此确定其他路径失败原因 |

共享 fixture 的两个真实 session 存在且拥有相同 pane ID；客户端执行期间输入计数为 **0 bytes**。自有进程结束、临时 keys 删除；没有操作用户授权文件，也没有上传 raw stderr、凭据或连接配置。[实际 manifest](probe/manifest.json)和[阶段结果](stage-outcomes.json)记录上述范围。

后续静态定位：固定源码 `src/api/schema/response.rs` 将真实 snapshot 包为 `result.type=session_snapshot`、`result.snapshot={version,protocol,panes,...}`，首版适配器误读了 flat result。适配器 owner 改为严格 wrapper；harness 增加 flat/nested 已知字段诊断、进程退出码／报告长度，并在生成凭据前单独 analyze/compile Dart CLI。Dart 的认证后异步失败由适配器 owner 查证。只有后续真实 run 才能判断修复是否有效。
