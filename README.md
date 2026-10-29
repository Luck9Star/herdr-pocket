# herdr-pocket

> 手机上的 herdr：一个 Flutter 客户端，iOS / Android 同一套 UI，**内置** Tailscale / EasyTier / ZeroTier 穿透，不需要系统 VPN。

状态：**M0 调研完成，代码未开始**。本仓库当前只放调研、架构、坑清单与路线图。

## 为什么做

生态里已经有两半，但没人把它们拼起来：

- **跨平台统一 UI** 有 3 个活样本：React Native（benkraus/Herdr Mobile）、Flutter（tuan3w/herdr-mobile）、PWA（Collie / Ovis / 0cv relay / Roamgate）。
- **App 内自带穿透** 只有 Heeler 一家做了，而且只有 iOS（Swift + tsnet / libzt / EasyTier no-TUN）。
- 镜像事实：**没有任何 Android 客户端、也没有任何跨平台客户端做过 in-app overlay**。这是空白，不是重复造轮子。

## 为什么是 Flutter

不是"Flutter 好"，是三条事实刚好凑齐（详见 [`docs/02-architecture.md`](docs/02-architecture.md)）：

1. `dartssh2` 4.x 已支持 `direct-streamlocal` → 不经主机 socat/python 就能直连 herdr 的 unix socket。
2. `herdr terminal session observe` 直接吐 NDJSON 终端帧（base64 ANSI，首帧全量 + 后续增量）→ 不需要逆向 herdr 的二进制协议。
3. `xterm3` / `terminal_view` 在移动端够快（113 MiB/s 纯 ASCII），三个 overlay 库都能 FFI 接。

## 文档

| 文件 | 内容 |
| --- | --- |
| [`docs/00-research.md`](docs/00-research.md) | 调研结论：生态、herdr 对客户端暴露的协议面、实测证据 |
| [`docs/01-comparison.md`](docs/01-comparison.md) | 13 个客户端 × 17 项能力矩阵 + 实现对比 + 各自设计取向 |
| [`docs/02-architecture.md`](docs/02-architecture.md) | Flutter 分层、选型、overlay 契约、Host/Route 竞速 |
| [`docs/03-pitfalls.md`](docs/03-pitfalls.md) | **32 条坑清单**（含实测证据与规避），开工前必读 |
| [`docs/04-roadmap.md`](docs/04-roadmap.md) | M0–M5 里程碑与验收标准 |
| [`docs/assets/comparison.html`](docs/assets/comparison.html) | 同一份对比的可视化版（手机友好、暗色模式） |
| [`docs/adr/`](docs/adr/) | 架构决策记录 |

## 待定

- 许可：未定。取决于自用 / 开源 / 商业闭源 —— 商业闭源会直接砍掉 ZeroTier 那条线（libzt 是 BSL 1.1）。
- 仓库名 / 产品名：暂定 `herdr-pocket`。

## 与 herdr 的关系

本项目是第三方客户端，与 herdr 官方无关。客户端能力全部建立在 herdr 公开的 socket API 与 CLI 上。
