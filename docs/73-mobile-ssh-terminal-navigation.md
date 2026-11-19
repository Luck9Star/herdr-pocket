# 手机普通 SSH 活动终端与切页

2026-11-19，本地验证通过两壳的活动终端、模拟键盘开合和设置往返。用户约定是从活动终端切到看板、网络或设置的实际页面后，保留原 SSH 会话和回显。切走时禁止终端输入，从底栏返回终端时保持键盘收起。主动断开才关闭本轮测试会话。

两壳修前使用 `0705b9b70ac1cda2b58b20e0ebaf7596cbd8ebcb`。Flutter 修后为 `b6f89a3bcf317bdf69211d6a3c11ce7c7f491b71`，包含 `e47b593`。Tauri 修后为 `ea1694c29e3d9f5a12fca35875d54c3b9396ea55`。画板来自 `c063e785da173ad41bc740cf0dc64eaa8ccce3fb` 的[冻结设计](../design/penpot/direct-ssh-mobile.md)。iOS 和 Android 原生模拟器结果留待独立作业，原生设备矩阵沿用已有记录。[普通 SSH 原生证据](72-mobile-ssh-auth-snapshot.md)

## 同尺寸画面与测量

320 × 640 的顶部／底部安全区为 24／24 pt，模拟键盘上缘为 402 pt。390 × 844 使用 47／34 pt，模拟键盘上缘为 553 pt。截图均为缩放 1、原尺寸，键盘展开图记录预留空间。Flutter 使用 Widget 测试引擎、San Francisco／苹方和注入的安全区、键盘 inset。Tauri 使用独立 WebKit 26.5、CSS 安全区与模拟 VisualViewport。系统状态栏、底部手势区和键盘本身未参与几何计数。

| 壳与视口 | 键盘收起 | 键盘展开 | 活动时设置 |
| --- | --- | --- | --- |
| Flutter 320 × 640 | [修前](evidence/mobile-ssh-terminal-navigation-20261119/screens/flutter-before-320-terminal-closed.png) · [修后](evidence/mobile-ssh-terminal-navigation-20261119/screens/flutter-after-320-terminal-closed.png) | [修前](evidence/mobile-ssh-terminal-navigation-20261119/screens/flutter-before-320-terminal-open.png) · [修后](evidence/mobile-ssh-terminal-navigation-20261119/screens/flutter-after-320-terminal-open.png) | [修前仍在终端](evidence/mobile-ssh-terminal-navigation-20261119/screens/flutter-before-320-terminal-echo.png) · [修后](evidence/mobile-ssh-terminal-navigation-20261119/screens/flutter-after-320-settings-active.png) |
| Flutter 390 × 844 | [修前](evidence/mobile-ssh-terminal-navigation-20261119/screens/flutter-before-390-terminal-closed.png) · [修后](evidence/mobile-ssh-terminal-navigation-20261119/screens/flutter-after-390-terminal-closed.png) | [修前](evidence/mobile-ssh-terminal-navigation-20261119/screens/flutter-before-390-terminal-open.png) · [修后](evidence/mobile-ssh-terminal-navigation-20261119/screens/flutter-after-390-terminal-open.png) | [修前仍在终端](evidence/mobile-ssh-terminal-navigation-20261119/screens/flutter-before-390-terminal-echo.png) · [修后](evidence/mobile-ssh-terminal-navigation-20261119/screens/flutter-after-390-settings-active.png) |
| Tauri 320 × 640 | [修前](evidence/mobile-ssh-terminal-navigation-20261119/screens/tauri-before-320-terminal-closed.png) · [修后](evidence/mobile-ssh-terminal-navigation-20261119/screens/tauri-after-320-terminal-closed.png) | [修前](evidence/mobile-ssh-terminal-navigation-20261119/screens/tauri-before-320-terminal-open.png) · [修后](evidence/mobile-ssh-terminal-navigation-20261119/screens/tauri-after-320-terminal-open.png) | [修前](evidence/mobile-ssh-terminal-navigation-20261119/screens/tauri-before-320-settings-active.png) · [修后](evidence/mobile-ssh-terminal-navigation-20261119/screens/tauri-after-320-settings-active.png) |
| Tauri 390 × 844 | [修前](evidence/mobile-ssh-terminal-navigation-20261119/screens/tauri-before-390-terminal-closed.png) · [修后](evidence/mobile-ssh-terminal-navigation-20261119/screens/tauri-after-390-terminal-closed.png) | [修前](evidence/mobile-ssh-terminal-navigation-20261119/screens/tauri-before-390-terminal-open.png) · [修后](evidence/mobile-ssh-terminal-navigation-20261119/screens/tauri-after-390-terminal-open.png) | [修前](evidence/mobile-ssh-terminal-navigation-20261119/screens/tauri-before-390-settings-active.png) · [修后](evidence/mobile-ssh-terminal-navigation-20261119/screens/tauri-after-390-settings-active.png) |

