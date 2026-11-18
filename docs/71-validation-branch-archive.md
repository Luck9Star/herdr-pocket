# 验证分支归档

2026-11-18 归档了九个 Android、macOS 与普通 SSH 验证分支的源码快照。每个 GitHub 附注标签名均为 `archive/20261118/<完整旧分支名>`。已从 GitHub 向全新仓库仅取这九个标签，逐一核对标签指向的提交、根目录树和原分支一致，`git fsck --full` 通过。历史报告保留实际使用的源码、工件和结果。标签可恢复源码，GitHub Actions 工件仍按各自的保留期到期。

| 原分支 | 原提交 | 主线覆盖与归档用途 |
| --- | --- | --- |
| `codex/acceptance-android-dual-native/m2o-netmon` | [`45ea7dc`](https://github.com/Luck9Star/herdr-pocket/commit/45ea7dc6f9b99b9bc2fba0f2e53f6e31c7a0ccbf) | Android 接口枚举和测试隔离已由原生修复 `a9be92d` 吸收，保留早期构建和隔离实验供回看。 |
| `codex/acceptance-android-ts-node-plain/logdir-fixed-r2` | [`191d85f`](https://github.com/Luck9Star/herdr-pocket/commit/191d85fdcf64e2ff65ff57d8eae6fba9e0306607) | 本轮提取 normal / QA 两变体在 Android 模拟器上真实启动的严格门禁，要求两者均有完整证据。 |
| `codex/acceptance-android-ts-node-plain/round2-fd2` | [`1ef1cac`](https://github.com/Luck9Star/herdr-pocket/commit/1ef1caca77ada51855ed4eeeeba70de6de507e8e) | Go 启动修复已在主线。进程私有 fd2 采集及未完成的对照实验留作历史诊断。 |
| `codex/acceptance-android-ts-node/round2-earlylog-c199b08` | [`2566e82`](https://github.com/Luck9Star/herdr-pocket/commit/2566e8248802740d7d9dd0f7fb758232e507a67c) | 与 `c199b08` 文件树相同，保留以旧原生库重跑早期日志的触发点。 |
| `codex/acceptance/macos-secure-baseline` | [`93ec6e2`](https://github.com/Luck9Star/herdr-pocket/commit/93ec6e2074f924e4a351ad6892917ca1fe413538) | XCUITest 的等价补丁已入主线。旧表单对照源码与原始运行仍可追溯。 |
| `codex/acceptance/tauri-android-dual-overlay-device-r2-foreground-diagnostic` | [`9093dcb`](https://github.com/Luck9Star/herdr-pocket/commit/9093dcb0f117a6337661d4a44af952e8b5186190) | 主线 `8b8b4b9` 已有失败时采样和脱敏。一次性单向前台诊断留作历史。 |
| `codex/android-baseline-20261105` | [`b086299`](https://github.com/Luck9Star/herdr-pocket/commit/b08629980217b483784dde13b3949fa43fd399fc) | 保留两份旧只读看板 APK 的构建来源。主线工作流已有 Android 专用矩阵，旧矩阵缩减补丁留档。 |
| `codex/android-dual-client-acceptance` | [`98fe097`](https://github.com/Luck9Star/herdr-pocket/commit/98fe097aacca32d02a9d704d7b6e211c9127c650) | SSH 拒绝握手时报告实际指纹已由 `8657bc2` 纳入主线。本轮补齐独立 Flutter 双网 APK 的原生制品固定与来源校验，保留该分支的早期诊断。 |
| `codex/ts-easytier-concurrency` | [`c199b08`](https://github.com/Luck9Star/herdr-pocket/commit/c199b08a225cd81d05edf634b2fdfd4330109944) | Go 启动修复已在主线。固定格式的早期 logcat 采集保留用于历史复查。 |

本轮在独立 Flutter 双网 APK 构建和 Android 真实启动验收中，将 normal / QA 的原生输入由 `93ca6cd` 更新为 `547106e`，与 [Android 双网设备验收](67-android-dual-network-startup.md) 使用的源码对齐。构建和启动验收均检查下载摘要、原生来源和包内容。原生工件来自 [构建 43939326685](https://github.com/Luck9Star/herdr-pocket/actions/runs/43939326685)。

两项 CI 均使用源码 `0ad9734` 并通过。

- Android API 35 模拟器上的 normal 和 QA 变体均从 `needs-login` 到 `stopped`。清理通过，SSH 认证、新增授权和注册均为零。[真实启动验收 44290964257](https://github.com/Luck9Star/herdr-pocket/actions/runs/44290964257)
- Flutter 独立构建产出 normal 和 private-ca-qa 两份 x86_64 debug APK。本次验收范围为打包及清单校验，Flutter UI 设备测试另有独立记录。[Flutter APK 验收 44290964970](https://github.com/Luck9Star/herdr-pocket/actions/runs/44290964970)

## 恢复一个历史分支

在有 GitHub 仓库访问权限的终端运行以下命令，将 `b086299` 恢复到新的本地分支。

```sh
git init herdr-pocket-baseline-replay
cd herdr-pocket-baseline-replay
tag='archive/20261118/codex/android-baseline-20261105'
git fetch --no-tags https://github.com/Luck9Star/herdr-pocket.git "refs/tags/${tag}:refs/tags/${tag}"
git switch -c codex/replay-android-baseline-20261105 "${tag}^{commit}"
git rev-parse HEAD HEAD^{tree}
git fsck --full
```

预期提交为 `b08629980217b483784dde13b3949fa43fd399fc`，树为 `aaf7f06f2a4ebb2e251a7096e1f9ad5c4ac45d15`。
