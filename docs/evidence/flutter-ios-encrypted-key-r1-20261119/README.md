# Flutter iOS 加密私钥 R1 原始工件

2026-11-19，Flutter 专用作业使用提交 `31a4bfd08fb2922a0dff8d8259858b87502bf928`，在 iPhone 11 / iOS 26.2 模拟器完成普通密码、密码换钥及独立加密 OpenSSH Ed25519 私钥三案。Flutter 作业通过，同一运行的 Tauri 作业跳过。[运行 44494931219，作业 135459578044](https://github.com/Luck9Star/herdr-pocket/actions/runs/44494931219/job/135459578044)

本目录保留字节一致的 [Actions 原 ZIP](flutter-ios-encrypted-r1.zip)，共 585,930 字节。GitHub API 的工件摘要、本地下载和 Git 归档副本的 SHA256 均为 `b56fc432ae53d65d10512069d90bc662a55da6b135bbe43771b9cda773fc5b13`。[官方工件 14515586833](https://github.com/Luck9Star/herdr-pocket/actions/runs/44494931219/artifacts/14515586833)

## ZIP 成员

| 案例 | 系统原图 | OCR | 服务端主机密钥顺序 |
| --- | --- | --- | --- |
| 普通密码 | `ordinary-terminal.png` | `ordinary-terminal-ocr.json` | A → A |
| 密码换钥 | `key-change-terminal.png` | `key-change-terminal-ocr.json` | A → B → B → B |
| 独立加密私钥 | `encrypted-key-terminal.png` | `encrypted-key-terminal-ocr.json` | A → A |

`result.json` 保留脱敏结果、独立服务端计数、各案截图和 OCR 摘要，以及清理记录。三张 828 × 1792 的终端原图均通过目标及回显像素验证。另有换钥核对原图 `key-change-review.png` 与已遮罩的连接前原图 `preconnect.png`。

加密私钥使用独立回环夹具。首次探测无认证，错误口令本地拒绝，正确私钥连接只有一次公钥认证、一次 PTY 和一次 shell，收到一行 9 字节的终端命令并回显 102 字节。主动断开后回到首页，两条连接在驱动退出前关闭。私钥与主机换钥的组合、实体设备、物理键盘、系统中文 IME 与跨网仍待验证。[验收快照](../../72-mobile-ssh-auth-snapshot.md#flutter-ios-加密私钥独立验收)

## 原件校验

[SHA256SUMS](SHA256SUMS) 对应 ZIP 整包，[SHA256SUMS.members](SHA256SUMS.members) 对应解压后的 9 个文件。进入本目录后运行以下命令，依次核验整包 SHA256、成员 CRC 和成员 SHA256。

```sh
set -e
shasum -a 256 -c SHA256SUMS
unzip -t flutter-ios-encrypted-r1.zip
originals="$(mktemp -d)"
manifest="$PWD/SHA256SUMS.members"
unzip -q flutter-ios-encrypted-r1.zip -d "$originals"
(cd "$originals" && shasum -a 256 -c "$manifest")
```
