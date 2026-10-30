# 调研依据与复核（2026-10-29）

本文区分原调研记录、2026-10-29 上游核对与后续项目验证。**2026-10-29 基线只有设计文档；2026-10-30 的验证壳、云构建和有限 macOS 实测见[验证记录](09-prototype-validation.md)。** 下文“本轮”指2026-10-29的文档核对，没有操作用户的 herdr 会话、网络配置或凭证。

## 1. 能支持的结论

1. 项目目标已明确为公开开源的 iOS / Android / Windows / macOS / Linux 统一 GUI，手机优先、桌面紧随；首版五端均控制远端 herdr，本机接入后置。Flutter 改为第一验证候选，Tauri 2 + xterm.js + Rust 是手机终端 A/B 的主要挑战者；SSH streamlocal、herdr observe 和原生桥接不专属于 Flutter，依据见[技术评估](06-technology-evaluation.md)。
2. Flutter 的五端构建能力不代表 overlay 五端可用。Dart `tailscale` 0.9.0 明确不支持 Windows；Windows 适配必须单独验证，不能据此推断上游 tsnet 整体不可在 Windows 运行。
3. Tailscale / EasyTier / ZeroTier 全部进入设计与集成目标；每端正式支持至少通过 Tailscale + EasyTier，三网完整支持逐格验收。Flutter 路径先验证 MIT 候选 `terminal_view` 0.5.0，`xterm3` 因 AGPL 许可作为条件不同的备选；与 Tauri 路径使用相同手机正确性门槛，不能仅凭许可或平台标签定案。旧竞品调查不支持唯一或首创断言。
4. 产品范围、可靠性约束与验收分别以[产品设计](05-product-design.md)、[架构](02-architecture.md)和[路线图](04-roadmap.md)为准。

## 2. 2026-10-29 关键证据表

“上游已核对”只证明指定资料中的能力或约束，不代表本项目集成通过。

