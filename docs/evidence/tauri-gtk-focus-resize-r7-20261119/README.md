# Tauri GTK 分屏键盘与窗口验收 R7

2026-11-19，两轮 R7 在 Ubuntu 24.04 x86_64 的原生 GTK WebView 各完成两条真实回环 OpenSSH/herdr 连接。两轮使用 `5e50a4d5a7b688b36adda16b970486b18986b274`。A、B 各用一个进程内测试身份连接不同的命名会话。两个会话的 pane 名均为 `w1:p1`，稳定终端 ID 各不相同。[验收汇总](../../74-desktop-split-resize.md#tauri-分屏键盘退出与窗口变化) · [冻结工作流](https://github.com/Luck9Star/herdr-pocket/blob/5e50a4d5a7b688b36adda16b970486b18986b274/.github/workflows/paired-gui-validation.yml)

| 模式 | 结果 | 作业与原件 |
| --- | --- | --- |
| stock，原版 herdr 0.9.5 | 通过，原生窗口 1440 → 700 → 1440，原 SSH 对端 A／B 分别收到 0／0 字节 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44533698168/job/135593449788) · [工件 14533849813](https://github.com/Luck9Star/herdr-pocket/actions/runs/44533698168/artifacts/14533849813) · [原 ZIP](stock-r7-actions-14533849813.zip) |
| guarded，同源码的隔离受保护输入扩展 | 通过，固定 1440 × 1200 原生窗口，原 SSH 对端 A／B 分别收到 9／1 字节 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44533705204/job/135596416871) · [工件 14536696752](https://github.com/Luck9Star/herdr-pocket/actions/runs/44533705204/artifacts/14536696752) · [原 ZIP](guarded-r7-actions-14536696752.zip) |

## Stock 原生窗口与双 SSH

原生 WebDriver 从正常首页操作，独立核对两个设备身份和两条 SSH 的认证记录，再从实际快照选择终端。原生窗口矩形与 WebView 视口分别读取，均经历 1440 × 1200 → 700 × 1200 → 1440 × 1200。收窄时 A 因布局暂停，B 继续观察。回宽后，B 在左、A 在右，横坐标分别为 265 和 839 像素，宽度均为 560 像素。纵坐标随取证滚动变化。B 的逻辑选中状态保持，DOM 焦点采样为 B 面板、面板外、面板外。[冻结驱动](https://github.com/Luck9Star/herdr-pocket/blob/5e50a4d5a7b688b36adda16b970486b18986b274/validation/remote-harness/s06_tauri_gui.py)

回宽时 A 在同一目标取得新完整帧。可见终端取证计数 A／B 由 339／339，经窄窗 B 的 346，推进至回宽后的 392／392。驱动实际点击「返回主机看板」并等两侧均暂停，随后点击「终端」返回原分屏并收起配对资料。第二轮收窄和回宽后，两边仍暂停且旧画面保持 400／399。驱动点击「设为输入焦点」选中 A，随后点击「恢复观察」。只有 A 恢复，取得新完整帧且推进至 416，B 保持暂停及旧画面 399。截图和计数在各阶段分别采集。[stock ZIP 中的 manifest.json](stock-r7-actions-14533849813.zip)

原 SSH 对端各只认证一次，各接收零字节，分别在 WebDriver 退出前确认关闭。A／B 的远端 PTY 每 50 ms 采样，共 1682／1680 次，均保持 119 × 40，记录中无尺寸变化或 `SIGWINCH` 通知。临时授权已撤销，所属进程已停止，临时密钥已移除，用户授权文件未改动。应用的 80 × 24 本地观察画布独立于远端 PTY。[stock ZIP 中的 manifest.json](stock-r7-actions-14533849813.zip)

## Guarded 原生逐键退出

固定 1440 × 1200 窗口中，B 先主动输入 1 字节，再以真实 WebDriver 键盘按一次 `Ctrl+Shift+F6`。`guardedDirectEscape` 六项均为真。应用消费可信组合键，DOM 焦点移至 A 原有的「设为输入焦点」按钮，选中的目标仍是 B，原目标与两条原 SSH 均保留，双侧处于只读观察，SSH 对端未收到额外字节。随后 A 显式发送草稿，A／B 最终收到且逐字节匹配 9／1 字节。每侧只认证一次，驱动退出前两条 SSH 均关闭。两个 PTY 每 50 ms 采样 1597／1590 次，均保持 119 × 40，临时授权、进程及密钥清理通过。[guarded ZIP 中的 manifest.json](guarded-r7-actions-14536696752.zip)

ZIP 中的 `s06-tauri-connected.png` 是开启逐键输入前的双侧工作台原图，退出时的焦点、观察状态及对端字节由 manifest 和驱动验证。[guarded 原 ZIP](guarded-r7-actions-14536696752.zip)

## 修前与修后的原图

下表列出 Actions ZIP 中的 PNG 成员。两轮分别创建隔离的设备身份和会话，账本在各轮内核对原终端和原连接。截图用于比较同尺寸的工作台排版和终端画面，状态、目标与字节以 manifest 或失败诊断为准。R6 失败图保留过期的暂停提示，结构化诊断记录 A 断开、B 暂停。R7 的手动暂停图在明确恢复 A 前捕获。[R6 stock 原 ZIP](../tauri-gtk-focus-resize-r6-20261119/stock-r6-attempt2-actions-14532718510.zip) · [R7 stock 原 ZIP](stock-r7-actions-14533849813.zip)

| 场景 | 像素尺寸 | R6 stock ZIP 成员 | R7 stock ZIP 成员 |
| --- | --- | --- | --- |
| 初始宽屏，两侧独立观察 | 1440 × 1200 | `s06-tauri-resize-wide-before.png` | `s06-tauri-resize-wide-before.png` |
| 窄屏，仅显示 B，A 收纳 | 700 × 1200 | `s06-tauri-resize-narrow.png` | `s06-tauri-resize-narrow.png` |
| 回宽，两侧画面推进 | 1440 × 1200 | `s06-tauri-resize-wide-restored.png` | `s06-tauri-resize-wide-restored.png` |
| 看板返回后的手动暂停 | 1440 × 1200 | `s06-tauri-manual-return-failure.png`，返回断点 | `s06-tauri-resize-manual-paused.png`，返回并完成第二轮宽度往返 |

## 修复范围与复跑

R6 暂停时原生端切换观察 epoch 并撤下帧确认，前端却仅按连接 token 判断 ACK 失败，可能把同一条已暂停的连接误当作需要取消。保留的官方记录展示 A 的断开结果。生产前端在 Chromium 151 和 WebKit 26.5 中使用实际 GUI 按钮与隔离 IPC 重现了 ACK 迟到后的断开，并复核修后的双暂停、单侧恢复和新完整帧。`5e50a4d` 将帧、解析回调和确认结果绑定到原连接、当前观察 epoch 和控制版本，同时检查暂停和关闭状态。当前观察的 ACK 失败仍会取消该连接，过期结果无需重试。[产品源码修复](https://github.com/Luck9Star/herdr-pocket/commit/5e50a4d5a7b688b36adda16b970486b18986b274) · [定向回归](../../../validation/tauri/test/desktop-split.test.mjs)

D1 的焦点退出（`0aa046d`）和标签切换（`d4aa60a`）先把 DOM 集合转成数组再枚举按钮。原生 guarded 在固定宽屏核对可信 `Ctrl+Shift+F6`、焦点落到另一侧按钮、原选中目标保持和零额外输入。D2 的布局修复（`a065fc0`）在逐键输入时保留实际挂载的 xterm 编辑器。逐键输入中收窄和回宽的 DOM 焦点与原输入租约，由 Chromium 和 WebKit 的受控 IPC 独立覆盖。只读窗口变化由上述原生 stock 覆盖。原生 GTK 逐键期间的窗口变化、物理输入法、系统密钥库及真实组网仍待验收。[D1 浏览器复跑](../tauri-desktop-focus-escape-20261119/README.md) · [D2 浏览器复跑](../tauri-active-input-split-resize-20261119/README.md) · [guarded R6 原件](../tauri-gtk-focus-resize-r6-20261119/README.md#guarded-的逐键退出)

在包含冻结源码的 `codex/` 分支运行 `paired-gui-validation.yml`，两轮都设置 `s06_route=tauri`、`s06_split=true`，guarded 轮再设置 `s06_guarded=true`。合并分支另有 `linux_direct_ssh` 参数，S06 使用 `off`。集成基线 `5a04ad2853d602ed9c2a65edff5c4d4b97b91b20`，归档前集成提交 `6dd86cc9d8213456f50aa6c1b5bb229e1dca2507`。集成前后的 Tauri 产品、Rust 传输与 S06 驱动和运行入口一致，工作流另合入了普通 SSH 密码路径。单独回滚本次 ACK 修复可 revert `5e50a4d5a7b688b36adda16b970486b18986b274`，随后复跑对应模式。[S06 隔离运行说明](../../../validation/remote-harness/README-s06-real-ssh.md)

在 `validation/tauri` 安装锁定依赖后运行定向回归。四个用例覆盖暂停通知前、暂停后、手动恢复到新完整帧后及仍在当前观察时的确认失败。

```sh
node --test --test-name-pattern='split frame acknowledgement failure' test/desktop-split.test.mjs
```

## 校验原件

Actions ZIP 保留原字节。stock／guarded 的 13／9 个成员已逐一校验 CRC，内部 11／7 项 SHA-256 一致。六张 PNG 为未裁切的原生视口原图，逐张解码核对尺寸。ZIP 内只有脱敏 manifest、公开契约、依赖锁、布局测量、字体版本与夹具画面。画面中的终端文本由隔离夹具生成。私钥、实际会话内容和原始对端日志未归档。成员校验清单同时覆盖 Actions 的内置 `SHA256SUMS` 和后来附入的 GTK 字体记录。[ZIP SHA-256](SHA256SUMS) · [成员 SHA-256](SHA256SUMS.members)

在本目录核验并解开原件。解开的 PNG 可直接用于上表对照。

```sh
set -e
shasum -a 256 -c SHA256SUMS
archive_dir="$PWD"
proof="$(mktemp -d)"
unzip -t stock-r7-actions-14533849813.zip
unzip -q stock-r7-actions-14533849813.zip -d "$proof/stock"
(cd "$proof/stock" && shasum -a 256 -c SHA256SUMS)
unzip -t guarded-r7-actions-14536696752.zip
unzip -q guarded-r7-actions-14536696752.zip -d "$proof/guarded"
(cd "$proof/guarded" && shasum -a 256 -c SHA256SUMS)
(cd "$proof" && shasum -a 256 -c "$archive_dir/SHA256SUMS.members")
```
