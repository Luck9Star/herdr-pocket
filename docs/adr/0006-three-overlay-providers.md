# ADR-0006 · Tailscale、EasyTier、ZeroTier 三网络集成

状态：已接受架构与集成目标（2026-10-29）；当时本项目尚无运行验证。2026-10-30 已有验证壳、部分原生编译/加载与实验修复记录，见[当前验证记录](../09-prototype-validation.md)及[修复记录](../10-blocker-repair.md)。这些不等于 overlay 入网或 GUI 集成；Tailscale / EasyTier / ZeroTier 的 15 格单网与 20 格并发运行矩阵仍未验证。

## 范围变更

用户明确要求 EasyTier 必做，并参考 Heeler 将三种网络一起纳入设计。因此，本 ADR 更新 ADR-0003 原先“首发只做 Tailscale”的范围，补充 ADR-0004/0005 的发布矩阵；userspace、五端统一产品、公开开源、首版仅连接远端和既有输入可靠性规则继续有效。原 Flutter 框架选择现由 [ADR-0001](0001-single-flutter-stack.md)重新开放 A/B，不改变本 ADR 的三网目标。

**Tailscale 与 EasyTier 是每个正式支持平台的核心必需能力；ZeroTier 同步纳入首版集成目标，不放长期 backlog。**三网五端是完整目标，不把当前参考代码当作 15 个组合已经支持。

## 已核实参考与复用边界

| 项目 | 锁定证据 | 可借鉴与限制 |
| --- | --- | --- |
| Heeler | `bd837c7ede634ba86a3ba247c2d9198ed20dbf77` | 已有三 provider Swift 抽象、节点 registry 与路由设计；所选框架均需迁移共享语义，不能直接使用 Swift 生命周期作为五端实现 |
| heeler-overlay-natives | v1.0.3 / `6a2817fc02aeb552df251d9478753c22fd4738bb` | Go/C/Rust 桥与构建记录可逐件评估；已发布 slice 仅 iOS 18+ arm64 device/simulator，macOS 构建宿主不等于发布支持 |
| EasyTier 参考依赖 | `728ba94b5029240add6204eed591f22e4e039e6b` | 2.7.0 开发提交，不标成正式 2.7.0 release；no-TUN smoltcp data plane 与桥需一起锁定 |
| libzt 参考依赖 | fork `7e5d0f99a2de81c45faa28e44289bcd19d933bf2` | 必须连同 sources.lock 中的 ZeroTierOne、补丁与构建选项审查，不能用另一个上游 main 的许可代替 |

