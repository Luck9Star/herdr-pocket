# Android 双网启动诊断与验收边界

截至 2026-11-16，Android API 35 x86_64 启动控制点已通过；两种 UI 双会话及停网方向仍在验收，尚无双网端到端通过结论。本页补充 [第 66 页](66-iteration-handoff-2026-11-16.md)之后的诊断和分层证据。

## 设备诊断

基线诊断 [run 43873881946](https://github.com/Luck9Star/herdr-pocket/actions/runs/43873881946) 的 plain normal 与 QA 两个包均捕获到 `panic`，消息 SHA-256 同为 `7ccfbfe94828331c4bc8b556780ccf9f78afb3ad9c9228f4c7b80ed43c880758`。摘要显示两条均为 `origin=null`、`frames=[]`、`truncated=true`；设备输出没有保留可用于定位调用链的栈帧，也不能据此证明完整调用路径。两条的 `currentExit.available=false`，不将退出原因当作已查明。

该摘要与 Tailscale v1.104.1 [`logpolicy.go:282`](https://github.com/tailscale/tailscale/blob/v1.104.1/logpolicy/logpolicy.go#L282) 的固定 panic 字面量经 UTF-8 编码计算的 SHA-256 精确一致。这是**消息一致**的证据，并非设备栈帧直接证明该调用点。摘要不包含原始 stderr、地址、私有路径或凭据。

## 源码解释与隔离实验

固定上游源码中，[`ipnlocal.NewLocalBackend` 的 local.go:656](https://github.com/tailscale/tailscale/blob/v1.104.1/ipn/ipnlocal/local.go#L656) 将 `logpolicy.LogsDir(logf)` 作为 `sockstatlog.NewLogger` 的参数。Go 在调用函数前求值参数，因此即使 `NewLogger` 内部随后依据能力条件选择不创建 logger，也不能避免此前的目录探测。目录探测路径在无法找到安全位置时会触发上面的固定 panic。

本机隔离 A/B 实验分别执行一次：原顺序调用目录探测一次并 panic；将 sockstats 与 logtail 能力条件前移后，目录探测零次且正常返回。该实验是针对调用顺序和构建能力的局部观察，不是 Android 产品二进制、Android 文件系统或真实网络的验证，也不能单独证明设备完整调用链。

## 修复后启动控制点

原生源码固定于 [`a9be92d`](https://github.com/Luck9Star/herdr-pocket/commit/a9be92d98b8c26b15ccbc7f6faa240ed3d674929)。原生构建 [run 43877918495](https://github.com/Luck9Star/herdr-pocket/actions/runs/43877918495) 的 normal 和 QA 两个 job 成功；独立重下载的 x86_64 bundle 校验成功。重下载校验本身未运行 Android 加载或节点启动。

[run 43880234995](https://github.com/Luck9Star/herdr-pocket/actions/runs/43880234995) 的 plain normal、QA 两包均在 API 35 x86_64 模拟器达到 `startOk=true`、`needsLoginReached=true`、`states=[needs-login]`、`stopOk=true`、`passed=true`；两包均未调用 login 或 dial，同 UID 私有 stderr 摘要为空。两包 scope、identity、安装包及会话清理成功，AVD 包装器和 namespace 清理检查通过。仅保留[脱敏字段摘要](evidence/android-dual-startup-20261116/startup-probe-43880234995.json)；该摘要对应验证工件 14230924293。

这一控制点证明两个包到达预登录并完成受检关闭流程，不证明授权、SSH 会话、双网并发或停网后存活。两种 UI 的双会话和两个停网方向仍须分别以设备结果验收。

## 后续验收范围

后续以实际运行结果为准：在 API 35 x86_64 Android 模拟器上验证产品双网行为，并对两台隔离 SSH 端点分别验证连接和交互；还应明确网络切换及清理结果。模拟器结果不等同于实体设备、其他架构或五平台验证。本页不预填双网端到端通过结果。
