# 手机普通 SSH 活动终端与切页

2026-11-19，本地验证通过两壳的活动终端、模拟键盘开合和设置往返。用户约定是从活动终端切到看板、网络或设置的实际页面后，保留原 SSH 会话和回显。切走时禁止终端输入，从底栏返回终端时保持键盘收起。主动断开才关闭本轮测试会话。

两壳修前使用 `0705b9b70ac1cda2b58b20e0ebaf7596cbd8ebcb`。Flutter 修后为 `b6f89a3bcf317bdf69211d6a3c11ce7c7f491b71`，包含 `e47b593`。Tauri 首版布局修后为 `ea1694c29e3d9f5a12fca35875d54c3b9396ea55`。画板来自 `c063e785da173ad41bc740cf0dc64eaa8ccce3fb` 的[冻结设计](../design/penpot/direct-ssh-mobile.md)。Flutter Android、Flutter iOS 均通过本批原生模拟器导航验收。Tauri Android R3 复现系统键盘已打开但网页状态未同步，修后同一源码已通过 Android 和 iOS [原生模拟器 R4](#tauri-android-与-ios-原生模拟器-r4)。R4 之后的一次[键盘布局回归对照](#tauri-android-r5-键盘修前后官方对照)按整案失败归档。[普通 SSH 原生证据](72-mobile-ssh-auth-snapshot.md)

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

两轮在 `active_keyboard_opened` 报 `direct_active_ui_invalid`。R2 记录连接、终端和断开按钮均在，WebView 仍显示「打开键盘」，「收起键盘」的矩形为零。R2 驱动检查过本应用键盘可见，失败工件没有保留点击前后的 IME 样本，无法排除键盘是从表单阶段残留的。R3 改用原生触摸，并在触摸前后分别独立确认应用自有 IME 从 `owned_hidden` 到 `owned_visible`。此时 WebView 仍显示「打开键盘」，「收起键盘」的矩形仍为零，CSS 视口维持 393 × 851。R3 因此复现了系统键盘可见但网页状态没有同步的问题。修订版的本地证据见下节，原生复验见 [R4](#tauri-android-与-ios-原生模拟器-r4)。

两轮失败时均记录两条连接，其中活动会话有一次认证、一次 PTY、一次 Shell，零输入，仍打开。普通案八步未完成，未取得换钥结果。作业确认移除其创建的模拟器，公开摘要没有主动断开回执或失败画面。R3 的输入法证据仅证明可见性和所属应用。[R2 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44460008448/job/135344209659) · [R2 工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44460008448/artifacts/14499952750) · [R3 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44461890953/job/135350418144) · [R3 工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44461890953/artifacts/14500966515) · [失败差异与哈希](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-android-r2-r3/official-index.json)

## Tauri Android 键盘修复的本地对照

修前使用 `9825bffdf8d6be0dadb6655a2ab22964812dd248`，修后使用 `b11e2b94c18ca5b11e876fc93fc71c9c806b6e7d`。隔离构建在 Chromium 157 运行实际产品页面，CSS 安全区和原生 IME 状态由测试提供。页面的点击与命中来自浏览器，SSH 经临时 IPC 桥使用实际 Rust 传输和独立 Paramiko 回环。图片为 DPR 1 的浏览器原图，系统键盘未绘制。

| 开键盘后的试验尺寸 | 布局视口不缩时的修前原图 | 布局视口不缩时的修后原图 |
| --- | --- | --- |
| 320 × 640 | [修前](evidence/mobile-ssh-terminal-navigation-20261119/android-ime-browser/before-320x640-unchanged-opened.png) | [修后](evidence/mobile-ssh-terminal-navigation-20261119/android-ime-browser/after-320x640-unchanged-opened.png) |
| 390 × 844 | [修前](evidence/mobile-ssh-terminal-navigation-20261119/android-ime-browser/before-390x844-unchanged-opened.png) | [修后](evidence/mobile-ssh-terminal-navigation-20261119/android-ime-browser/after-390x844-unchanged-opened.png) |
| 393 × 851 | [修前](evidence/mobile-ssh-terminal-navigation-20261119/android-ime-browser/before-393x851-unchanged-opened.png) | [修后](evidence/mobile-ssh-terminal-navigation-20261119/android-ime-browser/after-393x851-unchanged-opened.png) |

修前三档仍显示且可命中「打开键盘」，底栏维持可见。修后三档显示且命中「收起键盘」，隐藏底栏，标题、端点、收起和断开控件均在有效可见区内并可命中。三档有效高度依次为 402、553 和 551 pt。393 × 851 使用与 R3 一致的起始视口，测试设置的键盘遮挡量为 300 pt。

| 393 × 851 的键盘响应 | 布局／可视视口高度 | 原生观测剩余覆盖 | 应用有效高度 | 底部留量 |
| --- | ---: | ---: | ---: | ---: |
| 修前均不缩 | 851／851 | 300 | 851 | 0 |
| 修后均不缩 | 851／851 | 300 | 551 | 300 |
| 修后只缩 VisualViewport | 851／551 | 300 | 551 | 300 |
| 修后原生 WebView 已缩 | 551／551 | 0 | 551 | 0 |

只缩 VisualViewport 与原生 WebView 已缩时，有效高度同为 551 pt。后一种情况没有二次扣减。[只缩 VisualViewport](evidence/mobile-ssh-terminal-navigation-20261119/android-ime-browser/after-393x851-visual-opened.png) · [原生 WebView 缩高模拟，图为 393 × 551](evidence/mobile-ssh-terminal-navigation-20261119/android-ime-browser/after-393x851-native-opened.png)

修后点击「收起键盘」和模拟系统 Back 都恢复底栏可用状态。Back 仅改变受控的系统 IME 观测，用来验证 DOM 焦点可能保留时页面仍会复位。返回看板清除键盘状态，再进终端保留同一目标。修前 3 条与修后 5 条真实回环轨迹均记录一次探测，第二条连接认证、PTY 和 Shell 各一次，未向服务器提交输入。主动断开后服务端确认会话 #2 关闭，桥和夹具退出。R4 验证了 Android 原生键盘开合，系统 Back 与开合瞬间的系统画面仍待另测。

从仓库根目录运行以下命令，分别复跑产品的视口逻辑回归，并检查归档像素尺寸、哈希、控件命中、键盘恢复和服务端计数。浏览器采图批次的原始探针与数据摘要见[来源索引](evidence/mobile-ssh-terminal-navigation-20261119/android-ime-browser/index.json)。

```sh
node --test validation/tauri/test/mobile-viewport.test.mjs
node docs/evidence/mobile-ssh-terminal-navigation-20261119/android-ime-browser/verify.mjs
```

## Tauri Android 与 iOS 原生模拟器 R4

两个作业均通过并以同一源码 `b11e2b94c18ca5b11e876fc93fc71c9c806b6e7d` 归档。Android 使用 API 35、`pixel_5` 配置和 x86_64 Google APIs 镜像，iOS 使用 iPhone 17 Pro Max、iOS 26.2。两个作业的仓库权限均为 `contents: read`，测试只操作各自创建的模拟器、测试应用和隔离回环 SSH 夹具。

| 平台 | GitHub Actions | 工件与证据索引 |
| --- | --- | --- |
| Android | [作业 135371456594](https://github.com/Luck9Star/herdr-pocket/actions/runs/44468343239/job/135371456594) | [工件 14504020837](https://github.com/Luck9Star/herdr-pocket/actions/runs/44468343239/artifacts/14504020837) · [原生证据索引](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-android-r4/official-index.json) |
| iOS | [作业 135371098046](https://github.com/Luck9Star/herdr-pocket/actions/runs/44468232817/job/135371098046) | [工件 14503503703](https://github.com/Luck9Star/herdr-pocket/actions/runs/44468232817/artifacts/14503503703) · [原生证据索引](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-ios-r4/official-index.json) |

- **Android 普通案**通过 ADB 触摸应用的「打开键盘」和「收起键盘」按钮，依据设备的 WebView 边界定位，并检查中心命中。五次系统输入法采样依次为 `owned_hidden → owned_visible → owned_visible → owned_hidden → owned_hidden`，对应打开前、打开后、收起前、收起后和切页前。每次焦点和编辑器均归属本应用。收起按钮当次成功，未触发系统 Back 兜底。看板、网络、设置各自通过浏览器驱动点击实际页面控件、再从底栏返回原终端。回到终端后由浏览器驱动提交夹具输入，与服务器核对 9 字节标记，再另测 Esc、Tab、Left、Ctrl-C 的实际接收。完成后主动断开并返回首页。
- **iOS 普通案**通过 XCTest 实点键盘开合与三个页面的进入／返回控件。八步均核对同一窗口与 WebView 的控件归属、启用、完整可见和中心命中。键盘按钮均为 44 × 44 pt，点击「收起键盘」时记录的可见区为 `[0,54,440,601]` pt。打开后观测到原生键盘，后续七步均保持收起。完成切页后提交 9 字节，服务端记录 102 字节输出。实点断开和返回首页，设备与服务端均确认收尾完成。
- **两端服务端**在普通案的八个导航检查点持续观测到同一条连接 #2 保持打开，累计一次成功认证、一次 PTY、一次 Shell，输入始终为零。两端换钥案均按 `A → B → B → B` 验证拒绝、取消保留 A、重探和显式确认 B。前三条连接的认证、PTY、Shell 和输入输出计数均为零。最后一条连接认证、PTY 和 Shell 各一次，收到 9 字节输入并输出 102 字节，主动断开后确认关闭。
- **加密私钥案仅 Android 运行。** 它核对指纹后，在实际认证页填写加密 OpenSSH 私钥和口令。回环服务端确认认证、PTY、Shell、标记输入和会话关闭，应用核对终端回显、临时凭据清空及返回首页。两个平台各自清理了测试模拟器和回环夹具，详见工件索引。

以下四张是夹具输入回显后的完整原生终端图，均通过标记、令牌和回显顺序的 OCR 门禁。两张 Android 图可见系统键盘，两张 iOS 图拍于收起键盘后。Android 原图按字节保存，iOS 仅移除 PNG 文本和 EXIF，四张图的解码像素与原图逐一相同。索引同时保留原始图、归档图、OCR 门禁文件和原工件 ZIP 的 SHA256。打开键盘瞬间的系统原图另案采集，系统输入法组词、实体设备和真实跨网仍待独立验证。

| 原生系统画面 | 普通案回显 | 换钥案回显 |
| --- | --- | --- |
| Android，1080 × 2340 px | [终端原始像素](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-android-r4/ssh-terminal-android.png) | [终端原始像素](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-android-r4/ssh-rotation-terminal-android.png) |
| iOS，1320 × 2868 px | [终端原始像素](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-ios-r4/ordinary-terminal.png) | [终端原始像素](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-ios-r4/key-change-terminal.png) |

## Tauri Android R5 键盘修前后官方对照

本节归档一次修前／修后对照运行的官方证据。两个整案均以失败告终，仅截图证据链自洽，不作为通过依据；此前的 R4 通过证据保持不变。修前产品为 `bc99258239354953e17dbeca03a6cf72d0b02fcd`（驱动 `301f64d8cd2bd7ef6f9a96ed500f5d61c39b49fe`，[作业 135390332758](https://github.com/Luck9Star/herdr-pocket/actions/runs/44471920633/job/135390332758)，attempt 2），修后产品为 `b11e2b94c18ca5b11e876fc93fc71c9c806b6e7d`（驱动 `e40d4cdfb0d9e57fe214fa1c63e8f55a8c651a0a`，[作业 135383192874](https://github.com/Luck9Star/herdr-pocket/actions/runs/44471913995/job/135383192874)，attempt 1），两案 APK 哈希相异，产品布局修复落在两案产品源之间。环境均为 API 35 `pixel_5` x86_64 Google APIs 镜像、393 × 851 视口，自有模拟器起灭，系统输入法采样确认键盘归属本应用。

两张图都是键盘打开瞬间的系统原屏（`adb exec-out screencap`），通过标记 OCR、隐藏认证表单与零输入门禁；回环服务端仅观测到一次成功认证与一条保持的 Shell，输入始终为零。修前图终端延伸到键盘下方，「收起键盘」按钮框为零；修后图终端收缩到键盘上方，「收起键盘」按钮为 44 × 44 且与断开控件分离，辅助行可见。两图的逐行像素与官方工件内原图一致，未做任何改写。

修前整案在 `active_keyboard_opened` 阶段失败（`direct_active_ui_invalid`），与未修复布局缺少可命中收起控件相符。修后整案完成八步导航后在 `terminal_input` 二次开键盘失败，同错误码，但证据中没有第二次完整采样，不推测具体原因。两案限制相同：模拟器回环夹具与 ADB/CDP 驱动，非系统中文输入法组词，非实体设备，未验证真实跨网。

| 对照 | 键盘打开瞬间 | 整案状态 |
| --- | --- | --- |
| 修前（产品 bc99258，运行 44471920633） | [系统原屏](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-android-r5/before-keyboard-opened-native.png) | 失败于 `active_keyboard_opened` |
| 修后（产品 b11e2b9，运行 44471913995） | [系统原屏](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-android-r5/after-keyboard-opened-native.png) | 失败于 `terminal_input` |

索引与逐文件 SHA256 见 [证据索引](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-android-r5/official-index.json)。

## Tauri Android R7 导航后第二次打开键盘

Android API 35 x86_64 模拟器上的正式作业通过普通连接、换钥和加密 OpenSSH 私钥三案。运行源码 `1ceab7c84a6c8ed87e55586e5d0640e2b1b364ca` 的 `validation/tauri` 与 `7890fcd` 字节一致。R6 仅留下清理阶段的断点记录，无法据此确定唯一根因。原工件 ZIP 的 SHA-256 为 `dc0744be8a8cdad08e8d40733b2ae70da566872b15c2fdb43b5f8dfea07d573c`。 [官方作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44486748851/job/135432008494) · [原工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44486748851/artifacts/14511926239) · [原始清单](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-android-r7/manifest.json) · [逐文件 SHA-256](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-android-r7/SHA256SUMS)

普通案完成八次操作，依次打开与收起键盘、进入看板与返回终端、进入网络与返回终端、进入设置与返回终端。导航后的第二次打开键盘前后，系统采样从 `owned_hidden` 到 `owned_visible`，编辑器激活状态从 `false` 到 `true`。两次都核对到同一条活连接，累计成功认证、PTY 和 Shell 各一次，输入仍为零。三案随后均核对输入回显、主动断开及五项清理，包括浏览器、应用、端口正反向转发和夹具连接。

三张原始系统图均保留对应门禁 JSON。键盘图通过夹具标记、隐藏认证表单和零输入检查，普通与换钥回显图通过标记、令牌及回显顺序检查。R7 当时未覆盖加密私钥换钥。实体设备、系统输入法组词和真实跨网仍待验证。[键盘原图](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-android-r7/ime-keyboard-opened-native.png) · [普通连接原图](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-android-r7/ssh-terminal-android.png) · [换钥原图](evidence/mobile-ssh-terminal-navigation-20261119/native/tauri-android-r7/ssh-rotation-terminal-android.png)

## 2026-11-20 · Flutter 与 Tauri Android 同源复验

同一提交 `2e8c3557e2e51ae62b423f9e25a9f1fc5d72cecf` 的两壳密码案，在 API 35 x86_64 模拟器分别完成打开和收起键盘，以及看板、网络、设置的进入和返回，共八项。两侧各自保持原认证会话、一次 PTY 和一次 shell，切页期间输入为零，返回原终端后才提交回显标记。服务端确认主动断开后的会话结束，两壳分别有加密私钥及换钥组合的独立证据。[同源验收与官方 ZIP](evidence/ordinary-ssh-android-same-source-20261120/README.md)

本轮密码回显的 Flutter ADB 原图拍于键盘收起后，Tauri ADB 原图拍于键盘打开时。归档索引保留这两张原图、同次截图门禁及 Tauri 的 WebView 图。R7 的键盘原图仍对应上方历史场景。实体设备、真实中文组字和真实跨网仍待验收。[原图成员及 SHA-256](evidence/ordinary-ssh-android-same-source-20261120/official-index.json)

## 2026-11-20 · Flutter iOS 模拟器 R2

Flutter `b3c1182` 的密码案在 iPhone 11 / iOS 26.2 模拟器实际完成键盘开合及看板、网络、设置往返。八个检查点均由对端记录同一条认证会话，累计一次认证、一次 PTY 和一次 shell，导航期间零输入。返回原终端后才提交回显，主动断开并返回首页。原屏 OCR 同时核对回显与活动目标。系统键盘开合已有证据，实体设备和中文输入法组字仍待验证。[Flutter 原件与检查点](evidence/ordinary-ssh-ios-local-result-20261120/README.md#flutter-连接回显与关闭)
