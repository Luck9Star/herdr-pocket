# 坑清单

写客户端之前读一遍。每条都标了**证据来源**与**严重度**（P0 = 会推翻架构，P1 = 会返工，P2 = 会踩但可局部修）。
证据来源分级：① 本机 herdr 0.9.5 实测 → ② 参考实现 ADR / 源码 → ③ 库源码（gh search code）→ ④ 未核实推断。

---

## A. herdr 协议面

**P-01 · herdr 只监听 unix socket，没有 TCP/HTTP** — P0 · 证据①
`herdr status` 打印 `socket: ~/.config/herdr/herdr.sock`。任何"手机直连"都先要一条 SSH（或主机 relay）。
→ 架构上先定传输路径，再谈 UI。

**P-02 · socket 一次连接只服务一个请求** — P1 · 证据②（Heeler ADR-0011/0002）
长生命周期的只有 `events.subscribe` 那条。客户端要么每请求开一个 channel，要么自己在 channel 上做多路复用（NDJSON 自带 id，可复用）。
→ 高频快照（看板刷新）要合并/去抖，否则 channel 开闭的 RTT 会变成卡顿。

**P-03 · streamlocal 失败无法区分原因** — P2 · 证据②
`direct-streamlocal` channel open 失败时，libssh2/dartssh2 都拿不到服务端描述：可能是 socket 不存在，也可能是 sshd 禁了 `AllowStreamLocalForwarding`。
→ 只做一次只读诊断 `test -S <sock>`；存在则报"herdr 可能没跑，或 SSH 禁止 stream-local 转发"这一条合并原因，**不要假装能分得更细**。

**P-04 · 不要逆向 herdr 的二进制 endpoint 协议** — P0 · 证据①
终端流已经有 `herdr terminal session observe` 的 NDJSON 帧协议（见 P-06）。Heeler 自己重造低层协议花了 3,076 个 commit，那是它的历史包袱，不是你的路线。

**P-05 · `observe` 不需要 PTY，`attach` 类才需要** — P1 · 证据①
实测：无 TTY 直接 `herdr terminal session observe wF:p1 --cols 80 --rows 24` 正常出帧。
→ 别把"老 SSH 库不能同时发 PTY + exec"的限制（swift-nio-ssh 的封闭枚举）当成 herdr 的限制。

**P-06 · 终端帧的字段语义** — P1 · 证据①
```json
{"type":"terminal.frame","seq":1,"full":true,"width":80,"height":24,"encoding":"ansi","bytes":"<base64>"}
```
`full:true` = 全量重绘（可安全丢弃旧状态），`full:false` = 增量；尺寸随帧携带。
→ 客户端只做三件事：base64 解码 → 喂终端模拟器 → 按 `seq` 丢弃过期帧。重连后必须等新的 `full:true` 再绘制，否则会拼出乱码画面。

**P-07 · JSON API 没有原始输出流事件** — P1 · 证据②（Collie ARCHITECTURE）
`pane.read` 给的是渲染后的网格快照，`events.subscribe` 里没有字节流事件。
→ 实时终端必须走 `observe`；只靠轮询做出来的"终端"一定卡，且轮询间隔越短越费电。

**P-08 · agent 与 pane 是两套 target 语义** — P1 · 证据①
实测：对普通 shell pane 调 `herdr agent send-keys` 返回 `{"error":{"code":"agent_not_found"}}`；`pane send-text` 同一 pane 正常。
→ UI 上必须区分"这是 agent"和"这是终端"，命令分派也要分层。

**P-09 · `agent.prompt` 在 blocked 时不会发出去** — P2 · 证据②（socket API 文档）
已 blocked 的 agent 调 `agent.prompt` 直接返回 `agent_blocked`，不发送输入。
→ 审批流程要"先拿到选项 → 用户点选 → 再发键位/文本"，不能盲发。

**P-10 · 版本演进会让方法缺失** — P2 · 证据②
客户端与服务端协议代际协商；服务器没实现的方法不能当断线处理。
→ 按方法缺失降级对应 UI（禁用按钮 + 说明），不要全局报错。

