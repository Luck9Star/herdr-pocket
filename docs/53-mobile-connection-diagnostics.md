# 配对后从手机看板持续观察

2026-11-08。Flutter 和 Tauri 的手机 GUI 都可以审查连接资料、创建本机设备身份、提交公钥请求，再复核主机的授权回执。手机主动发起 SSH 连接后，从会话看板选择具体终端，持续观察首帧和后续变化。本批为这条路径加入分阶段诊断，并验证从历史看板重新选择同名的受阻窗格。[本批源码](https://github.com/Luck9Star/herdr-pocket/commit/dd025952321fb944465a48ec762ae76adc74f830) · [上一批 Android 逐场实测](50-android-paired-tui-validation.md)

## 手机上怎样核验

1. 在隔离测试主机上生成配对资料。手机审查账号、主机指纹和命名会话后创建本机专属密钥。设备私钥留在本机。主机确认手机提交的公钥，手机复核回执后点击连接。
2. 从正常连接页面展开「本次连接核验」（Flutter）或「最近一次连接诊断」（Tauri），依次查看网络路径、主机指纹、SSH 公钥认证、会话看板与终端首帧。仅选中本机网络路径时仍需等待连通证据。用户展开面板不会额外发起连接。主机指纹变化时先独立核验身份。
3. 在看板点选窗格并等待完整画面，再观察一条来自原目标的新输出。主动停止后回到历史摘要，重新打开受阻任务需再次审查。两个任务即便显示同名，也分别以会话、pane 和 terminal 标识核对。观察默认关闭输入，切换视口不请求改变远端共享 PTY。断线或输入回执未知时不自动重放。

手工试测可以走公开 JSON 交接入口。依次交接连接资料、手机的公钥请求、主机的确认回执。请用专门的测试账号核对两端指纹，记录请求 ID，验完用同一 ID 撤销测试授权并关闭应用。[主机 helper 操作与撤销](../helper/README.md) · [手机配对资料的预览与交接](45-mobile-pairing-handoff.md)

## 当前实测

| 环境 | 已取得的证据 |
| --- | --- |
| Mac，独立源码快照 | Tauri 的 Node 22 测试 472 项通过，Vite 构建 64 个模块。远端验收工具 103 项、Flutter Android 驱动 89 项、使用临时文件的 helper 测试 15 项通过。 |
| Mac Chrome，320 和 390 CSS px | 从已保存主机打开新标签，审查并主动连接。实际编译的 Tauri 前端接受合成连接事件。选定目标后终端首帧仍为等待，xterm.js 绘制并确认后才显示已核验。两种宽度均可看到五项状态，页面横向溢出为零。展开时新增连接、输入、resize 调用均为零。独立浏览器已退出。 |
| Mac，实际 herdr 0.9.5 的隔离会话 | 两个新增窗格均通过官方状态报告接口显示为受阻，名称同为 `pocket-blocked`，但窗格和终端标识不同，输出分别含 A 和 B。原窗格未收到输入，共享 PTY 前后均为 119×40；两个等待进程、临时服务器和目录均已清理。测试使用已核对摘要的现装二进制，源码与该二进制的构建对应关系未验证。 |

设备侧检查要求从实际看板点选第二个窗格，重新审查连接与目标身份后，从当前观察页取得真实绑定和输出。只有目标 B 匹配、屏幕无 A、仍处于观察模式，且宿主独立读取的两个标识一致，才接受这次回执。[Mac 原始测量](evidence/mobile-pair-gui/mobile-connection-diagnostics-20261108.json) · [受阻任务的状态与恢复设计](51-mobile-blocked-targets.md) · [Android 集中构建与验收](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185)

## Android API 35 模拟器

分发 APK 为 arm64-v8a debug。下表各场景都使用同一源码的 x86_64 构建，受保护输入场景另启隔离的测试宿主。两份包均完成构建，首次集中运行的总状态为失败。[构建运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185)

登录 GitHub 后分别下载并解压，用 `shasum -a 256 app.apk` 核对下表。两份归档的大小和摘要均已与 GitHub 核对，包内 APK 字节也与各自的构建清单相符。下载链接于北京时间 2026-11-22 05:32（Flutter）和 05:33（Tauri）到期。

| 路线 | 测试包 | 解压后 app.apk 的 SHA-256 |
| --- | --- | --- |
| Flutter | [下载 arm64-v8a debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185/artifacts/13591233797) | `027a7881183275e966f602a8a48f0ffc51f4d718476cc9aa1fab151f45499a32` |
| Tauri | [下载 arm64-v8a debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185/artifacts/13591323156) | `569313409cfb7e2b88fe3fa0d267817ca727276866613364824002561a567604` |

| 场景 | 实际结果 |
| --- | --- |
| Tauri，原版 herdr | 通过。主机确认本机设备公钥，sshd 核验了获批公钥；从看板持续观察并停止，再从陈旧的两条同名记录中选 B。手机重新审查后观察到正确 B 的完整标记，未出现 A。主机收到 0 字节，1,310 个共享 PTY 采样均为 119×40。恢复原配对资料、撤销、关闭应用和退出模拟器均完成。[设备与宿主记录](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185/artifacts/13591209198) |
| Tauri，受保护输入 | 通过。两次输入分别收到 1 和 9 字节，随后十个 TUI 操作通过。十二个不同请求均绑定同一目标。退出 TUI 后终端模式恢复，未出现尾随输入。1,598 个共享 PTY 采样均为 119×40；授权已撤销，应用及模拟器已退出。[输入场景](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185/artifacts/13591298324) |
| Flutter，原版 herdr | 配对、设备密钥 SSH、原目标持续观察和停止已执行。历史看板重新选择 B 后已核对实际绑定，测试未能证明 B 的完整标记位于可见区域，停在 `blocked_marker`。主窗格和两个受阻窗格均未收到输入。5,651 个共享 PTY 采样中未发生 resize。[只读场景](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185/artifacts/13591712803) |
| Flutter，受保护输入 | 前两笔共 10 字节已送达。返回原标签并点击恢复后，仍为旧终端，直接输入保持关闭。采样中 TUI 画面的 24 行均匹配，缺少新完整帧的验收证据，未继续十个按键。2,831 个共享 PTY 采样均为 119×40。两场 Flutter 应用、模拟器和临时主机均已清理。[恢复失败与清理证据](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185/artifacts/13592175433) |

首次 Flutter 源码任务有一条多余导入，widget 等测试 435 项通过、1 项跳过、4 项失败。失败分别位于横向滚动控件选择、字符样例资产就绪和标签容量夹具。独立的组合重音绘制回归 10 项通过。[源码测试](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185/job/128532916790)

两包的原生来源清单与包内文件已核验，EasyTier 和 Tailscale 原生库逐字节一致。arm64 实体机安装、实际手机 IME、相机扫码、iOS 及三种真实组网并发均未验证。下一步优先补全手机端受阻窗格与恢复，再扩大设备覆盖。两条 GUI 路线继续保留。[包内数据](evidence/mobile-pair-gui/mobile-connection-diagnostics-20261108.json)

## Flutter 定向复测

锁定的 Dart 终端核心复现了首轮只读失败的一个确定条件。原标记从第 0 列开始，圆角视口保守核验的可见区间不包含这一列，完整标记因此无法通过。修订只将隔离宿主的两条输出缩进四列。Mac 实际读取的 A/B 窗格均显示该缩进，终端输入和共享 PTY 尺寸保持不变。设备测试保留原来的逐字符可见性、目标绑定和只读断言。另已修订失败的 widget 夹具，并为受保护输入恢复记录有限的状态枚举。[修订源码](https://github.com/Luck9Star/herdr-pocket/commit/9b065bfaa7d888cc9d2704e2dbacab60b680275c) · [Flutter 定向运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/42417473474)
