# Flutter iOS 普通 SSH 三案 R4

2026-11-19，[Flutter 作业 135546106261](https://github.com/Luck9Star/herdr-pocket/actions/runs/44520075525/job/135546106261)在 iPhone 11 / iOS 26.2 模拟器通过普通密码、密码换钥和独立加密 OpenSSH Ed25519 私钥三案。XCTest 1 项通过。作业与工件绑定到源提交 `2ccf9a57eba5114cd79849d66d25b114d3763dcc`。

[Actions 原 ZIP](flutter-ios-three-editor-r4.zip) 共 581,242 字节。本地原件与 [GitHub 工件 14529546402](https://github.com/Luck9Star/herdr-pocket/actions/runs/44520075525/artifacts/14529546402) 的 SHA256 一致，均为 `9423a05ce4594598c00a4d9f4d303a503248753909c527f422b02de689924a3a`。

| 案例 | 回环记录与设备断言 | ZIP 内终端原图与 OCR |
| --- | --- | --- |
| 普通密码 | A → A。首次确认指纹后，第二条连接才认证。打开与收起模拟器键盘，逐一访问看板、网络、设置再返回原终端，这八步均在同一条连接且无输入 | `ordinary-terminal.png` · `ordinary-terminal-ocr.json` |
| 密码换钥 | A → B → B → B。拒绝 B，取消保留旧 A。主动重探并核对 B 后才允许认证。前三条连接的认证、PTY、shell 和收发均为 0 | `key-change-terminal.png` · `key-change-terminal-ocr.json` |
| 独立加密私钥 | A → A。粘贴临时加密私钥，输入遮罩口令。密码和私钥两向切换都会清空前一种输入并保留同一信任。错口令本地拒绝，此时只有 A 探测且认证、PTY、shell 和收发均为 0。正确口令后第二条连接仅一次公钥认证，核对到一行完整输入，主动断开并返回首页 | `encrypted-key-terminal.png` · `encrypted-key-terminal-ocr.json` |

三案各有一条已认证会话，服务端各记录 1 次认证、1 次 PTY、1 次 shell、9 字节输入与 102 字节输出。三个会话在主动断开后均以 `peer_eof` 结束，并在驱动退出前关闭。所有探测连接也已关闭。凭据、剪贴板、私有输入材料、应用、夹具、测试工具和模拟器清理均获记录。普通案首次探测的 `preauth_peer_reset` 发生在零认证和零收发时，与已认证会话的关闭分开记录。

三个终端原图均为 828 × 1792。公开 `result.json` 的各案引用与 PNG、各自 OCR JSON 的 SHA256 相符。原作业 Tesseract 5.5.4 在终端区域读到合成回显标记、两行词串及其顺序，目标区域也通过识别。原图中的 `POCKET-ANDROID-SSH-OK` 是两端复用的合成回显标记。另有 `key-change-review.png` 记录拒绝状态、目标、旧新指纹和两个选择，以及密码遮罩的普通案 `preconnect.png`。五张原图仅含合成回环数据和测试 UI，附加 PNG 元数据只含色彩与尺寸信息。

## 旧批次及独立组合案

| 作业 | 已核实的结果 |
| --- | --- |
| R1 `31a4bfd` | 旧源码的普通密码、密码换钥和独立加密私钥三案均过，原记录继续有效。[R1 原始工件](../flutter-ios-encrypted-key-r1-20261119/README.md) |
| R2 `e777df4` | 密码换钥末条连接已有 1 次认证、PTY、shell 和 9/102 字节收发，终端 OCR 通过。主动断开时服务端记录 `session_socket_error`、Darwin 54，`sessionClosed=false`。独立加密案尚未开始。[作业 135506677907](https://github.com/Luck9Star/herdr-pocket/actions/runs/44508623493/job/135506677907) · [工件 14524341204](https://github.com/Luck9Star/herdr-pocket/actions/runs/44508623493/artifacts/14524341204) |
| R3 `3fdcae6` | 普通和密码换钥已有正常会话关闭。独立加密案停在 `encrypted_connect / control_not_ready`，底部 inset 692 px，诊断 `canConnect=true` 但连接控件未命中，服务端只有零认证的 A 探测。R4 驱动在口令编辑后等待焦点移出、键盘收起和滚动稳定再按连接。[作业 135528659137](https://github.com/Luck9Star/herdr-pocket/actions/runs/44515015385/job/135528659137) · [工件 14525259289](https://github.com/Luck9Star/herdr-pocket/actions/runs/44515015385/artifacts/14525259289) |
| 独立加密私钥 × 主机换钥 `2ccf9a57` | 失败于首次 A 探测 `rotation_initial_probe`，界面状态为 `probe_failed`。唯一连接 A 未完成握手，零认证、PTY、shell 和收发，随后关闭。口令编辑与换钥路径尚未执行。[作业 135546116097](https://github.com/Luck9Star/herdr-pocket/actions/runs/44520076236/job/135546116097) · [官方工件 14529006528](https://github.com/Luck9Star/herdr-pocket/actions/runs/44520076236/artifacts/14529006528) |

独立组合案的 [Actions 原 ZIP](ios-encrypted-rotation-editor-r2.zip) 仅含 `result.json`，SHA256 为 `37b0cbfe4e67a7f132c6a5145d91e84728c307219a966b837e01f38e43f4c030`。三案结果覆盖的是独立加密认证与密码换钥。实体设备、物理键盘、系统中文 IME 以及真实跨网仍待验证。[验收快照](../../72-mobile-ssh-auth-snapshot.md#flutter-ios-加密私钥独立验收)

## 校验原件

进入本目录后校验两个 ZIP 和 10 个成员。原始 ZIP 保持官方字节，未重新压缩。

```sh
set -e
shasum -a 256 -c SHA256SUMS
unzip -t flutter-ios-three-editor-r4.zip
unzip -t ios-encrypted-rotation-editor-r2.zip
originals="$(mktemp -d)"
manifest="$PWD/SHA256SUMS.members"
unzip -q flutter-ios-three-editor-r4.zip -d "$originals/three-cases"
unzip -q ios-encrypted-rotation-editor-r2.zip -d "$originals/encrypted-key-rotation"
(cd "$originals" && shasum -a 256 -c "$manifest")
```
