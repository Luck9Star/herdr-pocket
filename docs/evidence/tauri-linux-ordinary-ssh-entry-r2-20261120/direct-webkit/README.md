# 新桌面终端的 WebKitGTK 驱动对照

2026-11-20 在 Ubuntu 24.04.4 arm64 和 Xvfb 下，把 `ead4bcd14153af6f96233b9781339f28fcfa58ed` 的生产前端资产打包到原生 GTK 调试应用。八轮共用该二进制，SHA256 为 `72d2dbf8ec716ff366d5d6423d6d268a85f8d25a9993b71abe57709cda96c4ea`。WebKitGTK 和 `WebKitWebDriver` 均为 `2.52.6-0ubuntu0.24.04.2`，代理组另使用 tauri-driver 2.1.0。两组均使用 Paramiko 4.0.0、Pillow 12.2.0 和 Tesseract 5.3.4。

| 驱动提交 | 原件目录 | 完整通过 | 通过轮次的截图与清理 |
| --- | --- | ---: | --- |
| `19dd09770fd41386ab7cdd2aab0ef2ce072efb3e`，经 tauri-driver 转发 | `ead-proxy-1` 至 `ead-proxy-3` | 2 / 3 | 6 张原图，10 / 10 项清理 |
| `eb823ab627fdbccfcfa047350e38a1a4b253b83e`，直连 WebKitWebDriver | `ead-native-1` 至 `ead-native-5` | 5 / 5 | 15 张原图，25 / 25 项清理 |

代理组第一轮在 `connection_choice` 返回 `linux_direct_ssh_runner_failed`，回环连接数为零。此前同环境和代理链的诊断在 HTTP 请求返回 `RemoteDisconnected` 时记录了代理进程的 `SendRequest` 错误。直连组使用现有 Ubuntu 流程已安装的 `webkit2gtk-driver` 包，仍通过原生 WebDriver 启动 Tauri 调试应用和操作其实际窗口。

七轮成功各自使用不同的临时回环端口、主机指纹和终端合成词。可见入口、完整指纹比对、用户确认、密码认证和终端操作均由同一驱动执行。驱动点击屏幕中央的 xterm 后核对当前已显示目标和唯一 xterm 输入焦点，才发送一次 `hp-check`。夹具第一条连接只探测，第二条有一次成功认证、一次 PTY、一次 shell，记录 9 字节输入、102 字节输出及 `peer_eof`。原生截图记录终端回显、清空凭据后的断开页与返回首页后的消息。两组保持自己独立的临时目录、监听和进程清理。

[对照 ZIP 原件](ead4bcd-native-compare.zip)包含八份结果和 21 张原生 WebKitGTK 视口 PNG，每张 1440 × 1200。可依次校验 [ZIP 摘要](SHA256SUMS)、成员 CRC 和[成员摘要](SHA256SUMS.members)。原件保留各阶段结果，覆盖本地 Linux arm64 回环密码与原生窗口流程。GitHub 托管 Linux 的修复后验收仍待另行运行。

```sh
shasum -a 256 -c SHA256SUMS
unzip -t ead4bcd-native-compare.zip
manifest="$PWD/SHA256SUMS.members"
originals="$(mktemp -d)"
unzip -q ead4bcd-native-compare.zip -d "$originals"
(cd "$originals" && shasum -a 256 -c "$manifest")
```
