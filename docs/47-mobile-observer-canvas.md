# 手机持续观察的画布尺寸

2026-11-08。刚完成配对的主机和已保存主机的终端标签都可以在连接前选择 80×24、120×40 或 160×50。默认 80×24。用户可以在窄屏内上下、左右阅读；切标签、弹键盘和本地滚动均不需要调整共享 PTY。已发布的两份 `7470d5c` Android 测试包早于这项改动。[上批 APK 与配对验收](46-android-pairing-handoff-validation.md)

## 观察画布与远端尺寸

herdr 0.9.5 / protocol 22 根据观察者请求的矩形绘制。每帧的 `width`、`height` 是该帧可以读取的行列范围。快照没有报告共享 PTY 的实时尺寸。因此由用户选择观察范围，客户端以收到的合法尺寸绘制；共享 PTY 的尺寸在独立夹具内实测。[观察命令与帧输出](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/client/terminal_sessions.rs) · [服务端绘制](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/server/headless/render.rs)

画布属于本次观察或当前标签。连接后保持所选画布，重新选择须先停止。首帧必须是全帧。连续序号的全帧可以改变尺寸，增量必须与前一张全帧的尺寸一致。缺字段、错误类型、跳号或尺寸不匹配会结束观察；迟到的帧不能恢复旧连接。客户端限制为 2–512 列、1–512 行、最多 65,536 格。只读单次快照继续使用 80×24。[共享测试向量](../validation/shared/remote-frame-geometry-v1.json) · [传输约定](../validation/shared/remote-contract.json)

两个方向的阅读位置都按目标身份记录在内存。同一目标重新连接后，客户端取得新全帧才恢复位置。文字大小或可见范围变化时，按字符行列换算位置，并限制在当时可滚动的区域。新的目标使用自己的初始位置。[阅读与恢复基线](43-mobile-viewport-recovery.md)

## 实际验证

Penpot 新版沿用手机配色，从 S17 的 342×48 入口可进入 S56–S58 三种选中状态，S59–S60 演示 120×40 的左上和右下阅读位置。已在查看器中点击复核。尺寸与字形的运行证据见下表。[打开画布选择](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=25c76497-7d68-803e-8008-e8fdaa687c09) · [组件与交互读回](../design/evidence/v2-mobile-observer-canvas-review-20261108.json)

| 环境 | 操作与结果 |
| --- | --- |
| Mac，隔离的原版 herdr 0.9.5 | 同一个终端依次以三档画布订阅，每档均收到序号 1 的全帧及序号 2、3 的增量，行列与请求一致。一次性进程在共享 PTY 内取得 16 个尺寸样本，全部为 119×40。观察前 3 个，每档期间各 3 个，停止后 4 个。使用本地 IPC。 |
| Tauri 前端，Mac Chrome 156，合成原生通道 | 在 320 和 390 CSS 像素宽的视口中，新配对入口选 120×40，已存标签选 160×50。触摸拖动产生两轴滚动；继续平移至标记后，全帧与增量标记都落入可见区。已存标签可见第 50 行最右十个字符。两个入口各确认两帧，输入和远端 resize 调用均为 0。直接入口遇到尺寸错误的增量后停止，迟到全帧未生效。 |
| Flutter，Mac Dart 3.11，锁定的 terminal_view 0.5.0 | 7 种网格覆盖 2×1、实际样本尺寸 119×40 及 65,536 格边界。在真实核心缓冲区核对末格、光标与主／备用屏容量。提取自适配器的解析代码通过同一份 22 场景。已写 Flutter widget 回归；新画布的引擎绘制、选择器及备用屏纵向滑杆还需实际设备或模拟器验收。 |
| 独立源码快照 | Rust 传输库 92 项通过；Tauri 前端 389 项通过，Vite 构建成功。Mac 上的 Tauri Rust 命令层已通过编译检查。 |

[机器记录](evidence/mobile-pair-gui/observer-canvas-20261108.json) · [320 像素手机视口的增量标记](evidence/mobile-pair-gui/observer-canvas-direct-320-20261108.png) · [已存标签第 50 行的右边界](evidence/mobile-pair-gui/observer-canvas-tab-320-20261108.png)

## 下一批手机验收

1. 用隔离测试资料配对，经主机确认设备公钥，核验 SSH 主机指纹。从手机看板主动选择 pane；原版 herdr 场景在连接前选 120×40，受保护输入场景保留 80×24。
2. 测试主机在第 32 行第 92 列写入 `HPWIDE`。手机应在接收全帧和后续增量后，通过本地阅读控件看到这六个字符。检查观察环境的远端输入计数为零、共享 PTY 尺寸稳定，停止后画面陈旧。优先在同批 API 35 模拟器复测两壳。
3. 另行核验 Flutter 带输入场景的首发错误和清理，以及 Tauri 带输入后的撤销确认。在 arm64 真机验证触控、系统键盘和真实中文 IME；iOS、三网实际节点和跨组网并发仍各自待测。

移动方向键和粘贴还要读取目标程序当前的终端模式。真实 curses 操作、原版 herdr 的帧差异，以及候选宿主修订见[手机终端功能键与输入模式验证](48-mobile-terminal-function-keys.md)。
