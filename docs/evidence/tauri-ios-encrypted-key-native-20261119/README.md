# Tauri iOS 加密私钥原生粘贴 R6 与 R7

**未验证 — 环境受限。** 2026-11-19，两案均在 iPhone 17 Pro Max、iOS 26.2 模拟器上运行，使用 Xcode 16.4（16F6）及 Simulator SDK 18.5。范围是受控 `fixture@127.0.0.1` 临时端口及临时加密 OpenSSH Ed25519 私钥。公开结果未导出端口号。普通密码和主机换钥两案均为 `not_run`。

| 案次 | 源提交 | Actions 与归档 |
| --- | --- | --- |
| R6 | `0c6b89ba6b1c9798d378ec41bb8e99450c070d09` | [作业 135485062772](https://github.com/Luck9Star/herdr-pocket/actions/runs/44502343881/job/135485062772) · [工件 14519032472](https://github.com/Luck9Star/herdr-pocket/actions/runs/44502343881/artifacts/14519032472) · [原 ZIP](r6-actions-14519032472.zip) |
| R7 | `9f3fa8d8ef2d0b0e84b481e2dca06e98c76485ec` | [作业 135513780849](https://github.com/Luck9Star/herdr-pocket/actions/runs/44510667185/job/135513780849) · [工件 14524253848](https://github.com/Luck9Star/herdr-pocket/actions/runs/44510667185/artifacts/14524253848) · [原 ZIP](r7-actions-14524253848.zip) |

两份 ZIP 均与 GitHub Actions 的工件 SHA-256 一致，只含 `result.json`。两次构建成功，原生驱动和发布校验均报告失败，脱敏结果上传成功。原件无截图、原始 AX 数据、原始日志或凭据。可在本目录用 `shasum -a 256 -c SHA256SUMS` 校验。[SHA256SUMS](SHA256SUMS)

两次均从空首页进入普通 SSH，界面均记录主机指纹已核对。R6 点击产品「粘贴私钥」按钮后动作返回，采样未能取得 App 根快照，记录 `native_encrypted_key_paste_snapshot_unavailable`。R7 冷启动 App 后长按原本为空的 PEM 字段，同窗采样可读并记录 `field_empty`，没有取得唯一菜单及内容插入的证据，记录 `native_encrypted_key_paste_unproven`。两次均在错口令用例准备阶段停止，权限弹窗、菜单实际可用性和产品支持情况均未证实。

| 案次 | 清理前及清理后唯一对端记录 | 认证尝试 / 成功 | PTY / shell | 输入 / 输出 |
| --- | --- | --- | --- | --- |
| R6 | 第 1 条，主机密钥 A，服务端已完成握手，在 `await_channel` 阶段记录 `preauth_peer_reset` 后关闭 | 0 / 0 | 0 / 0 | 0 / 0 字节 |
| R7 | 第 1 条，主机密钥 A，服务端未记录握手完成，在 `handshake` 阶段记录 `preauth_peer_reset` 后关闭 | 0 / 0 | 0 / 0 | 0 / 0 字节 |

两次的模拟器删除、夹具关闭和私有临时文件移除均通过。没有已打开的 SSH 会话可用于证明主动断开。复验需从新鲜空字段开始，能够在同一 App 窗口可靠确认粘贴动作及内容确已插入。结果未知时停止，保留证据并清理，不能重放原动作。随后仍需独立取证错口令零认证、正确私钥的认证与终端回显、原屏 OCR、主动断开及清理。[验收快照](../../72-mobile-ssh-auth-snapshot.md)
