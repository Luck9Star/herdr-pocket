# 手机普通 SSH 活动终端与切页

2026-11-19，本地验证通过两壳的活动终端、模拟键盘开合和设置往返。用户约定是从活动终端切到看板、网络或设置的实际页面后，保留原 SSH 会话和回显。切走时禁止终端输入，从底栏返回终端时保持键盘收起。主动断开才关闭本轮测试会话。

两壳修前使用 `0705b9b70ac1cda2b58b20e0ebaf7596cbd8ebcb`。Flutter 修后为 `b6f89a3bcf317bdf69211d6a3c11ce7c7f491b71`，包含 `e47b593`。Tauri 修后为 `ea1694c29e3d9f5a12fca35875d54c3b9396ea55`。画板来自 `c063e785da173ad41bc740cf0dc64eaa8ccce3fb` 的[冻结设计](../design/penpot/direct-ssh-mobile.md)。Flutter Android、Flutter iOS 与 Tauri iOS 模拟器均通过本批导航验收。Tauri Android R3 已复现系统键盘可见、网页状态未同步的问题。[普通 SSH 原生证据](72-mobile-ssh-auth-snapshot.md)

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

[按版本和视口的服务端计数与导航摘要](evidence/mobile-ssh-terminal-navigation-20261119/navigation.json)仅保留固定夹具计数和断言结果。本机对照截图均为 1× 字号，系统输入法组词、实体设备、真实跨网和更高字体缩放仍需独立验证。

## Flutter Android 原生模拟器 R1

`cffe85c7b650f45ea5fe1f2b63063bc66a377e3f` 在 Android API 35 的 `pixel_5` 配置、x86_64 Google APIs 系统镜像上通过。普通案经过八个顺序检查点，包括键盘开启／收起，及看板、网络、设置各自进入／返回。每一步均在服务端连接 #2 上记录一次成功认证、一次 PTY、一次 Shell、零输入，连接保持打开。设备驱动核验各页返回的是同一终端。检查完成后才提交 9 字节的夹具输入，服务端记录 102 字节输出。界面确认主动断开和临时凭据清理，服务端两条连接均在驱动退出前关闭。[运行 44457386191](https://github.com/Luck9Star/herdr-pocket/actions/runs/44457386191/job/135335614812) · [正式工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44457386191/artifacts/14499051205)

同轮换钥案按 `A → B → B → B` 完成拒绝、取消保留 A、重探与显式确认 B。前三条连接均零认证、零 PTY、零输入，最后一条密码连接有一次认证、一次 PTY 和一次 Shell，收到 9 字节输入并输出 102 字节，主动断开后全部关闭。两案的原生终端截图均通过标记、令牌与回显序列 OCR 门禁。八项导航检查点只属于普通案。两案的 `physicalImeVerified=false`，系统键盘开合与驱动文本输入已有证据，系统输入法组词仍待验证。ADB 转发和反向转发、测试包、Flutter 进程、夹具及模拟器清理均通过。[服务端、截图与清理摘要](evidence/mobile-ssh-terminal-navigation-20261119/native/flutter-android-r1/official-index.json)

长期保留的前后图取两轮换钥后的已连接终端，系统键盘均可见。两轮系统镜像属性一致，屏幕原图均为 1080 × 2340 px。前图来自 [R2 的 `bda3c59`](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430480/job/135194350049)，后图来自本轮 `cffe85c`。归档校验了解码像素及原图和归档 SHA256。普通案原图也通过 OCR，两轮的普通案截图分别处于键盘展开和收起，未作为同状态图对照。设备图用于观察原生画面，逐锚 2 pt 结果沿用上文独立本地量测。[换钥后终端修前](evidence/mobile-ssh-terminal-navigation-20261119/native/flutter-android-r1/rotation-terminal-before.png) · [换钥后终端修后](evidence/mobile-ssh-terminal-navigation-20261119/native/flutter-android-r1/rotation-terminal-after.png)

## Flutter iOS 原生模拟器 R2

`2861a0b685b747d71a9d11cdf44eebf5d1d792c3` 在 iPhone 11、iOS 26.2 模拟器上通过。普通案依次检查键盘开合、看板进入／返回、网络进入／返回和设置进入／返回。八步服务端始终为连接 #2，累计一次成功认证、一次 PTY、一次 Shell，输入为零且连接未关闭。驱动确认返回同一终端。在八步之后提交 9 字节输入，服务端记录 102 字节输出，设备确认断开并清理临时凭据，两条连接均在驱动退出前关闭。[运行 44458501334](https://github.com/Luck9Star/herdr-pocket/actions/runs/44458501334/job/135339294777) · [正式工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44458501334/artifacts/14498459988)

换钥案按 `A → B → B → B` 验证拒绝、取消保留 A、重探和显式确认 B。前三条连接零认证、零 PTY、零输入，末条密码会话成功认证并建立一次 PTY 和一次 Shell，收到 9 字节输入、102 字节输出。两案均主动断开并通过原生截图 OCR。换钥案沿用独立的换钥检查点，八步导航属于普通案。两案记录 `physicalImeVerified=false`。模拟器、应用、Flutter 进程、回环夹具和临时文件均清理完成。[服务端、OCR 与清理摘要](evidence/mobile-ssh-terminal-navigation-20261119/native/flutter-ios-r2/official-index.json)

