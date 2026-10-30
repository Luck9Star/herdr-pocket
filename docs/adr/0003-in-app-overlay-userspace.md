# ADR-0003 · 进程内 userspace overlay 与三 provider

状态：已接受方向，三 provider 集成目标由 [ADR-0006](0006-three-overlay-providers.md)补充（2026-10-29）。原先“首发只做 Tailscale”的范围已被用户新要求替代。

## 背景

目标是同一产品在 iOS、Android、Windows、macOS、Linux 上自行连接已配置的私网主机，避免要求用户切换系统 VPN。首版仍只控制远端 herdr，不提供本机 daemon 管理，也不承诺后台持续在线。

## 决策

Tailscale、EasyTier、ZeroTier 全部纳入当前架构与首版集成目标。其中 Tailscale 与 EasyTier 为每个正式支持平台的核心必需能力；完整三网五端目标需 15 个组合分别通过。

各网络使用进程内 userspace data plane，只为本 App 的 SSH 第一跳提供 TCP 字节流；不申请 NetworkExtension / VpnService，不自动安装外部系统 VPN。三网可用不等于三网同时在线，节点/网络并发按实际实现单独验证。

共用 profile/节点 registry 与可取消全双工字节流契约，provider 负责自己的原生接口、解析、身份与生命周期。原生句柄保持不透明；不能把三库都强制转换成同一种 OS fd。

## 参考实现与迁移边界

锁定 Heeler `bd837c7ede634ba86a3ba247c2d9198ed20dbf77`，依赖 native 1.0.3（`6a2817fc02aeb552df251d9478753c22fd4738bb`）。它已有三个 Swift provider 与桥实现，但 native 发布仅覆盖 iOS 18+ arm64 device/simulator；不是现成的五端 SDK。

- Tailscale 参考路径按配置管理 tsnet/state；Flutter wrapper 的单节点与 Windows 缺口另行处理，不能混同两种接口能力。
- EasyTier 参考路径为 smoltcp/no-TUN 的直接 TCP data plane，C ABI v2 返回 Unix socketpair 一端；当前桥仅 IPv4/网内 hostname，并明确不提供 SOCKS5、监听或为其他节点中继的服务。Windows 与其他 Unix 平台需要分别迁移平台代码。
- ZeroTier 参考路径为进程级 node、网络 join/leave 和逻辑 socket pump；不调用 `zts_node_stop`。离网、停用 profile、忘记身份与销毁 runtime 分开，不承诺统一 stop 行为。

原生 worker/pump 或非阻塞接口必须验证短写、背压、EOF、取消和关闭；不能靠“放 isolate”自动获得全双工，也不能承诺 isolate 隔离 native crash。loopback TCP 仅是可验证的内部桥候选，不引入公共 SOCKS 服务。

## 许可与发布

代码复用逐件审查：Heeler 与 native glue 的许多部分为 Apache-2.0，EasyTier bridge 为 LGPL-3.0-or-later，libzt fork 及其 ZeroTierOne 子模块需按锁定版本分别记录。公开开源不代替依赖声明、对应源码和实际适用的重链接/安装说明；本 ADR 不作整体分发合规保证。

[Heeler Overlay 说明](https://github.com/ZingerLittleBee/Heeler/blob/bd837c7ede634ba86a3ba247c2d9198ed20dbf77/Packages/HeelerOverlay/README.md)、[native 构建与许可](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/README.md#licences)、[锁定依赖](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/sources.lock)。

## 验收

三网各自关闭外部系统 VPN，验证节点、SSH 信任、herdr RPC/observe/输入、取消、离网与恢复。五端均记录真实构建、运行、凭据存储和包体/内存开销；拿到虚拟 IP 或 iOS 参考代码不算本项目通过。

平台未通过某 provider 时准确标记实验/未支持，不能自动用系统 VPN 替代。支持矩阵与完成标准以 [ADR-0006](0006-three-overlay-providers.md)、[产品设计](../05-product-design.md)和[路线图](../04-roadmap.md)为准。