来源：[Heeler Overlay](https://github.com/ZingerLittleBee/Heeler/blob/bd837c7ede634ba86a3ba247c2d9198ed20dbf77/Packages/HeelerOverlay/README.md)、[native README](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/README.md)、[sources.lock](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/sources.lock)。这些是参考源码证据，不是本项目双向数据传输、后台或打包的实测。

## 统一契约，保留 provider 差异

共享层只消费可全双工读写、有背压、支持 deadline/取消请求及明确 EOF/错误的 TCP 字节流。底层 handle 不透明，适配所选 SSH 库后仍走相同的 host key、SSH 认证、herdr session、RPC/事件/observe 和禁止写入重放规则；`SSHSocket` 是 DartSSH2 候选的接口，不是框架无关契约。不增加第二套远端协议。

NetworkProfile 记录 provider、配置、身份/秘密引用和能力；Host Route 引用 profile。registry 依据 provider 规则映射实际 node/runtime，Host 只拥有流的 lease。按需启动并限制资源，不默认将三网全常驻；需要用户认证的配置不在 route 竞速中自动触发登录。

用户已确定首版前台可以通过不同 provider 同时连接多台主机。Tailscale + EasyTier 并发是核心最低验收，声明 ZeroTier 支持的平台还须验证 Tailscale + ZeroTier、EasyTier + ZeroTier 与三者同开；这不承诺任意同 provider 多身份，也不要求未使用的节点空转。

| Provider | 参考节点/数据流语义 | 必须在本项目验证 |
| --- | --- | --- |
| Tailscale | 原生 tsnet 按配置实例/state；现有 Flutter wrapper 单进程单节点且 POSIX-only | 自建桥或 wrapper 的真实平台/身份限制；Windows 路径；持久身份与受保护存储 |
| EasyTier | 按网络 UUID 的实例 key；参考桥最多 32 key，不作为本产品并发承诺。直接 TCP data plane 经 Unix socketpair 暴露，当前仅 IPv4/网内 hostname；不提供 SOCKS5、监听或为其他节点中继的服务 | FFI/字节流桥、取消与超时、start/stop barrier、平台构建及地址族限制；保留 no-TUN 直接拨号路径 |
| ZeroTier | 进程级 node、网络 join/leave；逻辑 fd 由单 owner pump 转 OS socketpair；参考实现不调用 `zts_node_stop` | node/网络/流所有权；离网与忘记身份区别；逻辑 fd 并发限制；重叠网络定向、身份切换和需要重启的场景 |

这里“不提供中继服务”指 App 不充当其他节点的转发/出口，不保证客户端连接路径永不经过网络的中继节点。

EasyTier 代码依据：[直接 TCP 与 UnixStream::pair](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/native/easytier/src/lib.rs#L509-L569)。Unix socketpair 和 Apple 专用选项不能直接外推到 Windows/Linux；各端可采用适配后的 native 字节流或受控 loopback TCP 桥，不引入公共 SOCKS 服务。

**取消请求与底层清理分开。**取消立即使连接 attempt 失效、禁止成为胜者；若 native connect 不可主动打断，则等待其有界超时/返回并清理迟到流。该清理过程仍占资源预算，不能因 UI 已返回而无限新增后台尝试。不能将参考实现“connect 返回后检查取消”称为原生可中断 API。

流关闭可幂等等待；停用 profile、离开网络、删除身份与销毁 runtime 是不同操作。ZeroTier 等进程级 runtime 可能保留到应用退出，必须解释实际行为；不能为了统一接口强行调用不安全的 node stop。普通错误限制在相关 profile/流，但同进程 native 崩溃可能影响整个 App，isolate 不提供进程级崩溃隔离。

网络内名称和地址族由所选 provider 的已验证能力解释，不静默改用系统 DNS 或另一网络。profile 标签只是路由选择证据，**不证明底层已能定向重叠网段**；API 无法保证正确接口时禁止该并发组合，要求显式切换。单网可用、多配置保存、三网并发及同 provider 多身份是分开的能力。

## 五端十五格

下表全部是本项目**待验证**。iOS 的 Heeler 参考实现不能将本项目 iOS 格提前变成通过；其他平台也不能从库宣传或构建成功推断可用。

| 客户端 | Tailscale（核心必需） | EasyTier（核心必需） | ZeroTier（同步集成） |
| --- | --- | --- | --- |
| iOS | 待验证 | 待验证 | 待验证 |
| Android | 待验证 | 待验证 | 待验证 |
| Windows | 待验证 | 待验证 | 待验证 |
| macOS | 待验证 | 待验证 | 待验证 |
| Linux | 待验证 | 待验证 | 待验证 |

每格需验证：原生构建/加载、受保护身份保存、节点进入网络、profile 定向、SSH 信任、RPC/observe/输入、取消/迟到清理、离网、切网与后台或休眠恢复，以及实际安装产物。无公开入站路径且外部系统 VPN 关闭时完成链路；获得 IP、只 dial 成功或套用系统 VPN 均不算完整通过。

跨 provider 并发作为首版门槛单独记录，不能用上述 15 个单网格代替。至少覆盖 Tailscale + EasyTier 同时连接、一个 provider 出错/离网时其他有效 lease、重复虚拟 IP 定向、资源压力与恢复；声明 ZeroTier 支持的平台还验证 TS+ZT、ET+ZT 与三者同开，不能以顺序逐网连接代替。同 provider 多身份上限另记，未验证不得暗示支持；底层不能安全定向的重叠地址组合拒绝启用并解释限制。

- 平台核心目标完成：基础 UI/终端/安全存储/打包均通过，且该平台 Tailscale + EasyTier 两个单网格与前台并发验收通过。
- 五端核心目标完成：五端上述基础门槛、10 个核心单网组合及各平台 Tailscale + EasyTier 前台并发全部通过。
- 完整三网五端完成：基础门槛与全部 15 格通过，并完成上述必需跨 provider 组合的独立并发验收；不能以单网通过替代。
- 预览可先发布已验组合，但明示实验/未支持项；不能以删掉 EasyTier 或把 ZeroTier 移到长期后续来宣称完成原目标。

## 许可与公开构建

三网 native 构建优先运行于云端目标系统 runner，按源提交、子模块、补丁、工具链、构建选项和目标 ABI 生成受控版本产物；App 只消费来源与校验和匹配的库。少变 native 库不必随每次 UI 修改重编，缓存仅作加速，不能成为唯一依赖来源或发布证明。Heeler iOS device/simulator slice 不覆盖 macOS 或其他平台；Windows cgo/MSVC 互链、Android NDK/API/ABI 与预编译库、Linux 运行基线仍须实际验证，详见[云端构建与测试分发](../07-build-and-release.md)。

参考仓库 root 与许多 glue 部分为 Apache-2.0，`native/easytier` 为 LGPL-3.0-or-later，实际 EasyTier 依赖另按锁定提交核对。参考 libzt fork 的 LICENSE 记载 Change Date 2026-01-01 与 Apache-2.0 变更许可；ZeroTierOne core 有自身 MPL-2.0 条件，nonfree 是否纳入必须以本项目真实构建清单确认，不能只看 root LICENSE。

复用时保留对应来源、补丁、许可证与声明，并为本项目实际分发物准备适用的对应源码、重链接材料或安装说明。Heeler 提供这些材料不等于本项目自动满足；公开开源也不替代逐组件审查。本轮不生成最终 LICENSE 或宣称整体分发合规。[native 许可说明](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/README.md#licences)。

参见[架构](../02-architecture.md)、[产品设计](../05-product-design.md)、[路线图](../04-roadmap.md)和[共同可靠性边界](0004-mvp-reliability-boundaries.md)。
