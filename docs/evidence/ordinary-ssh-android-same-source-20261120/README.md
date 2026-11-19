# 普通 SSH Android 同源验收

2026-11-20，Flutter 和 Tauri 在同一提交 `2e8c3557e2e51ae62b423f9e25a9f1fc5d72cecf` 的五个作业中共通过八个案例。每次使用独占 Android API 35 x86_64 模拟器、Google APIs rev 9 镜像、Emulator `37.2.13.0`，以及经 `adb reverse` 连接的隔离 Paramiko SSH 对端。服务端提供 SSH 认证、PTY、shell 通道和夹具回显。实体设备、真实中文输入法组字和真实跨网仍待验证。[官方工件索引](official-index.json) · [夹具说明](../../../validation/remote-harness/README-direct-ssh-android.md)

## 连接、换钥与断开

| 客户端与场景 | 服务端与界面证据 | 作业与原件 |
| --- | --- | --- |
| Flutter 密码与密码换钥 | 普通案八项导航后原会话完成回显。换钥案拒绝 B、取消保留 A，重探后明确接受 B。两案的有效连接各成功认证、申请 PTY 和开启 shell 一次，两个有效会话各记录 9 字节输入、102 字节累计输出。主动断开、清空凭据、对端在驱动退出前关闭。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573407155/job/135734306545) · [工件 14555283420](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573407155/artifacts/14555283420) · [原 ZIP](44573407155-14555283420.zip) |
| Flutter 加密 OpenSSH Ed25519 | 显式确认指纹。错误口令在本机被拒，服务端认证尝试为 0。随后成功公钥认证、PTY 和 shell 各一次，服务端记录 9 字节输入、144 字节累计输出。主动断开后凭据、剪贴板及私有输入文件清理，对端在驱动退出前关闭。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573506017/job/135734676523) · [工件 14556390968](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573506017/artifacts/14556390968) · [原 ZIP](44573506017-14556390968.zip) |
| Flutter 加密私钥换钥 | 拒绝新指纹后取消并保留 A，重探并明确接受 B。有效连接一次公钥认证成功、一次 PTY、一次 shell，服务端记录 9 字节输入、102 字节累计输出。主动断开后凭据与剪贴板清空，对端在驱动退出前关闭。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573516056/job/135734703489) · [工件 14554934904](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573516056/artifacts/14554934904) · [原 ZIP](44573516056-14554934904.zip) |
| Tauri 密码、密码换钥与加密私钥 | 密码案八项导航后原会话完成回显，Esc、Tab、左方向键及 Ctrl-C 顺序由对端核对。密码换钥案取消保留 A，重探并确认 B 后有效连接一次认证成功、一次 PTY、一次 shell，记录 9 字节输入、102 字节累计输出。密码和加密私钥普通案明确记录断开、返回首页及对端关闭。密码换钥记录主动断开、清空密码及对端结束。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573407306/job/135734306403) · [工件 14556372813](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573407306/artifacts/14556372813) · [原 ZIP](44573407306-14556372813.zip) |
| Tauri 加密私钥换钥 | 拒绝 B、取消保留 A、重探后确认 B。末条连接记录 2 次认证尝试、1 次公钥认证成功、1 次 PTY、1 次 shell，服务端记录 9 字节输入、102 字节累计输出。记录主动断开、清空凭据及实测对端结束。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573527306/job/135734744145) · [工件 14557115765](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573527306/artifacts/14557115765) · [原 ZIP](44573527306-14557115765.zip) |

四个换钥案例的连接顺序均为 A 初探、B 拒绝、B 重探、B 获准。前三条连接都在无认证、无 PTY、无输入的状态下关闭，只有末条建立终端。Tauri 两个换钥清单单独记录 `disconnected`、末条 `sessionClosed` 与 `connectionsClosed`。清单中的 `returnedHome` 来自 Tauri 两个普通认证案例。Flutter 三种工作流都执行 `verifyReturnHome`，该断言位于设备测试代码中。[Flutter 设备流程](../../../validation/flutter/integration_test/direct_ssh_ui_steps.dart) · [Tauri 驱动](../../../validation/remote-harness/tauri_android_direct_ssh.py)