---

## B. 传输层

**P-11 · Dart 没有 `Socket.fromFd`** — P0 · 证据③
overlay 的 fd 不能像 Swift 那样直接交给 SSH 层。
→ 两条路：① FFI 实现 dartssh2 的 `SSHSocket`（推荐）；② 原生侧开 127.0.0.1 listener 转发。**先定这条再写代码**，否则整个传输层的接口会返工。

**P-12 · dartssh2 4.0 起默认禁掉老算法** — P1 · 证据③（CHANGELOG）
`diffie-hellman-group14-sha1`、`ssh-rsa`、`aes256-cbc` 等只在显式请求时启用。
→ 老路由器/NAS/嵌入式 sshd 会直接握手失败；需要一条"兼容老算法"的开关，并在失败时给用户看得懂的提示。

**P-13 · swift-nio-ssh / Citadel 不支持 streamlocal** — P2 · 证据②
channel 类型是封闭枚举，无扩展点（Heeler ADR-0002 记的就是这条）。
→ 如果考虑 Swift 参考实现，别在这条路上浪费时间。

**P-14 · 主机侧转发器是额外依赖** — P2 · 证据②
`exec + socat` 需要 socat；python mux 需要 python3，且每次请求起一次进程（tuan3w 的方案）。
→ 首选 streamlocal；兼容路径只在用户明确需要时提供，并且**只留一条**（两条传输路径 = 双份配置/错误/测试面永久存在）。

**P-15 · relay 型把"可达性"外包给了系统 VPN** — P1 · 证据②（benkraus README）
Herdr Mobile (RN) 要求"设备到 relay 的私有网络路径，通常是 Tailscale"。
→ 这正是本项目要补的洞；但如果决定同时做 relay 后端，别把它当成"穿透解决方案"。

---

## C. Overlay / 穿透

**P-16 · 不要用 NetworkExtension / VpnService 做 overlay** — P0 · 证据②（Heeler ADR-0021）
要 entitlement、独立 extension target 有内存限额、用户要批 VPN 配置、**并且会和用户已装的官方 Tailscale/ZeroTier 抢隧道**；iOS 同一时刻只允许一条系统隧道。
→ 要的是 **userspace 网络栈 + dial 出一条字节流**，只服务自己进程。

**P-17 · libzt 是进程级单例** — P1 · 证据②
一个进程一个 ZeroTier 节点 / 一个身份；libzt 仍只接受一个 planet，多网络的自定义 planet 要靠补丁注入 moon。
→ 身份在启动期决定，"多网络并存"要在设置里显式说明身份共享；删除最后一个 ZeroTier 网络时才清身份。

**P-18 · tsnet 是每网络一个 state 目录** — P1 · 证据②
登出必须显式清理 state，否则下次带旧 auth key 会静默重登；登出后 Host 连接会断，要标记 `signedOut` 不可重试。

**P-19 · EasyTier 必须 no-TUN 才能嵌进 App** — P1 · 证据②
用 smoltcp 用户态栈（Heeler 的 `heeler-easytier`），否则就变成要 NE/VpnService 的系统 VPN。
→ 好处是一进程可多实例；代价是要自己处理虚拟 IP 分配与路由选择。

**P-20 · 许可会直接否掉一条线** — P0 · 证据②
libzt 是 **BSL 1.1**：闭源商业内置需 ZeroTier 商业授权。EasyTier 是 **LGPL-3.0**：可闭源调用，但静态链接要提供可重链接物 + 安装信息。
→ 先定用途（自用/开源 vs 商业闭源），再定要不要做 ZeroTier。

**P-21 · GPL 参考实现不能抄代码** — P1 · 证据②
`tuan3w/herdr-mobile`、`Sherpr` 都是 GPL-3.0；`Heeler` 是 Apache-2.0（可移植，保留声明）。
→ 读设计可以，复制代码不行。

