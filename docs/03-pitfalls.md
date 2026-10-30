# 坑清单

写客户端之前读一遍。每条标记**证据类型**与**严重度**（P0 = 可能推翻架构，P1 = 会返工，P2 = 可局部修）。核查基线为2026-10-29；下文“本轮”指当时的文档与公开源码复核。2026-10-30新增验证壳、真实编译失败与有限Mac实测见[验证记录](09-prototype-validation.md)，不覆盖此前风险。

证据类型：① 历史本机 herdr 0.9.5 实测；② 上游/参考实现文档与源码；③ 库文档与源码；④ 未核实假设；⑤ 本轮客户端设计裁决。参考实现行为不等于本项目已验证。当前契约以[架构](02-architecture.md)、[ADR-0004](adr/0004-mvp-reliability-boundaries.md)、[五端范围 ADR-0005](adr/0005-unified-mobile-desktop.md)及[三网 ADR-0006](adr/0006-three-overlay-providers.md)为准。当前目标为公开开源的 iOS、Android、Windows、macOS、Linux 远端客户端；五端正式支持须逐平台验收。

---

## A. herdr 协议面

**P-01 · 首发目标的 API 通过 Unix socket 访问** — P0 · 证据①
历史 Unix 主机样本中，`herdr status` 打印 `socket: ~/.config/herdr/herdr.sock`。本项目首发五端均通过 SSH 访问远端此路径；Windows GUI 不代表支持 Windows 本地 daemon/named pipe，不将单一主机样本外推为所有平台能力，上游其他平台可能采用不同本地传输。
→ 架构上先定传输路径，再谈 UI。

