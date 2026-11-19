# Linux 普通 SSH 加密私钥四格验收

2026-11-20，Flutter 和 Tauri 各以 Linux 原生 GTK 窗口完成普通加密 OpenSSH Ed25519 私钥及主机换钥两个场景。四案均在 Ubuntu 24.04 运行，以 Xvfb 提供 X11 显示，SSH 对端为独占回环夹具。Flutter 经真实应用界面使用测试输入，Tauri 使用 WebKitGTK WebDriver 键入。此前的密码原件见[同源两壳密码验收](../linux-ordinary-ssh-password-same-source-20261119/README.md)。这些运行覆盖隔离夹具，生产网络、物理键盘和输入法组合须另行验收。

| 客户端与场景 | 可复核的认证顺序 | 官方作业与原件 |
| --- | --- | --- |
| Flutter 普通私钥 `0c94bdd` | A 探测为零认证。切换密码和私钥会清空凭据。错误口令在本机被拒，仍仅有最初的 A 探测。末条 A 一次公钥认证成功。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44591418208/job/135798125572) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44591418208/artifacts/14563498302) · [原 ZIP](44591418208-14563498302.zip) |
| Flutter 私钥换钥 `0c94bdd` | 初探 A、拒绝 B、取消保留 A、重探 B、显式确认 B。前三条连接零认证并关闭。错误口令在最早的本地检查即被拒。末条 B 一次公钥认证成功。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44591417302/job/135798125521) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44591417302/artifacts/14561864988) · [原 ZIP](44591417302-14561864988.zip) |
| Tauri 普通私钥 `ead84ec` | A 探测为零认证。错误口令一案完成 A 握手后关闭，认证、PTY 和输入均为零。末条 A 有两次认证尝试、一次公钥认证成功。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44597006620/job/135817905294) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44597006620/artifacts/14565129801) · [原 ZIP](44597006620-14565129801.zip) |
| Tauri 私钥换钥 `bd20757` | 初探 A、拒绝 B、取消保留 A、重探并确认 B。前三条连接零认证并关闭。末条 B 有两次认证尝试、一次公钥认证成功。Tauri 的错误口令由上面的独立普通案验证。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44599845356/job/135827937341) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44599845356/artifacts/14567941419) · [原 ZIP](44599845356-14567941419.zip) |

每案只有最后一个成功会话申请一次 PTY、开启一次 shell。各收到一次精确输入行，共 9 字节，累计输出 102 字节。四案均确认主动断开后凭据清空、对端 `peer_eof`、全部连接关闭，并返回首页。清理检查确认夹具监听和临时凭据释放。Flutter 另有所属测试进程退出和私有目录清理。Tauri 另有 WebDriver 进程及端口释放和私有目录清理。[逐案计数、清理和 SHA-256](official-index.json)

## 原始报告与图像

四份官方 ZIP 保留原字节，分别包含 `result.json`、回显、断开、返回首页三张原图。两个换钥原件各多一张拒绝新指纹的原图。Flutter 的原图是 1920×1080 X11 帧，报告绑定其中 1280×720 的实际应用窗口。Tauri 原图是 1440×1200 WebKitGTK WebDriver 原视口。四张回显图均与官方 Tesseract 5.3.4 报告的图像 SHA-256 及终端边界吻合。复核用 Apple Vision 独立识别回显标记及紧随的两行校验词，四张均通过。[校验清单](SHA256SUMS) · [14 张原图索引](official-index.json)

```sh
shasum -a 256 -c SHA256SUMS
for archive in *.zip; do unzip -t "$archive"; done
work=$(mktemp -d)
unzip -p 44591417302-14561864988.zip ordinary-terminal.png > "$work/flutter-rotation.png"
unzip -p 44599845356-14567941419.zip ordinary-terminal.png > "$work/tauri-rotation.png"
unzip -p 44599845356-14567941419.zip result.json
```

## 定向复跑

手动运行 [Paired GUI to isolated SSH](../../../.github/workflows/paired-gui-validation.yml)，密码选项为 `password`（Tauri）和 `flutter-password`。加密私钥选 `tauri-key` 或 `flutter-key`，换钥选 `tauri-key-rotation` 或 `flutter-key-rotation`。两个 S06 选项保持关闭。复跑前先确认分支完整源码 SHA，按阶段核对该次报告中的认证、原图、断开和清理。这四份工件分别绑定表中历史源码与作业。