**P-22 · 原生库要与 app 的历史解耦** — P2 · 证据②
Heeler 早期把 XCFramework 与构建脚本提交进主仓库，导致每次原生变更让 git 历史涨几十 MB。
→ natives 独立目录/仓库 + 固定版本 + 校验和 + 可复现构建脚本。

---

## D. 移动端平台

**P-23 · 后台没有 SSH** — P0 · 证据②（Heeler ADR-0008）
进程被挂起后长连接必断。通知只能走 APNs/FCM：插件 hook `pane.agent_status_changed` → 去抖复查 → 每主机密钥加密 → 无状态 relay → 平台推送。
→ 这是设计输入，不是可选项。前台时改走本地事件流（零延迟），并抑制系统横幅避免双弹。

**P-24 · 状态检测会抖动** — P2 · 证据②
herdr 的 agent 状态是启发式识别的。
→ hook 侧等 ~5s 复查状态再发；同状态重复用 state 目录去重；客户端按 pane 去重。

**P-25 · 配对的一次性密钥要真的是一次性** — P1 · 证据②（Heeler ADR-0007）
bootstrap key 走 `restrict,command=` 强制命令，短 TTL（2 分钟），成功/过期/清扫时删除 authorized_keys 行。
→ 不要用长期密钥做首次配对。

**P-26 · Android 的 Doze 会杀后台连接** — P1 · 证据④（未实测）
userspace overlay + SSH 在 Doze 下没有公开实测数据。
→ 需要前台服务（Sherpr 的做法）或接受"回到前台重连"；后者的代价是丢实时性，需要推送补位。

**P-27 · 别把产品口径写成 VPN** — P1 · 证据④
App 内 userspace 网络栈不触发 VPN 配置审核，但人审会问"这是不是 VPN"。
→ 文案写"私有网络直连/内网穿透"，不写 VPN；不申请 NE entitlement 就不要暗示系统级能力。

**P-28 · 前台保活与推送会双弹** — P2 · 证据②
→ 前台：in-app banner + 系统横幅静音；后台：仅推送。

---

## E. Flutter 工程

**P-29 · SSH 与 FFI 阻塞必须在 isolate** — P1 · 证据②（tuan3w 的 isolate 架构）
每机一个 transport isolate，UI isolate 只跑 widget/状态。
→ 否则终端打字和滚动会掉帧。

**P-30 · 终端写入要按帧批量** — P2 · 证据③
xterm 系原版在高速输出下会卡；`terminal_view` 的改动就是"按帧批量写入"。
→ 无论用哪个，都自己做一层节流：一帧内合并多次 write。

**P-31 · 尺寸协商会与桌面端打架** — P2 · 证据②
`observe` 带 `--cols/--rows` 是只读视图尺寸；`control --takeover` 才会改共享 PTY。
→ 默认只用 observe；"接管尺寸"做成显式动作，并在退出时归还。

**P-32 · 探测 herdr 一律用一次性 workspace** — P1 · 纪律
在天哥正在跑的 pane/agent pane 里做实验会影响真实工作。
→ `herdr workspace create --cwd /tmp/probe --label probe` → 探测 → `workspace close` → `workspace list` 验证回到原数量。

---

## 附：参考实现本身的坑（选型时要注意）

| 实现 | 坑 |
| --- | --- |
| herdr mobile (tuan3w) | 依赖主机 python3，每次 channel 起一段脚本；GPL-3.0 |
| Herdr Mobile (benkraus) | 必须常驻 Bun relay；内网可达外包给系统 Tailscale |
| Collie | 轮询为主（无原始输出事件），实时性受限；依赖 bridge + tailscale serve |
| 0cv relay | 需要 WebRTC 网关或 Cloudflare Tunnel；许可待核 |
| Roamgate | 闭源分发（仓库 MIT 但产品形态是单二进制）；仍是浏览器客户端 |
| Moshi | 商业订阅；快捷键前缀必须与 host `config` 对齐，否则面板按钮无效 |