**P-02 · socket 一次连接只服务一个请求** — P1 · 证据②（Heeler ADR-0011/0002）
herdr 0.9.5 普通请求处理完响应即返回；`events.subscribe` 是独立长连接。observe 则走 SSH exec，不与 RPC 混用。NDJSON 的 id 不会让服务端支持多请求复用。
→ 普通 RPC 一请求一 streamlocal channel；重复读取合并/去抖并限制并发，写操作不合并重排。依据：[固定版本 server.rs](https://github.com/herdrdev/herdr/blob/bc8c28988f75c538d4ca058b702f5adbea30566e/src/api/server.rs#L488-L519)。

**P-03 · streamlocal 失败无法区分原因** — P2 · 证据②
`direct-streamlocal` channel open 失败时，libssh2/dartssh2 都拿不到服务端描述：可能是 socket 不存在，也可能是 sshd 禁了 `AllowStreamLocalForwarding`。
→ 可做一次正确引用路径的只读诊断 `test -S <sock>`；文件存在仍不能证明 daemon 活跃、权限正确或转发允许。保留这些可能原因，**不要假装能分得更细**。

**P-04 · 不要逆向 herdr 的二进制 endpoint 协议** — P0 · 证据①
历史记录中 `herdr terminal session observe` 已提供 NDJSON 帧（见 P-06）。
→ 先验证此公开路径，不以参考实现的提交数量估算本项目难度。

**P-05 · `observe` 不需要 PTY，`attach` 类才需要** — P1 · 证据①
实测：无 TTY 直接 `herdr terminal session observe wF:p1 --cols 80 --rows 24` 正常出帧。
→ 别把"老 SSH 库不能同时发 PTY + exec"的限制（swift-nio-ssh 的封闭枚举）当成 herdr 的限制。

**P-06 · 终端帧的字段语义** — P1 · 证据①
```json
{"type":"terminal.frame","seq":1,"full":true,"width":80,"height":24,"encoding":"ansi","bytes":"<base64>"}
```
历史记录将 `full:true` 识别为全量画面，`full:false` 为增量；尺寸随帧携带。当前只核实导出字段，未把 seq 的连续性或终端解析器重置规则当作完整上游保证。
→ 每次 observe 使用独立本地 epoch，先等新 full 帧；旧连接/旧 epoch 帧一律丢弃。序号只在当前流解释；损坏、无法解释的序列或缓冲溢出时重建观察。M0.5 固定完整帧语义与 fixtures。EOF 也能结束观察，不硬等 `terminal.closed`。

**P-07 · JSON API 没有原始输出流事件** — P1 · 证据②（Collie ARCHITECTURE）
`pane.read` 给的是渲染后的网格快照，`events.subscribe` 里没有字节流事件。
→ 本项目实时终端选择 `observe`；网格快照用于状态与恢复。轮询刷新频率与耗电/时延需测量，不以“有快照”替代连续终端流。

**P-08 · agent 与 pane 是两套 target 语义** — P1 · 证据①
实测：对普通 shell pane 调 `herdr agent send-keys` 返回 `{"error":{"code":"agent_not_found"}}`；`pane send-text` 同一 pane 正常。
→ UI 上必须区分"这是 agent"和"这是终端"，命令分派也要分层。

**P-09 · `agent.prompt` 在 blocked 时不会发出去** — P2 · 证据②（socket API 文档）
已 blocked 的 agent 调 `agent.prompt` 直接返回 `agent_blocked`，不发送输入。
→ 首版只做有当前终端上下文的输入辅助，不从屏幕文字推断权威审批选项。没有服务端 action token 时不承诺原子审批；输入确认也不等于审批或任务完成。

**P-10 · 版本演进会让方法缺失** — P2 · 证据②
客户端与服务端协议代际协商；服务器没实现的方法不能当断线处理。
→ 按方法缺失降级对应 UI（禁用按钮 + 说明），不要全局报错。

---

## B. 传输层

**P-11 · Dart 没有 `Socket.fromFd`** — P0 · 证据③
三种原生库可提供 stream、Unix socketpair 或逻辑 socket handle，不能都当作 OS fd；Dart 适配仍需明确字节流和生命周期。
→ 各 provider/platform 的原生字节流适配 `SSHSocket`，必要时验证受控 loopback TCP 桥；不对外开放 SOCKS，也不强行要求所有库共享 fd 语义。必须验证全双工、短写、取消、背压与关闭；不能仅靠 fd 可读写推断 SSH 接入完成。

**P-12 · dartssh2 4.0 起默认禁掉老算法** — P1 · 证据③（CHANGELOG）
`diffie-hellman-group14-sha1`、`ssh-rsa`、`aes256-cbc` 等只在显式请求时启用。
→ 可能影响老路由器/NAS/嵌入式 sshd；先展示协商失败原因。首版不自动降级；将来兼容选项必须按 Host 明确开启并显示风险，不能用全局开关默默放宽所有连接。

**P-13 · Swift 参考库的历史限制不能当当前结论** — P2 · 证据②
Heeler 旧 ADR 记录 swift-nio-ssh / Citadel 的 channel 枚举限制；本轮没有锁定并重新检查这些库的当前版本。
→ 首版采用已选 Dart 路径；未来重评 Swift 实现时需重查版本与扩展能力。

**P-14 · 主机侧转发器是额外依赖** — P2 · 证据②
`exec + socat` 需要 socat；python mux 需要 python3，且每次请求起一次进程（tuan3w 的方案）。
→ 首版只保留 streamlocal RPC，不实现兼容回退。observe 的 SSH exec 是终端协议路径，不是 socat/python RPC 回退。

**P-15 · relay 型把"可达性"外包给了系统 VPN** — P1 · 证据②（benkraus README）
Herdr Mobile (RN) 要求"设备到 relay 的私有网络路径，通常是 Tailscale"。
→ 这正是本项目要补的洞；但如果决定同时做 relay 后端，别把它当成"穿透解决方案"。

---

## C. Overlay / 穿透

**P-16 · 不要用 NetworkExtension / VpnService 做 overlay** — P0 · 证据②（Heeler ADR-0021）
系统 VPN 接入会引入平台权限、生命周期及与用户其他网络配置的交互面。参考实现选择进程内节点；具体系统能力不能用“一条隧道”的简化说法覆盖所有配置。
→ 要的是 **userspace 网络栈 + dial 出一条字节流**，只服务自己进程。

**P-17 · libzt 是进程级单例** — P1 · 证据②
锁定 Heeler 参考实现为进程级 node，网络 join/leave，不调用 `zts_node_stop`；逻辑 socket 经单 owner pump 转为 OS socketpair。
→ ZeroTier 同步集成。关闭 Host、离网、停用 profile、删除身份与销毁 runtime 分别定义；不能承诺停用立即销毁节点或可直接切换身份，具体限制要验证并显示。

**P-18 · tsnet 节点与 Flutter wrapper 不是同一契约** — P1 · 证据③
原生 tsnet 可在同一 binary 运行多个 Server；state 目录按节点身份隔离，不等同网络。`package:tailscale` 0.9.0 对外每进程只允许一个节点，Android 持久身份有 API 31+ 门槛。
→ 若选该 wrapper，遵守它的单节点限制；不能推广为整个三网架构只有一个节点。stop、logout、清除 state 分别定义，登出后禁止自动重连。wrapper 为 POSIX-only，Windows 不支持，需要自建 tsnet 桥等候选验证；不能把 wrapper 限制外推为底层 tsnet 限制。Linux 持久身份需要 `secret-tool` 与已解锁 Secret Service。未通过平台标实验，不以系统 VPN 替代内置节点验收。

**P-19 · EasyTier 核心集成采用 no-TUN 直接 data plane** — P1 · 证据②与⑤
Heeler native 1.0.3 的 smoltcp TCP 路径使用 Unix socketpair，当前桥仅 IPv4/网内 hostname，不提供 SOCKS5、监听或为其他节点中继的服务。参考代码有 Unix/Apple 平台假设，不能原拷五端。
→ EasyTier 与 Tailscale 同属正式平台核心必需；验证 native 构建、地址族/网络定向、全双工、取消/迟到回收和生命周期。实现源码存在不代表本项目已经支持。

**P-20 · 许可必须绑定版本、依赖与分发方式** — P0 · 证据③
旧调研把 libzt 一概判为 BSL 1.1，已不足以作当前决策。2026-10-29 核实的[固定版本 LICENSE](https://github.com/zerotier/libzt/blob/a707ea6ae0910efdc1125d04758c411e2e9ea4f9/LICENSE.txt)载明 Change Date 2026-01-01、Change License Apache-2.0；该日期已过，但子模块和补丁仍需逐项检查。
→ 不因“商业闭源”预先删 ZeroTier。先锁 libzt/ZeroTierOne/补丁和实际分发物再审查；EasyTier、tsnet 也保留完整依赖许可与构建记录。另外，xterm3 6.3.7 自 6.0.0 起为 AGPL-3.0-or-later，公开开源不自动解决项目许可兼容。终端优先 spike MIT 的 terminal_view 0.5.0，最终依赖与项目许可仍需共同审查；不擅自生成 LICENSE。Heeler native 1.0.3 中 EasyTier bridge 为 LGPL-3.0-or-later，其他 glue 与子模块许可分别记录；参考 fork 不能用另一个上游 main 的结论代替，见 ADR-0006。本文件不作发行合规结论。

**P-21 · 参考代码复用前先核对许可** — P1 · 证据②
历史调研记录 `tuan3w/herdr-mobile`、`Sherpr` 为 GPL-3.0，Heeler 为 Apache-2.0。实际复用须绑定源提交与许可证；本项目分发方式尚未确定。
→ 可以学习设计；复制代码前审查适用许可及兼容性。不能简单将 GPL 写成一律不能复制，也不能将 Apache 写成无条件移植许可。

**P-22 · 原生库要与 app 的历史解耦** — P2 · 证据②
Heeler 早期把 XCFramework 与构建脚本提交进主仓库，导致每次原生变更让 git 历史涨几十 MB。
→ 独立目录不隔离 Git 历史。原生源码/脚本可同仓库，大型预编译产物不直接入 Git；固定源、补丁、工具链与产物校验和。“逐字节可复现”须实际验证。

---

## D. 移动与桌面生命周期

**P-23 · 后台不能保证 SSH 持续可用** — P0 · 证据②与⑤
移动系统可能挂起进程并使连接失效；桌面休眠和切网也会使连接失效，最小化则不等同挂起。不能承诺后台每 30s 读取或实时状态。推送是未来独立链路，不是首版的必要依赖。
→ 移动首版明确前台使用，后台缓存标 stale；移动回前台、桌面唤醒或网络恢复时重建/验证连接、事件订阅、快照与 observe。推送接入后再验证去重、加密和通知权限，不宣称“零延迟”。

**P-24 · 状态检测会抖动** — P2 · 证据②
herdr 的 agent 状态是启发式识别的。
→ 状态显示须带来源与新鲜度；未来推送需去抖复查与事件身份去重。约 5s 只能作为待测参数，不是正确性保证。

**P-25 · 配对的一次性密钥要真的是一次性** — P1 · 证据②（Heeler ADR-0007）
历史参考设计使用受限 forced command、短 TTL 与清扫一次性 authorized_keys 项。具体 OpenSSH 选项、撤销竞争与失败恢复尚未在本项目验证。
→ 手机扫码已进入首版，按 [ADR-0007](adr/0007-pairing-and-config-transfer.md)区分资料 QR、host key 信任与 SSH 授权；默认设备独立密钥，码中不携带私钥或长期秘密。历史参考的临时授权转换仍未验证，不直接采用其 TTL/密钥格式，也不把静态 QR 宣称为一次性授权。后台通知仍后置。

**P-26 · Android 后台行为尚未在本项目验证** — P1 · 证据④
本项目没有 userspace overlay + SSH 在 Doze、进程挂起和不同设备省电策略下的实测记录。
→ 首版接受回到前台重连，不承诺后台实时性。前台服务或推送只有在后续场景要求并完成平台验证后加入，不能作为已解决问题的占位词。

**P-27 · 文案不能替代平台审核判断** — P1 · 证据④
userspace 架构和不申请 NE/VpnService 不构成审核豁免；实际功能、数据处理与分发规则仍须检查。
→ 准确说明仅服务 App 的私网连接，不暗示系统级能力；不能靠避写“VPN”保证上架。

**P-28 · 前台保活与推送会双弹** — P2 · 证据②
→ 推送后置。接入时明确前台/后台通知策略、事件去重与失效深链接处理；不能仅按 pane 去重不同时间的独立事件。

---

## E. Flutter 工程

**P-29 · isolate 不能替代可取消的全双工 I/O** — P0 · 证据⑤
UI 不做同步原生阻塞；同一个 transport isolate 若被无限 read 卡住，write、cancel、stop 也可能无法处理。
→ 原生 worker/event loop 或非阻塞接口必须同时满足读、写与取消；测试部分写入、断流、关闭等待与资源回收，再接入 SSH。

**P-30 · 批量写入不等于任意丢帧** — P2 · 证据③与⑤
终端优先 spike terminal_view 0.5.0；官方基准只覆盖解析/缓冲，不含绘制。五端声明不等于五端 IME/ANSI/负载已验收，历史性能描述不能外推为当前组件一定卡顿或足够快。
→ 渲染调度可按显示帧合并，但必须保留终端字节顺序；队列有上限，超限重新同步，不能任意丢增量。移动性能仍须真机测量。

**P-31 · 尺寸协商会与桌面端打架** — P2 · 证据②
历史参考记录区分 observe 视图与 control/takeover；确切尺寸权限、重开与关闭行为仍列入 M0.5。
→ 默认只用 observe，尺寸变化重开并等待新 full；首版不做 takeover，不能在未验证时承诺退出一定“归还”共享尺寸。

**P-32 · 探测 herdr 一律用一次性 workspace** — P1 · 纪律
在天哥正在跑的 pane/agent pane 里做实验会影响真实工作。
→ `herdr workspace create --cwd /tmp/probe --label probe` → 探测 → `workspace close` → `workspace list` 验证回到原数量。

---

## F. 本轮补充的可靠性边界

以下均为⑤客户端设计要求，不冒充上游已经实现的字段或保障。

**P-33 · 最快返回 host key 不等于可信连接** — P1
→ 验证预期 key 后才交付认证凭证，认证和 herdr 能力检查完成后才选中。首次信任、key 变化、路由失败分别处理；jump host 也要验 key。

**P-34 · 取消后仍可能收到迟到连接与帧** — P1
→ 每代连接与每次 observe 独立标识；旧回调只清理资源。取消先令 attempt 失效，native 若不可中断则有界等待返回并清理，期间仍占预算。共享 overlay 的 lease 与节点生命周期分开，关闭一个 Host 不停止其他 Host。

**P-35 · 写入超时不等于未执行** — P1
→ 设置“结果未知”状态，不自动重发或离线排队；先恢复当前快照/画面供用户核对。输入写入确认不等于命令完成。

**P-36 · 快照与事件没有共同序列边界** — P1 · 另有证据②
→ 按 herdr 0.9.5 等 `subscription_started` 后另连读取 `session.snapshot`；事件只触发权威读取。`events_lost` 后重订阅+快照，恢复当前状态，不承诺补齐历史。[固定版本 socket API](https://github.com/herdrdev/herdr/blob/bc8c28988f75c538d4ca058b702f5adbea30566e/docs/versions/0.9.5/website/src/content/docs/socket-api.mdx#L793-L817)。

**P-37 · 终端输出可以包含副作用控制序列** — P1
→ 默认不允许输出写系统剪贴板、执行命令或自动打开外部链接；导航须由用户点击并校验协议。

**P-38 · 凭证、host key 与 overlay 身份不是同一种状态** — P1
→ 五端各自验证受保护凭据存储，应用状态只存引用；不能只验证手机便宣称Windows/Linux安全保存可用。存储服务不可用明确失败，禁止明文fallback；各自定义备份/注销/删除行为，日志脱敏。SSH 用户的实际权限就是 App 权限，不能把观察 UI 当作服务端只读隔离。RPC 与 observe 还须绑定同一个选定 session/socket；命名 session 不能静默回退 default，pane 短 ID 不跨 session 复用。

**P-39 · 无上限队列会把慢设备变成持续失真状态** — P1
→ 对路由、RPC、解析、渲染和草稿设置预算，具体值由 spike 固定。超限明确失败/重新同步，不无声截断输入或增量。

**P-40 · Nerd Font 有图标不代表终端列宽正确** — P1 · 证据⑤
Oh My Zsh 本身是框架，具体主题才决定 Nerd Font/Powerline 需求。字体必须在客户端绘制端可用；远端安装字体不能让 App 自动获得字形。
→ 客户端锁定一套默认字体候选的版本/许可/样式/校验和，并单独验证 BMP 内外 PUA/Powerline、Nerd Fonts 主版本兼容、CJK/emoji/组合字符及受控 fallback。终端按 cell 网格绘制，不能用普通 UI 文本 fallback 改列宽；同一 fixture 检查光标、右 prompt、退格、换行、resize、动态重绘与 IME，记录远端 locale/宽度环境。缺字不静默改写码点，可提供无图标主题建议，但不自动修改远端 shell/profile。详见[架构字体契约](02-architecture.md#nerd-font字形与终端-cell)。

**P-41 · 三 provider 参考实现不是五端十五格已通过** — P1 · 证据②与⑤
Heeler native 1.0.3 的发布 slice 仅 iOS 18+ arm64 device/simulator；macOS 是构建宿主，其他端仍要迁移平台桥。三网独立可用也不证明三网并发稳定。
→ Tailscale + EasyTier 每端核心必需，ZeroTier 同步集成；15 格分别记录构建、身份、数据链路与恢复，组合并发另验。不以系统 VPN 替代内置能力，native 崩溃也不能声称由 isolate 隔离。

**P-42 · profile 标签不能保证重叠网段定向** — P1 · 证据⑤
同一个虚拟 IP 可以属于不同 overlay 或同 provider 的不同网络。应用持有 profile 引用不等于底层 dial 已绑定正确接口。
→ 验证 provider/API 的实际网络定向与解析行为；无法保证时禁止对应并发组合，要求显式切换，不能只给配置加标签便宣称隔离完成。

---

## 附：参考实现本身的坑（选型时要注意）

| 实现 | 坑 |
| --- | --- |
| herdr mobile (tuan3w) | 依赖主机 python3，每次 channel 起一段脚本；GPL-3.0 |
| Herdr Mobile (benkraus) | 必须常驻 Bun relay；内网可达外包给系统 Tailscale |
| Collie | 轮询为主（无原始输出事件），实时性受限；依赖 bridge + tailscale serve |
| 0cv relay | 需要 WebRTC 网关或 Cloudflare Tunnel；许可待核 |
| Roamgate | 历史记录为单二进制分发与浏览器客户端；不能从产物形式推出闭源，许可与分发来源未独立复核 |
| Moshi | 商业订阅；快捷键前缀必须与 host `config` 对齐，否则面板按钮无效 |