固定画板有 18／13／11 个应用锚点，分别对应收起、展开和设置。表中每格按「达标／超差／未测或未到达」记数，两种视口的各项数目相同。阈值为矩形 x、y、宽、高各自绝对偏差 ≤2 pt，可触锚点同时要求中心命中及至少 44 × 44 pt。

| 壳与版本 | 键盘收起 | 键盘展开 | 活动时设置 |
| --- | ---: | ---: | ---: |
| Flutter 修前 | 1 / 4 / 13 | 1 / 4 / 8 | 0 / 0 / 11 |
| Flutter 修后 | 18 / 0 / 0 | 13 / 0 / 0 | 11 / 0 / 0 |
| Tauri 修前 | 0 / 18 / 0 | 0 / 13 / 0 | 0 / 9 / 2 |
| Tauri 修后 | 18 / 0 / 0 | 13 / 0 / 0 | 11 / 0 / 0 |

Flutter 在独立 Widget 回环中补测看板与网络两个底栏按钮，覆盖两个尺寸的收起终端和活动设置，共 8 项。实测坐标与画板一致，中心均命中。两尺寸的 42 项 Flutter 修后锚点各自全部通过，几何偏差为 0 pt。补测用 `6075d7f2fd884e38af6f8e80152ec24b8507ab75` 的测试与默认字体，当时 Flutter 产品源码与原修后图一致。补测没有新截图，表中图片继续引用最初的截图批次。[补测原始坐标](evidence/mobile-ssh-terminal-navigation-20261119/flutter-navigation-anchors.json)

Tauri 修后仅断开按钮比画板上移 1 pt，仍能命中。两壳在 320 pt 的面板高度从收起的 304 pt 减至展开的 146 pt，390 pt 从 523 pt 减至 322 pt。展开状态隐藏底栏，默认可见的七个共同辅助键均命中。Flutter 独有的 Ctrl-D 与 Enter 要横向滚动后才能触达，已实点并由回环侧证实。

Flutter 基线活动 SSH 为独立路由，活动时的看板、网络与设置往返均不可达。表中的旧侧第三格保留真实回显终端，设置锚点全部标未到达。Tauri 基线即可三页往返并保留会话，设置页缺少活动状态与连接目标，终端与底栏也与画板有偏差。修后两壳设置页均显示活动提示、同一目标、字号调整和导入／导出。

[逐锚矩形、命中与图片哈希](evidence/mobile-ssh-terminal-navigation-20261119/geometry.json)采用每张图左上角为原点。Flutter 顶栏源框包含顶部安全区，比较应用顶栏时扣除该段。旧 Flutter 终端面板使用旧 `TerminalView` 的可视外框。重新生成画板时，在仓库根目录运行以下命令，将各前缀的 `anchors` 与归档中的 `target` 对照，逐项用 `actual − target` 复算 `delta`。归档图片仅移除 EXIF 和文本块，已核对解码像素、原始和归档 SHA256。

```sh
capture_design="$(mktemp -d)"
node design/penpot/direct-ssh-mobile.mjs "$capture_design/atlas.svg" "$capture_design/boards"
shasum -a 256 "$capture_design/boards/geometry.json"
```

## 回环导航证据

- Flutter 的前后截图使用同一隔离服务重新采集，每张终端回显图对应一次探测和一条已认证、分配 PTY 的独立连接。实发一行夹具输入并显示回显后主动断开。[320 pt 回显](evidence/mobile-ssh-terminal-navigation-20261119/screens/flutter-after-320-terminal-echo.png) · [390 pt 回显](evidence/mobile-ssh-terminal-navigation-20261119/screens/flutter-after-390-terminal-echo.png)
- Flutter 的导航回归在同一修后源码另开隔离夹具运行。两档均经真实看板、网络和设置页，返回后仍是原 Shell 和 Terminal 对象。看板、网络以底栏返回，设置的 320 pt 用系统返回，390 pt 用终端标签。每档从打开到主动断开，服务端只有一次密码认证、一次 PTY。切走时注入的输入与过期键盘回调未发往服务端，返回后的输入和终端回显可见。[Widget 回归源码](../validation/flutter/test/direct_ssh_mobile_terminal_test.dart)
- Tauri 的前后截图由 WebKit 加临时 IPC 桥，经仓库的 Rust 普通 SSH 代码连接独立 Paramiko 回环。每档、每版均为一次仅探测连接和一条认证会话。服务端对后者记录一次密码认证、一次 PTY、一次 Shell，接收 X、七个辅助键和 Y，最终主动关闭。脚本另在看板、网络和设置可见时注入前端终端输出事件，返回后校验事件仍显示在原会话，且返回时终端输入控件未获焦。实际回环输入回显、DOM 导航和该前端注入各自有独立断言。

[按版本和视口的服务端计数与导航摘要](evidence/mobile-ssh-terminal-navigation-20261119/navigation.json)仅保留固定夹具计数和断言结果。两壳的系统键盘组词、原生壳生命周期、实体设备和真实跨网仍待验证。较高字体缩放的结论也需单独验证，本轮截图均为 1× 字号。
