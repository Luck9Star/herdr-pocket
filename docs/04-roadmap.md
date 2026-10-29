# 路线图

验收标准都是"能跑出来的东西"，不是"写完了"。

## M0 · 调研（已完成）

- [x] 既有实现盘点（13 个客户端）
- [x] herdr 协议面实测（socket / schema / observe 帧 / target 语义）
- [x] 参考实现 ADR 精读（传输 / overlay / 配对 / 推送）
- [x] 许可矩阵
- [x] 坑清单 32 条

## M1 · 协议层（3–5 天）

Dart 侧最小可用：SSH streamlocal → JSON RPC → observe 帧 → 落盘验证。**先在 Linux 上跑，不碰手机。**

- [ ] `packages/herdr_protocol`：NDJSON RPC 客户端（复用 channel、按 id 关联响应）
- [ ] `packages/herdr_transport`：dartssh2 + `forwardLocalUnix`，一请求一 channel
- [ ] `terminal.frame` 解码 + `seq` 丢弃 + `full` 重置
- [ ] `dart run` demo：列出 agent → 打开某个 pane 的 observe → 打印前 5 帧 → 发文本 → 看到回显
- 验收：在本机 herdr 上跑通，输出可复现的命令 + 结果截图/日志。

## M2 · Overlay 抽象 + Tailscale（1–2 周）

- [ ] `OverlayNode` 抽象 + `SSHSocket` FFI 实现（或 loopback 兜底）
- [ ] tsnet 绑定：iOS xcframework + Android `.so`，先跑通"启动 → 拿到 100.x 地址 → dial"
- [ ] Host/Route 竞速（400ms stagger）
- 验收：关掉系统 Tailscale，仅靠 App 内节点连上 CGNAT 后的主机，能开终端。

## M3 · Flutter UI 最小闭环（1–2 周）

- [ ] 多机列表 → 看板（blocked 置顶）→ 终端页 → 输入（修饰键条）
- [ ] 转屏 / 分屏重开 observe
- [ ] 审批：选项解析 → 点选 → `pane.send_text`
- 验收：iOS + Android 真机都能 60fps 滚终端、打字不丢键。

## M4 · 配对与推送（1–2 周）

- [ ] herdr 插件：popup 出二维码（地址/host key 指纹/一次性 bootstrap key）
- [ ] 客户端扫码 → forced command 注册 → 换设备密钥
- [ ] 插件 hook → 加密 → relay → APNs / FCM；前台走 in-app banner
- 验收：扫码 30 秒配对成功；锁屏收到 blocked 通知并直达对应 pane。

## M5 · 补功能面（按需）

- [ ] EasyTier（Rust no-TUN）与 ZeroTier（若许可允许）
- [ ] 文件浏览 / 预览（SFTP）
- [ ] Git diff / worktree（走 exec，不常驻）
- [ ] 会话历史（transcript / 日志读取）
- [ ] 生物锁、多语言、崩溃上报、更新通道

## 估算

- 自用可用：M1–M3 ≈ 5–8 周（单人 + AI 助手）
- 能给别人用：+4–6 周（签名、审核、崩溃上报、i18n、更新、文档）