归档保存两张 828 × 1792 px 的本轮终端截图，去除 PNG 文本及 EXIF 后解码像素与原图一致。普通案的键盘已收起，换钥案截图下方出现系统键盘提示。旧 [Flutter iOS R2 原生证据](72-mobile-ssh-auth-snapshot.md#r2-联合复验)使用同型号和像素尺寸，但两张旧原图都显示正常展开的系统键盘，因此两轮图片仅作回合记录，分开保留。[本轮普通终端](evidence/mobile-ssh-terminal-navigation-20261119/native/flutter-ios-r2/ordinary-terminal.png) · [本轮换钥终端](evidence/mobile-ssh-terminal-navigation-20261119/native/flutter-ios-r2/key-change-terminal.png)

本批 Flutter iOS R1 在 Python 预检的回环夹具有序关闭断言失败，未进入设备 GUI，也没有该壳的原生工件。R2 先修正夹具等待对端 EOF 的顺序，再定向重跑 Flutter。[Flutter iOS R1 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44457385579/job/135335613074)

## Tauri 原生 R1 状态

Tauri Android R1 在连接阶段报告 `direct_active_ui_invalid`。Tauri iOS R1 在活动流程检查点报告 `native_visible_frame_invalid`，换钥未运行。随后 iOS R2 通过，Android R2、R3 进一步定位到键盘状态差异。[Tauri Android 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44457386325/job/135335615405) · [Tauri iOS 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44457385579/job/135335613248)

## Tauri iOS 原生模拟器 R2

`2bd6dc83ce3e40a6ac34232078f3214163c04bba` 在 iPhone 17 Pro Max、iOS 26.2 模拟器通过。普通案的八个检查点依次为键盘开合、看板进入／返回、网络进入／返回和设置进入／返回。八步的回环服务端均为连接 #2，累计一次认证、一次 PTY 和一次 Shell，输入为零且连接未关闭。全部八个控件的原生记录均为归属已核验、启用、完整可见、中心可见和可命中。440 × 956 pt 原生屏中，键盘按钮为 44 × 44 pt，收起操作的可见区为 `[0,54,440,601]`。归档保留八条控件、状态栏和可见区完整矩形。[作业 44461266808](https://github.com/Luck9Star/herdr-pocket/actions/runs/44461266808/job/135348341572) · [正式工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44461266808/artifacts/14500344080) · [原生几何与服务端摘要](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-ios-r2/official-index.json)

普通案为 `A → A`，换钥案为 `A → B → B → B`。探测与拒绝阶段均零认证、零 PTY、零输入，换钥取消后保留 A，重探并确认 B 后才认证。两案末条连接各有一次认证、一次 PTY 和一次 Shell，收到 9 字节夹具输入并输出 102 字节。两案分别通过原图 OCR、主动断开及服务端关闭，普通案另确认退回空首页。模拟器、夹具和临时文件均已清理。八项导航只属于普通案。系统输入法组词、Tauri iOS 私钥、实体设备与真实跨网仍待独立验收。

本轮和旧 R7 使用相同型号与运行时。以下 1320 × 2868 px 原生终端图的系统键盘均不可见，可同状态目视对照应用顶栏、回显区和底栏。两张新图的解码像素与原图一致，只移除了文本及 EXIF 元数据。原生逐锚 2 pt 验收仍独立于这组对照。

| 已连接终端 | 旧 R7 | 本轮 R2 |
| --- | --- | --- |
| 普通案回显后 | [旧原生图](evidence/mobile-ssh-auth-r23/tauri-ios-r7/ordinary-terminal.png) | [本轮原生图](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-ios-r2/ordinary-terminal.png) |
| 换钥并确认 B 后 | [旧原生图](evidence/mobile-ssh-auth-r23/tauri-ios-r7/key-change-terminal.png) | [本轮原生图](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-ios-r2/key-change-terminal.png) |

## Tauri Android 原生模拟器 R2 与 R3

两轮在 `active_keyboard_opened` 报 `direct_active_ui_invalid`。R2 记录连接、终端和断开按钮均在，WebView 仍显示「打开键盘」，「收起键盘」的矩形为零，尚未取得系统键盘归属。R3 改用原生触摸，并在触摸前后分别独立确认应用自有 IME 从 `owned_hidden` 到 `owned_visible`。此时 WebView 仍显示「打开键盘」，「收起键盘」的矩形仍为零，CSS 视口维持 393 × 851。R3 因此复现了系统键盘可见但网页状态没有同步的问题，修复和原生复验待完成。

两轮失败时均记录两条连接，其中活动会话有一次认证、一次 PTY、一次 Shell，零输入，仍打开。普通案八步未完成，未取得换钥结果。作业确认移除其创建的模拟器，公开摘要没有主动断开回执或失败画面。R3 的输入法证据仅证明可见性和所属应用。[R2 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44460008448/job/135344209659) · [R2 工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44460008448/artifacts/14499952750) · [R3 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44461890953/job/135350418144) · [R3 工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44461890953/artifacts/14500966515) · [失败差异与哈希](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-android-r2-r3/official-index.json)
