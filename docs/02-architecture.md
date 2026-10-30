# 架构与运行契约

状态：**2026-10-29 架构设计基线，尚非已完成产品**。2026-10-30 已有并行验证壳与有限实测，见[验证记录](09-prototype-validation.md)；下文“本轮”指原设计核查。上游协议以 herdr 0.9.5 为取证对象，历史本机记录保留在[调研文档](00-research.md)。

项目面向公开开源，统一交付 **iOS、Android、Windows、macOS、Linux** 客户端，**手机优先、桌面紧随**。Flutter 是第一验证候选，Tauri 2 + xterm.js + Rust 是同规格 A/B 的主要挑战者；框架尚未最终锁定，依据和定案门槛见[技术栈复评](06-technology-evaluation.md)。共享协议、连接状态和输入规则，手机与桌面使用自适应界面。

**Tailscale 与 EasyTier 为各正式支持平台的核心必需能力，ZeroTier 同步纳入首版集成目标**。三种网络分别适配，不把它们压成一个已支持开关。五端目标不等于当前已支持：协议、终端/IME、overlay、安全存储和打包按平台通过 M0.5 及后续验收，才能进入正式支持矩阵。产品行为见[产品设计](05-product-design.md)，阶段门槛见[路线图](04-roadmap.md)。

## 1. 分层与责任

```text
UI        按主机分组的看板 → 终端观察 → 显式完整终端输入
          手机默认任务辅助；快捷键栏与本地草稿作为辅助
          独立主机管理与连接设置
          多终端标签：手机切换；桌面侧栏、工作区与分屏
          共享交互语义；终端渲染器可替换
领域      Host / Route / Workspace / Tab / Pane / Agent
          每个 Host 独立状态仓库；保留来源、更新时间与连接状态
协议      herdr JSON 请求/响应；事件订阅；terminal.frame 解码
传输      每个已连接 Host 一个 SSH session
          普通 RPC：一请求一 streamlocal channel
          事件：独立常驻 streamlocal channel
          终端：每个可见 pane 一个无 PTY 的 observe exec channel
穿透      OverlayRegistry 管理节点；Host 使用连接 lease
          Tailscale / EasyTier / ZeroTier 三 provider
          NetworkProfile 记录网络配置；统一全双工 TCP 字节流
平台      iOS / Android / Windows / macOS / Linux adapters
          安全存储、生命周期、网络变化、窗口/键盘、权限与日志脱敏
```

以上 Host、generation、lease 等是**本客户端拟定的内部设计**，不是上游 API 新增字段。现有 herdr 方法与参数以固定版本 schema 为准，不假定它实现完整 JSON-RPC 2.0 或任意批量请求。

UI 线程不做同步原生阻塞。transport worker 负责 SSH、解析与有上限队列；原生 I/O 必须使用可取消的 worker/event loop 或非阻塞接口。Flutter isolate 或 Tauri 后端任务均须验证调度与流控，不能仅把同步 read 换个入口就认为读写、取消和关闭不会互相阻塞。

## 2. 选型决策及验证边界

| 层 | 当前决策或候选 | 开工门槛与边界 |
| --- | --- | --- |
| UI | Flutter 第一验证候选；Tauri 2 为 A/B 主要挑战者 | 手机先验证软键盘/IME/触控，桌面紧随；不能以桌面生态或平台列表判定胜出 |
| 状态管理 | Flutter 候选可先用 Riverpod | 业务模型独立于 Widget/WebView；实现选择不改变状态与输入契约 |
| SSH/core | DartSSH2 与 Rust/russh 分别验证，core 不绑定 UI | DartSSH2 `forwardLocalUnix` 自 2.14.0 已有；russh 亦有 streamlocal/exec/自定义流，均验证 host key 与关闭语义 |
| 终端 | Flutter 侧 `terminal_view` 0.5.0；Tauri 侧 xterm.js 6.0.0 | 使用同一手机 fixture 比较 IME、ANSI、触控、Nerd Font/cell 和负载；通过前不锁组件 |
| RPC | SSH `direct-streamlocal@openssh.com` | 普通请求一条 channel，不做 exec+socat/python 回退 |
| 实时终端 | SSH exec 运行 `herdr terminal session observe`，不分配 PTY | 依赖远端 herdr CLI、正确 socket/会话定位及 exec 权限；与 RPC socket channel 分开 |
| Overlay | Tailscale + EasyTier 核心必需，ZeroTier 同步集成 | 三 provider 共用 TCP 字节流契约；五端 15 个组合独立验收，不以系统 VPN 替代内置节点 |
| 生命周期 | 挂起、休眠或网络恢复后重新检查连接 | 手机后台与桌面最小化不是同一事件；按平台验证休眠/唤醒/退出，推送与托盘常驻后置 |
| 凭据 | 共享接口 + 各平台受保护存储 | iOS/macOS、Android、Windows、Linux 分别验证；安全存储不可用不落明文 |
| 接入与配置 | 手机首版扫码配对；五端本地配置与加密导入/导出 | 资料 QR 不等于 SSH 授权或 host key 信任；排除设备身份/秘密克隆，无云账号或常驻 relay |
| 发布 | 同一仓库，云端 CI 优先、分平台产物 | 构建、签名/安装、渠道分发和设备验收分别记录；本地工具按调试需要选装 |

