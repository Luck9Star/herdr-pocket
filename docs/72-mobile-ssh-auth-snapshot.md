# 手机普通 SSH 核验与认证快照

截至 2026-11-19，R22 两壳在 Android API 35 模拟器通过入口批次。iOS 的两次尝试均在分配托管运行器前结束。R23 已完成目标、首次核验、密码与私钥、换钥、断开和返回的两壳本地复核，原生模拟器复验仍待补。活动终端、系统键盘和设置往返属于后续设备验收。

两批沿用 [PR #4 的冻结设计](https://github.com/Luck9Star/herdr-pocket/pull/4)。画板提交为 `79deef0e9c03425f368966e32ff1f1d399a3ac02`。旧版 [15 状态前测](https://github.com/Luck9Star/herdr-pocket/blob/af273abca77fe97fd4806fe624dce89c6595869b/design/evidence/direct-ssh-mobile-20261118/baseline/README.md) 与[首批入口对照](https://github.com/Luck9Star/herdr-pocket/blob/af273abca77fe97fd4806fe624dce89c6595869b/design/evidence/direct-ssh-mobile-20261118/first-batch/README.md)提供独立参照。

## R22 Android 设备证据

两次作业使用受控 API 35 x86_64 模拟器与回环 SSH，均完成普通连接、主机密钥变化、终端回显和断开。两次使用不同源码，原始 ZIP 已完整重新下载并计算 SHA256。[可复核的运行、工件及内部结果索引](evidence/mobile-ssh-auth-r23/r22-actions.json)

| 壳 | Actions 与证据工件 | 源码 | ZIP SHA256 |
| --- | --- | --- | --- |
| Flutter | [运行 44340477284](https://github.com/Luck9Star/herdr-pocket/actions/runs/44340477284) · [工件 14445171169](https://github.com/Luck9Star/herdr-pocket/actions/runs/44340477284/artifacts/14445171169) | `543ecc8ae0651df92b386dfa7d2c72692ccb229a` | `391451a82be30baefcb182721fbf106b0ee4ac45e64e0418cc14731b6335f1ab` |
| Tauri | [运行 44343883721](https://github.com/Luck9Star/herdr-pocket/actions/runs/44343883721) · [工件 14446570463](https://github.com/Luck9Star/herdr-pocket/actions/runs/44343883721/artifacts/14446570463) | `3c3105f93fba702530adf4a038939b651205a7e1` | `6846507ee0e0dfdc4372bba7306bce3917aeba7910276d958d7a0247931fa02b` |

- Flutter 回环服务端记录密码认证、PTY、输入、会话关闭，以及变钥拒绝阶段零认证。普通和换钥两案的截图门禁均通过。作业的 `physicalImeVerified` 为 `false`。
- Tauri 普通与换钥案通过终端截图门禁，保留旧信任并重探后可显式连接。独立加密私钥路径连接、回显并断开。WebView 的 CDP 输入覆盖界面事件，系统输入法组词仍需设备验证。两壳均完成受检清理。

原始 ZIP 的工件保留期由 GitHub Actions 管理。上述结果绑定 R22 源码。R23 的新目标、核验与认证页面仍需同源设备验证。

## R22 iOS 托管容量

[第一次尝试](https://github.com/Luck9Star/herdr-pocket/actions/runs/44340477261/attempts/1)与[第二次尝试](https://github.com/Luck9Star/herdr-pocket/actions/runs/44340477261/attempts/2)均使用 `543ecc8ae0651df92b386dfa7d2c72692ccb229a`。两次的 Flutter、Tauri 作业均取消、零步骤、无分配运行器。GitHub 给出了 macOS arm64 容量及未分配 hosted runner 的注解，第二次 Flutter 作业无单独注解。没有构建、设备结果或工件，停在托管调度阶段。复验保留在后续明确启动的设备批次。

## R23 本地核验与认证

统一产品与驱动检查点为 `4dc37dd3d9c1c2df75b82cc432d0e1c28956d689`，基于 R22 的 `3c3105f93fba702530adf4a038939b651205a7e1`。Tauri 产品检查点为 `58df315783c3eadd8e2d2ac5b3403a9ced47fae9`，Flutter 产品检查点为 `3fdd11b39ffdb59693d20795acccb2944a9220d9`，原生驱动检查点为 `500b1553f4efa6340a218764cfcdbb500a773473`。两壳保留独立的目标填写、可阅读的实际算法和完整指纹、显式核验与取消，以及互斥的密码和私钥输入。失败或取消无法进入会话。主动断开清空本次凭据、保留目标，返回看板时显示一次反馈。

- Flutter 3.47.9 Widget 在受控真实回环上覆盖密码、未加密与加密 OpenSSH 私钥、错误口令重试、换钥拒绝、保旧与显式重探、PTY 和回显。纯空格密码在界面保持原样，夹具未使用它认证。几何使用注入的安全区、字体与 IME inset。
- Tauri WebKit 26.5 实点运行产品 DOM、CSS 和 xterm。探测公钥由独立回环采样，IPC 夹具重放连接、拒绝、回显和关闭事件，检查原样密码、完整密钥门槛、相同会话以及看板与配对。Node 666 项及生产构建通过。安全区和键盘外框为模拟值。

Flutter 在 Widget Navigator 上复现旧版断开后边缘拖动无法开始，修复后验证取消拖动保留页面、完成拖动才返回并显示一次反馈。系统返回和按键同样复核。该修复覆盖 6 项返回测试和 11 项定向回归，原生手势待设备复验。Tauri 驱动使用当前页面的精确密码标签。本地原生驱动测试发现 628 项，跳过 5 项，失败 0 项。Swift 语法解析及 7 项针对性检查通过。

两壳均采用 320×640（上 24、下 24 pt）及 390×844（上 47、下 34 pt）。Flutter 140 个已量应用锚点在 2 pt 内，18 个源未量锚点单列。Tauri 158 个已量应用锚点最大偏差 1 pt。坐标与中心命中记录见[本地量测和四对截图](evidence/mobile-ssh-auth-r23/README.md)。物理键盘、中文 IME、原生状态栏与键盘几何、活动终端与设置往返、实体设备、外网与五平台就绪仍待补证。

## 恢复与回滚

在已有检查点对象的干净工作树恢复 R23。若本地缺对象，先从发布的草稿分支 `codex/ssh-mobile-auth-integration` 取回，再核对固定 SHA。

```sh
checkpoint=4dc37dd3d9c1c2df75b82cc432d0e1c28956d689
git cat-file -e "${checkpoint}^{commit}"
git switch -c codex/replay/mobile-ssh-auth-r23 "$checkpoint"
git rev-parse HEAD
```

本地先复跑 Tauri Node 和生产构建。Flutter 使用已安装的 3.47.9 SDK，Python 在独立环境准备回环夹具依赖。使用冻结源码准备隔离工程，从交付草稿分支取已更新的夹具运行器。运行前核对草稿里的运行器包含桌面普通 SSH、换钥、手机认证和断开返回四组测试，数量应为 32、2、5 和 6。复跑只使用隔离的环回身份。

```sh
(
  cd validation/tauri
  npm ci
  npm test
  npm run build
)

draft_ref=codex/ssh-mobile-auth-integration
git merge-base --is-ancestor "$checkpoint" "$draft_ref"
git diff --exit-code "$checkpoint" "$draft_ref" -- validation/flutter/lib validation/flutter/test validation/tauri/src validation/remote-harness
git show "${draft_ref}:validation/flutter/tool/direct_ssh_fixture_runner.py"

isolated="$(mktemp -d)"
project="$isolated/flutter-app"
runner_tree="$isolated/r23-draft"
git worktree add --detach "$runner_tree" "$draft_ref"
python3 validation/flutter/tool/ci.py prepare --destination "$project"
python3 validation/flutter/tool/candidate.py apply --destination "$project"
(
  cd "$project"
  flutter pub get
)
python3 "$runner_tree/validation/flutter/tool/direct_ssh_fixture_runner.py" --project "$project"
git worktree remove "$runner_tree"
```

恢复原生批次时，从同一固定提交选择目标平台，推送一条尚未使用的验收分支。设置 `platform=ios` 触发同一 iOS 工作流的两壳作业。设置 `platform=android` 触发两个 Android 工作流。推送即调度一次。 [iOS 工作流](../.github/workflows/direct-ssh-ios.yml) · [Flutter Android 工作流](../.github/workflows/direct-ssh-android.yml) · [Tauri Android 工作流](../.github/workflows/tauri-android-direct-ssh.yml)

```sh
platform=ios
attempt=r23-r1
git push origin "${checkpoint}:refs/heads/codex/acceptance/direct-ssh-$platform-$attempt"
```

核对两端作业的源码、步骤、设备、服务端计数、截图及清理。托管队列再次零步骤时，保留调度记录并停止追加同批尝试。

需要回到入口批次时，以 R22 检查点新建本地恢复分支，保留 R23 草稿与证据。

```sh
git switch -c codex/replay/mobile-ssh-entry-r22 3c3105f93fba702530adf4a038939b651205a7e1
git rev-parse HEAD
```

共享分支已纳入新批次时，先在独立工作分支审查并回退 R23 的产品与驱动合并提交，保留历史记录和其他变更。以 R22 检查点核对回退范围，再按待验平台重新取证。
