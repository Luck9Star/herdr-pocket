# Android 普通 SSH 活动终端与目标显示

状态：2026-11-17，**R4 同源 Flutter／Tauri Android 普通／换钥、Tauri 加密私钥回归及受检清理最终通过**。范围为受控 **API 35 x86_64 模拟器**；四张真实 ADB 原屏均可见当次目标、服务端回显和两行独立词串。系统软键盘实际呈现，但自动化输入不证明手工输入法／中文 IME 或实体机验收；生产主机及五平台不在本轮范围。

## R4 最终同批验收

统一源码为 [`f25cbdce9f933ae6ce5aeb9a7ce849e95f590f57`](https://github.com/Luck9Star/herdr-pocket/commit/f25cbdce9f933ae6ce5aeb9a7ce849e95f590f57)。Flutter [运行 44003412691](https://github.com/Luck9Star/herdr-pocket/actions/runs/44003412691)和 Tauri [运行 44003412623](https://github.com/Luck9Star/herdr-pocket/actions/runs/44003412623)均成功。四张最终原屏与对应原字节判据如下：

| 客户端／场景 | 真实 ADB 原图（1080×2340） | 原字节判据 |
| --- | --- | --- |
| Flutter 普通 | [当次目标与完整回显](evidence/mobile-ssh-terminal-20261117/r4-flutter-44003412691-connected-device.png) | [ordinary-screen-proof](evidence/mobile-ssh-terminal-20261117/r4-flutter-44003412691-ordinary-screen-proof.json) |
| Flutter 换钥 | [明确复核后的连接与回显](evidence/mobile-ssh-terminal-20261117/r4-flutter-44003412691-rotation-connected-device.png) | [key-rotation-screen-proof](evidence/mobile-ssh-terminal-20261117/r4-flutter-44003412691-key-rotation-screen-proof.json) |
| Tauri 普通 | [当次目标与完整回显](evidence/mobile-ssh-terminal-20261117/r4-tauri-44003412623-ssh-terminal-android.png) | [ordinary-screen-proof](evidence/mobile-ssh-terminal-20261117/r4-tauri-44003412623-ordinary-screen-proof.json) |
| Tauri 换钥 | [明确复核后的连接与回显](evidence/mobile-ssh-terminal-20261117/r4-tauri-44003412623-ssh-rotation-terminal-android.png) | [rotation-screen-proof](evidence/mobile-ssh-terminal-20261117/r4-tauri-44003412623-rotation-screen-proof.json) |

[最终来源及哈希索引](evidence/mobile-ssh-terminal-20261117/r4-official-index.json)记录 Flutter [官方工件 14294041431](https://github.com/Luck9Star/herdr-pocket/actions/runs/44003412691/artifacts/14294041431)（815,881 字节）与 Tauri [官方工件 14293762403](https://github.com/Luck9Star/herdr-pocket/actions/runs/44003412623/artifacts/14293762403)（820,387 字节）的完整 ZIP SHA256；两者均已按下载原字节重算。归档包含四张原图、[Flutter 完整结果](evidence/mobile-ssh-terminal-20261117/r4-flutter-44003412691-result.json)、[Tauri 完整清单](evidence/mobile-ssh-terminal-20261117/r4-tauri-44003412623-manifest.json)、四份场景判据及[Flutter](evidence/mobile-ssh-terminal-20261117/r4-flutter-44003412691-independent.json)／[Tauri](evidence/mobile-ssh-terminal-20261117/r4-tauri-44003412623-independent.json)独立复核记录，共 12 份原字节文件。

两侧普通／换钥均在第 1 轮实际截图采样通过。CI Tesseract 5.3.4 对原屏严格识别后，主控以本机 5.5.4 独立复核 Flutter 四图（含 integration 表面图）与 Tauri 两图；四张主要原屏改用别场次词串均拒绝。两侧换钥均保持 A／B／B／B：取消前后仍为 2 条连接，显式重核后才有第 3 条探测，再明确确认后认证。前三条认证尝试／成功、PTY、shell、输入／输出均为 0；末条认证尝试／成功各 1 次，输入 9、输出 102 字节（shell 应用数据），全部关闭。

Tauri 普通／换钥均由 `uiautomator_full_frame` 实测原生 WebView 边界后认证终端坐标。实际原屏的系统栏下沿为 136px，「添加主机」按钮顶部为 187px，目标框顶部约 569px；两场原图均已解除 R3 的按钮覆盖。加密私钥分支的认证、PTY／shell、输入回显、主动断开及清理均通过。R4 成功不能还原 R3 泛化失败的具体原因，历史记录仍按当时证据保留。

最终本机复核：Flutter 596 项通过、5 项按条件跳过，静态分析无问题；Tauri 前端 641／641、设备驱动 53／53；远端脚手架共 510 项、含 4 项跳过（506 项通过）；Kotlin 2.2.21 的合成桩 probe 通过。跳过项不计通过，Kotlin 桩检查不作为设备剪贴板或输入法证据；日志哈希与计数在最终索引中。

本轮由既有 Herdr 协作会话分工开展 Flutter 页面／设备驱动与 Tauri 交互开发。主控随后独立核对官方工件、实际原图与服务端协议，作为最终验收和后续迭代的交接依据。

## 旧批的通过范围与截图缺口

[上一轮换钥专项](68-android-ssh-host-key-rotation.md)在源码 [`77052412af63cff61392e1fc412e7d2fe35552fd`](https://github.com/Luck9Star/herdr-pocket/commit/77052412af63cff61392e1fc412e7d2fe35552fd) 验证了同一目标 A→B、阻止认证、显式复核、服务端收发和断开清理。服务端收到测试输入、发送回显，以及客户端缓冲或 DOM 中出现回显，各自都有价值；它们不能证明用户在当时设备画面中看见了回显。

对 [Flutter 官方工件 14283905471](https://github.com/Luck9Star/herdr-pocket/actions/runs/43981097578/artifacts/14283905471) 中两张原图逐字节复核：

| 原图 | 尺寸 | 实际终端画面 | SHA256 |
| --- | --- | --- | --- |
| `connected.png` | 1080×2340 | 仅 `POCKET-ANDROID-READY`、提示符与光标，未见 `POCKET-ANDROID-SSH-OK`；已连接页未显示当前目标。 | `c2b572a520ffbd96375b89873fbeb8ace93ab962b985a2c9151f3570cfd4aea7` |
| `rotation-connected.png` | 1080×2340 | 同样仅见 READY、提示符与光标，未见回显或当前目标。 | `fd16ce10bc76d1fc78ce11e5853ce4d0f7c2a2fd6c0afb27b61c19caf67349bf` |

两张图都不能作为活动终端回显可见的通过证据。它们不推翻已独立验证的 ABBB 传输与信任状态检查。Tauri 旧批 manifest 的终端文本检查及 S10 拒绝页截图，也不补足活动终端的像素证明；不能把上述两张 Flutter 图当作 Tauri 图。

[旧图像素复核记录](evidence/mobile-ssh-terminal-20261117/baseline-pixel-review.json)保留来源、原图哈希、裁剪范围和拒绝原因，不重复复制旧工件中的图片。

## 新的公开验收判据

两壳使用各自的受控临时 SSH 服务，保留原输入 `hp-check`。开启 `DirectSshFixture(screen_proof=True)` 后，对端从[固定公开的 32 个常见四字母词](../validation/remote-harness/screen_proof_token.py)中独立随机选择 8 次，形成 40 bit、约 1.1 万亿种组合的公开 token。收到输入后一次发送原回显 `POCKET-ANDROID-SSH-OK`，随后分两行、每行 4 词发送该 token；每行 19 字符，短于原回显。该值用于本次截图新鲜度，不代替 SSH 主机身份。token 由服务端产生，不作为客户端输入，也不传给产品页面用于特判。原有未开启路径及加密私钥场景保持原协议。

驱动须在真实已连接画面中保留目标身份，并在收到回显后捕获原始 PNG。共用[截图门禁](../validation/remote-harness/terminal_screenshot_gate.py)只读取驱动测得的终端矩形内像素：同一张图必须同时识别完整回显和本次服务端 token。应用缓冲、DOM、状态文案与标题栏都不参与该结论。目标可见性由真实页面检查及原图复核独立确认，不由终端 OCR 代替。

识别先用 Tesseract 整块文本分段（`psm 6`）；若未同时匹配，才用稀疏文本分段（`psm 11`）重验同一裁剪图。同一次识别必须精确给出相邻、有序的回显及两行完整词串；空白行可忽略，提示符和其他内容不能用来拼接证明。不能拼接两次识别的局部匹配，也不接受近似字符或词纠正。本次预期值及 32 词表均不传给 OCR，仍保持原先禁用系统／频率词典的参数。公开判据另记分段模式、尝试次数与 `proofSequenceVisible`。旧 12 字符格式保留读取兼容，同样要求回显及完整 token 相邻；不要求 OCR 永远误拒旧格式。

门禁保留原图 SHA256、尺寸、终端矩形、预期回显、公开预期 token、OCR 引擎版本及两个可见布尔值。失败时保留同样的有限诊断，并以非零状态结束；不导出识别到的原文、密码、私钥或原始应用日志。token 绑定本轮服务端，旧图、错误 token、仅 READY、错误回显词、标题栏冒充及裁剪掉 token 的图片均须拒绝。

公开判据中的 `terminalBounds` 使用原图像素 `(x, y, width, height)`。复核者可在安装依赖后重跑：

```sh
python3 validation/remote-harness/terminal_screenshot_gate.py \
  --image connected.png --token "$EXPECTED_SCREEN_TOKEN" \
  --bounds "$TERMINAL_X_Y_WIDTH_HEIGHT"
```

两个变量分别取该图公开判据中的 `expectedToken` 与 `terminalBounds`；后者按逗号连接四个整数。原图及预期值必须来自同一案例。

## 本机验证与设备结果分开

[专项测试](../validation/remote-harness/test_terminal_screenshot_gate.py)用独立绘制的栅格控制图验证多字号、两类字体和 ANSI 绿色文字；包含 READY、错误词、错误／不完整 token、标题栏冒充、裁剪与缺失／失败 OCR 等反例。另以真实 loopback SSH 检查默认逐字协议未变、token 为每实例生成并由服务端单独发送。

本机使用隔离的 Pillow 12.2.0、Paramiko 4.0.0 和 Tesseract 5.5.4，词串修正后的 19 项截图／协议专项与原换钥 fixture 5 项回归，共 24 项通过。含 32 组固定字体随机词串，以及错一字符（CAVE→HAVE）、错词、词序对调、两行交换、缺行、重复首行、夹杂额外文字或提示符、READY 和跨识别路径拼接反例。对前述两张旧设备原图使用 `(0,392,1080,1748)` 终端矩形实跑，均以 `terminal_screenshot_echo_not_visible` 拒绝；回显与 token 可见值均为 false。这些结果验证门禁与反例，不增加 Android 设备覆盖。

另在独立临时工程以 Flutter 3.47.9 的原 `TerminalView` 实际绘制，显式加载项目 ProbeNerd／JetBrainsMono 字体，字号 14、逻辑尺寸 360×600，按 3 倍像素捕获 1080×1800 PNG。注入 READY 并完成首帧后，再写入回显和可区分 token；尚未 pump 时，已绘制层与首帧图 SHA256 完全相同，差异像素为 0，框架报告有帧待处理。实际 pump 100ms 后，新增 12,636 个差异像素，回显与 token 均在实际绘制图中可见。此实验说明写入完成与下一帧已绘制存在可观察间隔；它不能单独认定旧 Android 表面截图停在 READY 的具体原因。

该真实字体图的整块分段能识别回显，却漏识别 token；同一图改用稀疏分段后两行均精确匹配。因此补入第二条严格识别路径，并将[最小字体像素控制样本](../validation/remote-harness/testdata/flutter-terminal-font-control.png)纳入正例及同图错误 token 回归。该图裁自本机实际 Widget 绘制，内容为受控注入；没有 SSH 连接、Android 设备或凭据。

主控另使用本机真实 xterm 渲染的截图交叉复核：[公开检查记录](evidence/mobile-ssh-terminal-20261117/local-independent-control-audit.json)确认正确 token 通过、同一张图改用错误 token 拒绝、两张旧设备图拒绝。本机 xterm 图属于控制样本，不是 Android 原生 WebView 或 Flutter 设备显示证据。

## R1 OCR 假阴性与表示修正

首批 Android 的随机连续字符暴露了另一类 OCR 假阴性。Flutter [运行 43992117555](https://github.com/Luck9Star/herdr-pocket/actions/runs/43992117555)的[官方工件 14288109122](https://github.com/Luck9Star/herdr-pocket/actions/runs/43992117555/artifacts/14288109122)，ZIP SHA256 为 `583f80a3f20c12fb2c4c75ac65f0a351b7d41ef2d2a84b242ec7902231a3c9e2`。换钥案例的 integration 与独立 ADB 图均通过；普通案例首张原图清楚显示目标 `fixture@127.0.0.1:60585`、完整回显及 `TJ97R697V9MY`，但 Ubuntu Tesseract 5.3.4 两路均仅识别到回显，12 次不重发输入的截图重取仍拒绝。该批普通案例失败，不能因人工读得出而改写成机器验收通过。[最小原像素样本与来源](../validation/remote-harness/testdata/screen-token-samples.json)保留这次观察；回归只强制错一字／错会话拒绝，正确内容若能被严格读出应允许通过。

表示选择经过同字体对照：39px JetBrains 字体中，连续 12 字符仅 5／12，原字符集按三字符分组 9／12，去难字形后分组仍仅 14／24；未采用这些不稳定方案。固定词串在该字体 32／32 通过；再用真实 Flutter 3.47.9 `TerminalView`、字号 14、DPR 2.75、1080×907 实际绘制 33 个控制，33／33 通过。[真实绘制的小样本](../validation/remote-harness/testdata/flutter-word-token-control.png)用于严格正反例，未输入本次词表给 OCR。主控另以本机 Chromium 的真实 Tauri xterm 验证两行新词串通过、同图换另一 fixture 的完整预期拒绝；该次有模拟桥，仍不作为 Android 实机证据。

## 本机窄屏目标显示与回归

本机 Chromium 的 320×500 窄屏比较进一步检查长目标：输入后，修改前目标文字顶端为 `y=-21`、高 58，首行已被滚动裁掉；定稿后改为可横滑单行，顶端为 `y=15`、高 22。目标内容宽 544、可见宽 288，实际可横滑至末尾偏移 256；不是将完整长目标挤进同一画面。两张真实 xterm 图中的终端均保持 `y=65`、高 192。将表单地址改为 `changed-form.invalid` 后，已连接快照仍为 `long-fixture-user-plus-23@[2001:db8:abcd:1234::aa]:22`，显示目标与该快照相同，没有跟随已修改的表单。原记录及对应 PNG 的哈希、像素尺寸见同一公开检查记录的 `chromiumGeometryControls`；未重复归档本机大图。

390×844 正常短目标另经实际浏览器驱动检查：`targetMatched`、`targetVisible`、`terminalVisible` 均为 true；目标矩形为 `(16,188.8125,358,22)`，终端为 `(24,238.8125,337,352)`，设备像素比为 2。这些坐标使用 CSS 逻辑像素；长、短目标控制图均检查浏览器实际绘制及页面状态，不证明 Android、原生 Tauri 运行或本轮 SSH 传输通过。

源码 `80aab97` 的独立本机复核：Flutter analyze 无问题，596 项通过、5 项按条件跳过；Tauri Node 638／638；共享回环 harness 共 480 项、4 项跳过；定稿 Tauri Android 驱动 33／33。这组数字早于可读词串修正，后者的 24 项专项另记如上。跳过项不计通过，上述本机检查不替代设备运行。

## R2 官方设备结果与失败边界

R2 两壳统一源码为 [`5f588efde42c66472c8b909500a1d8cadc11d829`](https://github.com/Luck9Star/herdr-pocket/commit/5f588efde42c66472c8b909500a1d8cadc11d829)，均使用受控 Android API 35 模拟器。[原字节归档与官方来源索引](evidence/mobile-ssh-terminal-20261117/r2-official-index.json)记录两份 ZIP 的重算 SHA256、原始文件字节数及截图哈希。**Flutter 通过、Tauri 失败；本批没有两壳共同通过结论。**

### Flutter：普通与换钥均通过

[运行 43996793904](https://github.com/Luck9Star/herdr-pocket/actions/runs/43996793904)成功；[官方工件 14290377942](https://github.com/Luck9Star/herdr-pocket/actions/runs/43996793904/artifacts/14290377942)的 ZIP 为 **826,666 字节**，SHA256 `6d79735d85dcb22045928459c3398050f0bd6f74baed412d5dfb42c6b565c5b0`，与下载原字节重算相等。[原始结果 JSON](evidence/mobile-ssh-terminal-20261117/r2-flutter-43996793904-result.json)记录通过及受检清理完成，未上传原始日志。

[普通判据](evidence/mobile-ssh-terminal-20261117/r2-flutter-43996793904-ordinary-screen-proof.json)与[换钥判据](evidence/mobile-ssh-terminal-20261117/r2-flutter-43996793904-key-rotation-screen-proof.json)均在采样轮次 1 接受。每场分别保留 integration 表面图及独立 ADB 原屏图，共四图；均为 1080×2340，终端矩形为 `(0,468,1080,907)`。普通目标为 `fixture@127.0.0.1:49333`，换钥目标为 `fixture@127.0.0.1:36167`；两张 ADB 原图均可见对应目标、完整回显和两行本次词串。四图在 CI Tesseract 5.3.4 严格通过，主控再以本机 5.5.4 对原图、正确 token 及哈希[独立重跑](evidence/mobile-ssh-terminal-20261117/r2-flutter-43996793904-independent.json)。采样轮次与同一图内部的两种 OCR 分段尝试不是同一个计数。

换钥四连接顺序 A／B／B／B。前三条的认证尝试／成功、PTY、shell、输入与输出均为 0；末条 B 认证尝试与成功各 1 次，PTY／shell 各 1 次，输入 **9 字节**、输出 **102 字节**，最终四条关闭，清理通过。这些字节属于 shell 应用数据，不代表 SSH 总流量。

### Tauri：真屏可读，驱动坐标认证失败

[运行 43996793907](https://github.com/Luck9Star/herdr-pocket/actions/runs/43996793907)已构建 APK，但[原始 manifest](evidence/mobile-ssh-terminal-20261117/r2-tauri-43996793907-manifest.json)为失败，错误 `direct_terminal_framebuffer_mapping_invalid`。普通场景三次截图采样后仍未完成坐标认证；[保留判据](evidence/mobile-ssh-terminal-20261117/r2-tauri-43996793907-ordinary-screen-proof-failed.json)的第三次采样前后均为 `webViewHierarchyParsed:false`。换钥场景未运行，不能计为通过或据此推断失败。

[官方工件 14289969072](https://github.com/Luck9Star/herdr-pocket/actions/runs/43996793907/artifacts/14289969072)的 ZIP 为 **170,659 字节**，SHA256 `284264efff4f3df9c8b2c2f9690ef162ca1eb3603e1bd7eeee39a16decd9bb0f`，与下载原字节重算相等。[保留的普通设备原图](evidence/mobile-ssh-terminal-20261117/r2-tauri-43996793907-ordinary-overlap.png)为 1080×2340，SHA256 `18f223d4fa3391b57544b5178aa842210bb6ed34b29f4e7ccb13def220cc8f31`。图中正确目标 `fixture@127.0.0.1:46781`、回显和完整词串均可见；顶部系统状态栏覆盖应用标题与按钮，另作 R3 的画面对照。

主控在该原图手工量得 `(66,684,484,820)`，三行严格 OCR [通过](evidence/mobile-ssh-terminal-20261117/r2-tauri-43996793907-manual-ocr.json)。**手工量图只确认该矩形里的实际像素内容，不能替代驱动缺失的 WebView→原屏坐标认证，也不改变本次失败结论。** 已观察到的状态栏遮挡与坐标认证失败分别记录，不由截图单独推断因果。

## R3 当时：终端分项通过，Tauri 完整流程失败

同源 [`84177d58e1f3f167b79d4338ef63bcc4e4c6d1e1`](https://github.com/Luck9Star/herdr-pocket/commit/84177d58e1f3f167b79d4338ef63bcc4e4c6d1e1) 的受控 Android API 35 模拟器结果如下。[历次官方索引](evidence/mobile-ssh-terminal-20261117/official-batches-index.json)与[R3 来源及原字节清单](evidence/mobile-ssh-terminal-20261117/r3-official-index.json)保留两端官方工件、文件哈希和独立复核记录。

| 客户端 | 官方运行 | 普通／换钥终端分项 | 完整工作流 |
| --- | --- | --- | --- |
| Flutter | [43999535238](https://github.com/Luck9Star/herdr-pocket/actions/runs/43999535238) | 两场均在第 1 轮采样接受，正确目标、回显和完整词串可见。 | 成功，受检清理通过。 |
| Tauri | [43999535331](https://github.com/Luck9Star/herdr-pocket/actions/runs/43999535331) | 两场均在第 1 次实际 ADB 采样接受，并完成原生 WebView 边界认证。 | 随后 `encrypted_key` 阶段失败，错误 `direct_driver_failed`；整条工作流失败。 |

Flutter [官方工件 14291876959](https://github.com/Luck9Star/herdr-pocket/actions/runs/43999535238/artifacts/14291876959)为 **834,058 字节**，ZIP SHA256 `47d8c3ed0fb8f78c6cc4f8d90b50b1a31a452701545bdb2a50eaaf9e55e9809d`；Tauri [官方工件 14291269159](https://github.com/Luck9Star/herdr-pocket/actions/runs/43999535331/artifacts/14291269159)为 **818,173 字节**，ZIP SHA256 `62a48f3e80b54f9398e81fe545808c0e8b13cb6fda0af19bbf7971704a620e75`。两份 ZIP 均已按下载原字节重算核对。

### 实际原图与自动坐标认证

两端普通／换钥共四张主要 ADB 原图均显示本次目标与按序的回显、两行词串。Flutter [普通](evidence/mobile-ssh-terminal-20261117/r3-flutter-43999535238-ordinary-screen-proof.json)／[换钥](evidence/mobile-ssh-terminal-20261117/r3-flutter-43999535238-key-rotation-screen-proof.json)另有 integration 表面图；主控对四张 Flutter 图[独立重跑](evidence/mobile-ssh-terminal-20261117/r3-flutter-43999535238-independent.json)。Tauri [普通](evidence/mobile-ssh-terminal-20261117/r3-tauri-43999535331-ordinary-screen-proof.json)／[换钥](evidence/mobile-ssh-terminal-20261117/r3-tauri-43999535331-rotation-screen-proof.json)均记录 `coordinateMethod=uiautomator_full_frame`、唯一实测 WebView 原生边界 `(0,0,1080,2340)`，终端原屏矩形 `(66,710,945,967)`；两张 ADB 图的正确 token 与哈希也已[独立重跑](evidence/mobile-ssh-terminal-20261117/r3-tauri-43999535331-independent.json)。因此 R3 的两场 Tauri 像素结论使用驱动认证坐标，不借用 R2 的手工裁剪。

Flutter [原结果](evidence/mobile-ssh-terminal-20261117/r3-flutter-43999535238-result.json)与 Tauri [原 manifest](evidence/mobile-ssh-terminal-20261117/r3-tauri-43999535331-manifest.json)分别保留换钥阶段证据，两个客户端的普通／换钥分项成立。原图哈希与官方内部路径在 R3 索引中；本批仅在本地保留下一节的一张遮挡例图，避免重复归档每版图片。

### R3 当时未收口的两项

[R3 Tauri 普通设备原图](evidence/mobile-ssh-terminal-20261117/r3-tauri-43999535331-ordinary-overlap.png)仍可见系统图标压住「添加主机」按钮紫底。对同一采样帧的 CDP 图与实际 ADB framebuffer 逐像素对照：检查区间 `x=820..1009、y=45..114` 中，**494 个** CDP 纯品牌紫像素 `(79,70,229)` 在 framebuffer 变为 `(32,28,92)`，变化像素包围盒为 `x=897..1002、y=78..86`（均为含端点坐标）。此结果已独立复算并记入 R3 索引，证明实际画面仍有系统覆盖；终端 OCR 通过不代表顶部遮挡已修好。

此外，R3 Tauri manifest 明确处于 `phase=encrypted_key`，该分支 `connectionObserved=false`、`authenticationAccepted=false`，然后以泛化的 `direct_driver_failed` 结束。没有观察到该分支的对端连接，不能据此认定是服务端拒绝、私钥校验失败或某个特定原因；此前普通／换钥的成功字段也不能覆盖该分支失败。R3 整条 Tauri 工作流按当时证据保持失败结论。

主控另用仓库相同版本 Kotlin 2.2.21 完成 Android clipboard／insets probe 的本机编译检查。该项属于编译证据，不改变上述 ADB 原图的覆盖观察，也不构成加密私钥设备回归通过。

两条 CI 固定使用 Ubuntu 24.04 的 [Tesseract 5.3.4-1build5](https://packages.ubuntu.com/noble/tesseract-ocr)、[English 1:4.1.0-2](https://packages.ubuntu.com/noble/tesseract-ocr-eng) 和 Pillow 12.2.0，并设置 `HERDR_REQUIRE_SCREENSHOT_OCR=1`；缺依赖或实际 OCR 失败均不能跳过。CI 引擎与本机 5.5.4 分开记录。

R1 源码为 [`80aab97fc78fa11a115d4fe47b69c374aba80011`](https://github.com/Luck9Star/herdr-pocket/commit/80aab97fc78fa11a115d4fe47b69c374aba80011)，R1／R2／R3 均保留各自当时的结果。最终验收以本页顶部的 R4 同源原屏、完整流程与[已收口的官方总索引](evidence/mobile-ssh-terminal-20261117/official-batches-index.json)为准；范围仍限 API 35 x86_64 模拟器与受控 SSH 服务。
