# Flutter Windows 普通 SSH 私钥验收

2026-11-20（北京时间），Flutter debug 应用在 GitHub `windows-2022` 的可见 Win32 客户区通过普通 SSH 私钥验收。Flutter integration test 向已聚焦的编辑框输入一枚临时生成的未加密 OpenSSH Ed25519 私钥，对端只监听本机回环并只接受对应公钥的签名认证。Windows 加密私钥、主机换钥、Tauri、实体键盘与 IME、外网和发布包待另验。 [Windows 密码验收](../windows-ordinary-ssh-password-20261120/README.md)

| 来源 | R3 |
| --- | --- |
| 源码 | 合并树 `f22c0fecb373d2f01cc036df421b9a433aa97fc7`，父提交 `7646a2d`、`c09eadd`。相对 `7646a2d`，变更限于 Windows 验收工作流、驱动及测试，产品 Dart、原生入口和依赖锁一致。 |
| 作业 | [运行 44624822657](https://github.com/Luck9Star/herdr-pocket/actions/runs/44624822657) · [作业 135915738447](https://github.com/Luck9Star/herdr-pocket/actions/runs/44624822657/job/135915738447)。首次运行成功。工作流以 `authentication=publickey` 手动触发，作业名仍为 `flutter-password`。 |
| 工件 | [14578623619](https://github.com/Luck9Star/herdr-pocket/actions/runs/44624822657/artifacts/14578623619)，ZIP 64,032 字节，SHA-256 `4c64cf4b18cc107c60f3304a4cf49b9dcd243877b2c712f7f6e1793ec7cda871`，成员 CRC 全部通过。GitHub 记录到期时间为 `2026-12-03T22:06:13Z`。 |
| 原始报告 | `result.json` SHA-256 `d85da4130842f662e5c95271cc39a738ae17fb8eeec976b55eace5b4d0ec33fc`，`status=passed`，`checkpoint=complete`。Flutter 3.47.9（`c197ca5199e9ee5661e865596c9c07294dfab51c`），45 份产品 Dart 通过源码核对。三份验收脚本的工件哈希与固定提交的 CRLF 版本一致。 |

| 检查 | 实际结果 |
| --- | --- |
| 核对和认证 | 核对独立计算的完整 SHA256 指纹和 `rsa-sha2-512` 主机密钥算法，再显式确认。第一条 A 探测连接关闭，认证、PTY、shell 和收发字节均为 0。驱动确认私钥完整回读且口令为空后，第二条同一 A 连接完成一次 Ed25519 签名认证。 |
| 终端 | 对端记录一次 PTY 和一次 shell，PTY 从 80×24 调到 82×27，精确收到单行 9 字节，累计发送 102 字节。Tesseract 5.5.3.20260724 在终端裁框内识别回显与同次会话校验序列。 [终端原图](ordinary-terminal.png) |
| 主动断开和返回 | 驱动仍运行时对端记录 `peer_eof`，两条连接均关闭。UI 清空凭据，回到原首页并保留「本机已断开」回执。首页仍显示本机资料存储警告。 [断开原图](ordinary-disconnect.png) · [首页原图](ordinary-home.png) |
| 五项清理 | Win32 进程作业为空、对端监听释放、夹具密码字段清空、临时目录删除、含临时私钥的交接文件已移除。Win32 监听表已无该端口，再连返回拒绝。 |

三张 1024×705 PNG 均为工件中的原字节，来自可见 Win32 桌面的 `FLUTTERVIEW` 客户区。截图尺寸和 SHA-256 逐一对照 `terminal`、`disconnectOutcome`、`homeOutcome` 的原始报告字段。画面中地址和账号属于临时回环夹具，回显标记中的 `ANDROID` 来自共享测试夹具。 [原图校验清单](SHA256SUMS)

R1 停在首页，SSH 连接数为 0。R2 通过独立指纹比对，唯一探测连接在认证前关闭，随后停在私钥输入阶段。 [R1](https://github.com/Luck9Star/herdr-pocket/actions/runs/44620751917) · [R2](https://github.com/Luck9Star/herdr-pocket/actions/runs/44622622536)

## 核对或复跑

在本目录校验三张原图。下载原始工件需要仓库读取权限，并须在工件有效期内完成。

```sh
shasum -a 256 -c SHA256SUMS
work=$(mktemp -d)
gh api repos/Luck9Star/herdr-pocket/actions/artifacts/14578623619/zip > "$work/r3.zip"
printf '%s  %s\n' 4c64cf4b18cc107c60f3304a4cf49b9dcd243877b2c712f7f6e1793ec7cda871 "$work/r3.zip" | shasum -a 256 -c -
unzip -tq "$work/r3.zip"
unzip -p "$work/r3.zip" result.json | jq '{sourceSHA, status, checkpoint, peer, cleanup}'
```

在 Actions 选择 `Windows ordinary SSH` 工作流，从包含固定源码的 `codex/` 分支手动运行，认证方式选 `publickey`。通过时工件包含 `status=passed`、`checkpoint=complete` 和三张原图。 [固定源码工作流](https://github.com/Luck9Star/herdr-pocket/blob/f22c0fecb373d2f01cc036df421b9a433aa97fc7/.github/workflows/windows-ordinary-ssh.yml)
