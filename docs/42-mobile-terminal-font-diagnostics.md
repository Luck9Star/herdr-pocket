# 手机终端的字体与字符诊断

2026-11-08 新增 Powerlevel10k 和 Oh My Posh 的真实提示符样例。两套手机诊断使用同一份引擎输出；列位置、Mac 字体回退与下一批设备步骤见[主题对照记录](52-mobile-theme-prompts.md)。

2026-11-07。Flutter 与 Tauri 候选在手机终端的正常观察页增加了「字体与字符诊断」。新配对和从已保存主机打开的终端均可进入。收到选定目标的全量画面后即可检查字形，原厂只读 herdr 也能使用。结果来自以下源码和 Mac 实验；当前可下载的 Android 包仍为 `1d604fa`。[检查数据](evidence/mobile-pair-gui/terminal-font-diagnostics-20261107.json) · [现有 Android 包与配对链路](40-android-paired-dashboard-validation.md)

## 在手机上怎么检查

1. 从主机看板选择一个终端，等到当前目标画面出现，再打开诊断。两条路线以相同的本地字体文件、当前字号和固定的 16 列 × 8 行绘制独立只读终端。打开时撤销输入许可，原会话继续观察，未发送草稿留在原目标。
2. 从上到下核对 ASCII、Powerline 分隔符、Nerd Font 私用区图标、中文、组合重音、普通 emoji、组合 emoji 和 ANSI 粗红字。八行右侧的 `|` 应位于第 15 列。图例的预期宽度只统计样例正文。特别检查第五行小写 e 上的尖音符与大写 A 上的圆圈是否可见，以及第七行两个 emoji 的右边界。[共用样例与原始输入字节](../validation/shared/terminal-font-diagnostics-v1.json)
3. 若提示符图标缺失，可自行选择无图标主题；诊断只在本机绘制样例。关闭后回到观察，要输入时须重新选择模式。诊断本身不向 SSH 发送字符，也不会改变共享 PTY 大小。

## 本轮实测

| 范围 | 结果 |
| --- | --- |
| Tauri · Mac Chrome 156 | 320 × 820 和 390 × 820 两种视口，分别经新配对表单和已保存标签进入。四个场景均通过触摸打开与关闭、Tab 焦点隔离、Esc 返回安全按钮、草稿保留及离开时关闭。真实 xterm 屏幕为 134 × 144 CSS 像素，八行均可见，宽度未溢出；连接和 SSH 使用替身，四个场景的远端发送与 resize 请求均为 0。[320 像素实景](evidence/mobile-pair-gui/font-diagnostics-tauri-320-20261107.png) |
| 字符列与字体回退 | 真实 xterm 使用固定 Unicode provider，八行缓冲区的右界均位于第 15 列，ANSI 粗体、红色和复位均已核对。Chrome 报告图标与重音使用包内 JetBrainsMonoNFM-Regular，中文行使用 PingFangSC-Regular，emoji 行使用 AppleColorEmoji。独立 macOS Core Text 探针从同一 TTF 读取的字形段结果一致。[可复跑的原生字体探针](../validation/native/tool/mac-font-runs.swift) |
| 构建与测试 | 隔离源码下 Node 22.22.2 的 235 项 Tauri 测试通过，Vite 完成 54 模块构建。六项打包路径测试通过，核对了两条候选的资源准备步骤和字节内容。Dart 3.11 解析三份 Flutter 文件；本轮 Flutter analyzer、widget 运行及移动设备绘制尚未验证。 |

图例现在只显示样例名称与预期列数。第一次 Mac 复核发现，若在普通界面字体中再次打印私用区字符，诊断终端已绘出图标时，图例仍可能显示方框。两条路线都去掉了这份重复显示。

## 对应设计与下一次验收

Penpot v2 的 S02 观察页使用原有诊断按钮进入 S45，点击区已增高到 44 设计单位。独立查看器重载后验证了 S45 → S02 → S45。设计稿内两组私用区示例使用固定包内字体生成的静态轮廓；其余终端字形以应用实测为准。[S45 可点击原型](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e8b74585bb97) · [画板导出](../design/evidence/v2-S45-font-diagnostics-20261107.png)

下一批 Android 集中构建同时验收本页与[手机系统键盘](41-mobile-system-keyboard.md)：在同一设备、字号和目标上分别打开两套 GUI，对照八行的可见字形和边界，记录系统键盘显隐、后台恢复和连接持续性。Powerlevel10k／Oh My Posh 的实际提示符、真实中文 IME 和 iOS 字体回退仍需各自的设备结果。两条 GUI 路线继续并行。
