# 调研结论（herdr 0.9.5 · 2026-10-29）

## 1. 结论

1. 「跨平台统一 UI + App 内三网穿透」**目前是空白**：跨平台 UI 已有 Flutter / RN / PWA 三条活路径，in-app overlay 只有 Heeler（iOS，Apache-2.0）。
2. 客户端协议层不需要逆向：herdr 自己暴露了 JSON socket API + `terminal session observe` 的终端帧协议。
3. 真正的难点只有两块：**把 overlay 的字节流接进 Dart 的 SSH 层**（Dart 没有 `Socket.fromFd`），以及**移动端后台/推送**。

## 2. herdr 对客户端暴露的面

### 2.1 只有 unix socket

```
$ herdr status
client: version 0.9.5 / protocol 22
server: running, endpoint_compatible yes
        socket: ~/.config/herdr/herdr.sock
```

没有 TCP、没有 HTTP 端口。手机够到它只有三条路：

| 路径 | 做法 | 主机依赖 | 评价 |
| --- | --- | --- | --- |
| A. SSH `direct-streamlocal` | SSH 开 `direct-streamlocal@openssh.com` channel 指向 socket | 无（除 sshd 禁转发） | **首选**，对齐 Heeler |
| B. SSH exec + 主机转发器 | `ssh host socat - UNIX-CONNECT:<sock>`，或每次发一段 python mux | socat / python3 | 兼容路径 |
| C. 主机 relay | 常驻进程把 socket 翻成 HTTPS + WS | 常驻服务 + 端口 | 功能最全，多一层运维与攻击面 |

### 2.2 实测：终端帧协议

`herdr terminal session observe` **不需要 PTY**，普通 exec channel 即可，输出 NDJSON：

```json
{"type":"terminal.frame","seq":1,"full":true,"width":80,"height":24,"encoding":"ansi","bytes":"<base64 VT 流>"}
{"type":"terminal.frame","seq":2,"full":false,"width":80,"height":24,"encoding":"ansi","bytes":"..."}
```

实测记录（一次性 probe workspace，测完已关闭并验证 workspace 数量回到 1）：

- `observe wF:p1 --cols 80 --rows 24` 无 TTY 运行 3 秒 → 首帧 `full:true` 2,868 字节 b64，次帧 `full:false` 208 字节。
- `pane send-text wF:p1 "echo hello-from-probe"` 生效，下一帧里能读到 `hello-from-probe` 的渲染结果。
- 对普通 shell pane 调用 `herdr agent send-keys` → `{"error":{"code":"agent_not_found"}}`（agent 与 pane 是两套 target 语义）。

### 2.3 JSON 方法面（节选）

- 结构：`workspace.*` / `tab.*` / `pane.*` / `worktree.*` / `agent.*`
- 读：`pane.read`（渲染网格）、`agent.read`、`agent.get`、`agent.explain`
- 写：`pane.send_text`、`pane.send_input`、`agent.prompt`（可带 `wait`）
- 等：`agent.wait --until done|idle`（服务端事件驱动）
- 事件：`events.subscribe` / `events.wait`
- 插件：`plugin.action.list` / `plugin.action.invoke`

权威 schema：`herdr api schema --json`（跟二进制版本绑定）。

## 3. 参考实现的关键设计（Heeler ADR）

- **ADR-0011**：用 libssh2 + `direct-streamlocal`，**故意不留 `exec+socat` 兼容回退**（两条传输路径 = 双份配置/错误/测试面永久存在）。
- **ADR-0021**：in-process overlay。`OverlayNode.start/dial/status/stop`，dial 返回一条已连接流，只包住**第一跳**；明确拒绝 NetworkExtension（entitlement、extension 内存限额、用户批 VPN 配置、与官方 Tailscale/ZeroTier 抢隧道）。
- **ADR-0022**：Host 与 Route 分离。一台机器一个 Host（身份/密钥/信任），多条 Route 竞速，直连立刻发、overlay/jump 延后 400ms；**host key 信任绑 Host 不绑地址**。
- **ADR-0007**：配对用 herdr 插件出二维码（候选地址 + port + user + host key 指纹 + 一次性 bootstrap key，2 分钟 TTL），forced command 完成注册。
- **ADR-0008**：推送用插件 `[[events]]` hook `pane.agent_status_changed` → 去抖复查 → 每主机密钥加密 → 无状态 relay → APNs。

## 4. 许可矩阵

| 组件 | 许可 | 对闭源商业的影响 |
| --- | --- | --- |
| Tailscale tsnet / libtailscale | BSD-3 | 随便用 |
| EasyTier 核心 | LGPL-3.0 | 可闭源调用；静态链接需提供可重链接物（Heeler 用独立 natives 仓库 + tag 说明解决） |
| ZeroTier libzt | **BSL 1.1** | 闭源商业需商业授权；自用/开源无碍 |
| Heeler | Apache-2.0 | 可参考、可移植，保留声明 |
| herdr-mobile (tuan3w) / Sherpr | **GPL-3.0** | 只能读设计，代码不能进闭源产品 |
| Collie / Ovis / Herdr Mobile (RN) / wooloo / Roamgate | MIT | 可参考代码 |

## 5. 未核实（开工前必须先打掉）

1. `package:tailscale`（0.9.0，下载量低，unverified publisher）在 iOS 静态链接 + 后台切换下的真实表现 → 先写 spike。
2. libghostty 的 Android 支持（没找到可靠结论）；因此终端按 xterm3 估算。
3. userspace overlay 的耗电与 Doze 存活：无公开实测；Android 需要前台服务 / WorkManager 策略。
4. iOS 审核对「App 内 userspace 网络栈」的态度：Heeler 已上架说明可行，但宣传口径不要写 "VPN"。
5. Play 上 `dev.herdr.mobile` 与 benkraus 仓库的对应关系是「包名一致」推断，未逐一核实。
