# 手机终端的功能键与输入法边界

2026-11-08。Flutter 与 Tauri 原型源码增加了可展开的 F1–F12、Insert、Delete、Backspace 和 Shift+Tab。新配对连接页与已保存主机标签共用输入约束：先审查目标、收到新全帧，再明确选择逐键模式。连接原版 herdr 0.9.5 时，两壳保持只读；输入需要同一已认证连接上核验成功的保护扩展。[保护扩展与接收回执](../validation/herdr-input-extension/README.md)

本批运行证据包含 Mac Chrome 手机视口中的真实 curses 操作闭环，原生与传输接口使用合成桥。Flutter 的本地结果包含生产编码到真实 PTY 的操作，以及 IME 源码探针；没有新增手机安装包或设备验收。[机器记录](evidence/mobile-pair-gui/terminal-function-keys-20261108.json)

## 按键与组字

功能键区可以展开、收起并随页面滚动。Ctrl、Alt 只影响下一次明确点击的辅助键，随后释放。F1–F12、Insert、Delete 使用 xterm 修饰参数；Backspace 固定发送 DEL（`7f`），Shift+Tab 发送 `CSI Z`。后两者的 Ctrl／Alt 组合未定义，点击后不发送，修饰仍会释放。两壳使用同一份[编码向量](../validation/shared/terminal-function-keys-v1.json)。本机 `xterm-256color` 的 `kbs` 为 Ctrl-H。手机辅助键沿用 DEL；Ctrl+Insert 在手机辅助栏按显式按键编码，实体键盘沿用终端自身的复制快捷键策略。[xterm 功能键编码](https://invisible-island.net/xterm/ctlseqs/ctlseqs.html#h3-Function-Keys) · [项目锁定的 xterm.js 6.0.0 键盘实现](https://unpkg.com/@xterm/xterm@6.0.0/src/common/input/Keyboard.ts)

观察、草稿、失焦、隐藏、旧目标和结果未知时，辅助键不能发送；已有未确认输入不会重放。收起功能区会撤销其旧按钮回调，收起键盘沿用撤销输入许可的规则。画布和阅读位置仍只在本地改变。[键盘收起与恢复](41-mobile-system-keyboard.md) · [观察画布与阅读](47-mobile-observer-canvas.md)

Flutter 的受控 IME shim 在实际 `TextInputClient` 更新后、处理组合或提交文本前通知页面，并提供只读编辑值供按钮当场复查。相同文字的组合范围变化也会清除 Ctrl／Alt、撤销旧动作。功能区展开／收起保留编辑连接；键盘可见本身不表示正在组字。源码探针覆盖了组字期间 F1 与原辅助键零发送、中文提交一次、之后再次明确点击 F1，以及迟到编辑回调不能改变新代次。真实 Flutter 编辑通道、系统输入法与触控仍须在 SDK 和设备上复核。[shim 与来源校验](../validation/flutter/patches/ime-observation-manifest.json)

## 本地闭环的范围

Mac Chrome 156 使用触摸事件，在以下入口操作同一个合成 curses 界面。浏览器显示实际 PTY 输出，按钮产生的字节送回该专属 PTY；配对、设备存储、宿主 IPC 和 SSH 由合成接口代替。

| 手机视口（CSS 像素） | 入口 | 实际结果 |
| --- | --- | --- |
| 320×820 | 新配对连接页 | 选中 Review、编辑详情、增删行、打开／关闭帮助、刷新并结束。 |
| 320×820 | 已保存主机标签 | 同一操作链完成，结果与新配对入口一致。 |
| 390×820 | 新配对连接页 | 同一操作链完成，帮助和返回列表均可见。 |
| 390×820 | 已保存主机标签 | 同一操作链完成，最终选中 Review，详情剩一个字符。 |

这些操作实际覆盖方向键、Tab、Backspace、Shift+Tab、Insert、Delete、F1、F5、F10。其余 F 键和修饰组合本批有编码向量验证，尚未逐项验收真实 TUI 行为。该夹具的 PTY 为 80×24；桥接帧按收到的网格显示，不能把前端请求画布当成 PTY 尺寸。

Flutter 与 Tauri 的生产编码分别驱动专属真实 PTY，完成相同十步操作；退出时出现备用屏退出序列，PTY 的 termios 恢复、尺寸保持。这条验证不经过 Flutter 引擎或手机 UI。Flutter 另在 Dart 3.11 中直接执行生产辅助键 codec，逐项核对共享向量、一次性修饰消费和禁用时零输出；旧字母及导航编码也保留。IME 探针执行提取后的依赖编辑方法与应用守门代码，编辑值、状态和发送环境使用替身。普通 reference 与 combining candidate 两种 Flutter 准备模式均校验固定归档和补丁前后 SHA；reference 保留原绘制核心，candidate 保留既有组合字符修复。源码准备和工具检查不能代替 analyzer、widget、编译或系统 IME 结果。

同一份干净 HEAD 归档叠加本批文件、排除无关本地 ZeroTier 改动后，通过了以下回归；各项范围独立，不相加为设备验收结果。

| 检查 | 结果 | 证明范围 |
| --- | --- | --- |
| Flutter Python 准备工具 | 15 项通过 | 实际归档 SHA、两种依赖准备模式与补丁接线。 |
| Tauri 前端测试与构建 | 394 项通过，0 跳过；Vite 构建成功 | 前端逻辑与产物打包；Chrome 实点结果另列在上表。 |
| 远端 harness | 67 项通过 | 驱动和夹具回归；不是手机或 SSH 运行证明。 |
| 宿主候选 Python 工具 | 19 项通过 | 自建 Unix socket 和构建调用替身；需在允许本地 socket 的环境执行。 |
| POSIX helper | 15 项通过 | 自建临时资料，未使用真实授权文件。 |

## 应用模式没有随原版观察帧传来

另一次专属 Mac herdr 0.9.5 本地 IPC 观察中，真实 TTY 内的 curses 明确输出了 `DECCKM` 开启、`smkx`（`ESC[?1h` 与 `ESC=`）和备用屏 `1049h`。应用运行期间收到的标题全帧与进入 TUI 的增量都能显示 `Pocket TUI`，却没有这些模式序列。跨进程时序核对确认，当时应用最近发出的 DECCKM 命令仍为开启。该场只观察、不按键，到时退出；共享外层 PTY 的已采样尺寸保持 119×40，所有自启进程均已退出。

最终独立回归还切换了四次仅影响输入模式的状态：每次都未收到模式变化帧，随后可见内容更新均正常。连续 116 个 PTY 尺寸样本保持一致。这个样本数属于本次运行，会随采样调度变化；它不表示观察帧数量。

原版 CLI 帧字段只有 `type`、`seq`、`encoding`、`width`、`height`、`full`、`bytes`。固定源码将运行时绘制成单元格和光标，再编码观察者 ANSI。因此，客户端渲染器的模式不能视为应用的输入模式；本次也没有直接读取运行时的 `mode_get`。安装二进制的版本与哈希已记录，但没有证明它由该固定提交构建。[CLI 输出](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/client/terminal_sessions.rs) · [帧结构](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/protocol/wire.rs) · [观察流重绘](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/server/render_stream.rs)

上面的浏览器闭环由合成桥传入真实 curses 的原始模式序列，所以下方向键实际发送了应用光标编码 `ESC O B`。这证明了桥接条件下的客户端行为，不证明原版 herdr 或宿主候选已经提供同样的模式信息。

宿主候选补丁已增加向观察者附带应用光标与方括号粘贴状态的源码，并写入模式切换、双观察者、背压和目标替换等反例。增量补丁与合并补丁的应用结果一致，格式和空白检查通过；因缺少锁定的离线依赖与指定构建工具，尚未编译、执行 Rust 回归或运行该候选。帧与输入路径仍相互独立，模式快照可能落后于尚未解析的应用输出。旧版保护扩展的输入能力响应只确认目标绑定与原始字节输入。要确认模式同步，还须校验新宿主补丁及其运行结果。[宿主候选补丁](../validation/herdr-input-extension/herdr-0.9.5-pocket-input.patch) · [构建与预检边界](../validation/herdr-input-extension/README.md)

## 下一批验收

1. 在固定工具链与依赖完整的隔离环境构建宿主候选，执行已写反例，再用实际候选核对模式变化及观察恢复。普通 herdr 保留只读场景。
2. 对 Flutter reference 与 combining candidate 执行 SDK 检查和 widget 回归，复核同文字组合范围变化、辅助键旧回调、一次中文提交和功能区开合；随后验证真实系统 IME。
3. 分别让两壳经实际设备密钥 SSH 和保护输入扩展运行同一 curses 操作链，记录目标、全帧、输入回执及 PTY 效果，移除本批合成桥。发送结果未知时保持锁定，不重放。
4. 在物理手机验收触控、字形与中文输入法。iOS、其他桌面端、三网节点和跨网并发继续分别记录，不由本批浏览器结果推定。
