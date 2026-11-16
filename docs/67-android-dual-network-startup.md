# Android 双网启动诊断与验收边界

截至 2026-11-16，Android 双网启动尚无通过结论。本页补充 [第 66 页](66-iteration-handoff-2026-11-16.md)之后的 panic 诊断，不将本机隔离实验当作 Android 修复或设备验收。

## 设备诊断

基线诊断 [run 43873881946](https://github.com/Luck9Star/herdr-pocket/actions/runs/43873881946) 的 plain normal 与 QA 两个包均捕获到 `panic`，消息 SHA-256 同为 `7ccfbfe94828331c4bc8b556780ccf9f78afb3ad9c9228f4c7b80ed43c880758`。摘要显示两条均为 `origin=null`、`frames=[]`、`truncated=true`；设备输出没有保留可用于定位调用链的栈帧，也不能据此证明完整调用路径。两条的 `currentExit.available=false`，不将退出原因当作已查明。

该摘要与 Tailscale v1.104.1 [`logpolicy.go:282`](https://github.com/tailscale/tailscale/blob/v1.104.1/logpolicy/logpolicy.go#L282) 的固定 panic 字面量经 UTF-8 编码计算的 SHA-256 精确一致。这是**消息一致**的证据，并非设备栈帧直接证明该调用点。摘要不包含原始 stderr、地址、私有路径或凭据。

## 源码解释与隔离实验

固定上游源码中，[`ipnlocal.NewLocalBackend` 的 local.go:656](https://github.com/tailscale/tailscale/blob/v1.104.1/ipn/ipnlocal/local.go#L656) 将 `logpolicy.LogsDir(logf)` 作为 `sockstatlog.NewLogger` 的参数。Go 在调用函数前求值参数，因此即使 `NewLogger` 内部随后依据能力条件选择不创建 logger，也不能避免此前的目录探测。目录探测路径在无法找到安全位置时会触发上面的固定 panic。

本机隔离 A/B 实验分别执行一次：原顺序调用目录探测一次并 panic；将 sockstats 与 logtail 能力条件前移后，目录探测零次且正常返回。该实验是针对调用顺序和构建能力的局部观察，不是 Android 产品二进制、Android 文件系统或真实网络的验证，也不能单独证明设备完整调用链。

## 后续验收范围

后续以实际运行结果为准：在 API 35 x86_64 Android 模拟器上验证产品启动与双网行为，并对两台隔离 SSH 端点分别验证连接和交互；还应明确网络切换及清理结果。模拟器结果不等同于实体设备、其他架构或五平台验证。本页不预填任何设备通过结果。
