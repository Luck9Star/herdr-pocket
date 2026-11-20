# Tauri Windows 普通 SSH 密码验收

2026-11-20，Tauri 应用在 GitHub `windows-2022` 的可见 WebView2 原生窗口完成普通 SSH 密码连接、终端输入与回显、主动断开及返回首页。服务端是仅监听本机回环的一次性夹具。验收通过 W3C WebDriver 操作产品页面，Windows 原屏截图与对端记录分别核验；这不是实体键盘或 IME 验收。Windows Tauri 私钥认证、主机换钥、外部主机和发布安装包仍须另验。Flutter Windows 的 [密码](../windows-ordinary-ssh-password-20261120/README.md)与[未加密私钥](../windows-ordinary-ssh-publickey-20261120/README.md)分别有独立证据。

| 来源 | R3 正式运行 |
| --- | --- |
| 源码 | `c888d09bf4b99914772bdc7e72711a70c89aa115`。相对 `b8651f738369e60eb3f8fd04b2e661c59dddc6e3`，变更仅为 Windows 验收工作流、驱动及定向测试；不以验收驱动的构建代替产品运行。 |
| 作业 | [运行 44679367062](https://github.com/Luck9Star/herdr-pocket/actions/runs/44679367062) · [作业 136098813864](https://github.com/Luck9Star/herdr-pocket/actions/runs/44679367062/job/136098813864)，`tauri-password` 成功，手动选择 Tauri 与密码。 |
| 工件 | [14604195620](https://github.com/Luck9Star/herdr-pocket/actions/runs/44679367062/artifacts/14604195620)，ZIP 60,371 字节，SHA-256 `a8c177a984caf74e9549d30c3567e0c73dcde5683a4cacd5ed589e260c0c44b8`，与 GitHub API 的 digest 一致；ZIP 四个成员 CRC 全部通过。API 记录到期时间为 `2026-12-04T05:18:20Z`。 |
| 报告与程序 | [原始 result.json](result.json) SHA-256 `c0ec2f8ba12d6ac98f2ab3347e240387b6ddaf3cd110cc791563d7ea5eb3735a`，`status=passed`、`stage=complete`；运行程序 SHA-256 `1935be8d87f9e4bbd10222b97b90851f8cbbb7b0a2969008998b341663738ada`。`checkpoint=fixture_cleanup` 是清理阶段记录，最终状态以 `stage=complete` 为准。 |

| 检查 | 实际结果 |
| --- | --- |
| 首页与窗口 | 从空首页“添加主机 → 普通 SSH”进入目标表单。应用窗口属于本次 Win32 Job；正常 `SetForegroundWindow` 后读回前台（`windowActivation=set_foreground`），没有使用备用标题栏点击。输入前检查同一窗口前台；页面点击、填写、提交通过 W3C WebDriver 控件及键盘动作。 |
| 首次指纹 | 夹具独立计算完整 SHA256 指纹，驱动对可见且可命中的目标、`ssh-rsa` 公钥编码和指纹核对后，明确点击确认。第一条 A 探测连接在认证前关闭，认证、PTY、shell、输入与输出均为 0；报告中协商的主机签名算法为 `rsa-sha2-512`。工件不含指纹审核截图，此项来自运行时 UI 读回与对端记录。 |
| 密码认证与 PTY | 第二条仍为 A，密码认证尝试和成功各 1 次；PTY 与 shell 各请求 1 次，PTY 从 80×24 调到 88×32。 |
| 输入与可见回显 | 向已聚焦终端发送一次 `hp-check` 与回车；对端记录 9 字节输入、累计 102 字节输出。Tesseract `5.5.3.20260724` 在终端裁框识别回显标记及该次夹具的随机校验序列。[终端原图](ordinary-terminal.png) |
| 断开与回首页 | 在驱动退出前主动断开，UI 确认凭据已清空；对端记录 `peer_eof`，两条连接均关闭。返回原首页仍显示“本机已断开”。[断开原图](ordinary-disconnect.png) · [首页原图](ordinary-home.png) |
| 清理 | 报告确认进程 Job 为空、对端监听释放、临时密码清空、WebDriver 两端口释放、私有临时目录删除；Win32 监听表不再含夹具端口，再连返回拒绝。 |

三个 `result.json` 均保留原始 CRLF 字节，本目录的 `.gitattributes` 禁用这些报告的换行转换，并允许逐行审查。三张 1024×705 PNG 是官方工件中的原字节，来自前台 Win32 窗口客户区的实际桌面像素；驱动对窗口归属、尺寸、可见区域与遮挡检查前后读回。三张图片的尺寸和 SHA-256 与原报告对应字段一致。图中 `127.0.0.1`、账号及端口均为临时夹具，回显中的 `ANDROID` 是共享测试夹具的标记，不代表 Android 环境。[原件校验清单](SHA256SUMS)

## 未通过的早期轮次

- R1 [运行 44673977003](https://github.com/Luck9Star/herdr-pocket/actions/runs/44673977003) · [工件 14601148240](https://github.com/Luck9Star/herdr-pocket/actions/runs/44673977003/artifacts/14601148240)，源码 `e031c5676e1168bf4580e62a033d4533750f81f8`，ZIP SHA-256 `c41afc98c5fe884dc8e20671a21711928c804837f4d4a3f63766721111d9f0eb`。[原报告](r1-result.json)停在 Job 放行后，记录 `PermissionError` / WinError 32；peer 连接为 0。原始记录不足以区分启动错误和清理错误。
- R2 [运行 44676087099](https://github.com/Luck9Star/herdr-pocket/actions/runs/44676087099) · [工件 14601919674](https://github.com/Luck9Star/herdr-pocket/actions/runs/44676087099/artifacts/14601919674)，源码 `ab82c3d0cb8d1ce647871a2c22b178e2aeba363d`，ZIP SHA-256 `cfa63d18e08995e09fd92cf28cafd1f8610afbefb75b4dd54afb24291c8b2721`。[原报告](r2-result.json)到达窗口激活，但窗口未在前台；peer 连接为 0。两轮都不能计为 SSH 认证通过。

## 核对或复跑

工件下载需要仓库读取权限且受 Actions 保留期限限制。下列命令在本目录校验已归档的原图和三个原始报告，并可重新核对官方 ZIP：

```sh
shasum -a 256 -c SHA256SUMS
work=$(mktemp -d)
gh api repos/Luck9Star/herdr-pocket/actions/artifacts/14604195620/zip > "$work/r3.zip"
printf '%s  %s\n' a8c177a984caf74e9549d30c3567e0c73dcde5683a4cacd5ed589e260c0c44b8 "$work/r3.zip" | shasum -a 256 -c -
unzip -tq "$work/r3.zip"
unzip -p "$work/r3.zip" result.json | jq '{sourceSHA,status,stage,windowActivation,fingerprintReviewed,peer,cleanup}'
```

在 `Windows ordinary SSH` 工作流选择包含固定源码的 `codex/` 分支，设置 `application=tauri`、`authentication=password`。也可按[固定源码工作流](https://github.com/Luck9Star/herdr-pocket/blob/c888d09bf4b99914772bdc7e72711a70c89aa115/.github/workflows/windows-ordinary-ssh.yml)使用专用运行分支；必须重新核验新作业及工件，历史通过不代替复跑。
