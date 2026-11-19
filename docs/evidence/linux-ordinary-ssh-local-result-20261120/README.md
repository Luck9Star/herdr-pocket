# Linux 普通 SSH 密码本机断开回执

2026-11-20，Flutter 和 Tauri 在同一源码 `c5aa64a0c9703d0494f5694ec0028018f7f2a0b8` 的两个官方 R3 作业中通过 Linux GTK/Xvfb 普通 SSH 密码验收。两案分别从产品首页进入目标表单，核对临时 RSA 主机指纹后输入密码，在真实回环会话内回显，主动断开并返回首页。作业使用合成输入和一次性 SSH 凭据。Linux 私钥、主机换钥、物理键盘与中文输入法、真实跨网仍待验证。[逐文件索引](official-index.json)

| 客户端 | 官方来源 | 原件与画面 |
| --- | --- | --- |
| Flutter | [作业 135771839335](https://github.com/Luck9Star/herdr-pocket/actions/runs/44583976852/job/135771839335) · [工件 14560117102](https://github.com/Luck9Star/herdr-pocket/actions/runs/44583976852/artifacts/14560117102) | [原始 ZIP，95,858 字节](44583976852-14560117102.zip) · 1920 × 1080 的 X11 帧缓冲，应用窗口 1280 × 720 |
| Tauri | [作业 135772264557](https://github.com/Luck9Star/herdr-pocket/actions/runs/44584102171/job/135772264557) · [工件 14560117602](https://github.com/Luck9Star/herdr-pocket/actions/runs/44584102171/artifacts/14560117602) | [原始 ZIP，87,984 字节](44584102171-14560117602.zip) · 1440 × 1200 的原生 WebKitGTK WebDriver 视口 |

## 回显、断开与清理

两案各记录两次连接。第一条仅探测 A，认证、PTY、shell 和收发均为零。显式确认同一 A 后，第二条各一次密码认证、PTY 和 shell，收到 9 字节输入、送出 102 字节并确认输入标记。点击断开后，已认证连接的关闭原因为 `peer_eof`，两条连接均已关闭。

两份 ZIP 各有三张原图和一份 `result.json`。终端图 `ordinary-terminal.png` 的 SHA-256、尺寸及终端区域与报告绑定，Tesseract 5.3.4 核对合成回显标记紧接本次夹具词串。驱动另核对所显示的连接目标。 `ordinary-disconnect.png` 记录「本机已断开」及凭据清空提示，`ordinary-home.png` 记录返回看板后的「本机已断开」。两张结果图绑定原图哈希与回执矩形。关闭证据包含本机回执和对端连接结束。

Flutter 的四项清理含驱动进程、对端监听、夹具密码和私密目录。Tauri 的五项清理含 WebDriver 进程及端口、对端监听、夹具密码和私密目录。报告中相应字段均为真。原图可从 ZIP 取回，只显示临时夹具数据；检查未发现 PNG 文本或 EXIF。

## 校验与复跑入口

在此目录执行以下命令可校验两份 ZIP 和八个内部成员。

```sh
set -e
shasum -a 256 -c SHA256SUMS
originals="$(mktemp -d)"
members="$PWD/SHA256SUMS.members"
for archive in *.zip; do
  unzip -t "$archive"
  unzip -q "$archive" -d "$originals/${archive%.zip}"
done
(cd "$originals" && shasum -a 256 -c "$members")
```

在本次固定源码的工作流选择 `linux_direct_ssh`。Flutter 使用 `flutter-password`，Tauri 使用 `password`。旧同源批次和 Tauri 入口定向本地复验保留各自运行记录。[固定源码工作流](https://github.com/Luck9Star/herdr-pocket/blob/c5aa64a0c9703d0494f5694ec0028018f7f2a0b8/.github/workflows/paired-gui-validation.yml) · [旧同源批次](../linux-ordinary-ssh-password-same-source-20261119/README.md) · [Tauri 入口本地复验](../tauri-linux-ordinary-ssh-entry-r2-20261120/README.md)
