# Linux Flutter 普通 SSH 密码验收

2026-11-19，[作业 135595704307](https://github.com/Luck9Star/herdr-pocket/actions/runs/44534343868/job/135595704307)使用源码 `b46b7508ed1428c84c8f97c548b1dcab5d0c84cd`，在 Ubuntu 24.04、Xvfb 和 Flutter 3.47.9 上通过原生 Linux GTK 调试应用的普通 SSH 密码路径。原作业使用 `linux_direct_ssh=flutter-password`。Flutter 集成测试在原生窗口中操作可见控件，通过 Flutter 测试输入提交内容。[固定版本工作流](https://github.com/Luck9Star/herdr-pocket/blob/b46b7508ed1428c84c8f97c548b1dcab5d0c84cd/.github/workflows/paired-gui-validation.yml)

[官方 ZIP 原件](flutter-linux-password-r1.zip)完整保留 26,535 字节，与 GitHub 的 SHA256 `5c6fea70e1b149a24747d82130bc994890016a9f06bc766ac6d5ed0b85323d01` 一致。报告中的 Linux 集成测试和共享 SSH 交互步骤摘要已与该提交逐一核对，原作业还核对了 45 个生产 Dart 文件。[工件 14535268498](https://github.com/Luck9Star/herdr-pocket/actions/runs/44534343868/artifacts/14535268498)

## 界面与回环服务端

从首页进入普通 SSH，填入隔离回环目标，核对实际主机算法和完整指纹后明确确认。终端仍显示同一回环目标。驱动输入 `hp-check` 并通过可见回车控件提交。

| 连接 | 主机密钥 | 认证尝试 | 认证成功 | PTY | shell | 入／出字节 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 首次探测 | A | 0 | 0 | 0 | 0 | 0／0 |
| 2 核对后会话 | A | 1 | 1 | 1 | 1 | 9／102 |

主动断开后，服务端记录 `peer_eof` 并确认会话关闭，两条连接均已关闭。界面确认凭据清空并返回首页。四项清理通过，分别是 Flutter 进程退出、回环监听释放、夹具密码清空、夹具目录删除。

## 原图与 OCR

ZIP 仅含 `result.json` 和 `ordinary-terminal.png`。PNG 是 1920 × 1080 的全 X11 原始帧缓冲，左上窗口为 1280 × 720，原作业使用缩放 1。官方 Tesseract 5.3.4 在原图终端区域（左 0、上 121、宽 1280、高 559 像素）识别出回显标记及紧接的两行合成词。结果内嵌 OCR 记录及 PNG 摘要。复核用 macOS Vision 读取同一原图的回环目标和回显顺序。为读全贴近左边缘的字符，Vision 分析时在内存中为终端区域增加边距，并按同一像素行合并识别块。归档 PNG 保持原始字节。

## 两壳比较范围

Flutter 的原图是全 X11 帧缓冲，既有两次 Tauri 的原图是 1440 × 1200 的 WebKitGTK WebDriver 视口。窗口和截图范围不同，输入分别采用 Flutter 测试接口与原生 WebDriver。两份原图可核对连接目标和回显，逐点视觉等价需统一窗口和取景后另行验证。[既有 Tauri 两次原生结果](../tauri-linux-ordinary-ssh-password-20261119/README.md)

同源码的 [Tauri 作业 135595726743](https://github.com/Luck9Star/herdr-pocket/actions/runs/44534351332/job/135595726743)另行运行。本归档的 Flutter 通过结论限于普通密码与独立回环。两壳的换钥、私钥认证、物理键盘、系统中文 IME、真实跨网、部署安装及 Windows 均仍待验证。[普通 SSH 矩阵](../../63-design-parity-and-direct-ssh.md#普通-ssh-验收矩阵2026-11-18-汇总)

## 校验原件

```sh
set -e
shasum -a 256 -c SHA256SUMS
unzip -t flutter-linux-password-r1.zip
originals="$(mktemp -d)"
manifest="$PWD/SHA256SUMS.members"
unzip -q flutter-linux-password-r1.zip -d "$originals"
(cd "$originals" && shasum -a 256 -c "$manifest")
```
