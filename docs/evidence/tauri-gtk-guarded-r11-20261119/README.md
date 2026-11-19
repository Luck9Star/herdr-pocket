# Tauri GTK R11 双 SSH 关闭断点

2026-11-19 UTC，Ubuntu 24.04 x86_64 原生 GTK 守卫作业在同一次运行中完成首键、逐键窗口往返和后续输入检查，最终未确认两条 SSH 在退出驱动前均已关闭。运行源码为 `d35b2e80836533df8e7b83a380f89d1dcad26bbc`。[Actions 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44561620244/job/135695767673) · [Actions 工件 14550777195](https://github.com/Luck9Star/herdr-pocket/actions/runs/44561620244/artifacts/14550777195) · [原始 ZIP](guarded-r11-actions-14550777195.zip)

## 首键与窗口阶段

`s06-tauri-first-direct-key.json` 记录 B 的原编辑器在前台可写，收到一次可信 `keydown`。事件到达原编辑器的现有处理器之后，`defaultPrevented` 为真。B 回执匹配，原 SSH 对端 A／B 的独立首键计数为 **0／1**。IPC 资源时序在该 WebView 中不可用。

最终错误为 `s06_tauri_close_s06_tauri_peer_close_unconfirmed`。按本轮驱动的执行顺序，错误之前已通过 1440→700→1440 及原编辑器保留、A 布局暂停后只读恢复的检查，也通过了可信退出组合键、草稿和迟到输入隔离。原件里的 PNG 是开启逐键前的初始分屏。窗口各阶段的尺寸和焦点样本当时只在整轮成功后写入，R11 ZIP 未保留这些逐阶段数据。[冻结驱动](https://github.com/Luck9Star/herdr-pocket/blob/d35b2e80836533df8e7b83a380f89d1dcad26bbc/validation/remote-harness/s06_tauri_gui.py) · [R8–R10 记录](../tauri-gtk-guarded-r8-r10-20261119/README.md)

## 关闭证据

驱动进入对端等待前已经点击两侧的「关闭此标签」，确认两块面板移除及工作台隐藏。现有工件无法判定缺证来自哪一侧、是否产生额外认证，或是 sshd 已终结连接但未找到合格的终止记录。后续的密钥撤销、受控进程停止及临时密钥移除均完成。这些清理记录与退出前的 SSH 关闭检查是独立证据。[验收汇总](../../74-desktop-split-resize.md#tauri-分屏键盘退出与窗口变化)

## 校验原件

ZIP 的长度为 161959 字节，SHA-256 与 Actions API 摘要一致。11 个成员的 CRC、9 项内置 SHA-256 和全部成员摘要均已核对。1440×1200 PNG 已解码并核对，画面只显示隔离夹具。成员包含脱敏 manifest、布局和首键取证、公开契约、依赖锁、字体记录和初始截图。[ZIP SHA-256](SHA256SUMS) · [成员 SHA-256](SHA256SUMS.members)

从仓库根目录核验。

```sh
set -e
cd docs/evidence/tauri-gtk-guarded-r11-20261119
shasum -a 256 -c SHA256SUMS
archive_dir="$PWD"
proof="$(mktemp -d)"
unzip -t guarded-r11-actions-14550777195.zip
unzip -q guarded-r11-actions-14550777195.zip -d "$proof/r11"
(cd "$proof/r11" && shasum -a 256 -c SHA256SUMS)
(cd "$proof" && shasum -a 256 -c "$archive_dir/SHA256SUMS.members")
```
