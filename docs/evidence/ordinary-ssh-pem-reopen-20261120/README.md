# 普通 SSH 私钥收起与重开验收

2026-11-20，[PR #56](https://github.com/Luck9Star/herdr-pocket/pull/56) 的七个原生作业已按各自源码归档。Windows Flutter、Linux Flutter 和 Linux Tauri 完成受控回环会话。Windows 和 Tauri Linux 证实私钥摘要可实际点击，编辑器重开后得到同一份完整草稿，再失焦时收起。Flutter Linux 的现有作业证实点击摘要并逐字读回，第二次收起仍需用加强后的驱动复验。

## 原生作业与新交互

| 客户端和范围 | 作业实际结果 | 私钥交互实证 | 官方来源 |
| --- | --- | --- | --- |
| Flutter Windows，Win32 调试窗口 | 未加密私钥通过。A → A，探测零认证，第二条连接认证、PTY 和 shell 各一次。终端 OCR、关闭、返回首页和清理均通过。 | 工件直接记录 `collapsedSemanticsAbsent`、`summaryHit`、`reopenedExactFocused`、`collapsedAgain` 和空口令均为真。语义检查属 Flutter 测试框架。 | [作业 136026510470](https://github.com/Luck9Star/herdr-pocket/actions/runs/44657280869/job/136026510470) · [工件 14594141698](https://github.com/Luck9Star/herdr-pocket/actions/runs/44657280869/artifacts/14594141698) |
| Flutter Linux，GTK/Xvfb | 加密 Ed25519 通过。切换认证方式后清空原草稿并保留主机信任。错口令本地拒绝，服务端仍只有首条探测。正确口令后认证、PTY 和 shell 各一次，终端 OCR、关闭、返回首页和清理均通过。 | 同 SHA 的 `pastePem` 强制等待摘要、实点并逐字读回。明确验证重开焦点和再次收起的断言出现在后续驱动，此运行未覆盖。 | [作业 136021736998](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655843951/job/136021736998) · [工件 14592029874](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655843951/artifacts/14592029874) |
| Tauri Linux，WebKitGTK/Xvfb | 加密 Ed25519 通过。错口令分支完成一次握手并关闭，认证、PTY 和输入均为零。第三条连接有两次认证尝试和一次成功，PTY 和 shell 各一次。终端 OCR、关闭、返回首页和清理均通过。 | 同 SHA 的 `fill_encrypted_credentials` 在错／对口令两轮均强制实点摘要、读回完整草稿并核对编辑器焦点，再点口令框验证收起。与成功作业联证，报告没有逐项布尔值。 | [作业 136035013147](https://github.com/Luck9Star/herdr-pocket/actions/runs/44659819875/job/136035013147) · [工件 14595262144](https://github.com/Luck9Star/herdr-pocket/actions/runs/44659819875/artifacts/14595262144) |
| Flutter iOS，iPhone 11／iOS 26.2 模拟器 | 作业失败。普通密码与密码换钥已通过各自的回环、终端 OCR 和连接关闭。加密案在 `encrypted_review` 报 `StateError`，服务端仅一条已关闭 A 探测，零认证、PTY 和收发。模拟器与临时凭据已清理。 | 报告第 897 行指向等待确认后回调，具体抛出位置由本地 Flutter Widget 复现定位。旧脚本在切换到私钥后读取已收起的编辑控件。修复已纳入 `bb989d7d` 并通过本地回归。此作业尚未验到新的重开路径。 | [作业 136021575113](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655797075/job/136021575113) · [工件 14593164376](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655797075/artifacts/14593164376) |
| Tauri iOS，iPhone 17 Pro Max／iOS 26.2 模拟器 | 手填加密案完成指纹确认及错误 PEM 逐字读回，在口令检查点报 `native_encrypted_key_owner_unproven`。唯一探测已关闭，认证、PTY、shell 和收发均为零。普通密码与换钥未运行，清理通过。 | 记录只到错误 PEM 读回。口令填入、摘要重开全链路和成功认证仍待验。 | [作业 136021697365](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655832397/job/136021697365) · [工件 14593878299](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655832397/artifacts/14593878299) |
| Flutter macOS，原生窗口 XCUITest | 四项运行，三项通过。密码、加密私钥及返回后重开通过。系统遮蔽综合用例 `testSystemMasking` 在第 302 行报焦点／交互失败，整项作业失败。加密案已观测口令输入、服务端鉴权、PTY、shell 和断开窗口内关闭。 | 该次工件没有私钥收起／重开的完整断言与截图。加密 SSH 子用例通过，系统遮蔽全流程仍待复验。 | [作业 136023680726](https://github.com/Luck9Star/herdr-pocket/actions/runs/44656429126/job/136023680726) · [工件 14593682533](https://github.com/Luck9Star/herdr-pocket/actions/runs/44656429126/artifacts/14593682533) |
| Flutter Android，API 35 x86_64 模拟器 | 已观察应用包，未观察应用检查点，也未交付凭据。SSH 连接数为零。Emulator 37.3.10 的受管进程退出值为 132，反向转发及卸载两项清理未证实。 | 本次未达私钥交互。退出码记录了模拟器进程的终止状态，现有工件不足以定位触发原因。 | [作业 136021715465](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655838242/job/136021715465) · [工件 14593502076](https://github.com/Luck9Star/herdr-pocket/actions/runs/44655838242/artifacts/14593502076) |

作业使用临时 SSH 夹具和受控回环。Win32、GTK/Xvfb 与 macOS XCUITest 均运行对应原生桌面应用，输入由验收驱动完成。手机记录来自模拟器。实体设备、物理 IME 和真实远端或跨网连接不在本批范围内。

## 截图和源码

| 场景 | 截图 | 实测驱动 |
| --- | --- | --- |
| Flutter Windows，1024 × 705 Win32 客户区 | [终端](windows-flutter/ordinary-terminal.png) · [断开](windows-flutter/ordinary-disconnect.png) · [首页](../windows-ordinary-ssh-publickey-20261120/ordinary-home.png) | [`32e1a7c7` 私钥交互](https://github.com/Luck9Star/herdr-pocket/blob/32e1a7c7d1083d9d86119a2681e3b9213cce6fa8/validation/flutter/integration_test/windows_direct_ssh_test.dart#L422-L505) |
| Flutter Linux，1920 × 1080 X11 原屏 | [终端](linux-flutter/ordinary-terminal.png) · [断开](linux-flutter/ordinary-disconnect.png) · [首页](linux-flutter/ordinary-home.png) | [`8769fd5` 粘贴及逐字读回](https://github.com/Luck9Star/herdr-pocket/blob/8769fd50e6044d632a9427bd38c578a06dadd6fa/validation/flutter/integration_test/linux_direct_ssh_test.dart#L263-L306) |
| Tauri Linux，1440 × 1200 WebKitGTK 视口 | [终端](linux-tauri/ordinary-terminal.png) · [断开](linux-tauri/ordinary-disconnect.png) · [首页](linux-tauri/ordinary-home.png) | [`939097e1` 错／对口令共用驱动](https://github.com/Luck9Star/herdr-pocket/blob/939097e17ffceef1ca5739f580eda36e4572932b/validation/remote-harness/tauri_linux_direct_ssh.py#L250-L272) |
| Flutter iOS 模拟器，828 × 1792 系统原屏 | [普通密码终端](ios-flutter/ordinary-terminal.png) · [密码换钥后终端](ios-flutter/key-change-terminal.png) | [`8769fd5` 确认后回调](https://github.com/Luck9Star/herdr-pocket/blob/8769fd50e6044d632a9427bd38c578a06dadd6fa/validation/flutter/integration_test/direct_ssh_ui_steps.dart#L883-L905) |

归档图逐张检查画面和 OCR，未发现私钥正文或可读口令。图中端点和终端验证词来自公开合成夹具。桌面图保持原 PNG 字节，Windows 首页图与已有归档字节完全一致。两张 iOS 原屏图只移除 EXIF 块，解码像素逐字节一致。首轮 iOS 工件内的密码遮罩、换钥核对和 Tauri 首页图仍可按原 ZIP 取回。原图及 OCR 判据的 SHA-256 单独记录。[工件索引](official-index.json) · [归档文件校验](SHA256SUMS)

同尺寸合成对照使用 Flutter Widget 产品基线 `72afe632` 和 Tauri Playwright WebKit 产品基线 `8769fd5`。图片用于比较表单空间与摘要位置。Flutter 的修复前后对照使用同一配置和公开合成文本。[Flutter 修复前失焦图](../../../design/evidence/ordinary-ssh-pem-geometry-20261120/before-blur.png) · [Flutter 修复后失焦图](../../../design/evidence/ordinary-ssh-pem-geometry-20261120/after-blur.png)

| 视口 | Flutter Widget 摘要 | Tauri Playwright WebKit 摘要 |
| --- | --- | --- |
| 390 × 844 | [Flutter 手机图](../../../design/evidence/ordinary-ssh-pem-geometry-20261120/mobile-collapsed.png) | [Tauri 手机图](../tauri-pem-collapse-geometry-20261120/pem-collapsed-390.png) |
| 980 × 780 | [Flutter 桌面图](../../../design/evidence/ordinary-ssh-pem-geometry-20261120/desktop-collapsed.png) | [Tauri 桌面图](../tauri-pem-collapse-geometry-20261120/pem-collapsed-980.png) |

[Flutter 几何、源图和复跑](../../../design/evidence/ordinary-ssh-pem-geometry-20261120/README.md)覆盖 Widget 几何、语义树和焦点，含本机受控回环指纹探测。[Tauri 双尺寸探针与复跑](../tauri-pem-collapse-geometry-20261120/README.md)覆盖公开合成草稿、DOM 和焦点，使用合成 IPC。两项均属于本地界面证据。

## 校验和复跑

七个 ZIP 的大小、SHA-256 和源码 SHA 均与 GitHub Actions 工件记录一致。每个 ZIP 的 CRC 和 `result.json` 的源码、状态已复核，内图逐张核对原始报告的摘要。Windows 测试源码按检出时的 CRLF 核对，Linux Flutter 按 LF 核对。索引保留原报告哈希、判定和值班所需的协议计数，原始报告和日志仍由上表的工件链接提供。

在本目录执行下列命令。若 GitHub 工件仍在保留期，需使用有读取权限的 GitHub CLI。ZIP 存在于独立临时目录。

```sh
shasum -a 256 -c SHA256SUMS

artifact=14594141698
zip=$(mktemp)
gh api "repos/Luck9Star/herdr-pocket/actions/artifacts/$artifact/zip" > "$zip"
unzip -t "$zip"
shasum -a 256 "$zip"
unzip -p "$zip" result.json | shasum -a 256
```

将下载的 ZIP 和报告哈希与 [工件索引](official-index.json)比较。Android 原报告路径为 `direct-ssh-public/result.json`，可在索引的 `manifestFile` 查看。

本地 Flutter 回归从目标提交导出到临时目录，使用 Flutter 3.47.9 和 Paramiko 4.0.0。几何测试使用本机临时 SSH 夹具，工作树无需切换。

```sh
set -eu
repo=$(git rev-parse --show-toplevel)
tmp=$(mktemp -d)
mkdir "$tmp/source"
git -C "$repo" archive 8769fd50e6044d632a9427bd38c578a06dadd6fa | tar -x -C "$tmp/source"
python3 "$tmp/source/validation/flutter/tool/ci.py" prepare --destination "$tmp/app"
python3 -m venv "$tmp/venv"
"$tmp/venv/bin/pip" install 'paramiko==4.0.0'
(
  cd "$tmp/app"
  flutter pub get --enforce-lockfile
  HERDR_FIXTURE_PYTHON="$tmp/venv/bin/python" \
    flutter test --no-pub test/direct_ssh_pem_geometry_test.dart test/direct_ssh_pem_collapse_test.dart
)
```

云端须用已授权的验收分支，先核对远端分支指向索引中的目标 SHA。每次选需复验的作业，参数和分支要求取决于目标工作流。以下 `ref` 是已存在的 `codex/` 验收分支名。

```sh
git ls-remote --exit-code origin "refs/heads/$ref"
gh workflow run windows-ordinary-ssh.yml --ref "$ref" -f authentication=publickey
gh workflow run paired-gui-validation.yml --ref "$ref" -f linux_direct_ssh=flutter-key
gh workflow run paired-gui-validation.yml --ref "$ref" -f linux_direct_ssh=tauri-key
gh workflow run flutter-macos-secure-xcui.yml --ref "$ref"
gh workflow run direct-ssh-android.yml --ref "$ref" -f auth_case=encrypted-key
```

iOS 通过分支前缀选择必需路径。Flutter 使用 `codex/acceptance/direct-ssh-ios-flutter-only-encrypted-key-`，Tauri 使用 `codex/acceptance/direct-ssh-ios-tauri-only-encrypted-manual-`，后缀标识独立复跑。前者还能因匹配 push 条件启动，检查已有 run 后再决定是否调度。

```sh
gh workflow run direct-ssh-ios.yml --ref "$ios_ref"
```

复验时核对作业 SHA、设备、凭据交互门禁、服务端认证与 PTY 计数、终端 OCR、主动断开和清理。回环会话通过与私钥交互结果各自记录。
