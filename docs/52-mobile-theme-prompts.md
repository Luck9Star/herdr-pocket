# 手机终端的 Powerlevel10k 与 Oh My Posh 样例

2026-11-08。手机打开已配对的终端，进入「字体与字符诊断」，可以在字符列宽、Powerlevel10k 和 Oh My Posh 之间切换。后两项使用同一份真实引擎输出和包内 Nerd Font，分别显示预期与本地终端计算的光标位置。窄屏可在诊断区域横向阅读。关闭后回到原观察页，草稿仍属于原目标。[功能源码](https://github.com/Luck9Star/herdr-pocket/commit/1cea5a27b035b7a36750ce0cf6d4be53ff124da5) · [原字符与组合重音检查](42-mobile-terminal-font-diagnostics.md)

## 两个可复现的提示符

在两个独立的临时目录运行固定引擎和配置，工作目录名为「中文」。两次生成的 ANSI 字节完全相同，样例包含目录图标、Powerline 分隔符和带颜色的提示符。共享 JSON 的 SHA-256 为 `1b86567e91ad08dc8c4d74a593b94da9946dd3515f610c0ca9a11976b92f3e6d`。[版本与复跑步骤](../validation/theme-prompts/README.md) · [输入数据](../validation/shared/theme-prompt-samples-v1.json)

| 引擎 | ANSI 长度 | 手机界面中的预期光标 | Mac 实测 |
| --- | ---: | --- | --- |
| Powerlevel10k 1.20.0，zsh 5.9 | 225 字节 | 第 1 行、第 15 列 | xterm.js 和两份 terminal_view 核心均到达该位置 |
| Oh My Posh 31.9.1 | 190 字节 | 第 1 行、第 16 列 | xterm.js 和两份 terminal_view 核心均到达该位置 |

诊断网格为 40 列 × 3 行。界面从 1 开始数行和列；测试记录使用零基 `(列, 行)`。这些样例覆盖目录段和提示符字符。Git 分支及脏状态、异步重绘、真实 IME 与运行交互主题时的光标移动仍需用实际会话验收。

## 绘制与交互实测

- Mac Chrome 在 320 与 390 CSS px 下分别打开两种主题，共四个场景。页面横向溢出为零，诊断区可横移 98 与 28 px。Chrome 报告目录图标所在行使用包内 JetBrainsMonoNFM-Regular，两个中文字符使用系统 PingFangSC-Regular。返回原控件成功，合成连接上未发生终端输入或远端 resize 调用。测试浏览器已关闭。[绘制、字体和坐标数据](evidence/mobile-pair-gui/mobile-theme-prompts-20261108.json)
- 在锁定的 Dart 终端核心上分别写入两个原始样例，基准和组合重音修订版均得到表中的坐标。Flutter 的窄屏、草稿保留和错位提示已增加 widget 测试，本轮未在 Flutter 引擎或手机上执行。
- 独立原型源码的 Tauri Node 测试 463 项通过，Vite 构建通过。Flutter 资源准备与两套打包路径测试 6 项通过。原始文件、Tauri 静态资源与最终前端分发目录中的 JSON 字节一致。Android 驱动两组分别 89、87 项通过；这两组在 Mac 上运行。

## 已保存的交互原型

原有 S45 增加主题样例入口。查看器重载后，已实际点击 S45 → Powerlevel10k → Oh My Posh → S45。主题状态画板保留靛蓝配色，将字体示意与应用实测位置分列。[Penpot · Powerlevel10k](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=0d4ede31-cfe7-8093-8008-e9356c1b4337) · [Penpot · Oh My Posh](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=0d4ede31-cfe7-8093-8008-e9356c2c8086) · [保存、交互和两张导出的记录](../design/evidence/v2-theme-prompts-20261108.json)

## 下一批设备验证

两套 Android 驱动已接到正常的配对与观察流程。在原有 16×8 检查后，依次选择两个主题，取当前终端的实际尺寸和光标，对照同一份锁定输入。样例缺失、旧选择的迟到读数、未知字段或错列都会使主题检查失败。

下一批一起验收[手机受阻窗格入口](51-mobile-blocked-targets.md)、这两种主题，以及 [Flutter 带输入 TUI 的恢复](50-android-paired-tui-validation.md)。当前可下载的 APK 来自较早的 `2b497ea`。实际 Android／iOS 绘制、实体键盘与触控、真实 SSH 下主题异步刷新及三网并发仍未验证。
