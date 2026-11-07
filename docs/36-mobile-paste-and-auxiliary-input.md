# 手机粘贴审查、草稿找回与辅助键

从已配对主机进入看板、选中 pane 后，手机可以使用逐键输入或草稿。粘贴先核对内容与原目标，再选择追加、替换或取消。使用粘贴只改本地草稿。发送时单独确认目标、原始文本和换行，保留中文及组合字符，不附加回车。[源码](https://github.com/Luck9Star/herdr-pocket/commit/a9914fefeb9791aec5d3e041bf0d5d8a17f70e82) · [上一批配对与观察结果](34-mobile-host-task-summary.md)

## 手机操作与恢复

| 操作 | 应当观察到的结果 |
| --- | --- |
| 保留一份草稿，从终端或草稿框粘贴多行内容 | 预览将换行、ESC 和双向控制字符显示出来。追加后超过 4096 个 UTF-8 字节时，仍能取消，或在新内容本身符合上限时选择替换。 |
| 组字、粘贴审查或发送确认期间切换目标 | 新标签不能使用原目标的审查。原草稿经过编辑再改回同样文字也要重新确认。 |
| Tauri 直接表单重新核验并连接已存主机 | 草稿归属包含审核过的设备、连接路径、命名会话、pane 和 terminal。同一 pane 号指向新 terminal 时不会带入旧草稿。手动连接按本次连接隔离。 |
| 发送后本端收到明确拒绝 | 表单只在原目标、原草稿版本仍适用时恢复原文本。已有新草稿、换了目标或仍需核查本机记录时，可以在只读区按原目标找回。找回区已满会保留现有内容并阻止下一次草稿发送。结果未知时保持输入锁定。 |
| 在 Tauri 已存终端标签开启逐键输入 | 辅助键提供 Esc、Tab、Enter、方向、Home、End、PgUp、PgDn，以及一次性 Ctrl／Alt 组合。触点保持当前终端焦点，方向键跟随当前终端的光标模式。组合状态不改写输入法文字。 |

Tauri 在目标启用括号粘贴时，发送确认计入首尾标记的字节数并拒绝内含结束标记的草稿。Flutter 在草稿菜单和粘贴快捷键处处理显式粘贴，直接终端也接管 Ctrl／Cmd+V 和 Shift+Insert。输入法把剪贴板建议作为普通文字提交时，应用按普通 IME 提交处理。[Flutter PasteTextIntent](https://api.flutter.dev/flutter/widgets/PasteTextIntent-class.html) · [Flutter 上下文菜单](https://api.flutter.dev/flutter/widgets/EditableText/contextMenuBuilder.html)

## Mac 实测与复核

在 320×820、390×820 两种视口分别从 Tauri 的新配对表单、已存主机看板进入真实 xterm 控件。浏览器使用合成粘贴事件和隔离的原生接口替身。

1. 两个入口均保留了预览前的原稿，显示了换行、ESC 和 U+202E。追加、取消、替换产生的远端输入均为 0。
2. 给 4094 字节的草稿粘贴“中”，追加被禁用；取消保留全部 4094 字节，再次粘贴可选择替换。
3. 在两个尺寸的已存标签分别按 Ctrl+C 和向上键，接收端得到 `03` 和 `1B 5B 41`。四个场景的 PTY 调整请求均为 0。

隔离源码副本通过 190 项 Tauri JavaScript 测试、前端构建、31 项测试驱动检查。6 个变动的 Dart 源文件完成语法解析。专用浏览器和夹具服务已关闭。[本地读数](evidence/mobile-pair-gui/mobile-paste-20261107.json)

## 同源云验证与可下载测试包

2026-11-07，[集中运行 42339225239](https://github.com/Luck9Star/herdr-pocket/actions/runs/42339225239) 使用 `a9914fefeb9791aec5d3e041bf0d5d8a17f70e82`，最终为 `failure`：原生库、共享 Rust、输入夹具、Flutter 源码检查及两套 APK 的 6 个 job 成功；两个 Android 模拟器 job 失败。成功打包没有覆盖后面的失败。

两份包均为 API 35、`arm64-v8a` 的组网实验测试 APK。下载后重新计算压缩包及 APK 的 SHA-256、核对 APK 字节数和记录的同源原生 manifest；本次是离线产物复核，没有安装或运行这两份 arm64 包。

| 测试包 | APK 字节数 | APK SHA-256 |
| --- | ---: | --- |
| [Flutter](https://github.com/Luck9Star/herdr-pocket/actions/runs/42339225239/artifacts/13561835087) | 483760608 | `dbbf5a01a27ea800fdb0199f3a406a65a0027e4ad7b55754ac9d33639a85e820` |
| [Tauri](https://github.com/Luck9Star/herdr-pocket/actions/runs/42339225239/artifacts/13561422120) | 591450439 | `0dd3ae7d013ecceb66873b9f032f152a5ea416b206bfa8c6362571fedf493668` |

两包记录的原生 manifest SHA-256 均为 `ef183f873aa73d68291e27feb8cb09ee3603d43ef9f3e024e634badadfcd576c`。原生库、压缩包完整哈希及校验范围见[结构化证据](evidence/mobile-pair-gui/mobile-paste-20261107.json)。Actions artifact 受仓库访问权限和保留期限制。

## 首轮 Android 模拟器结果

四条路线分别启动和关闭临时 API 35 x86_64 AVD；普通主机使用 herdr 0.9.5，受保护输入使用同 SHA 构建的隔离夹具。这些 AVD 使用各自的调试测试应用，不是上表两份 arm64 组网 APK 的运行验收。

| 路线 | 结果 | 已到达的边界 |
| --- | --- | --- |
| [Tauri 普通配对与观察](https://github.com/Luck9Star/herdr-pocket/actions/runs/42339225239/artifacts/13561447093) | 通过 | 完成配对、选 pane、full／delta 渲染和停止；远端输入为 0 字节。 |
| [Flutter 普通配对与观察](https://github.com/Luck9Star/herdr-pocket/actions/runs/42339225239/artifacts/13560902949) | 失败 | `create_not_available`（测试行 197）；未到达主机授权匹配，远端输入为 0 字节。 |
| [Flutter 受保护输入](https://github.com/Luck9Star/herdr-pocket/actions/runs/42339225239/artifacts/13560992720) | 失败 | `guarded_hidden_draft`（测试行 48）；已匹配临时设备身份，远端累计收到 1 字节。 |
| [Tauri 受保护输入](https://github.com/Luck9Star/herdr-pocket/actions/runs/42339225239/artifacts/13561457135) | 失败 | `android_draft_not_retained`；已匹配临时设备身份，远端累计收到 1 字节。 |

失败名定位到驱动断言阶段，现有材料不足以把它们定为应用、滚动定位或平台行为的根因。1 字节只证明此前发生过输入，不能证明草稿、粘贴、键盘或隐藏后恢复用例通过。四份压缩包的内部校验和已复核；各 AVD lifecycle 均记录关闭后自有 serial 不再存在，夹具 manifest 均记录自有进程及临时密钥已清理、未触碰用户授权文件。后续只重跑测试的 AVD 批次应单独保留来源及结果，不覆盖本轮失败记录。

## Linux GUI 与设备范围

同源 [Flutter Linux 隔离 SSH GUI](https://github.com/Luck9Star/herdr-pocket/actions/runs/42339225239/artifacts/13561540966) 通过：使用显式测试签名器、测试 catalog／input journal 和临时 OpenSSH 主机，完成配对、观察、暂停恢复及主机摘要检查；接收端累计得到 9 字节。记录含 10 帧、8 个 delta、2 次本地视口变化，固定 PTY 的 `changes=0`。结束时 `terminationSignal=0`，自有进程和临时密钥正常清理。它证明该 Linux widget 夹具中的输入闭环，不证明手机系统剪贴板、输入法或 arm64 包运行。

云端 Flutter analyzer 无问题，unit／widget 为 312 项通过、1 项跳过，组合字符绘制回归为 10 项通过。本机原先只做 Dart 语法解析的边界由此补充，但三个失败的 Android 场景仍保留失败状态。真实手机的系统剪贴板、输入法候选、物理触控、arm64 安装、iOS 生命周期及前台三网并发仍需分别实测。[完整读数及范围](evidence/mobile-pair-gui/mobile-paste-20261107.json)

## Android 定向复验

[复验 42351694649](https://github.com/Luck9Star/herdr-pocket/actions/runs/42351694649) 使用 `0036451e99867fbdad3d2ed8173ff65e1a1fd442`。相对上面的 APK 源码，只调整了测试驱动、测试与本次工作流的运行范围。两条路线在 API 35 x86_64 模拟器上完成配对审查、设备密钥 SSH 认证、看板、选定 pane、全量加增量观察及停止。输入夹具另验证隐藏、主动恢复、正常找回原草稿和显式发送。两个受保护输入场景均取得原 pane 和 terminal 上的两个独立请求回执。

| 模拟器场景 | 远端记录 | PTY 采样次数 |
| --- | --- | ---: |
| [Flutter 普通观察](https://github.com/Luck9Star/herdr-pocket/actions/runs/42351694649/artifacts/13566218165) | 只读，0 字节 | 5964 |
| [Flutter 受保护输入](https://github.com/Luck9Star/herdr-pocket/actions/runs/42351694649/artifacts/13565969469) | 1 ＋ 9 字节，两笔独立回执 | 2225 |
| [Tauri 普通观察](https://github.com/Luck9Star/herdr-pocket/actions/runs/42351694649/artifacts/13566715340) | 只读，0 字节 | 865 |
| [Tauri 受保护输入](https://github.com/Luck9Star/herdr-pocket/actions/runs/42351694649/artifacts/13566113149) | 1 ＋ 9 字节，两笔独立回执 | 1028 |

四份归档均核对了 GitHub SHA-256 和内部校验和。各自的共享 PTY 始终为 119×40，尺寸变化和 SIGWINCH 记录均为 0。应用及临时模拟器结束后已清理。

**该次 Actions 总状态仍为失败。** Flutter 回归组合步骤的退出状态为 1，analyzer 报告测试文件中一项多余导入，314 项 unit/widget 和 10 项绘制测试通过，另有 1 项环境限定用例跳过。两份 Flutter 模拟器证据均记录 `stock=0 guarded=0`。后续源码已移除多余导入，完整 Flutter analyzer 随下一批集中运行。上方 arm64 包仍来自 `a9914fe`。本次没有重新分发，也没有真机或真实组网结果。
