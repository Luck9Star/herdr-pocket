# 手机终端的键盘收起与重新展开

2026-11-07。手机在配对审查、主机确认、设备密钥连接和看板选定终端后，默认持续观察。键盘控件位于当前终端的输入操作区。此页记录后续原型源码；可下载的两个 arm64 APK 和四个 Android 模拟器场景对应较早的 `1d604fa`。[测试包与设备密钥链路](40-android-paired-dashboard-validation.md) · [本次检查数据](evidence/mobile-pair-gui/mobile-system-keyboard-20261107.json)

## 手机操作

| 用户操作 | 本地和远端的行为 |
| --- | --- |
| 只读观察 | 看板和终端继续接收更新，键盘控件禁用。 |
| 选择逐键或草稿后点「展开键盘」 | 针对当前已核验终端的编辑器请求显示系统键盘。草稿内容保存在本地，仍要显式发送。 |
| 点应用内「收起键盘」 | 回到观察，撤销输入许可，保留原目标草稿。再次输入需重新选择模式。旧输入回调和未发送队列不可随重新启用而恢复。 |
| 按系统返回键 | 系统自行关闭输入法。当前编辑器仍有有效许可时可以请求重新展开；焦点或许可丢失时要重新选择模式。测试时分别记录窗口、焦点与模式。 |
| 切换目标、标签或进入后台 | 丢弃失效输入和迟到的组合文本。键盘和布局变化只调整本地视口。 |

Tauri 在新配对表单和已保存标签中复核当前 pane、观察代次、输入模式与编辑器。Android 原生插件只接收动作和一次性手势编号，回到前台 WebView 检查焦点、时限和手势后请求系统输入法。Android 文档将显示和隐藏调用定义为请求，结果需要另行观察。[InputMethodManager](https://developer.android.com/reference/android/view/inputmethod/InputMethodManager) · [Android 输入法可见性](https://developer.android.com/develop/ui/views/touch-and-input/keyboard-input/visibility)

## 已保存设计

Penpot v2 延用 Tech Indigo 配色。S03 原有收起按钮通向 S43；S43 表示已撤权、草稿保留；S44 演示同一编辑器仍有许可时再次展开。查看器重载后实点 S44 → S03 → S43，并验证 S43 与 S44 往返。S03 原按钮点击区域为 64 × 42 设计单位，实机触控仍待检查。[S43 收起并锁定](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e8acfe51be24) · [S44 再次展开](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e8acfe6fa8fe) · [读回、点击记录与截图摘要](../design/evidence/v2-mobile-keyboard-20261107.json)

## 本地结果

- Mac 无头 Chrome 156 使用 CDP 触摸，在 320 × 820、390 × 820 两个视口分别经过新配对表单和已保存标签。两轮分别使用浏览器键盘替身、异步 Android 手势回调替身，共八个场景。每个场景观察时两键禁用，连续两次展开保留同一编辑器，收起保留草稿。模拟迟到组合文本和切换目标后，远端发送与 resize 调用数均为零。四个异步回调场景各有五个有效手势通过校验。
- 基于上一原型提交提取此次变更，Node 22.22.2 运行 226 项 Tauri 测试全部通过，Vite 构建通过。Mac Rust 宿主库 41 项通过；Kotlin 2.2.21 在 JVM 合成平台对象上运行键盘及剪贴板插件探针通过。Mac 宿主和浏览器均未打开 Android 系统输入法。
- Flutter 的应用内收起会撤销当前输入许可。检测到原本可见的键盘底部遮挡消失时，页面也撤销许可，以防系统返回后焦点仍由旧输入框持有。Dart 3.11 单独执行了真实输入队列的两个情形：旧请求有回执时只放行重新选择后产生的新输入，旧请求结果未知时也拦住新输入，原队列都没有重放。此批 Flutter widget 套件及 Android 系统窗口尚待集中运行。
- 使用含加密依赖的隔离 Python 环境，Flutter 驱动 58 项、Tauri 驱动 15 项、共享夹具 32 项和 POSIX helper 15 项全部通过。新增驱动在发送一次系统返回键前先核对测试应用窗口归属和输入法确实可见，要求两次连续采样；Flutter 另采集窗口遮挡高度。缺少系统证据时该场景无法通过。

## 下一批 Android 实测

1. 在一次性 API 35 模拟器用两套 GUI 分别走配对审查、设备密钥 SSH、选定 pane 和持续观察。只读场景核对输入法窗口隐藏、远端收到零字节。
2. 在受保护输入场景，分别展开、收起、重新选模式。在草稿中按一次 Android 系统返回键，再从同一目标重新展开。核对窗口实际显隐、焦点、原草稿、接收端字节及共享 PTY 采样。遇到归属不明、读数矛盾或发送结果未知，停止该次验收。
3. 同一台 arm64 手机上用真实中文输入法检查候选栏、组合期间切换目标、单次提交和软键盘遮挡。另验收相机扫码、iOS 真机和三网前台并发，保留两条候选直至正确性有可比较的设备结果。

同批手机复测还应从当前终端打开[字体与字符诊断](42-mobile-terminal-font-diagnostics.md)，比较两个候选的字形、列宽与恢复输入前的观察状态。
