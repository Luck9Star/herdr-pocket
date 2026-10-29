# 架构

## 1. 分层

```
UI            看板 / Agent 页 / 终端页 / 会话历史 / 文件 / 设置
              Flutter Widgets + xterm3
领域          Host / Route / Workspace / Tab / Pane / Agent 六层模型
              每机一个 Repository + 状态管理（Riverpod 或 Bloc）
协议          NDJSON JSON-RPC 客户端（方法名/schema 由 herdr api schema --json 生成）
              terminal.frame 解码器 + events.subscribe 事件流
传输          每机一个 worker isolate:
              SSHClient(dartssh2) · rpc channel(按请求) · events channel(常驻)
              observe channel(按 pane) · SFTP
穿透          OverlayNode 抽象 + 三实现:
              Tailscale(tsnet/Go) · EasyTier(Rust, smoltcp no-TUN) · ZeroTier(libzt)
平台          secure storage · FCM/APNs · 深链接 · 生物锁 · 后台策略
```

## 2. 选型

| 层 | 选型 | 理由 | 风险 |
| --- | --- | --- | --- |
| SSH | `dartssh2` 4.x | 纯 Dart；`forwardLocalUnix` 内部即 `direct-streamlocal`；支持自定义 `SSHSocket`；MIT | 4.0 起默认禁用 SHA-1/CBC/ssh-rsa，老服务器需显式开算法 |
| 终端 | `xterm3` 或 `terminal_view` | xterm3 纯 ASCII 写入 113 MiB/s（原版 15.8）；terminal_view 是移动端按帧批量写入的 fork | 不如 libghostty（Metal）；复杂 TUI 需实测 |
| 终端数据 | `herdr terminal session observe` | NDJSON 帧，首帧全量 + 增量 + 尺寸，无需 PTY | 只读，输入另走 `pane.send_text` |
| RPC | JSON over streamlocal | socket 一次连接一请求 → 每请求开 channel 或自帧化 | channel 开闭有 RTT，高频快照要合并 |
| 事件 | `events.subscribe` 常驻 | 驱动看板状态；后台由推送补位 | 无原始输出流事件 |
| Tailscale | `package:tailscale` 或自建 Go c-archive | userspace gVisor，一网络一 state 目录 | 0.9.0/下载量低 → 先 spike |
| EasyTier | Rust crate + C ABI（smoltcp，no TUN） | 一进程多实例；LGPL 可闭源调用 | 需自建 NDK + xcframework 管线 |
| ZeroTier | `libzt`（android-aar / iphoneos-framework） | 进程内 sockets over ZeroTier，一进程一身份 | BSL 1.1，闭源商业需授权 |
| 通知 | 插件 hook → 加密 POST → relay → FCM/APNs | 移动端后台没有长连接 | relay 需自托管；Android 可退化为端上生成 |
| 配对 | herdr 插件（Node）出二维码 | 候选地址 + host key 指纹 + 一次性 bootstrap key | 插件是两端共用的服务端代码 |

## 3. Overlay 契约与 Dart 的特有约束

**关键差异**：Heeler 在 Swift 里能把 overlay dial 出来的 **fd 直接交给 libssh2**。**Dart 没有 `Socket.fromFd`**，所以有两条等效路：

```dart
abstract class OverlayNode {
  OverlayKind get kind;
  Future<void> start();
  Stream<OverlayStatus> get status;                  // 在线 / 直连或中继 / 延迟 / 对端
  Future<SSHSocket> dial(String host, int port);     // A 案：直接给 dartssh2 用
  Future<void> stop();
}
```

- **A 案（推荐）**：用 FFI 调原生 `read/write`，实现 dartssh2 的 `SSHSocket`（stream + sink）。无本地端口、无额外拷贝，语义最接近 Heeler。**阻塞读写必须放 isolate**。
- **B 案**：原生侧在 `127.0.0.1` 开 listener 转发到 mesh 目标，Dart 连 localhost。实现省事，但多一次拷贝 + 要管端口生命周期与本地暴露面。

## 4. Host / Route 竞速（按 ADR-0022 语义）

```
Host  { name, user, auth, session, routes[] }
Route { address, port, jump?, overlayId? }

连接：
  直连 Route            → 立刻发起
  overlay / jump Route  → 延迟 400ms，或所有直连都失败时立刻
  先握到 host key 的赢  → 取消其余
  host key 信任绑 Host（不绑地址）→ 换网络不误报
```

一台机器在家走 LAN、在外走 tailnet。不做竞速就只能等超时或手动切地址。

## 5. 输入与状态分层

| 动作 | 用什么 | 注意 |
| --- | --- | --- |
| 列表 | `workspace.list` / `pane.list` / `agent.list` | 配 `events.subscribe`，后台 30s 兜底刷新 |
| 终端 | `terminal session observe --cols --rows` | 转屏/分屏重开 observe，以帧内 width/height 为准 |
| 打字 | `pane.send_text` / `pane.send_input` | 对任何 pane 有效，不抢 PTY 尺寸 |
| 按键 | `pane.send_keys` | 只吃按键名；普通 shell pane 用不了 `agent.*` |
| 审批 | `agent.prompt`（可带 wait） | 已 blocked 时返回 `agent_blocked`，先展示选项 |
| 接管 | `terminal session control --takeover` | 会与桌面端抢 PTY 尺寸，仅在用户明确接管时用 |

## 6. 仓库预期结构（代码阶段）

```
app/            Flutter 应用（UI + 领域 + 平台）
packages/
  herdr_protocol/   NDJSON RPC + 帧解码 + schema 生成物（纯 Dart，可单测）
  herdr_transport/  SSH/relay 传输 + isolate 桥
  herdr_overlay/    OverlayNode 抽象 + FFI 绑定（Dart 侧）
natives/            C ABI 与构建脚本（独立于 app 的历史，可复现构建）
plugin/             herdr 插件：配对二维码 + 推送 relay（Node/TS）
docs/               本目录
```

`natives/` 与 `plugin/` 之所以独立，是照 Heeler 的教训：原生库变更不应该污染 app 的 git 历史，且要能逐字节复现构建。

## 7. 开放决策

1. 许可 → 决定 ZeroTier 线是否保留。
2. 状态管理：Riverpod（简单）vs Bloc（严格）。倾向 Riverpod。
3. 终端组件：先 xterm3，压测不过再考虑 terminal_view。
4. 是否做 relay 型可选后端（换文件/diff/多设备能力），与 SSH 直连并存。
