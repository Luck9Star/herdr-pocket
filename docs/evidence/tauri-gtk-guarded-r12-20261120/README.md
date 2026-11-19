# Tauri GTK R12 原生逐键窗口往返与双 SSH 关闭

2026-11-20，Ubuntu 24.04 x86_64 托管作业使用同一个原生 GTK WebView 和两条真实回环 OpenSSH/herdr 连接，通过首键、逐键窗口往返、退出逐键和主动关闭检查。本次运行使用 `e6fb0683ba69b19ca9f2dc801bf1e52a1a375311`，设备身份保存在测试进程内。[Actions 作业 135715596467](https://github.com/Luck9Star/herdr-pocket/actions/runs/44566906610/job/135715596467) · [Actions 工件 14554241941](https://github.com/Luck9Star/herdr-pocket/actions/runs/44566906610/artifacts/14554241941) · [原始 ZIP](guarded-r12-actions-14554241941.zip)

| 阶段 | 同一次运行的证据 | ZIP 成员 |
| --- | --- | --- |
| 首键 | B 的原编辑器收到一次可信 `keydown`，应用回执匹配，SSH 对端 A／B 收到 0／1 字节。 | `s06-tauri-first-direct-key.json` |
| 窗口往返 | 原生窗口和 WebView 视口均为 1440×1200 → 700×1200 → 1440×1200。三次采样的 DOM 焦点均在 B，B 保留原编辑器、输入资格和回执。A 因收窄暂停，拉宽后回到原列，以同一目标的新完整帧恢复只读观察，可见帧计数由 298 增至 320。 | `s06-tauri-direct-resize.json` |
| 退出逐键 | 一次可信 `Ctrl+Shift+F6` 被应用消费，DOM 焦点移至 A 原有按钮，选中的终端仍为 B，两侧均降为只读，原连接保留且无额外输入。 | `s06-tauri-direct-escape.json` |
| 主动关闭 | 点击 A 的关闭按钮后，原 A 的 socket 已消失，原 B 仍连接。随后点击关闭 B。退出驱动前，两侧各认证一次，两个原连接均匹配合格关闭记录，零 reset，原 socket 均已消失。 | `s06-tauri-peer-close.json` |

两侧对端最终分别收到与预期匹配的 9／1 字节。A／B 的远端 PTY 每 50 ms 采样 1633／1626 次，均保持 119×40，记录中无尺寸变化。驱动确认关闭后，流程完成临时授权撤销、受控进程停止及临时密钥移除，用户授权文件未改动。[原 ZIP 中的 manifest.json](guarded-r12-actions-14554241941.zip)

R11 停在双对端关闭核验，缺少逐侧结论。R12 单次通过，窗口往返、退出逐键及关闭分别留下结构化记录。手动暂停保留和显式单侧恢复由 R7 stock 独立验证。物理输入法、其他平台原生窗口、手机真机和真实组网仍需对应证据。[R11 关闭断点](../tauri-gtk-guarded-r11-20261119/README.md) · [R7 手动暂停](../tauri-gtk-focus-resize-r7-20261119/README.md#stock-原生窗口与双-ssh) · [验收汇总](../../74-desktop-split-resize.md#tauri-分屏键盘退出与窗口变化)

## 校验原件

ZIP 为 164863 字节，SHA-256 为 `ec19a795d73539c561725283c5e528c32c2c2c70c9417e120f372ea01bc371e5`，与 Actions API 摘要一致。已核验 14 个成员的 CRC、12 项内置 SHA-256 和每个成员的独立摘要。唯一一张 PNG 是开启逐键前的 1440×1200 初始分屏原图，已核验解码和辅助块。窗口往返、焦点和关闭使用结构化记录。[ZIP SHA-256](SHA256SUMS) · [成员 SHA-256](SHA256SUMS.members)

从仓库根目录核验。

```sh
set -e
cd docs/evidence/tauri-gtk-guarded-r12-20261120
shasum -a 256 -c SHA256SUMS
archive_dir="$PWD"
proof="$(mktemp -d)"
unzip -t guarded-r12-actions-14554241941.zip
unzip -q guarded-r12-actions-14554241941.zip -d "$proof/r12"
(cd "$proof/r12" && shasum -a 256 -c SHA256SUMS)
(cd "$proof" && shasum -a 256 -c "$archive_dir/SHA256SUMS.members")
```
