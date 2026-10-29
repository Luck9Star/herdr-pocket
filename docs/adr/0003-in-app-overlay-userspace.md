# ADR-0003 · 内网穿透用进程内 userspace 网络栈

状态：已接受（2026-10-29）

## 背景

家用/办公主机常在 NAT 或 CGNAT 后面，只能从 Tailscale / ZeroTier / EasyTier 的网内到达。iOS 同时只允许一条系统隧道，且系统 VPN 会被用户已装的官方客户端占用。

## 决策

在 App 进程内跑 userspace 网络节点（tsnet / libzt / EasyTier no-TUN），对外只暴露一个契约：

```dart
abstract class OverlayNode {
  Future<void> start();
  Stream<OverlayStatus> get status;
  Future<SSHSocket> dial(String host, int port);  // 或回环监听兜底
  Future<void> stop();
}
```

**不申请 NetworkExtension / VpnService。**

## 理由

1. 不抢系统隧道：可以三个网络并存，也不影响用户已装的 Tailscale 客户端。
2. 无 entitlement / extension 内存限额 / VPN 配置审批，审核面更小。
3. 只服务自己进程的出站 TCP，正好是客户端需要的最小能力。

## 后果

- Dart 没有 `Socket.fromFd`，必须自己实现 `SSHSocket`（FFI + isolate 读写）或用回环监听兜底。
- 各库的进程级语义要显式设计：libzt 一进程一身份、tsnet 一网络一 state 目录、EasyTier 可多实例。
- 耗电与 Doze 存活没有公开数据，需要实测；Android 可能需要前台服务。
- 许可：libzt 是 BSL 1.1（闭源商业需授权），EasyTier 是 LGPL-3.0（静态链接需可重链接物 + 安装信息），tsnet 是 BSD-3。
