# 三网络原生可行性探针

2026-10-30。这里实际编译锁定来源，在 GitHub Actions 的 Windows、macOS、Linux runner 中暴露移植阻碍。**仅构建或加载成功不算原生网络可用，更不能外推 iOS/Android、真实 SSH 或三网并发通过。**具体结果须看每次 run 的 `results.json` 和原始日志，本文件不预填通过。

## 三项探针

| Provider | 执行内容 | 即使通过仍未覆盖 |
| --- | --- | --- |
| Tailscale | 使用已锁定 `tailscale.com v1.104.1` 的完整 go.mod/go.sum；编译 `tsnet.Server` 的 `Dial(context.Context, ...)` / `Close` 接口与 Go `c-shared` 最小 ABI，加载库并调用本项目无副作用的 ABI 版本函数。 | tsnet 实例启动、Windows cgo/MSVC 产品链接方式、实际 Dial/取消、秘密存储、入网、FFI stream生命周期；不启动节点、不从系统 tailscaled 取网络。 |
| EasyTier | 获取 Heeler 原生库锁定的 EasyTier 开发提交，校验并应用 3 个补丁，以 Rust 1.95.0、protoc 36.2 运行真实 `cargo check --locked --lib`。 | 不是 link 或运行测试；UnixStream / RawFd / Apple socket 参数若在 Windows/Linux 编译失败，记录真实错误供移植，不跳过当成功。 |
| ZeroTier | 获取锁定 libzt fork 及三个子模块，核实 gitlink，校验应用 4 个补丁；CMake 构建共享库，加载并解析 node/socket/connect/close 导出符号。 | 只解析函数地址，不调用 node_start、join 或 socket；没有身份/网络/单owner pump/多网络定向证据。 |

测试使用 [Heeler native 锁定提交](https://github.com/Ylarod/heeler-overlay-natives/tree/6a2817fc02aeb552df251d9478753c22fd4738bb) 的 `sources.lock`。解析它为数据，不在 shell 中 source；对源 commit、补丁和 Go 锁文件 SHA256 都执行验证。固定工具版本及 protoc 三平台 zip 的官方 digest 见 [`sources.json`](sources.json)。CMake、C/C++ 编译器来自 runner image，精确 image 和日志进入结果；尚未制作完全可复现的 C/C++ 工具链镜像。

## 云端执行与结果

[Native Actions](https://github.com/Luck9Star/herdr-pocket/actions/workflows/native-validation.yml) 只对 `codex/` 分支执行。Python runner 在非 GitHub Actions 环境直接拒绝编译，不在本机安装完整 SDK 或构建节点。每个平台依次执行三 provider；一个失败仍继续其他探针，最终任一失败则 job 非零退出。没有 `continue-on-error`，探索性失败不会变绿。

artifact 包含：

- `results.json`：每 provider 的 passed/failed、具体命令/exit code/耗时/错误、源 SHA、平台、来源与补丁列表；网络与设备项恒为 `not run`。
- 原始构建日志、上游 `sources.lock`、Go 锁文件、许可文件与整体 SHA256SUMS。
- 对构建出的库仅记录 SHA、大小及本次 load 结果，**暂不把库装入 GUI 或发布原生 SDK**；原生可分发包还需对应源码/重链接材料和许可审查。

调试超时会以 exit code 124 单列。工作目录在 runner 临时目录，拒绝覆盖已有目录；没有读取维护者 `~/.ssh`、组网身份或真实网络凭据的入口。CI 未调用 start/join，也没有操作真实主机授权文件。

## 当前许可边界与来源

- Heeler glue 各文件分别审查，不能只看 root：EasyTier C ABI 适配明确 `LGPL-3.0-or-later`；`cargo check` 不形成 GUI 发行许可结论。
- 所锁 libzt `LICENSE.txt` 标注 Change Date 2026-01-01 与 Change License Apache-2.0；这不覆盖 ZeroTierOne、lwIP、补丁和实际链接集合的全部义务。保留每个来源的原始许可，不在此宣布最终许可证已经确定。
- 实际来源以构建时报告为准，不用当前 main 的 API 或许可替代锁定提交。

本轮 Context7 分别执行 library→docs：`/tailscale/tailscale`、`/easytier/easytier`、`/zerotier/docs`。Tailscale 文档明确 Start/Dial 可能隐式启动与登录，因此本探针只做类型检查和无副作用 ABI；EasyTier 官方编译指南不能证明 Heeler glue 可跨平台；ZeroTier docs 中的 node/socket 示例只用来查 API，不在本次执行真实网络流程。精确 API/补丁/许可证仍以固定来源代码为准。

后续先解决实际编译错误，再加临时隔离网络中的字节流、取消/迟到清理与身份持久化测试，最后才接真实 SSH/herdr 和五端十五格/并发矩阵。不得用当前三桌面构建格替代产品支持矩阵。
