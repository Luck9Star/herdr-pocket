# Android 普通 SSH 原生复验

2026-11-20，两壳普通 SSH 在 Android API 35 x86_64 模拟器上通过复验。七份官方工件覆盖八个通过案例和两次历史失败。设备采用 Google APIs rev 9、Emulator 37.2.13.0 及经 `adb reverse` 连接的隔离 SSH 对端。终端输入由 Flutter 测试接口或 Tauri CDP 提交。覆盖范围限上述模拟器与受控网络，实体设备、实际中文输入法组字和真实跨网仍待独立验收。[官方工件索引](official-index.json) · [此前同源验收](../ordinary-ssh-android-same-source-20261120/README.md)

| 设备作业 / 客户端源码 | 已核对的场景与证据 | Actions 原件 |
| --- | --- | --- |
| Flutter R4 `1fdcb19` | 密码普通案与密码换钥案均通过。普通案首探零认证、八项键盘及导航检查均保留原认证会话。两案各一次成功认证、PTY 和 shell，各 9 字节输入、102 字节累计输出。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44588463433/job/135787725650) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44588463433/artifacts/14563056326) · [原 ZIP](44588463433-14563056326.zip) |
| Tauri R4 `65204b6` | `default` 下密码普通案、密码换钥案、普通加密私钥案均通过。密码普通案通过八项键盘与导航检查，夹具核对 Esc、Tab、左方向键和 Ctrl-C 的顺序。密码换钥最终会话一次成功认证、PTY 和 shell，9 字节输入、102 字节累计输出。普通加密私钥案以 WebView 回显及对端报告为证。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44589659555/job/135791907646) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44589659555/artifacts/14563403939) · [原 ZIP](44589659555-14563403939.zip) |
| Flutter `c5aa64a` 加密私钥 | 首次指纹经显式确认。错口令在本机被拒，该检查点服务端认证尝试为 0。正确口令后一次公钥认证成功、一次 PTY 和 shell，9 字节输入、144 字节累计输出。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44584332500/job/135773083268) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44584332500/artifacts/14559224332) · [原 ZIP](44584332500-14559224332.zip) |
| Flutter `c5aa64a` 加密私钥换钥，第 2 次运行 | 仅末次连接进行一次公钥认证、PTY 和 shell，9 字节输入、102 字节累计输出。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44584342158/job/135777315874) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44584342158/artifacts/14562075072) · [原 ZIP](44584342158-14562075072.zip) |
| Tauri `c5aa64a` 加密私钥换钥 | 末条连接有两次认证尝试、一次公钥认证成功、一次 PTY 和 shell，9 字节输入、102 字节累计输出。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44584349993/job/135773148918) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44584349993/artifacts/14561102653) · [原 ZIP](44584349993-14561102653.zip) |

四个换钥案例的对端记录都是 A 初探、B 拒绝、B 重探、B 获准。前三条连接均闭合，认证、PTY、shell 和输入计数均为零。客户端取消后保留 A，重探并显式批准 B 才连接。累计输出包含夹具欢迎行与回显。Tauri 普通密码和普通私钥的报告保留认证、PTY、shell 及回显的对端布尔证据，逐连接字节明细见两次换钥报告。

两个密码普通案依次打开和收起键盘、切换看板、网络和设置，并从每页回到同一终端。切页期间终端输入为 0。Flutter 的八个采样均为原连接 `#2`、一次认证成功、一次 PTY 和 shell。Tauri 的五次归属采样确认本应用内的隐藏、显示、显示、隐藏、隐藏序列。两壳均在完成导航后才提交回显标记。

## 断开和清理

Flutter 四案均记录主动断开、凭据清空、对端在驱动退出前关闭。普通密码工件另保存断开和返回首页的图，Flutter 的返回首页断言见设备测试代码。两个加密私钥案还确认剪贴板、私有输入文件和临时密钥已清理。Tauri 四案均记录主动断开、凭据清空和对端结束，其中两个非换钥案单独记录 `returnedHome=true`。Tauri 两个换钥案的对端审计确认四条连接均已关闭。

Flutter 的清理包含反向转发、测试包、专属 forward、夹具与 Flutter 工具。Tauri 每个通过的案例各确认浏览器、应用、forward、reverse 与夹具连接清理。七件的 AVD 生命周期均显示受检模拟器进程退出且设备传输消失。[设备测试](../../../validation/flutter/integration_test/direct_ssh_ui_steps.dart) · [Tauri 驱动](../../../validation/remote-harness/tauri_android_direct_ssh.py)

## R3 失败边界

- Flutter `c5aa64a` 的密码组在 `await_driver_exit` 报 `direct_android_device_test_failed`。AVD 已启动，普通和换钥对端均为 0 条 SSH 连接，报告没有可用的应用阶段。具体启动断点原因仍未知。应用包、转发、夹具及 AVD 清理通过。R4 新增了固定阶段诊断并实际通过两案。[作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44584317141/job/135773023383) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44584317141/artifacts/14560658602) · [原 ZIP](44584317141-14560658602.zip)
- Tauri `c5aa64a` 第 2 次在 `active_settings` 失败。此时已有一次成功认证、一次 PTY 与 shell，保持连接且输入为 0。只有 `sectionContent=false`。旧驱动把 CSS 隐藏的桌面说明与状态标题拼接后比对。修复检查设置页内各自可见的状态标题和原目标，随后定向设备复验通过。失败原件记录 AVD 退出，没有逐项应用清理清单。[作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44584324549/job/135777168671) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44584324549/artifacts/14559764597) · [原 ZIP](44584324549-14559764597.zip) · [驱动修正](https://github.com/Luck9Star/herdr-pocket/commit/bcc7bc55a06a8f2be0a3e46a973c01d2fb4cd06e)

## 原图与复核

七份 ZIP 保留官方原字节，包含脱敏报告、23 张 PNG 和 AVD 证明。Flutter 四个通过案例各有一张集成截图和一张 ADB 原图。Tauri 的密码普通案及两个换钥案各有一张 ADB 原图与同次 WebView 抓图。官方 Tesseract 5.3.4 报告绑定 11 张 1080×2340 回显原图，复核用 Apple Vision 独立识别同一个终端区域的回显标记和紧随其后的两行新鲜校验词，11/11 通过。Tauri 普通加密私钥案的回显来自 WebView 和对端断言，单独记录。[成员、尺寸与 SHA-256](official-index.json)

```sh
shasum -a 256 -c SHA256SUMS
unzip -p 44588463433-14563056326.zip direct-ssh-public/result.json
unzip -p 44589659555-14563403939.zip tauri-direct-evidence/manifest.json
```

复跑入口分别为 [Flutter Android 工作流](../../../.github/workflows/direct-ssh-android.yml) 的 `standard`、`encrypted-key`、`encrypted-key-rotation`，以及 [Tauri Android 工作流](../../../.github/workflows/tauri-android-direct-ssh.yml) 的 `default`、`encrypted-key-rotation`。逐案先核对索引中完整的源码 SHA，再比对设备报告、原图门槛和清理结果。