Flutter 清单确认移除 reverse、测试包、新增 forward，关闭夹具及 Flutter 工具。加密私钥两案另记录临时密钥移除。Tauri 每案各确认浏览器、应用、forward、reverse、夹具连接清理。所有五个 AVD 生命周期均记录模拟器进程退出及归属设备传输消失。[逐案清理与成员索引](official-index.json)

## 八项键盘与切页检查

两壳的密码普通案依次检查打开键盘、收起键盘、进入看板、返回终端、进入网络、返回终端、进入设置、返回终端。八步都保持原认证连接及原 PTY/shell，导航期间终端输入为零。Flutter 的八份服务端快照均来自连接 `#2`，累计一次认证成功、一次 PTY、一次 shell。Tauri 从实际 WebView 控件发起操作，五份 Android 系统键盘采样为隐藏、显示、显示、隐藏、隐藏，焦点与编辑器均归属本应用。导航完成后才提交回显标记。Flutter 文本从测试输入接口提交，Tauri 文本通过 CDP 提交。[原始导航清单与像素索引](official-index.json)

## 原始回显画面

五份 ZIP 原字节保留，包含 23 张 PNG 和对应设备及 OCR 记录。Flutter 四案的集成截图和 ADB 原图均有官方 OCR 回显顺序记录。Tauri 保存密码普通案和两个换钥案的 ADB 原图、同次 WebView 取证图及 OCR 记录。Tauri 加密私钥普通案的回显来自终端内容断言与服务端输入记录。系统图均为 1080 × 2340 像素。下表的 Flutter 普通案拍在键盘收起后，Tauri 的普通案和换钥系统图拍在键盘打开时。相邻的 WebView 图可核对同次应用内容，系统键盘画面以 ADB 原图为准。[原图和 OCR 文件的 SHA-256](official-index.json)

| 作业 | 普通案 ADB 图 | 换钥案 ADB 图 |
| --- | --- | --- |
| Flutter 密码组 | `direct-ssh-public/connected-device.png` | `direct-ssh-public/rotation-connected-device.png` |
| Flutter 加密私钥 | `direct-ssh-public/connected-device.png` | — |
| Flutter 加密私钥换钥 | — | `direct-ssh-public/rotation-connected-device.png` |
| Tauri 普通组 | `tauri-direct-evidence/ssh-terminal-android.png` | `tauri-direct-evidence/ssh-rotation-terminal-android.png` |
| Tauri 加密私钥换钥 | — | `tauri-direct-evidence/ssh-rotation-terminal-android.png` |

在本归档目录校验并提取密码组的两张系统原图。要提取同次 Tauri WebView 图，用 ZIP 内的 `ssh-terminal-android-webview-before.png` 成员名。[校验清单](SHA256SUMS)

```sh
shasum -a 256 -c SHA256SUMS
work=$(mktemp -d)
unzip -p 44573407155-14555283420.zip direct-ssh-public/connected-device.png > "$work/flutter-system.png"
unzip -p 44573407306-14556372813.zip tauri-direct-evidence/ssh-terminal-android.png > "$work/tauri-system.png"
unzip -p 44573407306-14556372813.zip tauri-direct-evidence/ssh-terminal-android-webview-before.png > "$work/tauri-webview.png"
```

## 复跑入口

在 `codex/` 验收分支核对 `git rev-parse HEAD` 等于上述完整 SHA 后，分别手动运行 [Flutter Android 工作流](../../../.github/workflows/direct-ssh-android.yml) 的 `auth_case=standard`、`encrypted-key`、`encrypted-key-rotation`，以及 [Tauri Android 工作流](../../../.github/workflows/tauri-android-direct-ssh.yml) 的 `scenario=default`、`encrypted-key-rotation`。工作流准备新的 API 35 AVD 和独占夹具。逐个核对 `result.json` 或 `manifest.json`、原图门禁、所有清理项与 AVD 生命周期。验收 ZIP 包含报告和图像，调试 APK 另按原作业构建物核验。

本机可用装有项目夹具依赖的 Python 环境复跑守卫和回环单元测试。真实模拟器上的步骤需由上述工作流执行。[依赖与运行约束](../../../validation/remote-harness/README-direct-ssh-android.md#证据与本地检查)

```sh
PYTHONPATH=validation/remote-harness python3 -m unittest \
  test_direct_ssh_android test_tauri_android_direct_ssh test_terminal_screenshot_gate
```
