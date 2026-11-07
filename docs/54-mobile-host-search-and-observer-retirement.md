# 在手机上查找任务并恢复观察

2026-11-08。Flutter 和 Tauri 的主机看板已支持按主机名称、地址、命名会话和网络类型搜索。离开终端后，可以从「上次受阻，待核查」找回原任务。Flutter 也已修复一个在静默观察连接上可复现的 SSH 关闭确认超时。当前可下载的 Android 包仍对应 `dd02595`。本页记录包发布之后的源码与 Mac 实测。[Android 包、设备验收及复测步骤](53-mobile-connection-diagnostics.md)

## 手机上怎样找回原目标

1. 在主机列表输入名称或会话的一部分，再选「当前待处理」或「上次受阻，待核查」。前者要求当前快照确认有可定位的受阻窗格，单次快照或陈旧报告进入后者。选择器上的数字是对应状态下的主机总数。列表另行显示同时满足文字和状态的主机数。
2. 展开历史记录。即使两项同名，也能用原会话、pane 和 terminal 标识区分 A 与 B。选择 B 后复核原主机及连接身份，主动恢复观察，等原 B 的新完整帧和后续输出。键入搜索、清空搜索与筛选本身均在本机完成。
3. 清除文字会保留任务状态。遇到空结果时，「清除全部筛选」恢复原列表。绑定的网络资料已丢失时，卡片显示路径未知。旧网络类型标签只供查找，连通性仍须单独核验。

Penpot 在原文件上保存了五个画板，覆盖状态选择、当前待处理、历史同名目标、B 的身份审查和只读首帧。独立预览实际点击了九次，重载后再次从首页进入。设计中所见的终端内容为示例。[打开可点击原型](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e94cd219075f) · [点击与保存记录](../design/evidence/mobile-host-filter-20261108.json) · [历史目标页面](../design/evidence/mobile-host-filter-history-20261108.png)

## Flutter 静默观察的关闭确认

在 Dart 3.11.0、dartssh2 4.1.0 和隔离 OpenSSH 下，旧适配器收到一张完整帧。暂停静默的观察进程后，本地通道已显示结束，远端对该通道的 CLOSE 仍未到达，随后返回 `channel_cleanup_timeout`。作为对照，持续有输出的 exec 和静默的 Unix socket 转发可以正常收到关闭确认。

修复将本次 SSH 连接创建的无 PTY 观察命令以 `exec` 启动。退场时只向这个观察进程发送一次 TERM，再关闭其 SSH 通道。复用连接仍须收到该通道的远端 CLOSE。专门忽略 TERM 的负例继续超时，适配器结束连接，输入保持关闭。共享 pane、herdr 服务器和其他 SSH 通道均有各自的生命周期。[适配器实现](../validation/flutter/lib/remote_adapter.dart) · [关闭与命令回归](../validation/flutter/test/remote_adapter_test.dart)

| 环境 | 本次结果 |
| --- | --- |
| Mac，隔离 OpenSSH 与静默测试进程 | 旧适配器在第一张完整帧后超时。修复后在同一已认证连接上暂停并恢复五次，共收到六张完整帧。独立通道实验中，六次静默读进程均收到准确的远端 CLOSE，延迟为 5–19 ms。 |
| Mac，实际 herdr 0.9.5 与新建隔离会话 | 五次恢复均收到新完整帧及同一观察代的后续增量，总计 6 张完整帧、5 张增量，最终状态为持续观察。原 pane 与服务器仍存活，输入 0 字节，PTY 采样始终为 119 × 40，采样错误为 0。二进制摘要见记录，尚未验证其构建对应的源码提交。 |
| Tauri，Mac Chrome 的 320 / 390 CSS px 视口 | 实际前端构建加载合成目录与连接事件。两种宽度均能检索另一同名主机的会话，找到历史 B，清除筛选后恢复两台主机。无页面横向溢出，搜索框高 46 px、状态选择器高 44 px，筛选新增原生调用为 0。 |
| 本地回归 | Tauri 的 474 项测试通过，Vite 构建 64 个模块。纯 Dart 搜索核心 10 项通过，核心 analyzer 无问题。远端验收工具 103 项、Flutter Android 驱动 90 项、隔离 helper 15 项通过。新增的 5 个 Flutter widget 用例尚未在 Flutter 引擎执行。 |

关闭测试后，独立浏览器、测试用 SSH 和 herdr 服务均已退出，临时密钥已清理。实验第一次清理时发现专门忽略信号的测试子进程仍存活，限定到自建进程清理后重新完成全部对照与退出检查。[结构化测量及环境边界](evidence/mobile-pair-gui/mobile-host-search-observer-20261108.json)

## 下一批手机验收

先在 Android API 35 重跑 Flutter 的配对、设备密钥 SSH、看板、隐藏标签恢复与受保护 TUI 十个按键，逐次核对原目标、新首帧、后续输出、输入回执及 PTY。将两条 GUI 的检索场景并入同批验收，再更新下载包。上一轮 Android 的 Flutter 受保护 TUI 仍止于通道超时，两条 GUI 的普通只读闭环已有设备作业记录。实体手机触控、系统中文输入法、相机扫码、iOS 和实际跨组网并发均待验证，技术选型继续保留两条路线。[上轮 Android 定向复测](https://github.com/Luck9Star/herdr-pocket/actions/runs/42417473474)
