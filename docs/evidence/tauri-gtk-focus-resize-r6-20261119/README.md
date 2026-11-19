# Tauri GTK 分屏键盘与窗口验收 R6

2026-11-19，Ubuntu 24.04 x86_64 的 GitHub Actions 原生 GTK WebView 从正常首页配对两条真实回环 SSH 连接，分别进入两个命名 herdr 会话。A、B 使用独立的进程内测试身份。两个会话的 pane 名同为 `w1:p1`，稳定终端 ID 各不相同。本次源码为 `c14af9d0bec0a5451318378bf5abaf1c94fd25b9`，归档基线 `eb2b90baaf4c84d78eed222943592bbeda0beddf` 的 Tauri 产品树、Rust 传输树、S06 驱动和工作流与云端对应路径一致。[验收快照](../../74-desktop-split-resize.md#tauri-分屏键盘退出与窗口变化) · [冻结工作流](https://github.com/Luck9Star/herdr-pocket/blob/c14af9d0bec0a5451318378bf5abaf1c94fd25b9/.github/workflows/paired-gui-validation.yml)

| 模式 | 结果 | 原件 |
| --- | --- | --- |
| guarded，隔离受保护输入扩展 | 通过，固定 1440 × 1200 原生窗口。SSH 对端输入 A／B 为 9／1 字节，各认证 1 次 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44524014037/job/135562342657) · [Actions 工件 14532181133](https://github.com/Luck9Star/herdr-pocket/actions/runs/44524014037/artifacts/14532181133) · [原 ZIP](guarded-r6-actions-14532181133.zip) |
| stock，原版 herdr 0.9.5 | 首次遇到 APT HTTP 503，产品未启动。第二次通过只读窗口往返，返回手动暂停的分屏时失败 | [首次作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44524007838/job/135559686242) · [第二次作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44524007838/job/135574626651) · [Actions 工件 14532718510](https://github.com/Luck9Star/herdr-pocket/actions/runs/44524007838/artifacts/14532718510) · [原 ZIP](stock-r6-attempt2-actions-14532718510.zip) |

## guarded 的逐键退出

在 B 的 xterm 中实际按下一个 `b`，等本地回执与 SSH 对端均确认收到 1 字节，再通过真实 WebDriver 键盘发送一次 `Ctrl+Shift+F6`。原 `manifest.json` 的 `checks[0].guardedDirectEscape` 六项均为真。

| 原断言 | 本次观察 |
| --- | --- |
| `trustedChordConsumed` | B 原 xterm 收到指定组合键，应用消费该键 |
| `domFocusMovedToA` | DOM 焦点落到 A 原有的「设为输入焦点」按钮 |
| `selectedTargetStayedB` | 产品仍选中 B |
| `originalTargetsAndPeersPreserved` | 两栏仍绑定原 pane 和稳定终端，各自原连接仍开启且认证次数仍为 1 |
| `readOnlyAfterEscape` | 两侧都处于只读观察 |
| `noExtraInputBytes` | 退出后独立读取 SSH 对端仍为 A 0／B 1 字节 |

接着在 A 明确确认一份草稿，最终 `peerInputBytes` 为 `[9,1]`，并按原字节核对。随后分别关闭两侧标签，独立对端在 WebDriver 退出前确认两条 SSH 关闭。两个 PTY 每 50 ms 采样，共 1673／1665 次，均保持 119 × 40，观察到 0 次 resize。临时授权已撤销，临时进程已停止，密钥已移除。用户授权文件未经触及。[冻结测试驱动](https://github.com/Luck9Star/herdr-pocket/blob/c14af9d0bec0a5451318378bf5abaf1c94fd25b9/validation/remote-harness/s06_tauri_gui.py)

`s06-tauri-connected.png` 是开始逐键输入前的 GTK 工作台原图，展示两栏和测试回显。快捷键的焦点、只读状态和字节数以 manifest 与驱动断言为准。逐键期间的 1440 → 700 → 1440 和手动暂停保持已有 WebKit／Chromium 证据，通过真实浏览器按键、视口变化和受控 IPC 复验，原生 GTK 逐键期间窗口变化仍待验证。物理输入法、系统密钥库和真实网络提供方也仍待验。[D1 浏览器修前后](../tauri-desktop-focus-escape-20261119/README.md) · [D2 浏览器报告与复跑](../tauri-active-input-split-resize-20261119/README.md)

## stock 窗口往返与手动暂停断点

第二次作业通过原生 GTK 准备和编译。驱动在正常只读观察中完成 1440 × 1200 → 700 × 1200 → 1440 × 1200。窄窗只显示 B，A 显示布局暂停。恢复原宽后两个原终端回到各自位置，等到同一目标的新完整帧，画面推进。原图中的 A／B 计数从 313／313，经过窄窗 B 的 318，推进到回宽后的 346／345。冻结驱动在每张阶段图保存前独立检查两条原 SSH 各认证 1 次、仍开启且对端均无输入。[stock 原件](stock-r6-attempt2-actions-14532718510.zip) · [冻结测试驱动](https://github.com/Luck9Star/herdr-pocket/blob/c14af9d0bec0a5451318378bf5abaf1c94fd25b9/validation/remote-harness/s06_tauri_gui.py)

驱动实际点击「返回主机看板」，确认看板可见且两栏的状态均为 `paused`，才点击终端导航返回。返回后配对面板已合上，两侧仍匹配原终端，B 保持选中。诊断读到 A 为 `disconnected`、B 为 `paused`，两侧都没有当前帧或输入控件。失败码为 `s06_tauri_window_resize_s06_tauri_layout_manual_paused`。原图同时保留两侧的暂停提示，A 的连接状态以结构化诊断为准，SSH 对端此时的状态未独立确认。[作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44524007838/job/135574626651) · [原诊断工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44524007838/artifacts/14532718510)

失败发生在手动暂停后的第二轮宽度往返、仅恢复选中侧及正常关闭两标签之前。作业未确认两条 SSH 是否在驱动退出前关闭。收尾报告仍确认撤销隔离授权、停止所属进程和移除临时密钥。两端 PTY 均为 119 × 40，采样 1927／1922 次，零 resize。[原 ZIP 中的 manifest.json](stock-r6-attempt2-actions-14532718510.zip)

## 核对与复跑

两份原 ZIP 均保留 Actions 字节，外层 SHA-256 对应各自 GitHub 工件 `digest`。guarded 的 9 个成员与内部 7 项 SHA-256、stock 的 14 个成员与内部 12 项 SHA-256 均已核验。ZIP 保留 manifest、公开契约、依赖锁、布局测量、测试字体版本和受控工作台原图。stock 失败图中可见临时回环端点和公开指纹。临时授权材料、私钥和原始日志未进入归档。[外层 SHA-256](SHA256SUMS)

在本目录执行以下命令查看原件。

```sh
shasum -a 256 -c SHA256SUMS
unzip -t guarded-r6-actions-14532181133.zip
unzip -p guarded-r6-actions-14532181133.zip manifest.json
unzip -t stock-r6-attempt2-actions-14532718510.zip
unzip -p stock-r6-attempt2-actions-14532718510.zip s06-tauri-manual-return-failure.json
```

需要复跑时，在包含完整冻结源码的 `codex/` 分支上手工运行 `paired-gui-validation.yml`，设置 `s06_route=tauri` 和 `s06_split=true`。仅在 guarded 轮设置 `s06_guarded=true`。APT 下载错误可在镜像恢复后沿用同一源码和参数重试。恢复 stock 完整验收还需查明返回终端时 A 的状态变化，并在同一次原生作业确认两侧在返回终端和窗口往返后保持暂停、仅显式恢复选中侧，以及退出驱动前两条 SSH 均关闭。[S06 隔离运行说明](../../../validation/remote-harness/README-s06-real-ssh.md)
