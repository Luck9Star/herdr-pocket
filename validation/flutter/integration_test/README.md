# Flutter Android 原生身份与持续观察验收

此入口在一次性 API35 x86_64 云 AVD 内运行正式 `main()` → `HostCatalogPage` → 配对页 → 远程页。它创建实际 Android 原生身份，以公开字段和点击完成临时主机批准、SSH 签名认证、snapshot 看板、选择 pane、消费 full/delta、主动停止及删除本机身份。测试不注入 signer、catalog、适配器、MethodChannel 响应或终端帧。

原版只读入口已在 2026-11-06 的 `307c863` 云 API35 AVD 通过，来源和范围见[手机验证记录](../../../docs/15-mobile-gui-validation.md)。本批新增的 guarded 分支及焦点／未知结果回归尚未运行 Flutter analyzer、Android 构建或 AVD，不能继承历史运行结果。

## 执行边界

- 仅允许 `GITHUB_ACTIONS=true`、数字 `GITHUB_RUN_ID`、`refs/heads/codex/`，使用既有临时 fixture 和 `RUNNER_TEMP` 下生成的专用 Flutter 工程。主机必须是临时 loopback sshd，不能带 PEM／真实身份配置。
- 复用 [AVD 启停脚本](../../remote-harness/with-android-emulator.sh)，独占 `emulator-5554`、Android API35、user 0。已有包、额外设备、非模拟器、重复 reverse、未核验 scaffold 均拒绝；不会卸载预先存在的应用。
- 使用固定 Flutter 3.47.9 / `c197ca5199e9ee5661e865596c9c07294dfab51c`。此版本 [`flutter test`](https://github.com/flutter/flutter/blob/c197ca5199e9ee5661e865596c9c07294dfab51c/packages/flutter_tools/lib/src/commands/test.dart) 对设备测试选择 debug；[设备驱动](https://github.com/flutter/flutter/blob/c197ca5199e9ee5661e865596c9c07294dfab51c/packages/flutter_tools/lib/src/test/integration_test_device.dart) 使用 VM Service。因此本入口证明 debug AVD 中的正式原生通路，不能声称 release/profile APK 或物理手机通过。
- SDK [`integration_test`](https://github.com/flutter/flutter/blob/c197ca5199e9ee5661e865596c9c07294dfab51c/packages/integration_test/README.md) 只加到专用临时工程。产品 `pubspec.yaml`、锁文件和生成的 Java/Kotlin 编译目标均不改。既有候选 terminal 补丁仍需先核验；测试依赖的新增包单独留证，既有依赖块漂移即失败。
- Android 路径为生产 `AndroidDeviceKeyStore`：AndroidKeyStore AES 包装种子，原生 Bouncy Castle 软件 Ed25519 签名。它不导出私钥到 Dart，也不是硬件 Ed25519／StrongBox 证明。

## 云端复验命令

在已有云 runner、固定 Flutter SDK、JDK 和 Android SDK 准备完成后，从仓库根目录执行。此文档不授权在开发者本机安装 SDK、启动设备或触发工作流。既有 `ci.py bootstrap` 可核验固定 Flutter tag／commit，并向 `GITHUB_PATH` 写入 SDK bin；同一 shell 若需立即使用，应由调用者明确设置该 bin 的 `PATH`。

先生成独立工程并完成原有候选锁验证：

```sh
python3 validation/flutter/tool/ci.py prepare --destination "$RUNNER_TEMP/flutter-android-gui"
python3 validation/flutter/tool/candidate.py apply --destination "$RUNNER_TEMP/flutter-android-gui"
python3 -c 'import os, subprocess; subprocess.run(["flutter", "pub", "get"], cwd=os.path.join(os.environ["RUNNER_TEMP"], "flutter-android-gui"), check=True)'
python3 validation/flutter/tool/candidate.py verify-lock --destination "$RUNNER_TEMP/flutter-android-gui"
```

仅在原有候选验证通过后，增加设备测试 SDK 依赖，再验证新增锁：

```sh
python3 validation/flutter/tool/android_device_test.py prepare --destination "$RUNNER_TEMP/flutter-android-gui"
python3 -c 'import os, subprocess; subprocess.run(["flutter", "pub", "get"], cwd=os.path.join(os.environ["RUNNER_TEMP"], "flutter-android-gui"), check=True)'
python3 validation/flutter/tool/android_device_test.py verify-lock --destination "$RUNNER_TEMP/flutter-android-gui"
```

准备结果为 `.herdr-android-device-test.json`，记录源 SHA、固定 SDK、生产 Dart／Android channel 文件摘要、测试源码摘要、Gradle 摘要、基线锁与设备测试锁摘要。旧包块必须逐字一致；新增 SDK 包限 `integration_test`、`flutter_driver`、`fuchsia_remote_debug_protocol`，新增 hosted 包必须在显式白名单内且有 pub.dev SHA256。无法按此解析则停止，不自动放宽。

共享 harness 已接入 `flutter-android` 路由，可在合规云 runner 中执行：

```sh
bash validation/remote-harness/with-android-emulator.sh \
  python3 validation/remote-harness/run-ci.py \
    --paired-gui flutter-android \
    --flutter-app "$RUNNER_TEMP/flutter-android-gui" \
    --output "$RUNNER_TEMP/flutter-android-evidence"
```

不要传 `--input-fixture`。本场景只接受原版 herdr 0.9.5；候选输入另验。驱动内部核验实际 SDK 版本后运行：

```sh
flutter test --no-pub --no-uninstall --reporter expanded -d emulator-5554 \
  --dart-define-from-file=<临时公开目标文件> \
  integration_test/android_pairing_observe_test.dart
```

此集成测试 APK 含测试入口及 fixture 公开目标，只用于本次 AVD；不得替代或打包成正常产品安装包。

## 独立的 guarded 输入场景

同一入口使用 `--dart-define=POCKET_GUARDED_INPUT=true`（或公开 define 文件内 JSON 布尔值 `true`）选择隔离候选主机场景。未传时保持原版只读和 0 bytes 断言；该开关只选择测试动作，不能赋予不支持能力查询的主机写权限。实际产品仍须新 full、匹配能力、持久发送标记、显式模式及有效焦点。

公开 target JSON 继续使用原来的 schemaVersion 1 和十个字段，不新增命令或写入正文。guarded 主机来源、候选补丁摘要及 `--input-fixture` 由共享 harness 单独核验；不能给 stock 场景偷偷换主机。

guarded GUI 在完成相同配对、full/delta 后，显式选择逐键输入并从焦点终端发送 ASCII `k`。读取生产页面显示的匹配回执后，切草稿输入 `Pocket测`；切回主机列表会停止旧连接。返回原标签不得自动恢复，必须重新审查连接、选同 pane、取得新 full，再从保留草稿预览确认发送。两次写入均不补回车。停止后模式关闭，再给终端键事件不得产生额外输入。

`result.json` 的 guarded `case` 为 `android-native-pairing-guarded-input`，保留原配对、帧和清理证据；`observeMode`、`directModeDisabled`、`draftModeDisabled` 此时表示停止后的状态。新增严格布尔项为 `guardedInput`、`directInputAccepted`、`draftInputAccepted`、`hiddenTabStopped`、`hiddenTabManualRecovery`、`unsentDraftRestored`、`postStopInputDisabled`。`inputReceipts` 是两项 `{requestId,paneId,terminalId,acceptedBytes}`，请求 ID 必须不同、目标相同、长度分别为 1 和 9；`acceptedByteCounts` 为 `[1,9]`。它们来自页面可见回执行，只有完整匹配响应 ID、稳定 terminal ID、pane 和长度才生成，证明队列受理。共享 harness 还须独立核验接收器精确收到 UTF-8 `kPocket测`（10 bytes）、临时主机设备指纹及真实 PTY 尺寸，才可报告通过。

逐键阶段细分为 `guarded_direct_available`、`guarded_direct_select`、`guarded_direct_focus`、`guarded_direct_commit`、`guarded_direct_ack`、`guarded_direct_receipt`，随后仍是 `guarded_hidden_draft`、`guarded_reconnect`、`guarded_draft_review`。固定 Flutter 的 [integration binding](https://github.com/flutter/flutter/blob/c197ca5199e9ee5661e865596c9c07294dfab51c/packages/integration_test/lib/integration_test.dart) 不注册假 IME；[测试输入 API](https://github.com/flutter/flutter/blob/c197ca5199e9ee5661e865596c9c07294dfab51c/packages/flutter_test/lib/src/test_text_input.dart) 明确允许未注册时向已连接的 GUI 客户端合成提交。入口实际点按 TerminalView，核对其 `hasInputConnection` 与焦点，再用 `TestTextInput.enterText` 合成 `k`。草稿用 `tester.enterText`。这两项是 GUI 自动化输入，不证明物理 IME、中文组成过程或实体触控。

本入口不注入未知响应／网络失败，未知结果后的人工恢复由 `remote_input_widget_test.dart` 的隔离替身回归检查；真实断线及进程重启恢复仍需单独验收。失败时只公开 `failure.json` 的静态阶段、白名单异常类型和测试源码行号；不写异常正文、原始 stack、公开响应或输入文本，原异常仍会重新抛出。

## 可选的真实 curses 第二阶段

`--android-tui` 仅可与现有 guarded 输入场景及隔离候选主机共同使用。Flutter runner 将其映射为 `HERDR_ANDROID_GUARDED_TUI=true`；不开启时保留原有只读或 guarded 场景。此次新增驱动未在本机执行 Flutter analyzer、Android 构建或 AVD，不代表设备通过；Python 隔离回归与 Dart 语法检查也不替代真实 SDK 运行。

原有 `k`、系统键盘、粘贴审查、`Pocket测` 草稿、隐藏恢复和两笔回执验收保持在先。之后手机通过 app-private 的单次 `tui-start` 检查点提供已显示的 terminal ID；主机以独立 snapshot 核对目标，在确认原 10 bytes 后由 `Approval.start_tui` 将同一 pane／terminal／PTY 切到真实 curses。该控制文件不含命令或按键，不是 SSH 输入桥；启动失败或确认丢失时不重试。手机隐藏并主动恢复原标签，等待生产 `Terminal` 对象替换和当前 `Pocket TUI` 完整画面，证明启动后收到新 full，再显式选择逐键输入。

手机依次点击可见辅助按钮 Down、Tab、Backspace、Shift+Tab、Insert、Delete、F1、F1、F5、F10。每笔只点一次，核对页面回执的新 request ID、原 pane／terminal 和精确字节数。前九步还要求本观察中的 seq 前进、当前完整合成屏逐行匹配，以及真实 renderer 中变化行的内侧文字完整可见；不在累积 ANSI 或 scrollback 中搜索，不导出远端正文。帮助页与主列表的完整标题分别核对，防止旧标题残留造成误判。F10 的应用完成由外层主机报告独立确认。

新增 `result.tui` 严格包含 `receipts`（十笔）、`screenChecks`（`initial`、`select-next`、`focus-detail`、`erase-character`、`focus-list`、`insert-row`、`delete-row`、`open-help`、`close-help`、`refresh`）及 `observedInitialFull:true`，共享 `mobile_tui_evidence` 会拒绝缺步、重用原两笔 ID、目标变化、字节不符或额外字段。原 `inputReceipts` 仍只含 1 和 9 bytes 两笔。GUI 回执只证明队列受理；外层另用 `verify_tui` 核对实际 curses 十步、结束状态和接收端字节遥测，不能只凭 GUI 回执声称无重放。

同一观察 channel 内的新 full 只更换终端解析器；相同 `inputTarget` 继续沿用已显式选择的输入模式。隐藏后恢复的新 channel 会产生新目标授权对象，仍需新 full 和显式重选模式。页面实时状态现在从实际 gate 显示只读、逐键、草稿、提交中或结果未知，delta 不再覆盖为“输入关闭”；本地错误提示保留，停止后显示停止状态。

## 共享 harness 与独立 job

[`paired-android-emulator.yml`](../../../.github/workflows/paired-android-emulator.yml) 保留原 Tauri job，并新增独立 `flutter-device-key` Linux job。既有批次调用该 reusable workflow，因此无需更改批次触发器，也没有因接线而启动工作流。

1. `run-ci.py` 的 `--paired-gui flutter-android` 仍要求 `--flutter-app`，复用 stock herdr 下载／SHA 核验、临时 sshd／helper 和接收器的现有约束。
2. `paired_gui.py::run_gui` 动态导入 `run_flutter_android`，仍执行 `FixtureApproval.verify_ssh(b'')` 和 `finally` 中的撤销；本机测试另核对失败路径也撤销。
3. 报告 scope 为 API35 AVD 正式 Flutter debug UI／AndroidKeyStore；frame 证据是生产 Terminal 对象和可见序号。只有该用例实际通过且原生身份、无存储替身／签名／帧注入的严格布尔证据完整，才移除该条目的 `protected system-store runtime` 未验标签。release/profile、物理手机、相机、真实 IME、三网、像素视觉验收保持未验。
4. 专用 scaffold 完成设备依赖锁验证和定向 `flutter analyze lib integration_test` 后才进入 AVD。新增 SDK 依赖由 `android_device_test.py` 在独立工程内负责，不进入普通产品构建工程。固定 Flutter 模板使用 [compile/target SDK36、NDK 28.2.13676358](https://github.com/flutter/flutter/blob/c197ca5199e9ee5661e865596c9c07294dfab51c/packages/flutter_tools/gradle/src/main/kotlin/FlutterExtension.kt)；job 准备这些构建依赖，运行设备仍是 API35，Java/Kotlin 目标继承原模板。
5. 始终上传的路径仅含脱敏协议／设备清理报告、AVD 工具版本、两阶段锁和来源摘要；不上传 integration APK、原始日志或公开配对原串。

## 证据和清理

正式看板之前另运行一次独立的原生 signer 探针：只通过 `NativeDeviceKeys` 创建一把临时身份、读取公钥、对固定公开挑战签名、删除并检查再次读取被拒绝。它不进入 catalog，不参与主机授权；失败则停止，不替换身份或重试未知结果的写操作。runner 仅在内存用 Python cryptography 对 Ed25519 公钥、签名和固定挑战验签，app-private 有界交换文件不上传；单独 `flutter-android-signer-probe.json` 只含固定 stage、验签、删除调用返回及删除后读取拒绝的布尔值。读取拒绝不单独证明其原因是删除。探针通过不等于完整配对通过，也不证明硬件保护或物理设备行为。

测试先从默认主机列表新增身份，再返回列表重开同一待批准请求，核对原身份，证明本机原生存储读回路径。runner 读取的只有 app cache 中有界的公开 request、result、固定阶段名；主机 helper 对实际公钥审查并生成公开 response，response 以 [`adb shell -T`](https://android.googlesource.com/platform/packages/modules/adb/+/refs/heads/main/docs/user/adb.1.md) 的 stdin 写入，再原子改名。测试通过文本字段输入该响应并点击审查／批准；不提供签名 RPC 或帧注入 API。

远程页首次 full 会新建生产 `Terminal`；随后在同一对象上观察到显示 seq 增加，作为已消费 delta 的证据。测试只读对象身份和可见文字，不改对象、适配器或帧。SSH 已认证及 snapshot 看板由实际远程页面出现佐证；共享 harness 还必须核对 sshd Accepted publickey 的设备指纹，并确认持续接收器仍活着且累计字节恰好 0。只检查模式按钮不足以证明 0 输入。

UI 主动停止并显示陈旧状态后，回主机列表明确删除本机资料与身份。runner 随后终止本次 Flutter 子进程组、停止／卸载仅本次安装的包、确认 app PID 消失、删除本次 SSH reverse 及新增 VM forward；既有 forward 保留。`flutter-android-device-cleanup.json` 单独留证；任何清理项未确认都会使场景失败。外层 harness 撤销临时主机授权并清理自建 sshd/herdr，AVD wrapper 最后关闭本次 emulator。

公开报告由固定布尔／整数白名单重建，包含 `storageMocked:false`、`signerInjected:false`、`framesInjected:false` 及实际 SDK 版本。原始 Flutter、sshd、herdr 和 AVD 日志、公开配对原串、连接配置只留私有临时目录，不上传为 artifact。清理失败也不会把原始异常正文写入报告。

## 本地轻量检查

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s validation/remote-harness -p 'flutter_android_test.py' -v
```

23 项测试使用临时文本工程、模拟命令结果、假进程及 stub 批准器，覆盖非 CI／错设备拒绝、源文件与锁漂移、已有包保护、公开交换边界、报告字段过滤、原生 route 委派、归属清理及失败不可报通过。其中 3 项共享 helper 路由测试需要既有 pairing requirements；普通 Python 缺少 cryptography 时明确跳过，已在既有临时隔离环境中全部执行。它们不会启动 adb、Flutter、AVD、sshd 或读取真实身份，也不属于 Android 系统存储或 SSH 运行证据。Flutter analyzer、Gradle 编译、真实 AVD 用例及共享 harness 报告必须在后续同 SHA 云端批次另验。
