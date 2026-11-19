# Tauri Android 加密私钥与主机换钥证据

2026-11-19，`direct-ssh-api35` 在 Google APIs x86_64 API 35 模拟器上通过 `encrypted-key-rotation`。固定源码为 `7d81500817e0afbc42f8924585be8a380ad4cf38`。Tauri Android WebView 通过原生 SSH 命令连接同一受控回环端点，输入由 CDP 提交。此作业的设备、网络与输入范围限于该配置。[作业 135472506072](https://github.com/Luck9Star/herdr-pocket/actions/runs/44498717182/job/135472506072) · [固定版本工作流](https://github.com/Luck9Star/herdr-pocket/blob/7d81500817e0afbc42f8924585be8a380ad4cf38/.github/workflows/tauri-android-direct-ssh.yml)

[原始证据 ZIP](tauri-android-key-rotation.zip) 完整保留官方工件的 395,776 字节。ZIP 及其中 10 个文件的 SHA-256 见[校验清单](SHA256SUMS)。报告与三张 PNG 均只存于 ZIP 内。[官方工件 14516986814](https://github.com/Luck9Star/herdr-pocket/actions/runs/44498717182/artifacts/14516986814)

## 同一端点的四条连接

`tauri-direct-evidence/manifest.json` 的 `rotationEncryptedKey` 记录了界面动作和夹具计数。首次确认 A 后，第二条连接呈现 B，界面阻止认证。取消核对后保留 A，用户重新探测并显式确认 B，第四条连接才接受临时加密 OpenSSH Ed25519 私钥对应的公钥。

| 连接 | 主机密钥 | 认证尝试 | 认证成功 | PTY | shell | 输入字节 | 输出字节 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 首次探测 | A | 0 | 0 | 0 | 0 | 0 | 0 |
| 2 换钥拒绝 | B | 0 | 0 | 0 | 0 | 0 | 0 |
| 3 显式重探 | B | 0 | 0 | 0 | 0 | 0 | 0 |
| 4 确认后连接 | B | 2 | 1 | 1 | 1 | 9 | 102 |

驱动记录终端输入、远端回显、主动断开和凭据清空。服务端记录四条连接均已关闭。`cleanup` 中 `browser`、`application`、`forward`、`reverse` 和 `fixtureConnections` 五项均为真。`avd-evidence/lifecycle.txt` 单独记录专属模拟器进程以状态 0 退出，首次检查即确认设备串号已消失。

## 原图与 OCR

下列文件均位于 ZIP 的 `tauri-direct-evidence/` 下。

| 原图 | 原始像素 | 取证方式与用途 |
| --- | --- | --- |
| `s10-host-key-change-android.png` | 1081×2341 | CDP 截取的主机换钥核对页 |
| `ssh-rotation-terminal-android-webview-before.png` | 1081×2341 | CDP 截取的终端 WebView，对照设备画面 |
| `ssh-rotation-terminal-android.png` | 1080×2340 | `adb exec-out screencap -p` 获取的设备原图，终端 OCR 的输入 |

`ssh-rotation-terminal-android.json` 与主报告中的 `terminalScreenshot` 一致。`imageSha256` 与 `webViewBeforeSha256` 分别匹配设备原图和 WebView 对照图。官方 Tesseract 5.3.4 在设备原图的终端区域（左 99、上 500、宽 875、高 769 像素）首次以 PSM 6 连续识别出回显标记和随后的两行合成词。本次归档用 macOS Vision 对同一原图的同一矩形独立核对，三行顺序匹配。

## 核验与复跑

在本目录运行以下命令可逐项验证 ZIP 和所有成员，无需解压到磁盘。

```sh
python3 - <<'PY'
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

archive = Path('tauri-android-key-rotation.zip')
lines = Path('SHA256SUMS').read_text().splitlines()
checks = {name: digest for digest, name in (line.split(None, 1) for line in lines)}
assert sha256(archive.read_bytes()).hexdigest() == checks.pop(archive.name)
with ZipFile(archive) as z:
    assert z.testzip() is None and sorted(z.namelist()) == sorted(checks)
    for name, digest in checks.items():
        assert sha256(z.read(name)).hexdigest() == digest, name
print(f'ZIP 与 {len(checks)} 个成员的 SHA-256 均匹配')
PY
```

复跑来源为原运行 `44498717182` 的 `workflow_dispatch` 事件及 `scenario=encrypted-key-rotation` 输入。以下命令请求按原 SHA 和原输入重跑。

```sh
gh run rerun 44498717182 --repo Luck9Star/herdr-pocket
```
