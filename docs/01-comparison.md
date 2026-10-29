# 既有客户端对比（快照 2026-10-29）

图例：✅ 有 · ◐ 部分/受限 · — 无 · ? 未能从公开资料核实。
`overlay` 指 **App 进程内自带穿透**，不等同于「能用系统 VPN」。

## 1. 功能矩阵

| 能力 | Heeler | Kelpie | herdrup | Sherpr | wooloo | herdr mobile (Flutter) | Herdr Mobile (RN) | Collie | Ovis | 0cv relay | Roamgate | Moshi |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 多机 / 多会话 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ crew | ✅ | ✅ 合并 | ✅ | ✅ |
| Agent 看板（blocked 置顶） | ✅ | ◐ TUI | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 实时终端 | ✅ libghostty | ✅ herdr TUI | ✅ SwiftTerm | ✅ | ✅ | ✅ | ✅ 原生模块 | ◐ 轮询为主 | ✅ | ◐ | ✅ | ✅ |
| 终端尺寸协商 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ◐ | ✅ | ✅ | ✅ | ✅ |
| 修饰键 / 快捷键条 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ◐ | ✅ | ✅ | ◐ | ✅ | ✅ |
| 结构化审批 | ✅ | ? | ✅ | ✅ 两击 | ✅ | ✅ 屏幕解析 | ◐ | ✅ | ✅ | ✅ | ◐ | ✅ |
| 会话历史 / Chat | ✅ transcript | ? | ◐ | ◐ | ◐ | ✅ ACP + keeper | ◐ | ✅ | ✅ chat 优先 | ✅ | ✅ | ✅ |
| 文件浏览 / 预览 | ◐ 仅贴图 | ? | ? | ✅ | ◐ | ✅ SFTP | ✅ | ✅ 上传 | ◐ | ? | ✅ | ◐ |
| Git diff / worktree | — | — | — | — | — | ? | ✅ 只读 | ◐ | ✅ | ◐ | ✅ | ◐ |
| 建 workspace / tab | ◐ | ◐ | ◐ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 推送通知 | ✅ APNs+中继 | ✅ | ◐ 需 fork | ✅ 端上生成 | ✅ | ◐ | ✅ Web Push | ✅ | ? | ✅ | ◐ | ✅ |
| 后台保活 | ◐ 靠推送 | ◐ | ◐ | ✅ 前台服务 | ◐ | ◐ | ◐ | ✅ 服务端 | ✅ 服务端 | ✅ 服务端 | ✅ 服务端 | ◐ |
| 二维码配对 | ✅ 插件 | ✅ 继承 | ? | ? | ✅ 导入 | ◐ | ◐ relay URL | ✅ | ✅ | ✅ | ✅ | ? |
| Host key 固定 | ✅ TOFU | ✅ | ✅ | ✅ 固定 | ✅ | ◐ | ◐ TLS | ◐ | ◐ | ◐ 设备凭据 | ◐ TLS | ✅ |
| 生物锁 / 语音 | ◐ 语音 | ◐ | ? | ✅ 两者 | ◐ | ◐ | — | ✅ 语音 | ◐ | — | — | ◐ |
| **内置内网穿透** | ✅ 三种 | ✅ 继承 | — | — | — | — | — | — | — | — | — | — |
| 许可 | Apache-2.0 | Apache-2.0 | 闭源 | GPL-3.0 | MIT | GPL-3.0 | MIT | MIT | MIT | 待核 | MIT | 商业 |

## 2. 实现对比

