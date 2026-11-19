# Linux Tauri 普通 SSH 密码入口本地复验

2026-11-20 在 Ubuntu 24.04.4 arm64 容器的 Xvfb 下，用同一个原生 GTK 调试程序先后运行旧驱动和修复后驱动。程序由 `2e8c3557e2e51ae62b423f9e25a9f1fc5d72cecf` 及其生产前端资产构建，SHA256 为 `3cc25d5cdc5c6ca35411bd577612ad87411eaa0455bb7c5a4d8d1159f3d9399d`。入口修复提交 `e267f40aab0855634064f05daf4609382728c8d5` 只改测试驱动和回归测试。环境使用 WebKitGTK 2.52.6、tauri-driver 2.1.0、Paramiko 4.0.0、Pillow 12.2.0 和 Tesseract 5.3.4。

- [GitHub 原作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44573467495/job/135734549324)在 `form` 阶段记录 `control_unavailable_host-open-remote`，回环连接数为零。原 ZIP 的 SHA256 为 `74aad67faeda4c64a04e0d12f9df6e61a2e8e5317adfb1e35a2c2070a131dbb7`。
- [本地旧驱动](baseline.json)在 `form` 阶段返回 `webdriver_click_element_not_interactable`，回环连接数为零。旧驱动一次读取空白看板，随后固定等待页头按钮。空主机目录加载后桌面样式会隐藏页头。针对该时序的回归测试旧版失败、修复后通过。
- [本地修复后首次通过](fixed/result.json)从空白看板点击「添加主机」并选择「普通 SSH 终端」，填写回环地址、用户名、端口，核对完整指纹后填写密码，进入终端并输入一行。第一次连接只探测指纹。第二次有一次认证、一次 PTY 和一次 shell 请求，发送 9 字节、接收 102 字节。用户断开后，第二条连接记录 `peer_eof`，两条连接均关闭，凭据字段清空，已返回首页且各项清理通过。
- [另一轮同环境复跑](fixed-repeat-failed.json)在 `target` 阶段报 `linux_direct_ssh_runner_failed`，回环连接数为零。这一轮未完成 SSH 路径。

[终端](fixed/ordinary-terminal.png)、[断开结果](fixed/ordinary-disconnect.png)和[返回首页](fixed/ordinary-home.png)均为 1440 × 1200 WebKitGTK WebDriver 原图。终端图中的回显标记和紧接的两行夹具合成词由 Tesseract OCR 确认，三个 PNG 的哈希可核对 [SHA256SUMS](SHA256SUMS)。

另以同一生产前端资产在浏览器完成真实点击，经过「＋ 添加主机 → 普通 SSH 终端 → 目标表单」，填写合成地址后返回首页。浏览器预览没有原生 SSH 功能，探测按钮保持禁用。Linux 原生证据覆盖本地回环密码路径，GitHub 修复后复跑及跨网连接仍待验证。