`package:tailscale` 0.9.0 的公开契约是每进程一个节点，Android 持久身份有 API 31+ 门槛；原生 tsnet 可以运行多个 Server 实例，但不意味着该 Flutter 包也暴露此能力。state 目录应按**节点身份**隔离，不写成“一网络一个目录”。不能因为抽象接口支持多个 provider，就宣称任一平台可同时运行三套网络。wrapper 的平台列表与 Flutter 本身支持的目标平台必须分别核查；缺失的平台需要自建适配或保持实验状态。

`tailscale` 0.9.0 明确是 POSIX-only，**不支持 Windows**；这不代表原生 tsnet 整体没有 Windows 路径。Windows 需要自建 tsnet 桥等独立 spike；通过前只可发布标明实际已验组合的预览版，不能宣称 Windows 的 Tailscale 能力或五端三网齐备。Linux 的 wrapper 持久身份依赖 `secret-tool` 和已解锁的 Secret Service，须纳入安装与存储失败验收。

三网参考实现锁定为 Heeler `bd837c7ede634ba86a3ba247c2d9198ed20dbf77` 与 heeler-overlay-natives 1.0.3（`6a2817fc02aeb552df251d9478753c22fd4738bb`）。它提供三 provider 的设计证据，现成 native 产物仅 iOS 18+ arm64 真机和 arm64 模拟器；macOS 是构建宿主，不是已有 macOS SDK slice。Swift 生命周期需迁移为本项目设计，Go/C/Rust 桥按许可与平台限制评估复用，不能视为已经拿到五端 SDK。来源：[Heeler Overlay](https://github.com/ZingerLittleBee/Heeler/blob/bd837c7ede634ba86a3ba247c2d9198ed20dbf77/Packages/HeelerOverlay/README.md)、[native 构建与许可](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/README.md)、[锁定依赖](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/sources.lock)。

Flutter 侧优先验证 `terminal_view` 0.5.0（发布者声明 MIT、五端覆盖）；其解析/缓冲基准不含绘制，变更记录中的 SGR 4 能力与 iOS 回车/resize 选区修复进入回归 fixture。Tauri 侧 xterm.js 的手机触控/选择与系统 WebView 差异也必须实测，不能预判终端胜负。`xterm3` 6.3.7 自 6.0.0 起采用 AGPL-3.0-or-later；在用户希望衍生持续开源的方向下允许进一步评估，但仍需许可兼容审查与完整终端实测，不因此自动更换候选，也不锁旧 MIT 版本忽略维护风险。来源：[terminal_view 0.5.0](https://pub.dev/packages/terminal_view/versions/0.5.0)、[变更记录](https://pub.dev/packages/terminal_view/changelog)、[xterm3 6.3.7](https://pub.dev/packages/xterm3/versions/6.3.7)。完整 A/B 与证据见[技术栈复评](06-technology-evaluation.md)。

Rust core 可供 Flutter FFI 或 Tauri 使用，不将其网络收益算成 WebView 独占优势。Tauri 候选使用有界 raw binary Channel 与终端消费确认验证背压；Channel 分发成功不代表终端已消费，也不预先宣称零拷贝。两条路径均先过正确性，再以相同设备、字体/cell 和输出 fixture 测整 App 资源与输入延迟。

公开包页面与 API：[tailscale 包](https://pub.dev/packages/tailscale)、[Tailscale 类](https://pub.dev/documentation/tailscale/latest/tailscale/Tailscale-class.html)、[tsnet](https://pkg.go.dev/tailscale.com/tsnet)、[dartssh2 更新记录](https://pub.dev/packages/dartssh2/changelog)。这些链接用于技术取证，依赖版本、源提交和产物校验和仍须在 spike 中固定。

### 五端共享与适配边界

共享层拥有 Host 身份、能力协商、RPC/事件、终端帧、generation/epoch、输入草稿及不重放规则。平台层只实现原生字节流、安全凭据存储、窗口/键盘与生命周期入口，不能另造一套桌面协议或放宽输入确认。首版支持多个终端标签：手机切换标签，桌面可分屏同时观察；任何时刻只有一个明确获得输入焦点的目标，多终端可见不等于向多个目标广播输入。

按用户确定的范围，桌面首版只作为**远端 herdr 控制 GUI**。Windows 客户端通过 SSH 访问已支持的远端 Unix socket，不代表 Windows 本地 daemon、named pipe 或 WSL 已受支持。本机连接留待后续，本地 socket adapter 仅保留扩展位置，不进入首版 API 或验收。首版不安装、启动或管理本地 daemon/shell/WSL。

平台能力与发布门槛见 [ADR-0005](adr/0005-unified-mobile-desktop.md)，不能仅凭任一框架构建成功宣称完整五端支持。

## 3. Host 身份与 Route 连接

```text
Host：稳定的本地 ID、名称、SSH 用户、凭证引用、受信 host key 集合、routes
定位：选定 herdr session、对应 socket、显式 herdr CLI 路径
NetworkProfile：provider、本地 profileId、配置与秘密引用、节点状态
Route：地址、端口、可选 jump、可选 NetworkProfile 引用
Connection：generation、状态、当前 route、能力快照、活动 channels
```

RPC 与 observe 必须定位到同一个选定 herdr session；Host 下保存明确的 session/socket/CLI 组合，并在能力检查中核对。命名 session 重连不得静默落回 default；定位不支持或无法确认时进入 `needsAttention`。pane ID 仅在所属 session 内有意义，不能仅凭 `w1:p1` 一类短 ID 跨会话复用输入目标。具体 CLI 定位参数由固定版本 schema/帮助与 fixture 验证，不在此虚构上游选项。

NetworkProfile 与 Host 分开：多台主机可复用一个已配置网络，Route 不复制网络密钥。注册表以 `(provider, profileId)` 隔离配置/state，并按该 provider 的节点模型映射实际 runtime；相同虚拟 IP 不代表相同网络。profile 标签也不证明底层已能按正确接口定向；无法保证的重叠网段并发必须拒绝并要求显式切换。保存多个 profile 不代表能同时启动多个节点。overlay 仅承载 SSH 第一跳，存在 jump 时先到 jump，两个主机身份仍分别验证。

凭证引用不包含可进入日志的密钥内容。Host 身份独立于地址；LAN、私网和其他路由只有验证为同一受信主机，才允许归到同一个 Host。jump host 自身也独立验证 host key。

连接顺序：

1. 为本次连接分配新 generation；直连候选优先，已配置的 overlay/jump 可延迟启动。按需启动节点并限制并行尝试，不默认把三网全开。需要用户认证/配置的 profile 返回待操作状态，竞速不自动弹出多种登录。400ms 只是初始策略参数，需测量，不能决定身份信任。
2. 每个候选先完成 SSH host key 验证，**验证通过前不交付认证凭证**。首次连接展示指纹并明确建立信任；已有 key 不匹配时失败关闭，不能通过另一条地址自动接受新 key。
3. 完成用户认证，再检查 herdr 版本、所需能力与 socket 可达性。首个通过这些条件的候选可成为唯一活动连接。
4. 取消其他候选，关闭其 socket/channel。每个异步结果都核对 generation；迟到的旧结果只能清理资源，不能覆盖新连接。
5. 普通网络失败可以尝试另一条已配置 route；身份冲突须单独展示并阻止静默降级。显式重新信任主机是独立用户动作。

初始状态机为客户端设计：`disconnected → connecting → verifying → authenticating → checking → ready`。断线进入 `reconnecting` 并保留标记为 stale 的旧视图；身份变化、凭证缺失、overlay 登出等进入 `needsAttention`，不能无限重试。连接失败、socket 不存在和方法不支持分别展示，不统称“网络断开”。

## 4. 三 provider 的字节流与资源所有权

统一契约是**可取消、带背压的全双工 TCP 字节流**，再适配所选 SSH 库（DartSSH2 候选为 `SSHSocket`，russh 候选为异步读写流）；不把底层句柄定义成 POSIX fd。以下对象和能力都是客户端设计，不是现成库 API。

| 对象/操作 | 必须保证 |
| --- | --- |
| NetworkProfile | provider、配置和秘密引用独立；Host Route 只引用，不拷贝身份 |
| 节点 registry | 按 provider 的单例/多实例规则管理 runtime；保存配置、启用节点和加入网络分别处理 |
| capabilities | 明确当前平台的地址族、网络内解析、节点/网络并发及身份操作限制；未知不能当已支持 |
| dial | 接受 deadline/取消请求和选定 profile；返回不透明字节流；取消使 attempt 立即失效，native 不可中断时等待有界返回并清理迟到流 |
| read/write | 正确处理短写、EOF、错误与背压；单 owner/pump 或非阻塞机制保证读不阻塞写与取消 |
| stream close | 幂等，解除等待读写，回收该流的 native handle、缓冲区和桥；可等待关闭完成 |
| lease | Host/route 仅释放自己拥有的流；不得停止别的 Host 或其他网络的有效节点 |
| 停用/离网/忘记身份 | 各自定义影响范围；底层 runtime 是否可销毁按 provider 能力处理，不能统一承诺 `stop` 等于销毁进程节点 |

取消后仍在等待 native 返回的尝试继续占资源预算，不因 UI 已取消就无限新建。参考 EasyTier 在 connect 返回后检查取消，不是已证实的原生即时中断 API。

网络内域名由选定 profile 的能力解析；不支持时明确报错，不静默改用系统 DNS、另一网络或另一条同 IP 路由。路由失败可尝试用户已配置的其他可信路线，但每条仍须通过原有 host key、session 和能力检查。

| Provider | 参考实现的真实边界 | 本项目适配要求 |
| --- | --- | --- |
| Tailscale | 原生 tsnet 可按配置独立实例/state；现有 Flutter wrapper 限每进程一个节点且无 Windows 支持 | 选定 wrapper/自建桥后公开实际限制；不能将原生多实例自动算作 wrapper 能力 |
| EasyTier | no-TUN smoltcp data plane；C ABI v2 直接拨 TCP，以 Unix socketpair 暴露字节流；当前桥仅 IPv4/网络内 hostname，不提供 SOCKS5、监听或为其他节点中继的服务 | 作为核心集成；保持直接 TCP 路径，抽离 Unix/Apple 平台假设；IPv6等能力未证实时明确不支持 |
| ZeroTier | 进程级 node，按网络 join/leave；逻辑 socket 经单 owner pump 转为 OS socketpair，重叠地址需网络接口归属 | 不能把 libzt handle 当 OS fd；退出网络不等于销毁全局 node；切换/忘记身份的重启要求单独验证 |

Heeler 的 Unix socketpair 是参考桥内部实现，不能直接外推 Windows。各平台可通过 native 字节流回调或受控 loopback TCP 桥实现同一契约；不为此暴露 SOCKS 服务，EasyTier 也不改走与参考路径不同的 SOCKS 架构。若使用 loopback，必须只绑定本机、短生命周期、验证连接归属/鉴权并关闭未授权接入，不能成为公开网络端口。FFI 仍有转换与生命周期成本，不预先承诺零拷贝。

普通网络/鉴权/取消错误应限定到相关 profile、node 或 stream，不重置其他 provider。三个 native runtime 默认共处后端进程，native 崩溃可能使整个应用或后端退出；Dart isolate 或 Rust task 都不能提供进程级崩溃隔离。资源预算和故障注入覆盖单网、切网、其他网络有活动 lease 时的离网，以及首版跨 provider 并发。

**首版前台支持通过不同 provider 同时连接多台主机**，Tailscale + EasyTier 并发是核心最低验收；声明 ZeroTier 支持的平台还须验证 Tailscale + ZeroTier、EasyTier + ZeroTier 与三者同开，并公开结果。按需启动实际使用的节点，不要求未使用的三网空转。单网可用、多配置保存、跨 provider 并发与同 provider 多身份在线是不同能力，不承诺任意同 provider 多身份并发。

各组合须验证身份/秘密隔离、取消与故障不连带关闭其他有效 lease、总资源预算及恢复。重复虚拟 IP 或重叠网段必须有实际接口/路由定向证据；只有 profile 标签不算通过，无法保证时拒绝该组合并解释需要显式切换。15 个单网格通过不能代替并发验收。

每层设置有限缓冲区和并发上限：节点启动、route attempts、RPC channels、待解析字节、待渲染帧、输入草稿均要有预算。具体数值由 M0.5 确定并纳入 fixtures/验收。积压超预算时取消并重新同步；不能任意丢弃终端增量后继续渲染。进程级 runtime 的受控保留资源与泄漏分开记录；应用退出时执行各库允许的清理流程。

五端 15 格支持矩阵、源版本与许可边界见 [ADR-0006](adr/0006-three-overlay-providers.md)。

## 5. RPC 与事件恢复

普通 RPC 每请求打开一个 streamlocal channel，发送一个请求并读取对应响应后关闭。请求 ID 仅用于关联、诊断与拒绝迟到响应；**不提供服务端幂等保证，也不意味着可复用 socket**。合并相同读取需求、限制并发可以减少开销；不合并或重排写操作。

事件订阅按 herdr 0.9.5 的恢复模式：

1. 独立 channel 订阅 `events.subscribe`，等 `subscription_started`。
2. 另开 channel 读取 `session.snapshot`，建立当前状态。
3. 事件作为“对应状态可能已变化”的通知，触发权威读取。快照与事件没有共享的序列边界，不能无条件回放缓冲事件覆盖快照。
4. 收到 `events_lost` 或订阅断开，重订阅并重读快照。恢复的是当前状态，不承诺补齐离线历史。

前台可做去抖与低频兜底读取；任何“30s 刷新”都只适用于前台活动连接。移动后台不依赖周期性 SSH 轮询。回前台、桌面系统唤醒或网络恢复时重新验证连接、订阅与快照，不能沿用“最后一次在线”作为现在在线。桌面最小化可在进程仍运行时继续连接，但不作为后台保活保证；退出时取消所有任务并释放资源。

上游依据：[herdr 0.9.5 socket API（固定源码提交）](https://github.com/herdrdev/herdr/blob/bc8c28988f75c538d4ca058b702f5adbea30566e/docs/versions/0.9.5/website/src/content/docs/socket-api.mdx)。M0.5 需要保存实际 schema、请求/响应 fixture 与能力探测结果；方法缺失只禁用相关功能，不冒充断线。

## 6. 终端流、输入与不确定结果

### 终端观察

默认使用 observe；不分配 PTY，不自动接管桌面尺寸。终端渲染事件带本地 `(connection generation, observe epoch)`，每次重开从新 epoch 开始，旧 epoch 的帧一律丢弃。上游帧的 seq 只在当前观察流内解释，具体连续性由固定版本协议验证。

每个标签及可见分屏视图分别绑定 Host/session/pane，拥有独立 observe epoch、VT buffer、viewport 与渲染预算；帧不得写入其他视图。首版对同一 Host/session/pane 优先复用已有标签，避免重复观察器、输入入口和尺寸争抢。标签共享所属 Host 的 SSH/overlay lease，关闭一个标签只释放其观察与视图资源，不关闭其他标签共用的连接。隐藏标签可暂停观察和渲染，保留目标、草稿及标明过期的本地画面；不暂停远端 PTY，也不承诺所有隐藏标签实时更新。恢复观察时创建新 epoch，等待新 full 帧重建后才允许输入。

布局、分屏拖动、软键盘和本地字号只改变本地 viewport；必要时按 observe 契约重开。远端共享 PTY resize 必须经过用户显式接管且验证上游能力，不能因布局改变静默执行；分屏本身不授予尺寸控制权。

重开、断线或尺寸变化后先等待新的 `full:true`。全量帧替换当前画面，增量按顺序应用；损坏帧、无法解释的序列或队列溢出触发重新观察，不能继续拼接不可靠增量。限制行长、base64 解码量、画面尺寸和积压；解析器与渲染器都必须能被取消。终止记录或 EOF 都可结束观察，不无限等待某个固定关闭事件。

终端输出不可信。默认禁用输出直接写系统剪贴板等副作用；链接仅在用户点击后按允许的协议打开。输出不得触发命令执行、自动下载、自动批准或未经用户动作的外部导航。

### Nerd Font、字形与终端 cell

Oh My Zsh 是 shell 框架，是否需要 Nerd Font/Powerline 字形由所用主题决定；Powerlevel10k 和 Oh My Posh 的相关主题是兼容性重点。**App 主题只控制客户端界面，远端 shell 主题由远端配置产生。**更换 App 主题或字体不能重写远端主题、locale 或输出。

字体资源由客户端提供，不依赖远端安装字体，也不依赖用户机器的默认终端字体。优先以 Powerlevel10k 推荐的 **MesloLGS NF** 四样式做兼容基线，同时验证 Oh My Posh 推荐的 **Meslo LGM NF**；两个名称不能混为同一字体。对网格终端还需比较 Mono/NFM 变体，Propo 不作为默认候选。推荐来源：[Powerlevel10k 字体说明](https://github.com/romkatv/powerlevel10k#fonts)、[Oh My Posh 字体说明](https://ohmyposh.dev/docs/installation/fonts)、[Nerd Fonts FAQ](https://github.com/ryanoasis/nerd-fonts/wiki/FAQ-and-Troubleshooting)。

首版默认只打包**最终通过许可审查与五端验证的一套家族**；候选未通过前不承诺默认字体已选定。字体来源、版本、Nerd Fonts 主版本、许可和校验和必须锁定。Regular/Bold/Italic/BoldItalic 的实际包含范围以样式正确性与包体预算验证后确定；不一次打包整个字体库，不把系统随机合成样式作为已验证效果。用户切换字体仅开放已验证配置；额外字体资源有独立体积和兼容性门槛。

字体文件许可单独审查，不能用主题仓库的许可证代替。Nerd Fonts 的 base font 与 glyph sources 有不同来源和许可；发行前锁定具体字体文件及样式、base font、patcher、图标来源与随包声明。2026-10-29基线未选择或下载字体；后续验证已固定测试字体及来源，见[共享fixture](../validation/shared/README.md)，仍不能据一个字体家族名称宣称所有字形均可再分发。依据：[Nerd Fonts 许可审计](https://github.com/ryanoasis/nerd-fonts/blob/master/license-audit.md)、[多来源许可说明](https://github.com/ryanoasis/nerd-fonts/blob/master/LICENSE)。

字形能显示与终端列宽一致是两项验收。客户端以 terminal cell 网格、帧的宽高和 VT 光标移动为约束，不能让普通 UI/网页文本排版按字形像素宽重新换行。Nerd Font 不替代 CJK/emoji 的受控 fallback；fallback 只能在终端已分配的 cell 范围内绘制，不能悄悄改变光标、选区或后续字符列号。

| 契约 | 验证内容 |
| --- | --- |
| 图标与版本 | BMP 内外 PUA（含补充平面图标）、Powerline 分隔符、Nerd Fonts 主版本与主题码点对应；旧主题缺字时诊断，不静默替换 PUA 输出 |
| 字符宽度 | 单/双 cell、中文、emoji、组合字符与零宽连接序列；字体 advance 与终端 Unicode 宽度规则分开记录 |
| 光标与重绘 | 右侧 prompt、覆盖/清行、退格、行尾换行、窗口 resize 与主题动态重绘，字形可见且光标列/边框持续对齐 |
| 输入与选择 | IME 组合、选区、复制、多行粘贴均保持同一目标与内容；候选框位置不能因 fallback 偏离输入位置 |
| 环境与资源 | 五端使用同一 fixture，记录字体文件/样式、终端引擎、Unicode/wcwidth 版本及 ambiguous-width 策略、远端 locale/宽度环境和主题版本，测包体与渲染开销 |

码点范围以[官方 Glyph Sets](https://github.com/ryanoasis/nerd-fonts/wiki/Glyph-Sets-and-Code-Points)核对，不能只测 BMP；[Unicode UAX #11](https://www.unicode.org/reports/tr11/)的 East_Asian_Width 也不能直接替代现代终端完整宽度算法。

缺字和列错位分别诊断：显示当前字体及版本、所缺码点或不匹配的测试项，并允许切回内置验证配置。必要时建议用户自行选择主题的无图标模式；**不自动改远端 `.zshrc`、Oh My Posh 配置或 PowerShell profile**。更换字体后重新计算本地 cell 度量；若有效行列数变化，沿既有 observe 重开流程等待新 full 帧，不自动接管远端 PTY。换字体不能被当作所有 wcwidth/locale/主题错位的通用修复。

以上是待实现的渲染契约；候选终端引擎必须用同一字体 fixture 通过五端测试，不以截图中几个图标能显示判定通过。

### 输入

**五端首版均提供完整终端交互，包括手机逐键输入、快捷键/组合键和交互式 TUI。**手机默认优先呈现任务辅助，但用户可显式进入终端输入；辅助键栏和本地草稿不能替代完整输入能力。默认观察，不因进入输入模式而自动分配 SSH PTY 或接管远端共享终端尺寸。

直接输入与草稿编辑使用明确模式，同一手势/按键不能被两个入口重复发送。IME 组合过程留在本地；逐键模式在提交后发送一次，草稿模式提交后仍留本地等待显式发送。草稿中的发送文本、回车与组合键分别呈现。具体上游方法、按键编码及换行行为由 M0.5 fixture 固定，不以直接 SSH PTY 绕过既有 herdr/session 契约。输入绑定 Host、pane 与当前会话身份；切目标不会把草稿或按键发到新目标，每个 pane 的发送按顺序处理。

焦点属于明确的终端视图和目标；输入事件生成时绑定目标、连接代次与焦点状态，发送前再次核对。切标签/分屏焦点或重连后，旧键盘、IME、快捷键回调不得向新目标发送；取消尚未发送的临时按键，草稿仍归原目标。写队列按远端目标串行，不能因布局拆分而产生并发输入入口。

| 本地发送状态 | 含义与行为 |
| --- | --- |
| 草稿/未发送 | 只存在端上，可以编辑或取消 |
| 发送中 | 不允许重复点击；正在尝试一次写入 |
| 已确认写入 | 上游确认输入已写入，不等于命令完成、审批成功或 agent 开始新一轮 |
| 结果未知 | 请求可能已生效但未收到确认；不自动重发，提示核对当前终端 |
| 明确未发送/被拒绝 | 展示原因；修复状态后由用户主动再次发送 |

本地尚未发送的草稿可保留供用户编辑，它不是待联网自动发送的队列。已发出的按键、文本或组合键若结果未知，不能重新变成“未发送草稿”或自动补发。所有写操作均不离线排队，不跨重连自动重放；连接/目标失效或写入结果未知时关闭直接输入，并取消尚未发出的临时按键。恢复后先取得快照与终端全量画面，由用户核实并显式继续。需要去重的未来动作必须先有服务端支持的幂等契约，不能只加本地 UUID 就声称解决。

### 待处理与审批

`agent.prompt` 在 blocked 时会返回 `agent_blocked`，不能作为通用审批动作。MVP 不提供可执行的一键批准按钮，将此场景视为**有上下文的终端输入辅助**：显示目标、当前画面和更新时间，用户核对后选择文本或按键输入。屏幕解析不能生成具有权威含义的批准选项；上下文失效立即禁用。未取得服务端 action token/版本检查前，不承诺原子审批。

## 7. 安全存储与主机前提

- 首版支持手工配置与手机扫码接入。扫码仅导入必要连接资料，需预览、核验来源与实际 host key，再独立完成 SSH 授权；默认每设备独立密钥，也保留已有凭据路径。私钥/密码通过共享凭据接口进入各平台受保护存储，业务状态只保留引用。iOS/macOS、Android、Windows、Linux 各自验证读取、锁定、删除与备份行为；存储服务不可用明确失败，禁止明文兜底。overlay state 单独确定加密、备份排除与清除策略。
- host key 信任、登录凭证、overlay 节点身份分别管理；删除一个 Host 不自动清除其他 Host 共用的网络身份。
- 远端 CLI、socket 和工作目录保存为明确路径；所有 exec 参数须使用受控构造与正确引用，不把扫描结果/用户文本拼进 shell 命令。
- App 获得的主机权限由 SSH 账户和 herdr 权限决定。能够调用写 API 的账户不是只读账户；本设计不额外提供多租户或细粒度服务端授权。
- 日志不记录私钥、密码、配对密钥或完整终端内容；诊断包按字段脱敏。后台预览隐私、崩溃上报与备份策略在发布验收中检查。

手机扫码与五端本地配置加密迁移属于首版，集中契约见 [ADR-0007](adr/0007-pairing-and-config-transfer.md)。QR 不含 SSH 私钥、overlay identity 或长期 token；加密文件也排除设备私钥、密码、入网 secret 和运行状态，仅迁移白名单元数据与偏好。导入先验证完整性/schema、预览冲突并显式确认，不自动信任、连接或发送。AEAD/KDF 与具体库后续核查，不自制密码算法。

手机首次扫码不能以安装本项目桌面 GUI 为前提：已选一次性主机 helper，经用户现有可信渠道读取手机公钥，主机端确认后安全追加手机专属公钥、生成响应码，并提供撤销方式；不监听或依赖同 LAN。每次写主机授权仍须明确确认、限当前用户权限，不覆盖既有授权或自动 sudo；已有凭据路径保留。离线 QR 不能解决网络不可达，overlay 入网与 SSH 授权仍各自完成。

后台通知/推送、SFTP、Git diff 和终端 takeover 属于后续里程碑；首版无云账号、自动配置同步或常驻主机 relay。三种 overlay 仍在当前集成范围，相关发布门槛不变。

## 8. 预期目录与构建记录

**构建优先放在 GitHub Actions 对应系统 runner 上**，适用于 Flutter 与 Tauri 两条候选，不以此提前锁定框架。本地主要保留编辑、版本管理与下载包验收；需要热重载、设备日志或 native 调试时再按需准备工具，不要求预装五端 SDK，也不清理已有环境。五端宿主、产物、签名与权限规则集中在[云端构建与测试分发](07-build-and-release.md)。2026-10-29基线未包含应用代码；2026-10-30验证壳和实际workflow结果见[验证记录](09-prototype-validation.md)，不据构建成功推断产品支持。

以下是 **Flutter 候选的目录草案**，用于说明责任边界，不是已选实现或现有代码；若 A/B 选定 Tauri，按相同责任映射前端与 Rust core，不复制两套协议规则。

```text
app/                      Flutter 候选 app；自适应手机/桌面 UI
                          五端 runner、窗口/键盘和生命周期适配
app/assets/fonts/         经许可审查的字体文件/样式、版本与校验和
packages/herdr_protocol/  固定版本 schema、RPC/事件/帧解码、fixtures
packages/herdr_transport/ SSH、连接状态机、取消与资源管理
packages/herdr_overlay/   profile/节点注册、公共字节流与三 provider 适配
packages/herdr_platform/  凭据、生命周期等共享契约与平台实现
natives/                  原生桥源码、构建清单、版本与校验和
                          Tailscale/EasyTier/ZeroTier 的平台桥
                          iOS/Android/Windows/macOS/Linux 独立目标
plugin/                   后续通知/推送扩展；首版不依赖常驻 relay
docs/                     产品、证据、架构、风险、路线图与 ADR
```

独立目录不会隔离 Git 历史。原生源码和构建脚本可以同仓库；大型预编译产物不直接提交，使用受控产物发布并固定校验和。可复现构建先要求固定源、补丁、工具链与可追溯产物；“逐字节一致”只有验证后才能宣称。用户希望衍生改动继续开放源码；具体许可证须审查依赖/子模块/补丁、静态/动态链接和分发方式，不自动定为 GPL/AGPL 或作法律保证。公开发行提供源代码、构建步骤、第三方声明及逐平台安装说明，审查前不写最终 LICENSE。平台原生产物和打包流水线分开，发布版本共享功能契约和兼容性记录。

三网 native 库在来源、补丁或工具链变化时独立构建，产出按目标 OS/ABI 固定版本的库、头文件、来源清单与校验和；App 构建只消费匹配产物。缓存用于加速，不能代替受控版本产物或来源证明。对应源码、构建材料、许可/NOTICE、依赖清单与符号关联随产物保存。一次性主机 helper 按实际远端 Unix 主机 OS/CPU 单列构建与验收，不套五端 GUI 矩阵，也不要求远端安装 Flutter/Tauri 或全部 overlay 运行库。

分发采用**源码与测试渠道先行，再逐步正式上架**。测试产物也须满足对应平台签名、安装、依赖许可和实际支持范围要求；阶段顺序不豁免这些条件，不把可下载预览当作正式支持或商店审核已通过。

构建产物生成、签名与可安装性、渠道可分发性、目标设备上的产品行为分别验收。未签 iOS 设备包不算可安装，模拟器构建不替代真机；Android 临时 debug APK 也不保证跨构建原地升级。云端产物用于同设备 A/B 与后续验收，不能由 CI 成功推断终端、扫码、三网并发或生命周期正确。

决策归档见 [ADR-0004：MVP 可靠性边界](adr/0004-mvp-reliability-boundaries.md)、[ADR-0005：统一移动与桌面客户端](adr/0005-unified-mobile-desktop.md)、[ADR-0006：三网络集成](adr/0006-three-overlay-providers.md)及 [ADR-0007：扫码配对与配置迁移](adr/0007-pairing-and-config-transfer.md)。
