# 手机看板持续状态更新

2026-11-06，延续[手机独立标签与保留连接](22-mobile-terminal-tabs.md)。本批源码让当前主机的会话／pane 看板持续反映新增、退出与 agent 状态；已发布的两份 `546c3eb` Android 包不包含这些后续改动。两路线仍是候选，尚未作框架选型。

## 交互与身份边界

看板分别显示“旧状态”“正在核验”“已同步”和“持续更新不可用”。只有权威快照能更新行，事件仅触发重新读取；终端收到 full 不代表会话元数据已同步。订阅断开或事件丢失时立即显示旧状态，不能用在途的旧快照抹去失效状态。

选择携带实际看到的 pane ID 和稳定 terminal ID，并在原连接内再次核对。相同 pane 名称被其他终端复用时拒绝旧点击；观察中的原目标被替换或移除时结束原观察，不自行选择邻项。连接 generation、观察 epoch 和本地快照 revision 分别隔离迟到更新。

隐藏标签退休订阅、终端观察和输入权限；显式恢复仍使用原 SSH，重新取得快照与 full。进入后台按原契约关闭连接。没有自动输入重放、自动重新拨号或远端共享 PTY resize。看板更新须保留正在编辑的草稿节点、输入法 composition 和终端焦点。

## 固定协议与有界刷新

[共享 session-watch-v1.json](../validation/shared/session-watch-v1.json)记录 SW01–SW11、限制和固定来源。父代理直接读取 stock `2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01` 的四个 GitHub 文件，逐一核对 fixture 所列 blob SHA：[事件](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/schema/events.rs)、[响应](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/schema/response.rs)、[订阅](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/subscriptions.rs)、[服务端](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/server.rs)。

全局生命周期订阅 ACK → 权威快照 → 按当前 pane 增加状态订阅并等 ACK → 再次读取快照。事件正文不直接改变状态；100 ms 合并、一个在途快照和一个 dirty counter 限制工作量，30 秒前台兜底刷新。成员变化必须重建订阅，逐 pane 拒绝不能直接判整个方法不支持。明确不支持时保留一次性快照并标明不可持续更新。

父审发现旧 RPC 失败分支可能提前返回而跳过 channel 清理；此前结束整个 SSH 隐藏了问题，新增 watch 重试会累积通道。本批改为无论成功、读取超时或异常响应都先退休确切 channel。打开 channel 超时且没有 recipient ID 时关闭原 SSH，不能在同一连接上无限制造迟到 open。

## 实际验证边界

逐文件 SHA、实际命令、检查范围与未执行项见[源码验证记录](evidence/mobile-pair-gui/session-watch-source-20261106.json)。

- 共享 Rust：父代理完整默认回归 64 项单元 + 1 项 CLI 通过。真实 loopback SSH peer 验证生命周期／状态、事件风暴、丢失、同 SSH 恢复、目标替换和旧代际隔离，另含四项失败清理反例。peer 是合成固定协议，未执行真实 herdr 进程。
- Tauri：父代理独立复跑 104 项 Node 测试、实际 native crate 的 30 项 Rust 测试和前端构建，全部通过。草稿焦点／composition 的回归使用合成 DOM，不是手机输入法实测。
- 源码来源：共享目录 43 个 SHA256 项全部匹配；官方四个协议文件 blob 匹配。
- Flutter：独立审查修复了初始旧快照可选、多个等待者覆盖、迟到通道清理和暂停输入权限边界。52 个 Dart 文件仅完成 tree-sitter 语法解析；本机无 Flutter SDK，新增 analyzer、widget 和真实订阅链路尚未执行，不继承旧提交的通过结果。
- 本批没有新增 CI、APK、真实手机、相机、中文 IME 或 overlay 结果。没有打开本机测试 GUI。

两路线的失败恢复仍有差别：Rust 在同一 SSH 按 500–2000 ms 间隔继续重建订阅，Flutter 连续重试超过 3 次则停止当前连接，要求重新审查；都不会自动重新拨号。实际长期运行、事件风暴与恢复体验需在下一次集中云验证及设备测试中比较。绘制与输入正确性仍先于性能选择。

## 后续顺序

先完成两套 GUI 的持续看板与选择／恢复验收，再把未知输入记录按原主机、会话、终端和网络身份隔离；后者的源码与独立结果已另记于[按目标隔离的输入恢复](24-target-input-recovery.md)，不回填为本批原始证据。随后分别实现 Tailscale 与 ZeroTier 原生桥，与手机批次一起集中构建。设备条件具备时补运行结果，将发现反馈到 Penpot v2，再推进桌面分屏。现有 v2 配色与画板本批未更改。
