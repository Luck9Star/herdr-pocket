# 从手机看板打开受阻终端

2026-11-08。主机卡片和工作台现在都列出具体受阻窗格。用户可以从两个同名任务中按 pane 和 terminal 选中一个，重新审查连接，在独立标签里只读观察。此功能已进入两套原型源码，现有 Android 下载包来自较早的 `2b497ea`。[功能提交](https://github.com/Luck9Star/herdr-pocket/commit/f4bb334717f6ca2a572a91b6619da4eb73c8a392) · [现有 APK、配对与 SSH 模拟器记录](50-android-paired-tui-validation.md)

## 交互与恢复

- 只有会话快照明确报告为 `blocked` 的窗格才进入清单。未知状态单独计数。后台或断线后保留最后一次报告，历史条目提供“重新核查此目标”。
- 用户重新确认主机、设备身份及连接路径后，新的标签从会话快照核对原 pane 和 terminal。任务消失、完成、同名替换或身份变化时停止。旧按钮不能选择新快照中的另一个窗格。
- 首张完整画面抵达前，任务必须仍明确受阻。若已经开始观察，任务变为完成后继续显示该终端的新输出。用户可看到完成结果并主动离开。
- 新标签使用观察模式和空草稿。展开清单、切换或重核目标均不授予逐键输入权限，也不请求变更共享 PTY 的尺寸。

## 已验证范围

以下测试使用原型分支的独立源码快照。Tauri 浏览器检查使用实际前端和 xterm.js，目录、原生命令和看板事件使用隔离替身。[逐场数据](evidence/mobile-pair-gui/mobile-blocked-targets-20261108.json)

| 检查 | 结果 |
| --- | --- |
| Tauri，Mac Chrome，320／390 CSS px | 7 个场景通过。新鲜与陈旧入口各选中正确目标；完成和替换在选择前被拒绝。失效按钮保留焦点且不会新开标签；首帧前完成会取消且确认帧数为零，首帧后完成仍确认下一帧。六个实际点选场景中，按钮高 44 或 58 px，页面横向溢出和发送／远端 resize 调用均为零。隔离 Chrome 已关闭。 |
| Tauri，Node 22.22.2 | 416 项通过。Vite 8.3.5 构建通过，共 62 个模块。包含重复目标、重复选择信号以及异步绘制期间状态变更的回归。 |
| Flutter，Mac Dart 3.11 | 用合成数据执行生产摘要和目标匹配逻辑，覆盖新鲜、历史、空、未知、同名与身份变化。隔离样例分析通过。已增加 widget 回归，完整 Flutter 分析、widget 运行及本功能的 Android 运行仍待集中云测。 |
| Flutter，受保护 TUI 的恢复诊断 | 专项驱动 85 项与其他远端 harness 83 项通过。与 CI 同版本的终端核心覆盖 9 个诊断样例。下一次失败将区分“找看板、回原标签、找恢复按钮、等首帧”，仅记录白名单数值和布尔值，失败元数据继续限 512 字节。上次 Android 超时的根因仍待新设备记录。 |

## 复测与下一批顺序

2026-11-08 后续已在同名受阻窗格和真实隔离 SSH 上运行两条 Android 路线，逐场记录包含 Tauri 的 B 目标回执、Flutter 的可见性检查和后续复测。[配对、看板与持续观察的设备结果](53-mobile-connection-diagnostics.md)

1. 在隔离测试主机用测试设备密钥配对，从主机卡片和打开的工作台分别选中两个同名任务之一。复核身份后检查精确的 pane、terminal 和只读首帧，再产生一条可区分的增量。
2. 用新的测试标签分别覆盖三种顺序：重新连接前替换目标、绑定后首帧前完成、收到首帧后完成。前两项须停止，第三项须能继续看到增量。记录 SSH 侧的输入字节和原共享 PTY 尺寸。
3. 在同批 Android API 35 的 Flutter 与 Tauri 作业中验证入口；Flutter 同时复验带输入 TUI 的恢复和十个按键。保留按阶段的结果、确切的构建 SHA 及两个 APK 的哈希。真机触控、中文 IME、读屏、iOS 与三种真实网络并发继续单列。

本地可在 `validation/tauri` 运行 `npm test` 和 `npm run build`。在仓库根运行 `python3 -m unittest discover -s validation/remote-harness -p flutter_android_test.py` 和 `python3 -m unittest discover -s validation/remote-harness` 可分别复测两组驱动。Flutter widget 用例见[首帧目标核对](../validation/flutter/test/blocked_target_guard_test.dart)及[看板入口](../validation/flutter/test/host_task_summary_widget_test.dart)。
