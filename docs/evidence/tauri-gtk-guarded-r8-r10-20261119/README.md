# Tauri GTK 逐键输入与窗口往返 R8–R10

2026-11-19，三个 Ubuntu 24.04 x86_64 官方作业均打开原生 GTK WebView，通过两条隔离回环 OpenSSH/herdr 连接显示分屏。三轮均未完成逐键输入中的原生窗口往返。[验收汇总](../../74-desktop-split-resize.md#tauri-分屏键盘退出与窗口变化)

| 作业与源码 | 已确认结果 | 原件 |
| --- | --- | --- |
| [R8 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44537084680/job/135608539752)，`fbfb532e4356f64ee77fbda1901fe662ab40547b` | 两侧画面可见，停在 `direct_input_missing`。本轮仅有汇总计数，无法独立确认 A、B 收字节或按键送达情况。 | [原 ZIP](guarded-r8-actions-14537900568.zip) · [Actions 14537900568](https://github.com/Luck9Star/herdr-pocket/actions/runs/44537084680/artifacts/14537900568) |
| [R9 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44544008193/job/135632940824)，`9909213b75fab2cbb1ffcf6fd2124cfc8e42ec98` | B 的原编辑器收到一次可信按键，B 回执匹配，两端独立计数 A／B 为 **0／1**。驱动进入收窄阶段后检测到失焦，停在 `input_focus_lost_narrow`，未到拉宽。 | [原 ZIP](guarded-r9-actions-14540028175.zip) · [Actions 14540028175](https://github.com/Luck9Star/herdr-pocket/actions/runs/44544008193/artifacts/14540028175) |
| [R10 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44550598661/job/135657658787)，`1c281d2579f9ab5d80d78bf49e7f6ecd69a2b39c` | Xvfb 记录指针已在应用启动前安置。B 已获逐键资格，原编辑器在前台并收到一次可信 `keydown`。B 回执缺失，A／B 独立计数为 **0／0**，停在等对端输入，未开始收窄。丢失发生在哪一层仍未知。 | [原 ZIP](guarded-r10-actions-14544590344.zip) · [Actions 14544590344](https://github.com/Luck9Star/herdr-pocket/actions/runs/44550598661/artifacts/14544590344) |

R9 与 R10 的 Tauri、Rust 传输和工作流源码一致。manifest 的 `receivedInputBytes` 汇总字段在这些未完成的运行中均为 0。R9 与 R10 的逐侧结论来自各自 ZIP 内的 `s06-tauri-first-direct-key.json`。R9 窄窗记录的 `armed=true` 表示此前安装的观察器仍在，R9 的 `neverBlurred=false` 则记录原编辑器已失焦。各轮记录临时授权已撤销、受控进程已停止、临时密钥已删除。

## 本地组件对照

使用 Ubuntu 24.04 arm64 的 WebKitGTK 2.52.6 运行 R9/R10 同源前端和 xterm。实际键盘和窗口由原生 GTK 驱动，两侧连接、帧与输入受理由隔离 IPC 夹具提供。裸 Xvfb 缩窄时，默认指针从窗口内落到外部。编辑器先收到失焦，随后页面才收到 700px 的 resize。直接发出 X11 原生 resize 也复现。应用随即退出逐键输入，B 成为 `#view-content` 单面板，旧的子面板查询随之失配。

R10 的驱动提前将指针安置在宽窄窗口的共同区域。组件对照完成 1440→700→1440，B 保持原编辑器、前台和回执，A 回宽后恢复同一目标的只读观察并显示新帧。主动移出指针仍使 B 退出逐键输入。另一轮中手动暂停保持到明确点击恢复，且只恢复被选中的 A。同一次官方原生 Tauri 双 SSH 运行中的逐键窗口往返仍待验证。[R10 驱动改动](https://github.com/Luck9Star/herdr-pocket/commit/1c281d2579f9ab5d80d78bf49e7f6ecd69a2b39c)

## 校验原件

三个 ZIP 的 SHA-256 与 Actions 工件 API 摘要相同。已核对全部 31 个成员的 CRC、内部清单的 25 项 SHA-256，以及三张 1440×1200 PNG 的像素尺寸、解码和辅助块。三张图均为开启逐键前的分屏，终端内容由夹具生成。成员仅含脱敏结果、公开契约、依赖锁、布局和字体测量、取证截图及摘要清单。[ZIP SHA-256](SHA256SUMS) · [成员 SHA-256](SHA256SUMS.members)

从仓库根目录运行以下命令。成功时，各 ZIP 和解出的成员均显示 `OK`。

```sh
set -e
cd docs/evidence/tauri-gtk-guarded-r8-r10-20261119
shasum -a 256 -c SHA256SUMS
archive_dir="$PWD"
proof="$(mktemp -d)"
for zip in guarded-r*-actions-*.zip; do
  round=${zip#guarded-}
  round=${round%%-*}
  unzip -t "$zip" && unzip -q "$zip" -d "$proof/$round" || exit 1
  (cd "$proof/$round" && shasum -a 256 -c SHA256SUMS) || exit 1
done
(cd "$proof" && shasum -a 256 -c "$archive_dir/SHA256SUMS.members")
```
