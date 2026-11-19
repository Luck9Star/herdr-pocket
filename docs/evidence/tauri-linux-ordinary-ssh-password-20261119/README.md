# Linux Tauri 普通 SSH 密码验收

2026-11-19，[作业 135577003805](https://github.com/Luck9Star/herdr-pocket/actions/runs/44528983350/job/135577003805)使用提交 `2e3371cd39e270c6b2be62e4f548c354ab81d281`，在 Ubuntu 24.04 的 Xvfb 中启动原生 Tauri GTK／WebKitGTK 调试应用，完成独立回环 SSH 密码验收。原作业使用 `linux_direct_ssh=password`。窗口内点击和终端按键通过原生 WebDriver 执行。[固定版本工作流](https://github.com/Luck9Star/herdr-pocket/blob/2e3371cd39e270c6b2be62e4f548c354ab81d281/.github/workflows/paired-gui-validation.yml)

[官方 ZIP 原件](tauri-linux-ordinary-password-r1.zip)完整保留 43,488 字节，SHA256 为 `cf41aed95ba297c168a899cff19b94f311150e3219c3c5dd4a1a43dd69637c64`，与工件元数据一致。[工件 14531264822](https://github.com/Luck9Star/herdr-pocket/actions/runs/44528983350/artifacts/14531264822)

## 界面和服务端记录

经「添加主机 → 普通 SSH」输入临时回环目标。驱动对照同一夹具的完整公钥和指纹，并确认凭据与连接在核对前保持禁用。显式核对后，才填写临时密码并连接。活动终端目标与核对目标一致。驱动聚焦终端并提交一行 `hp-check`。

| 连接 | 主机密钥 | 认证尝试 | 认证成功 | PTY | shell | 入／出字节 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 探测 | A | 0 | 0 | 0 | 0 | 0／0 |
| 2 核对后连接 | A | 1 | 1 | 1 | 1 | 9／102 |

主动断开后，第二条连接记录 `peer_eof`，会话和两条连接均关闭。界面清空密码、私钥与口令字段，并验证返回首页。五项清理通过，分别是夹具监听释放、夹具密码清空、WebDriver 进程退出、WebDriver 端口释放、私有临时目录删除。

## 原图与 OCR

ZIP 仅含 `result.json` 和 `ordinary-terminal.png`。PNG 为原生 WebKitGTK WebDriver 视口原图，1440 × 1200 像素。官方 Tesseract 5.3.4 在终端矩形（左 272、上 353、宽 896、高 479 像素）识别出回显标记及紧接的两行合成词，OCR 结果和 PNG 摘要内嵌于 `result.json`。本次归档又用 macOS Vision 对同一原图独立核对了终端区域的三行顺序及目标区域的回环端点。原图只包含该夹具的合成数据。

本项验收限 Linux Tauri 的独立普通 SSH 密码路径。主机换钥、私钥认证、真实跨网、物理输入和部署安装仍待各自验证。S06 配对观察和其它平台的结论见[普通 SSH 矩阵](../../63-design-parity-and-direct-ssh.md#普通-ssh-验收矩阵2026-11-18-汇总)。

## 校验原件

在本目录校验 ZIP、成员 CRC 及两个成员的 SHA256。

```sh
set -e
shasum -a 256 -c SHA256SUMS
unzip -t tauri-linux-ordinary-password-r1.zip
originals="$(mktemp -d)"
manifest="$PWD/SHA256SUMS.members"
unzip -q tauri-linux-ordinary-password-r1.zip -d "$originals"
(cd "$originals" && shasum -a 256 -c "$manifest")
```
