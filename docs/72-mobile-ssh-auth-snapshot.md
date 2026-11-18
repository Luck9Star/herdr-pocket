# 手机普通 SSH 核验与认证快照

2026-11-19，合并前复验覆盖 Android API 35 和 iOS 26.2 模拟器。Android 两壳及 Flutter iOS 已通过普通 SSH 和换钥。Tauri iOS 复验停在密码框归属核验，普通 SSH 和换钥尚未通过。R22 入口批和 R23 本地核验保留在历史记录中。

各批沿用 [PR #4 的冻结设计](https://github.com/Luck9Star/herdr-pocket/pull/4)。画板提交为 `79deef0e9c03425f368966e32ff1f1d399a3ac02`。旧版 [15 状态前测](https://github.com/Luck9Star/herdr-pocket/blob/af273abca77fe97fd4806fe624dce89c6595869b/design/evidence/direct-ssh-mobile-20261118/baseline/README.md) 与[首批入口对照](https://github.com/Luck9Star/herdr-pocket/blob/af273abca77fe97fd4806fe624dce89c6595869b/design/evidence/direct-ssh-mobile-20261118/first-batch/README.md)提供独立参照。

## 合并前原生复验

### R2 联合复验

R2 四个作业使用 `bda3c59c7f6b4e5a4da119f26838bf511fbda780`。通过案例以独立回环 SSH 服务端核对认证、PTY、终端回显和关闭。证据 ZIP 的完整性及 SHA256 已与 Actions 工件核对。

| 壳与平台 | 结果 | 作业与工件 | ZIP SHA256 |
| --- | --- | --- | --- |
| Flutter Android API 35 | 普通、换钥通过 | [运行 44415430480](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430480/job/135194350049) · [证据 ZIP](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430480/artifacts/14480096265) | `65a6ae5e7410db187c04ca9006fa4ba4827bc1fb517114ec054bb4f9c513db64` |
| Tauri Android API 35 | 普通、换钥、独立加密私钥通过 | [运行 44415430496](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430496/job/135194348118) · [证据 ZIP](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430496/artifacts/14480765497) | `0db81a636e464589634cee3a53186649226e1490f0cf4a6370b277af87331ef0` |
| Flutter iOS 26.2，iPhone 11 模拟器 | 普通、换钥通过 | [运行 44415430176，Flutter 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430176/job/135194346642) · [证据 ZIP](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430176/artifacts/14479109985) | `30ab73fc32e11f0fdfc0c91a867d5b2d1eb4efbb700a69390707a7eee7ae5827` |
| Tauri iOS 26.2，iPhone 17 Pro Max 模拟器 | `app_install` 失败，两案均为 `not_run`，清理完成 | [运行 44415430176，Tauri 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430176/job/135194347041) · [证据 ZIP](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430176/artifacts/14479754075) | `902c514e0331a45d8eeb2fed50546d2cebc8806e1fcc718afbe7ba46dd2e6e15` |

通过的普通和换钥案例均记录了终端输入回显、主动断开和凭据清理。拒绝改变的密钥时服务端记录零认证，显式重探并确认后才连通。Tauri Android 普通与独立加密私钥均记录退回首页。两壳未在该批完成系统 IME、真机及真实跨网验收。

Flutter 认证页返回会取消尚未完成的 SSH 连接并清理临时凭据（`9b23ea5`）。Flutter iOS 作业中的 Widget 回归故意延迟回环握手，四条返回路径均在服务端留下零认证和零 PTY 记录，包括按键、系统返回、完成边缘滑动、取消滑动后按键。紧凑首页保留网络入口测试标识 `hosts-networks`（`5421861`），Widget 回归实点打开网络页并返回看板。两项分别覆盖 Widget 导航和回环连接取消。[Flutter iOS 作业及测试日志](https://github.com/Luck9Star/herdr-pocket/actions/runs/44415430176/job/135194346642)

### Tauri iOS 单壳复验

R3 沿用 R2 的 `bda3c59`。iPhone 17 Pro Max 模拟器成功安装并启动应用，经空首页、接入选择进入普通 SSH 表单。检查点推进到 `ordinary_fingerprint`，驱动报 `native_control_owner_unproven`。回环服务端记录 1 条已关闭的探测连接，认证、PTY、Shell 和输入计数均为 0。普通案失败，换钥未运行，模拟器与夹具清理完成。证据 ZIP SHA256 为 `128d3a56fcede8c919da8dcc1916afa6f54205341f7845a000c1315cc81cf073`。[运行 44418471473](https://github.com/Luck9Star/herdr-pocket/actions/runs/44418471473/job/135204869805) · [证据 ZIP](https://github.com/Luck9Star/herdr-pocket/actions/runs/44418471473/artifacts/14480489482)

R4 固定 `5af0a97c932156a01fee9c54e75fcefd5a7edd59`。相对 R2／R3，差异仅在本文及 `validation/remote-harness/` 下的 Tauri iOS Python／Swift 驱动与对应两份测试。驱动把确认、密码和连接控件限定在已核验的 WebView 下，要求当前控件唯一且可命中。出现多个候选或身份变化时停止动作。应用源码、构建输入、工作流及其余三个作业的驱动在两提交间逐字节一致。其余三个作业的证据绑定 R2 的实测 SHA。

R4 在 iPhone 17 Pro Max 模拟器上完成安装、进入普通 SSH 表单并探测主机密钥。在 `ordinary_fingerprint` 检查点，驱动点击确认后已识别认证页标题、目标端点、确认提示和仍禁用的连接按钮。随后密码框归属核验报 `native_mobile_password_owner_unproven`，未进入 `ordinary_password`，也未尝试输入凭据。公开工件和作业日志没有报告该密码框的 AX 角色、矩形和候选唯一性判定明细，具体失败条件无法从记录确认。回环服务端在清理前后均记录 1 条已关闭的 A 探测连接，认证、PTY、Shell、输入和输出均为 0。普通案失败，换钥未运行，模拟器、夹具和临时文件均已清理。工件仅含 `result.json`，ZIP SHA256 为 `75a9918eab70d01fca3335bd05b8556b0129808b8d0071f09ae4973d11543f6b`。[运行 44422766316](https://github.com/Luck9Star/herdr-pocket/actions/runs/44422766316/job/135219720647) · [证据 ZIP](https://github.com/Luck9Star/herdr-pocket/actions/runs/44422766316/artifacts/14482933932)

## R22 Android 设备证据

两次作业使用受控 API 35 x86_64 模拟器与回环 SSH，均完成普通连接、主机密钥变化、终端回显和断开。两次使用不同源码，原始 ZIP 已完整重新下载并计算 SHA256。[可复核的运行、工件及内部结果索引](evidence/mobile-ssh-auth-r23/r22-actions.json)

| 壳 | Actions 与证据工件 | 源码 | ZIP SHA256 |
| --- | --- | --- | --- |
| Flutter | [运行 44340477284](https://github.com/Luck9Star/herdr-pocket/actions/runs/44340477284) · [工件 14445171169](https://github.com/Luck9Star/herdr-pocket/actions/runs/44340477284/artifacts/14445171169) | `543ecc8ae0651df92b386dfa7d2c72692ccb229a` | `391451a82be30baefcb182721fbf106b0ee4ac45e64e0418cc14731b6335f1ab` |
| Tauri | [运行 44343883721](https://github.com/Luck9Star/herdr-pocket/actions/runs/44343883721) · [工件 14446570463](https://github.com/Luck9Star/herdr-pocket/actions/runs/44343883721/artifacts/14446570463) | `3c3105f93fba702530adf4a038939b651205a7e1` | `6846507ee0e0dfdc4372bba7306bce3917aeba7910276d958d7a0247931fa02b` |

- Flutter 回环服务端记录密码认证、PTY、输入、会话关闭，以及变钥拒绝阶段零认证。普通和换钥两案的截图门禁均通过。作业的 `physicalImeVerified` 为 `false`。
- Tauri 普通与换钥案通过终端截图门禁，保留旧信任并重探后可显式连接。独立加密私钥路径连接、回显并断开。WebView 的 CDP 输入覆盖界面事件，系统输入法组词仍需设备验证。两壳均完成受检清理。

原始 ZIP 的工件保留期由 GitHub Actions 管理。上述结果只对应 R22 入口源码。其后的同源模拟器复验见上节。

## R22 iOS 托管容量

[第一次尝试](https://github.com/Luck9Star/herdr-pocket/actions/runs/44340477261/attempts/1)与[第二次尝试](https://github.com/Luck9Star/herdr-pocket/actions/runs/44340477261/attempts/2)均使用 `543ecc8ae0651df92b386dfa7d2c72692ccb229a`。两次的 Flutter、Tauri 作业均取消、零步骤、无分配运行器。GitHub 给出了 macOS arm64 容量及未分配 hosted runner 的注解，第二次 Flutter 作业无单独注解。该批停在托管调度阶段，没有构建、设备结果或工件。

## R23 本地核验与认证

当时的统一产品与驱动检查点为 `4dc37dd3d9c1c2df75b82cc432d0e1c28956d689`，基于 R22 的 `3c3105f93fba702530adf4a038939b651205a7e1`。Tauri 产品检查点为 `58df315783c3eadd8e2d2ac5b3403a9ced47fae9`，Flutter 产品检查点为 `3fdd11b39ffdb59693d20795acccb2944a9220d9`，原生驱动检查点为 `500b1553f4efa6340a218764cfcdbb500a773473`。两壳保留独立的目标填写、可阅读的实际算法和完整指纹、显式核验与取消，以及互斥的密码和私钥输入。失败或取消无法进入会话。主动断开清空本次凭据、保留目标，返回看板时显示一次反馈。

- Flutter 3.47.9 Widget 在受控真实回环上覆盖密码、未加密与加密 OpenSSH 私钥、错误口令重试、换钥拒绝、保旧与显式重探、PTY 和回显。纯空格密码在界面保持原样，夹具未使用它认证。几何使用注入的安全区、字体与 IME inset。
- Tauri WebKit 26.5 实点运行产品 DOM、CSS 和 xterm。探测公钥由独立回环采样，IPC 夹具重放连接、拒绝、回显和关闭事件，检查原样密码、完整密钥门槛、相同会话以及看板与配对。Node 666 项及生产构建通过。安全区和键盘外框为模拟值。

Flutter 在 Widget Navigator 上复现旧版断开后边缘拖动无法开始，修复后验证取消拖动保留页面、完成拖动才返回并显示一次反馈。系统返回和按键同样复核。该修复覆盖 6 项返回测试和 11 项定向回归，该批记录来自 Widget，原生手势仍待单独实点复验。Tauri 驱动使用当前页面的精确密码标签。本地原生驱动测试发现 628 项，跳过 5 项，失败 0 项。Swift 语法解析及 7 项针对性检查通过。

两壳均采用 320×640（上 24、下 24 pt）及 390×844（上 47、下 34 pt）。Flutter 140 个已量应用锚点在 2 pt 内，18 个源未量锚点单列。Tauri 158 个已量应用锚点最大偏差 1 pt。坐标与中心命中记录见[本地量测和四对截图](evidence/mobile-ssh-auth-r23/README.md)。物理键盘、中文 IME、原生状态栏与键盘几何、活动终端与设置往返、实体设备、外网与五平台就绪仍待补证。

## 恢复与回滚

### 本地复跑

从仓库根目录运行。产品检查点为 `4dc37dd`，本地复跑固定到 `21f010a`。两个提交在 `validation/` 下只有夹具运行器有差异。新克隆若缺固定对象，先从 `origin` 取交付分支，再按完整 SHA 校验。脚本把固定源码导出到临时目录，当前工作树保留在原位。

准备已安装的 Flutter 3.47.9（framework `c197ca5199`）、Python 3.12 或更高版本及 `venv`、OpenSSH `ssh-keygen`、Node 和 npm。验证使用 Node 24.22.2、npm 12.2.1。依赖下载需可访问 pub.dev、PyPI 和 npm 注册表。Flutter 的 `ci.py prepare` 需要一个尚不存在的目标目录，它使用 SDK 生成隔离工程，校验并准备 `terminal_view` 参考渲染器和 IME 观测补丁。夹具运行器自行创建虚拟环境和临时回环身份。

```sh
(
  set -e
  replay=21f010af03705e5b272e78cc009e7a852381fcf0
  if ! git cat-file -e "${replay}^{commit}" 2>/dev/null; then
    git fetch origin refs/heads/codex/ssh-mobile-auth-integration
  fi
  git cat-file -e "${replay}^{commit}"

  isolated="$(mktemp -d)"
  src="$isolated/source"
  project="$isolated/flutter-app"
  mkdir "$src"
  git archive "$replay" validation > "$isolated/source.tar"
  tar -xf "$isolated/source.tar" -C "$src"
  printf '复跑目录 %s\n' "$isolated"
  flutter --version

  (cd "$src/validation/tauri" && npm ci && npm test && npm run build)
  python3 "$src/validation/flutter/tool/ci.py" prepare --destination "$project"
  (cd "$project" && flutter pub get --enforce-lockfile)
  python3 "$src/validation/flutter/tool/direct_ssh_fixture_runner.py" --project "$project"
)
```

Flutter 四组依次通过 32 项普通 SSH、2 项换钥、5 项手机认证与 6 项断开和返回。运行器还独立检查服务端认证、PTY、输入和密钥变化时的认证门槛。

### 原生 CI 复验

原生作业在 GitHub Actions 内准备 Flutter SDK，并执行 `candidate.py apply` 与 `verify-lock`。候选依赖只允许在 CI 生成的工程中应用。本地 Widget 复跑使用上面的参考依赖。

复跑 Tauri iOS R4 时选择 `platform=ios-tauri-only`，只触发 Tauri 作业。复跑 R2 时使用表中的 `bda3c59`，`platform=ios` 触发 iOS 两壳，`platform=android` 触发两个 Android 工作流。每次将 `attempt` 设为尚未使用的分支后缀。推送即调度一次。[iOS 工作流](../.github/workflows/direct-ssh-ios.yml) · [Flutter Android 工作流](../.github/workflows/direct-ssh-android.yml) · [Tauri Android 工作流](../.github/workflows/tauri-android-direct-ssh.yml)

```sh
(
  set -e
  checkpoint=5af0a97c932156a01fee9c54e75fcefd5a7edd59
  if ! git cat-file -e "${checkpoint}^{commit}" 2>/dev/null; then
    git fetch origin refs/heads/codex/ssh-mobile-auth-integration
  fi
  git cat-file -e "${checkpoint}^{commit}"
  platform=ios-tauri-only
  attempt=replay-r4-1
  git push origin "${checkpoint}:refs/heads/codex/acceptance/direct-ssh-$platform-$attempt"
)
```

核对两端作业的源码、步骤、设备、服务端计数、截图及清理。托管队列再次零步骤时，保留调度记录并停止追加同批尝试。

需要回到入口批次时，以 R22 检查点新建本地恢复分支，保留 R23 草稿与证据。

```sh
git switch -c codex/replay/mobile-ssh-entry-r22 3c3105f93fba702530adf4a038939b651205a7e1
git rev-parse HEAD
```

共享分支已纳入新批次时，先在独立工作分支审查并回退 R23 的产品与驱动合并提交，保留历史记录和其他变更。以 R22 检查点核对回退范围，再按待验平台重新取证。