| 项目 | UI 栈 | 传输 | 终端渲染 | 状态/事件 | 通知 | 主机侧依赖 |
| --- | --- | --- | --- | --- | --- | --- |
| Heeler | SwiftUI | SSH `direct-streamlocal`；一请求一 channel + 常驻 events + PTY channel | libghostty（Metal） | `events.subscribe` + 屏幕/transcript 解析 | 插件 hook → 加密 → relay → APNs；Live Activity | 只要 sshd |
| Kelpie | SwiftUI（Heeler fork） | 同上 | 直接铺 herdr TUI | herdr 原生 | 继承 | 只要 sshd |
| herdrup | SwiftUI | SSH + JSON API | SwiftTerm | `events_v2`，否则 5s 轮询 | 需服务端 fork | sshd（+fork） |
| Sherpr | Kotlin + Compose | SSH（Ed25519 + 固定 host key） | 自绘 + 修饰键条 | SSH 事件流 | 端上生成，前台服务保活 | 只要 sshd |
| wooloo | Kotlin + Compose | SSH + herdr 协议 | 自绘 live pane | herdr 状态 | 告警 | 只要 sshd |
| herdr mobile | **Flutter** + worker isolate | SSH exec + 主机 python3 mux（每 channel 一段） | Flutter 终端 | mux + events 脚本；ACP keeper | — | python3 |
| Herdr Mobile | **React Native (Expo)** | HTTPS REST + WS → 主机 relay（Bun, 127.0.0.1:8787） | 两端各写原生终端模块 | WS 结构事件 + 终端帧 | Web Push | Bun + relay 常驻 |
| Collie | TS web (PWA) | bridge + `events.subscribe`，轮询为主 | web 终端（网格快照） | 轮询 + 事件唤醒 | Web Push | bridge + tailscale serve |
| Ovis | TS web + Mac app | 本地 / relay 桥接 | web 终端 | chat 优先 | — | 常驻进程 |
| 0cv relay | Go relay + web | 社区 WebRTC 网关 或 Cloudflare Tunnel；per-device 凭据 | web 终端 | relay 合并多机 | Web Push | relay 常驻 |
| Roamgate | TS 单二进制 | 本地 socket 或 SSH 桥接 | web 终端 | 结构事件 | — | 常驻二进制 |
| Moshi | 双原生商业 | SSH / mosh + 自建探测 | 自绘 | herdr 状态识别 | 推送 + 锁屏跳转 | 只要 sshd |

## 3. 设计取向：一句话读一个产品

- **Heeler** — agent 控制台，终端是二级页。复杂度全压在传输与穿透层，UI 极简。可移植性最好（Apache-2.0 + 教科书式 ADR）。
- **Kelpie** — 不做抽象，直接把 herdr TUI 铺屏。成本最低，信息密度靠 herdr 自己的窄屏布局。
- **herdrup** — 「pane 和 agent 是 UI 对象，不是像素」。代价是紧跟 JSON API 演进，推送要 fork 服务端。
- **Sherpr** — 不要云、不要推送服务：通知在设备上从 SSH 事件流生成，前台服务保活，端上 whisper.cpp。隐私彻底，但 Android 专属。
- **wooloo / Herdroid** — Compose 原生、小而完整（spaces → agent → 终端三层），可作为 Android UI 参照。
- **herdr mobile (tuan3w)** — 唯一先例证明 Flutter + isolate 能跑 herdr；传输用 python mux 是因为当时 dartssh2 还没 streamlocal，这点不要继承。
- **Herdr Mobile (benkraus)** — 用 relay 换跨平台一致，功能最全（文件、diff、只读设备授权）；但把「内网可达」外包给了系统 Tailscale，正是本项目的空白点。
- **Collie / Ovis / 0cv / Roamgate** — 手机只是显示器，重活放主机。零安装、跨端一致，但结构上做不到自带穿透。
- **Moshi** — 商业终端思路：workspace 级 picker、锁屏事件直达 tab、快捷键前缀对齐。值得抄的是「事件 → 精确位置」的跳转语义。

## 4. 从矩阵读出的三条结论

1. 看板 / 实时终端 / 审批已是标配，不构成差异化。
2. 文件预览、Git diff、会话历史普遍只有 relay 型能做到（主机有常驻进程可跑 git、读文件），SSH 直连型普遍缺。
3. 所以差异化 = **直连式隐私 + relay 式功能 + 自带穿透** 三件同时做到。只堆看板，八周后得到的是「少了推送的 Sherpr」。
