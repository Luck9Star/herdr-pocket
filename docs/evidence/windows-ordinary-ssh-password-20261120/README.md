# Flutter Windows 普通 SSH 密码验收

2026-11-20，Flutter Windows debug 应用在 GitHub `windows-2022` 原生 Win32 窗口完成普通 SSH 密码连接、输入回显、主动断开和返回首页。临时 SSH 服务只监听本机回环，输入由 Flutter integration test 提交。Windows 私钥认证、主机换钥、Tauri、物理键盘与 IME、公开发布包和外部主机仍待另验。

| 批次 | 验收源码 | Actions 与原始工件 | 官方 ZIP SHA-256 |
| --- | --- | --- | --- |
| 主线复验 | `5d69cbaf6f39473076530caedabfc3796757199c` | [运行 44609170985](https://github.com/Luck9Star/herdr-pocket/actions/runs/44609170985) · [工件 14571877224](https://github.com/Luck9Star/herdr-pocket/actions/runs/44609170985/artifacts/14571877224) | `2e9e8fd0d87161ebfb4390259b36b473bcf1fc258ec8552bfd9549b1a0e6e8c8` |
| 早期 R8 | `7fcf7e458923995fb6ec66f34f9793bdb4745eda` | [运行 44607208937](https://github.com/Luck9Star/herdr-pocket/actions/runs/44607208937) · [工件 14571556209](https://github.com/Luck9Star/herdr-pocket/actions/runs/44607208937/artifacts/14571556209) | `f9a9d9959b9b27cc908c0274da21c8aed87dbb8050082edc1ac61c85959ded49` |

主线复验从 #41 的合并提交 `8ecc7c7` 衍生，包含独立 Windows 验收驱动。相对 `8a38ada`，Flutter 产品 Dart、原生入口、依赖锁、终端候选补丁和构建准备文件一致。作业验证了 Flutter 3.47.9 和 45 份生产 Dart 文件。Windows 验收入口已随 #45 合入 `46a2c1f`，主线复验源码是该合并提交的父提交。早期 R8 源码保留在归档标签 `archive/20261120/codex/windows-ordinary-ssh-run-r8`。 [PR #41](https://github.com/Luck9Star/herdr-pocket/pull/41) · [PR #45](https://github.com/Luck9Star/herdr-pocket/pull/45) · [固定源码工作流](https://github.com/Luck9Star/herdr-pocket/blob/5d69cbaf6f39473076530caedabfc3796757199c/.github/workflows/windows-ordinary-ssh.yml)

## 七项验收

| 检查 | 主线复验结果 |
| --- | --- |
| 首页进入 | 从实际应用首页进入普通 SSH。 |
| 首次指纹 | 显示 `rsa-sha2-512`，完整 SHA256 指纹先与夹具独立计算值一致，再明确确认。首条连接关闭，认证、PTY、shell、输入和输出均为 0。 |
| 密码认证 | 第二条连接沿用同一 A 主机密钥。临时密码认证仅尝试 1 次并成功。 |
| PTY 与 shell | 各请求 1 次。对端记录 PTY 从 80×24 调整为 82×27。 |
| 可见回显 | 对端收到 9 字节输入，累计输出 102 字节。Tesseract 5.5.3.20260724 在终端裁框内确认回显标记及校验序列。[终端原图](ordinary-terminal.png) |
| 主动断开 | UI 显示「本机已断开」并清空凭据。在驱动仍运行时对端记录 `peer_eof`，两条连接均关闭。[断开原图](ordinary-disconnect.png) |
| 返回及清理 | 返回首页并保留断开回执。确认进程作业为空、监听器释放、夹具密码清空和临时目录删除。Win32 监听表已无该端口，再连接返回拒绝。[首页原图](ordinary-home.png) |

三张 1024×705 PNG 保留主线工件中的原字节，取自 Win32 可见桌面内的 Flutter 客户区。回显中的 `ANDROID` 为共享夹具标记，画面上的地址和账号为本次临时夹具。原图也显示「资料损坏、存储锁定或不可用」提示，Windows 配对与本机资料存储仍待验。两份 Windows ZIP 的外层 SHA-256 与 GitHub API 一致，成员 CRC 均通过。两批各三张 PNG 均与各自 `result.json` 的尺寸、SHA-256 一致。 [主线图片校验清单](SHA256SUMS)

## 核对或复跑

在本目录校验归档原图。访问 Actions 工件需有该仓库的读取权限。

```sh
shasum -a 256 -c SHA256SUMS
gh run view 44609170985 --repo Luck9Star/herdr-pocket
gh api repos/Luck9Star/herdr-pocket/actions/artifacts/14571877224 --jq .digest
work=$(mktemp -d)
gh api repos/Luck9Star/herdr-pocket/actions/artifacts/14571877224/zip > "$work/windows.zip"
shasum -a 256 "$work/windows.zip"
unzip -t "$work/windows.zip"
unzip -p "$work/windows.zip" result.json | jq '{sourceSHA, status, checkpoint, fingerprintMatchedBeforeConfirm, returnedHome, cleanup}'
```

GitHub Actions 复跑从已含 #45 的主线提交创建 `codex/windows-ordinary-ssh-run-…` 分支。推送该分支会启动 `Windows ordinary SSH` 工作流。单独核对新运行的完整源码 SHA。

在交互式 Windows 桌面也可检出上表主线复验提交，按固定工作流安装依赖、准备 Flutter 临时工程并校验候选锁。随后运行同一驱动，目标输出目录需尚未创建。通过时生成 `checkpoint=complete`、`status=passed` 的报告和三张原图。

```powershell
$python = "$env:RUNNER_TEMP\direct-ssh-venv\Scripts\python.exe"
& $python validation/remote-harness/flutter_windows_direct_ssh.py --app "$env:RUNNER_TEMP\flutter-gui" --source-sha (git rev-parse HEAD) --output "$env:RUNNER_TEMP\windows-direct-ssh-evidence"
```
