# 参考客户端对比（历史调研快照 2026-10-29）

本表保留原调研的 12 个移动使用场景参考客户端条目；项目现已扩展为公开开源五端 GUI，本表没有补做完整桌面生态调查。没有逐项固定来源 URL / commit，本轮未重新逐格验证。图例中的状态仅代表原调研记录，不能用作当前功能承诺、许可清单或完整市场普查。关键技术事实的本次复核见[调研依据](00-research.md)，该2026-10-29比较不包含后续验证壳；2026-10-30原型、云构建与有限实测见[验证记录](09-prototype-validation.md)，不能视作正式产品能力。

新增限定复核：Heeler `bd837c7e…` 与其 native v1.0.3 的三网络源码已核对，确有 Tailscale / EasyTier / ZeroTier TCP 路径；现成原生产物只有 iOS arm64 真机 / 模拟器。EasyTier 是直接 no-TUN TCP 桥而非 SOCKS5。详见[固定来源与复用边界](00-research.md#23-heeler-三网络源码复核)，不扩张为 Heeler 全功能或五端运行验证。

当前框架尚未定案：用户已确定手机优先、桌面紧随；Flutter 为第一验证候选，Tauri 2 + xterm.js + Rust 为同规格手机 A/B 的主要挑战者。独立框架调查见[技术评估](06-technology-evaluation.md)，不由以下历史竞品的技术栈直接推出本项目应采用哪一种。

图例：✅ 原记录称有 · ◐ 原记录称部分/受限 · — 原记录未列出 · ? 未能核实。
`overlay` 指 **App 进程内自带穿透**，不等同于「能用系统 VPN」。

## 1. 功能矩阵

| 能力 | Heeler | Kelpie | herdrup | Sherpr | wooloo | herdr mobile (Flutter) | Herdr Mobile (RN) | Collie | Ovis | 0cv relay | Roamgate | Moshi |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 多机 / 多会话 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ crew | ✅ | ✅ 合并 | ✅ | ✅ |
| Agent 看板（blocked 置顶） | ✅ | ◐ TUI | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 实时终端 | ✅ libghostty | ✅ herdr TUI | ✅ SwiftTerm | ✅ | ✅ | ✅ | ✅ 原生模块 | ◐ 轮询为主 | ✅ | ◐ | ✅ | ✅ |
| 终端尺寸协商 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ◐ | ✅ | ✅ | ✅ | ✅ |
| 修饰键 / 快捷键条 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ◐ | ✅ | ✅ | ◐ | ✅ | ✅ |
| 审批 / 选项输入 UI | ✅ | ? | ✅ | ✅ 两击 | ✅ | ✅ 屏幕解析 | ◐ | ✅ | ✅ | ✅ | ◐ | ✅ |
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
| 许可 | 根 Apache-2.0，native 另计 | Apache-2.0 | 闭源 | GPL-3.0 | MIT | GPL-3.0 | MIT | MIT | MIT | 待核 | MIT | 商业 |

## 2. 实现对比

| 项目 | UI 栈 | 传输 | 终端渲染 | 状态/事件 | 通知 | 主机侧依赖 |
| --- | --- | --- | --- | --- | --- | --- |
| Heeler | SwiftUI | SSH `direct-streamlocal`；一请求一 channel + 常驻 events + PTY channel | libghostty（Metal） | `events.subscribe` + 屏幕/transcript 解析 | 插件 hook → 加密 → relay → APNs；Live Activity | sshd（完整前提待核） |
| Kelpie | SwiftUI（Heeler fork） | 同上 | 直接铺 herdr TUI | herdr 原生 | 继承 | sshd（完整前提待核） |
| herdrup | SwiftUI | SSH + JSON API | SwiftTerm | `events_v2`，否则 5s 轮询 | 需服务端 fork | sshd（+fork） |
| Sherpr | Kotlin + Compose | SSH（Ed25519 + 固定 host key） | 自绘 + 修饰键条 | SSH 事件流 | 端上生成，前台服务保活 | sshd（完整前提待核） |
| wooloo | Kotlin + Compose | SSH + herdr 协议 | 自绘 live pane | herdr 状态 | 告警 | sshd（完整前提待核） |
| herdr mobile | **Flutter** + worker isolate | SSH exec + 主机 python3 mux（每 channel 一段） | Flutter 终端 | mux + events 脚本；ACP keeper | — | python3 |
| Herdr Mobile | **React Native (Expo)** | HTTPS REST + WS → 主机 relay（Bun, 127.0.0.1:8787） | 两端各写原生终端模块 | WS 结构事件 + 终端帧 | Web Push | Bun + relay 常驻 |
| Collie | TS web (PWA) | bridge + `events.subscribe`，轮询为主 | web 终端（网格快照） | 轮询 + 事件唤醒 | Web Push | bridge + tailscale serve |
| Ovis | TS web + Mac app | 本地 / relay 桥接 | web 终端 | chat 优先 | — | 常驻进程 |
| 0cv relay | Go relay + web | 社区 WebRTC 网关 或 Cloudflare Tunnel；per-device 凭据 | web 终端 | relay 合并多机 | Web Push | relay 常驻 |
| Roamgate | TS 单二进制 | 本地 socket 或 SSH 桥接 | web 终端 | 结构事件 | — | 常驻二进制 |
| Moshi | 双原生商业 | SSH / mosh + 自建探测 | 自绘 | herdr 状态识别 | 推送 + 锁屏跳转 | sshd（完整前提待核） |

## 3. 设计取向：一句话读一个产品

- **Heeler** — agent 控制台，终端是二级页。可按具体许可复用三网络 glue、pump 与生命周期设计；Swift / Apple 产物需要适配所选客户端框架和其他平台，EasyTier wrapper 的 LGPL 义务不能用根 Apache 许可替代。
- **Kelpie** — 不做抽象，直接把 herdr TUI 铺屏。信息密度依赖 herdr 自己的窄屏布局，具体开发成本未比较测量。
- **herdrup** — 「pane 和 agent 是 UI 对象，不是像素」。代价是紧跟 JSON API 演进，推送要 fork 服务端。
- **Sherpr** — 不要云、不要推送服务：通知在设备上从 SSH 事件流生成，前台服务保活，端上 whisper.cpp。减少云侧通知依赖；实际隐私边界与后台表现仍取决于实现。
- **wooloo / Herdroid** — Compose 原生、小而完整（spaces → agent → 终端三层），可作为 Android UI 参照。
- **herdr mobile (tuan3w)** — 提供 Flutter + isolate 的参考路径。原记录称其使用 python mux；选择原因未核实。dartssh2 的 streamlocal 在 2.14.0 已加入，不能把竞品方案归因于 4.x 之前没有该能力。
- **Herdr Mobile (benkraus)** — 用 relay 换跨平台一致，原记录列出文件、diff、只读设备授权等能力；relay 的可达性仍需另外解决，本项目优先验证 App 内私网连接。
- **Collie / Ovis / 0cv / Roamgate** — 手机只是显示器，重活放主机。浏览器侧可免安装、跨端共享 UI；普通浏览器不能直接嵌入原生 overlay，但主机 bridge 可以提供终端字节流，不必另造 herdr 帧协议。
- **Moshi** — 商业终端思路：workspace 级 picker、锁屏事件直达 tab、快捷键前缀对齐。值得抄的是「事件 → 精确位置」的跳转语义。

## 4. 对本项目的决策价值

1. 原调研反复出现看板、终端和输入操作，首版应先把这些日常动作做可靠，不由能力矩阵推导“功能越多越好”。
2. 文件、Git diff、历史记录不是 relay 独占能力；SSH 的 SFTP / 按需 exec 也可提供部分功能。它们后置是范围决策，不是协议上做不到。
3. 当前方向是公开开源五端 GUI，手机优先、桌面紧随，首版仅连接远端 herdr，本机接入后置。Tailscale / EasyTier / ZeroTier 全部是集成目标，每端正式支持至少验证 Tailscale + EasyTier；三网完整支持逐格验收。Heeler 是实现依据，但其 iOS 产物与现成 Dart 包不能代表五端适配完成；框架与终端按同规格手机 A/B 和逐平台门槛决定。
4. 审批列只记录 UI 形态，不证明服务端有可验证的结构化 approval token。首版显示当前画面并由用户显式发送输入；不自动批准或重放。

当前范围以[产品设计](05-product-design.md)、[ADR-0004](adr/0004-mvp-reliability-boundaries.md)、[五端决策 ADR-0005](adr/0005-unified-mobile-desktop.md)与[三网络决策 ADR-0006](adr/0006-three-overlay-providers.md)为准。可视化版的本方案列使用“计划 / 后置 / 不承诺”，不与竞品历史状态共用完成标记。
