# Flutter Android 原生身份与持续观察验收

此入口在一次性 API35 x86_64 云 AVD 内运行正式 `main()` → `HostCatalogPage` → 配对页 → 远程页。它创建实际 Android 原生身份，以公开字段和点击完成临时主机批准、SSH 签名认证、snapshot 看板、选择 pane、消费 full/delta、主动停止及删除本机身份。测试不注入 signer、catalog、适配器、MethodChannel 响应或终端帧。

截至 2026-11-06，云端接线已完成，23 项 Flutter Android 隔离测试、13 项现有 harness 回归及 Dart 语法解析通过；本入口尚未运行 Flutter analyzer、Android 构建或 AVD。源码存在不能记作手机验收通过。现有 Widget＋内存 signer 和 Tauri Android 的历史结果仍各自独立。

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

## 共享 harness 与独立 job

[`paired-android-emulator.yml`](../../../.github/workflows/paired-android-emulator.yml) 保留原 Tauri job，并新增独立 `flutter-device-key` Linux job。既有批次调用该 reusable workflow，因此无需更改批次触发器，也没有因接线而启动工作流。

1. `run-ci.py` 的 `--paired-gui flutter-android` 仍要求 `--flutter-app`，复用 stock herdr 下载／SHA 核验、临时 sshd／helper 和接收器的现有约束。
2. `paired_gui.py::run_gui` 动态导入 `run_flutter_android`，仍执行 `FixtureApproval.verify_ssh(b'')` 和 `finally` 中的撤销；本机测试另核对失败路径也撤销。
3. 报告 scope 为 API35 AVD 正式 Flutter debug UI／AndroidKeyStore；frame 证据是生产 Terminal 对象和可见序号。只有该用例实际通过且原生身份、无存储替身／签名／帧注入的严格布尔证据完整，才移除该条目的 `protected system-store runtime` 未验标签。release/profile、物理手机、相机、真实 IME、三网、像素视觉验收保持未验。
4. 专用 scaffold 完成设备依赖锁验证和定向 `flutter analyze lib integration_test` 后才进入 AVD。新增 SDK 依赖由 `android_device_test.py` 在独立工程内负责，不进入普通产品构建工程。固定 Flutter 模板使用 [compile/target SDK36、NDK 28.2.13676358](https://github.com/flutter/flutter/blob/c197ca5199e9ee5661e865596c9c07294dfab51c/packages/flutter_tools/gradle/src/main/kotlin/FlutterExtension.kt)；job 准备这些构建依赖，运行设备仍是 API35，Java/Kotlin 目标继承原模板。
5. 始终上传的路径仅含脱敏协议／设备清理报告、AVD 工具版本、两阶段锁和来源摘要；不上传 integration APK、原始日志或公开配对原串。

## 证据和清理

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