| 对象 / 版本 | 本次核对结果 | 对设计的影响 | 一手依据 |
| --- | --- | --- | --- |
| dartssh2 4.0.1 文档；源码 `cee26346527ba7cabaf9d3bf6215018553d748d3` | `forwardLocalUnix` 使用 `direct-streamlocal@openssh.com`；可自定义 `SSHSocket`。该转发方法在 2.14.0 已加入 | 选择 streamlocal；锁定实际依赖版本做互通验证，不能把“4.x 可用”写成“4.x 首次支持” | [API 源码](https://github.com/vicajilau/dartssh2/blob/cee26346527ba7cabaf9d3bf6215018553d748d3/lib/src/ssh_client.dart#L545-L557)、[SSHSocket](https://github.com/vicajilau/dartssh2/blob/cee26346527ba7cabaf9d3bf6215018553d748d3/README.md)、[变更记录](https://pub.dev/packages/dartssh2/versions/4.0.1/changelog) |
| herdr 0.9.5 文档；仓库快照 `bc8c28988f75c538d4ca058b702f5adbea30566e` | 普通 socket 请求读取一行、返回响应后结束；事件订阅走长连接 | 每普通 RPC 新开 streamlocal channel；`id` 仅关联响应，不使服务端支持复用或幂等 | [server.rs](https://github.com/herdrdev/herdr/blob/bc8c28988f75c538d4ca058b702f5adbea30566e/src/api/server.rs#L328-L519) |
| herdr 0.9.5 事件协议 | `events_lost` 关闭订阅；订阅确认后再读快照；快照与事件没有共享序列边界 | 事件用于使缓存失效并触发权威重读；重连只恢复当前状态，不能声称补齐事件历史 | [事件恢复](https://github.com/herdrdev/herdr/blob/bc8c28988f75c538d4ca058b702f5adbea30566e/docs/versions/0.9.5/website/src/content/docs/socket-api.mdx#L793-L817) |
| herdr 0.9.5 observe / 输入 | observe 输出 NDJSON ANSI 帧且不取得输入 / 尺寸控制权；EOF 不一定有 `terminal.closed`。`agent.prompt` 的成功只确认写入，blocked 时拒发 | 读取与输入分离；结果不明的写操作不重放；不把 prompt API 当成结构化审批接口 | [CLI](https://github.com/herdrdev/herdr/blob/bc8c28988f75c538d4ca058b702f5adbea30566e/docs/versions/0.9.5/website/src/content/docs/cli-reference.mdx#L359-L405)、[帧导出](https://github.com/herdrdev/herdr/blob/bc8c28988f75c538d4ca058b702f5adbea30566e/src/client/terminal_sessions.rs#L129-L159) |
| 上游 tsnet | 每个 `Server` 是一个节点，可在进程内运行多个独立节点，状态由各自目录保存 | “节点”与“网络”分开建模；是否支持多节点还取决于绑定层 | [官方 tsnet 文档](https://github.com/tailscale/tailscale/blob/main/tsnet/README.md) |
| Dart `tailscale` 0.9.0 | 包 API 为单进程单节点；声明 iOS / Android / macOS / Linux，**Windows 不支持**。Android 持久身份要求 API 31+；Linux 要求 `secret-tool` 和已解锁 Secret Service，Apple 使用 Keychain。另有 Dart / Flutter / Go 与备份、日志要求 | 不能作为五端唯一绑定；验证 Windows 候选桥及各平台身份存储，不从 tsnet 或 Flutter 能力外推 wrapper | [包文档](https://pub.dev/packages/tailscale/versions/0.9.0)、[节点 API](https://pub.dev/documentation/tailscale/0.9.0/tailscale/Tailscale-class.html) |
| libzt `a707ea6ae0910efdc1125d04758c411e2e9ea4f9` | 根许可文件包含 BSL 1.1、Change Date `2026-01-01`、Change License `Apache-2.0`；README 的概述仍写 BSL | 当前已过该日期，不能仅凭“BSL”标签排除商业方案；必须继续核对实际锁定版本、子模块、补丁和分发物，不据根文件作完整许可结论 | [精确许可文件](https://github.com/zerotier/libzt/blob/a707ea6ae0910efdc1125d04758c411e2e9ea4f9/LICENSE.txt)、[子模块目录](https://github.com/zerotier/libzt/tree/a707ea6ae0910efdc1125d04758c411e2e9ea4f9/ext) |
| Heeler 仓库快照 `bd837c7ede634ba86a3ba247c2d9198ed20dbf77` | 已核对三网络 Swift 层与 native 包 1.0.3；根许可 Apache-2.0，原生依赖另有许可 | 源码证明三条路径已有实现；下节列出 iOS 产物、跨平台迁移与复用边界，不作本项目运行结论 | [仓库](https://github.com/ZingerLittleBee/Heeler/tree/bd837c7ede634ba86a3ba247c2d9198ed20dbf77) |

### 2.1 五端 GUI 的框架与组件依据

本表保留 Flutter 路径的依赖核查，不再表示框架已定案；新一轮框架对照、终端成熟度与尚缺实证统一见[技术评估](06-technology-evaluation.md)。

| 对象 / 本次读取版本 | 上游声明 | 本项目裁决与证据限制 |
| --- | --- | --- |
| Flutter 文档 3.47 | 官方列出 iOS、Android、Windows、macOS 及指定 Linux 发行版 / 架构组合 | 五端共享产品和协议层；最低系统、CPU 架构与发布产物另行锁定。[平台表](https://docs.flutter.dev/reference/supported-platforms)、[桌面支持](https://docs.flutter.dev/platform-integration/desktop) |
| Flutter 桌面构建 | Windows 使用 Visual Studio C++ 工具链；macOS 使用 Xcode；Linux 使用 clang / CMake / Ninja / GTK 等 | 分别建立对应宿主构建与运行验证环境；一个 macOS 构建通过不能代表 Windows / Linux 已通过。[Windows](https://docs.flutter.dev/platform-integration/windows/setup)、[macOS](https://docs.flutter.dev/platform-integration/macos/setup)、[Linux](https://docs.flutter.dev/platform-integration/linux/setup) |
| dartssh2 4.0.1 | 包页面声明五个目标平台，纯 Dart SSH / SFTP | 平台标签不证明 herdr streamlocal、host key 回调、自定义 overlay 字节流在每端通过。[版本页](https://pub.dev/packages/dartssh2/versions/4.0.1) |
| terminal_view 0.5.0 | 包页面声明五端及 web，MIT；解析器、缓冲与 Flutter 绘制分离，基准不含绘制 | **Flutter 路径的首轮终端候选**；同一套 IME、键鼠、TUI、恢复与性能门槛逐端验收。没有将上游声明变成已验收结论。[发布者页面](https://pub.dev/packages/terminal_view) |
| xterm3 6.3.7 | 包页面声明五端及 web；6.0.0 起为 AGPL-3.0-or-later。113.4 MiB/s 来自 6.3.0 在 M1 Pro / macOS 上的 headless core AOT 基准 | 作为许可条件不同的备选；项目公开开源不自动解决许可兼容，基准不是五端 GUI 帧率或端到端测量。[发布者页面](https://pub.dev/packages/xterm3) |

Context7 对 Flutter 与上游 tsnet 提供了匹配资料；对 xterm3 返回原始 xterm.dart，对 terminal_view 未返回匹配库。本表后两项因此直接核对对应发布者包页面，未将原始库的文档或许可套用给 fork。

五端首版均通过 SSH 控制已有远端 Unix herdr 主机；客户端运行在 Windows 不代表已支持 Windows 本机 named pipe、WSL 安装或本机进程管理。Tailscale 网络可能使用控制服务或中继；“无自建主机 relay”不表示“没有第三方网络服务”或“数据必定点对点直连”。

### 2.2 Nerd Font 与 shell 主题兼容性

2026-10-29 经 Context7 `library` → `docs` 查询 Nerd Fonts，并核对以下官方资料。远端 shell / 主题生成字符和 ANSI，herdr 与客户端终端处理屏幕及 cell，客户端字体负责绘制；仅在远端安装字体不能解决 App 的缺字。兼容对象应记录具体主题与配置，不能把 Oh My Zsh 名称当成统一字体需求。本轮没有下载、安装字体或修改 shell 配置。

| 依据 | 已核对内容 | 本项目决策 |
| --- | --- | --- |
| [Oh My Posh 字体文档](https://ohmyposh.dev/docs/installation/fonts) | 字体应配置在运行终端 UI 的主机；文档推荐 Meslo，具体列出 Meslo LGM NF | App 应自行确定可用字体与 fallback，不能依赖远端字体安装；OMP 主题作为 fixture 来源 |
| [Powerlevel10k 字体说明](https://github.com/romkatv/powerlevel10k#fonts) | 推荐 MesloLGS NF 的 Regular / Bold / Italic / Bold Italic | 作为 p10k 对照候选；不与 OMP 的 Meslo LGM NF 混为同一文件，也不自动修改远端主题 |
| [Nerd Fonts FAQ](https://github.com/ryanoasis/nerd-fonts/wiki/FAQ-and-Troubleshooting)、[代码点表](https://github.com/ryanoasis/nerd-fonts/wiki/Glyph-Sets-and-Code-Points) | Mono / NFM 面向单格字宽；普通 NF 图标可能更宽，Propo 用于比例字体场景。图标包含 Powerline PUA 与 U+FFFF 以外的代码点 | 优先比较 Meslo 候选的 Mono 变体与主题推荐字体；锁定字体发行版及主题代码点映射后才确定默认，不把“能显示图标”等同于宽度正确 |
| [Unicode UAX #11](https://www.unicode.org/reports/tr11/) | East_Asian_Width 需要按终端场景调整，不能直接当作完整终端宽度算法 | 记录远端 / herdr / 客户端所用 Unicode 与 `wcwidth` 版本或策略，验证歧义宽度、组合字符和 emoji；不是要求强制升级远端 Unicode 版本 |
| [Nerd Fonts 许可审计](https://github.com/ryanoasis/nerd-fonts/blob/master/license-audit.md)、[根许可](https://github.com/ryanoasis/nerd-fonts/blob/master/LICENSE) | 基础字体与图标来源分列，使用多种许可；Meslo LG 条目为 Apache-2.0，不代表任何打包后的 Meslo 文件只适用这一许可 | 发行前锁定实际字体文件、版本、哈希、样式、基础字体 / 补丁 / 图标来源及声明；不把 p10k 主题许可或 font-patcher 的许可当成字体许可 |

终端 spike 需加入同一组五端 fixture：p10k / OMP 提示符、Powerline 拼接、PUA 与补充平面图标、中英文混排、组合字符 / emoji、粗斜体、光标定位、换行和缩放。缺字、裁切、错位与 fallback 后网格漂移分别记录；herdr 已渲染的屏幕宽度错误不能靠客户端换字体保证修复。默认内置字体、CJK fallback 与用户字体导入仍须在许可和真实渲染通过后裁定。

### 2.3 Heeler 三网络源码复核

2026-10-29 根据三网络目标，读取 Heeler 上表固定提交的 Swift / C 源码，以及它精确依赖的 `heeler-overlay-natives` **v1.0.3 / `6a2817fc02aeb552df251d9478753c22fd4738bb`**。Context7 已执行 EasyTier `library` → `docs`；其当前 main 文档不能代替以下固定版本证据。本次仅下载文本源码到临时目录，未构建、启动节点、读取凭证或复制实现到本项目。

| 路径 | 固定源码中的实现 | 可复用方向与限制 |
| --- | --- | --- |
| Tailscale | libtailscale `d1dc45d…` / tailscale.com v1.104.1；每个配置独立 tsnet 和状态目录，TCP dial 返回 OS socketpair；超时 / 取消后返回的迟到 fd 会关闭 | 可移植 Go / C 桥并重写 Dart 生命周期；不是 Dart `tailscale` 0.9.0 单节点包已经具备多节点。[Swift dial](https://github.com/ZingerLittleBee/Heeler/blob/bd837c7ede634ba86a3ba247c2d9198ed20dbf77/Packages/HeelerOverlay/Sources/HeelerOverlay/TailscaleNode.swift#L105-L134) |
| EasyTier | 2.7.0 **开发提交** `728ba94b…` 加补丁；C ABI v2 用 instance key 隔离，最多 32 个 key。`data_plane_tcp_connect` → Unix socketpair → 双向 pump；目标是 IPv4 / 网络内 hostname。强制 no-TUN、仅主动连接，拒绝 SOCKS5 和监听等配置 | 已有直接 TCP 桥可按 LGPL 条件移植；不是“no-TUN 必须经 SOCKS5”，也不是任意协议 VPN。Windows 需替换 Unix socketpair 接口；Linux 等也须处理 Apple 专用 socket 选项。[TCP 实现](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/native/easytier/src/lib.rs#L509-L569)、[C ABI](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/native/easytier/include/heeler_easytier.h)、[出站策略](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/native/easytier/src/lib.rs#L241-L304) |
| ZeroTier | fork libzt `7e5d0f9…` + ZeroTierOne `fc5c3ec…` 与补丁；单进程单 node，network join / leave；每 dial 绑定 network 接口。libzt 是 lwIP 逻辑 socket，Heeler 用单线程 C pump 转 OS socketpair并处理半关闭 | 可移植 C pump 和网络绑定设计；不能把 libzt 句柄直接当系统 fd。Heeler 不调用 `zts_node_stop`，退出网络与销毁运行时必须分开建模。[dial / release](https://github.com/ZingerLittleBee/Heeler/blob/bd837c7ede634ba86a3ba247c2d9198ed20dbf77/Packages/HeelerOverlay/Sources/HeelerOverlay/ZeroTierNetworkNode.swift#L131-L171)、[pump](https://github.com/ZingerLittleBee/Heeler/blob/bd837c7ede634ba86a3ba247c2d9198ed20dbf77/Packages/HeelerOverlay/Sources/CHeelerOverlaySupport/OverlayPump.c) |
| 平台与构建 | native 发布清单只有 iOS 18+ 的 arm64 iPhoneOS / iPhone Simulator XCFramework；脚本固定上游、补丁、工具链与校验和 | macOS 是构建宿主，不等于有 macOS SDK slice；四个非 iOS 目标均须另做产物和运行验证。构建 / 测试脚本存在不代表本项目已复跑。[发布清单](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/Package.swift)、[构建依据](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/README.md#building)、[来源锁定](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/sources.lock) |

Heeler 的 [OverlayNetworkRuntime](https://github.com/ZingerLittleBee/Heeler/blob/bd837c7ede634ba86a3ba247c2d9198ed20dbf77/Sources/Heeler/Overlay/OverlayNetworkRuntime.swift) 按网络 UUID / revision 退休旧实例，并等待旧 stop 后再替换；EasyTier 按 key 串行化 start / stop 与进行中的 dial。可以复用隔离与资源所有权规则，但不能要求所有 provider 都有同样的节点、取消或 logout 语义。客户端统一层应暴露 TCP 字节流，接入所选 SSH 实现；Flutter / Dart 路径可适配 `SSHSocket`。POSIX fd、lwIP 句柄和 Windows 原生句柄留在各自桥内，背压、取消、半关闭及资源释放逐端验证。

**可按各组件许可复用 Heeler 代码，公开开源仍须满足分发义务。** Heeler 根许可为 Apache-2.0；native 仓库的构建脚本、Tailscale / ZeroTier glue 也声明 Apache-2.0，复制或改写须保留适用许可、版权和修改声明。`native/easytier` 明确是 LGPL-3.0-or-later，所链接 EasyTier 为 LGPL-3.0，需保留对应源码、补丁、构建与适用的重链接 / 安装资料；公开开源有利于满足这些要求，但应生成本项目的材料，不能照搬 Heeler 安装说明作为履约证明。该 libzt fork 的固定许可同样写有 2026-01-01 → Apache-2.0 转换；ZeroTierOne core 与修改仍有 MPL-2.0 义务，不能用根 Apache 标签覆盖。依据：[分组件许可](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/README.md#licences)、[EasyTier wrapper 声明](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/native/easytier/NOTICE.txt)、[固定 libzt 许可](https://github.com/Ylarod/libzt/blob/7e5d0f99a2de81c45faa28e44289bcd19d933bf2/LICENSE.txt)。最终项目许可证尚未裁定，本轮未引入这些代码。

未固定 commit 的文档链接只表示本次阅读时内容；最终依赖锁定时应保存包版本、源码哈希、schema 和许可证清单。上面的 herdr 源码快照与 `docs/versions/0.9.5` 是本次阅读依据，不等同于已经验证任意本地 0.9.5 二进制的行为。

### 2.4 云端构建与分发依据

2026-10-29 经 Context7 对 GitHub Actions 执行 `library` → `docs` 并核对官方资料：可把 Android / Linux、Windows、Apple 构建分别放到相应 hosted runner，本地完整 SDK 按调试需要选装。标准 runner 的 public 仓库计算免费不代表 larger runner、存储或发行账户全部免费；具体价格 / 额度不固定进本设计。[官方 runner 表](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)、[计费边界](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

已选择 CI 检查 / 临时产物与受信签名 / Release 分层，fork PR 不取得分发秘密，缓存不存凭据或节点身份。native、GUI 与一次性主机 helper 分开产出，附来源、补丁、许可与构建清单；五端构建成功不代替安装、运行、三网或真机输入验收。具体流程和来源见[云端构建与测试分发](07-build-and-release.md)。本次只核查并补设计，没有创建 workflow、编译、签名、上传或安装测试包。

## 3. 原调研：herdr 对客户端暴露的面

以下来自仓库原有记录，**本次未重跑**。记录标注 herdr 0.9.5 / protocol 22，但未随仓库保存完整原始日志、二进制哈希或 schema 文件；仅保留为原型输入。

### 3.1 原记录中的 socket

```text
client: version 0.9.5 / protocol 22
server: running, endpoint_compatible yes
        socket: ~/.config/herdr/herdr.sock
```

这是原记录中 Unix 主机的默认 session 路径，不是所有平台或命名 session 的统一路径；上游 socket 文档还列出 Windows named pipe。首版 Unix 主机应显式选择 session / socket，observe 使用同一目标，不能在重连时悄悄落回 default。

| 路径 | 做法 | 主机前提 | 本项目决策 |
| --- | --- | --- | --- |
| SSH streamlocal | SSH channel 指向指定 Unix socket | sshd 允许相应转发、用户有 socket 权限、herdr 已运行 | 主路径；每普通 RPC 一 channel |
| SSH exec + 转发器 | socat / python 桥接 socket | 额外工具或脚本 | 首版不提供 |
| 主机 relay | socket 转为 HTTPS + WebSocket | 常驻进程、端口、认证与运维 | 后续另行论证，不属于 MVP |

observe 仍需要远端 herdr CLI；“不加主机转发器”不等于没有主机前提。

### 3.2 原记录中的终端探测

原文称使用一次性 probe workspace，并在结束后恢复 workspace 数量；本次未验证该过程。记录的帧形状为：

```json
{"type":"terminal.frame","seq":1,"full":true,"width":80,"height":24,"encoding":"ansi","bytes":"<base64 ANSI>"}
{"type":"terminal.frame","seq":2,"full":false,"width":80,"height":24,"encoding":"ansi","bytes":"..."}
```

- 无 TTY 的 `observe wF:p1 --cols 80 --rows 24` 在三秒内收到全量与增量帧。
- `pane send-text` 后在后续渲染中观察到文本。
- 对普通 shell pane 调用 `agent send-keys` 返回 `agent_not_found`。

本次上游资料支持 observe / pane 与 agent 的基本分工，但 **seq 是否连续、full 对屏幕和解析器的完整恢复语义仍需固定版本 fixture / spike**。不要把旧观察直接升级为跨版本协议保证。

### 3.3 方法面

公开 API 包括 `session.snapshot`、`workspace.*`、`pane.*`、`agent.*` 和 `events.subscribe`。`herdr api schema --json` 导出的是相应二进制内置 schema；实现时须同时记录客户端与运行服务端版本，按已验证能力开放 UI，不能仅因本地 schema 有某方法就假定远端支持。

## 4. 参考实现与许可的使用边界

原调研记录了 Heeler 的 streamlocal、userspace overlay、Host / Route 分离、配对和推送 ADR。本轮已对三网络及其生命周期和构建来源作上节限定的源码复核；配对、推送及其他竞品仍未全面复核，也没有完成 Heeler 真机测试，不能照搬安全或上架结论。

许可审查针对实际代码和分发物：

- tsnet、Dart 包、原生桥与其依赖分别记录许可，保留必要声明；不使用“随便用”的结论。
- EasyTier 的 LGPL 义务取决于所用版本、修改与链接 / 分发方式；一个独立 natives 目录或 tag 不能自行证明履约。
- ZeroTier 按表中的版本与生效日期继续审查，不预先排除，也不宣称已获得完整发行许可。
- 参考 GPL 项目的设计不等于复制其代码；若要引入实现，先确认项目许可与分发条件是否兼容。

**公开开源目标已确定，具体项目许可证尚未选择。** 公开发布前应锁定依赖来源、原生补丁、构建工具链及声明，说明源码如何构建对应产物，并建立逐平台支持 / 测试 / 发行矩阵；不能把仓库可见当成许可或构建可复现。此轮不创建 LICENSE、CI 或分发产物。

## 5. 进入开发前的验证缺口

1. **字节流桥**：三 provider × 五端从 overlay dial 到 SSH 的双向数据、背压、取消、半关闭、断线和资源释放；Windows 等非 iOS 绑定与产物是明确缺口。FFI 不代表零拷贝，单个 isolate 永久阻塞读取也不能完成全双工设计。
2. **终端与输入**：中文 IME、Unicode、桌面键鼠 / 快捷键、移动触控、复杂 TUI、全量恢复与中断输入。现已找到原文 `113 MiB/s` 的上游 headless 基准来源，但本项目未复跑，不能拿它作为 GUI 验收。
3. **身份与平台**：候选绑定的最低系统与架构、Keychain / Secret Service / Windows 候选存储、节点备份、退出登录与本地忘记身份的不同语义、日志上传设置。
4. **生命周期**：移动前后台、桌面休眠 / 唤醒、窗口关闭、网络切换与重连；移动首版接受回前台恢复，不承诺后台长连接或实时推送。
5. **分发**：签名、商店要求和第三方许可按最终产物另行验证。其他应用的上架记录不能证明本项目一定获批，文案应如实描述能力。

上述门槛以[路线图](04-roadmap.md)的 M0.5 验收记录收口；本轮没有执行这些测试。
