# Flutter iOS 加密私钥与主机换钥

2026-11-19，[R3 作业 135558963395](https://github.com/Luck9Star/herdr-pocket/actions/runs/44523800466/job/135558963395)在新建的 iPhone 11 / iOS 26.2 模拟器上通过临时加密 OpenSSH Ed25519 私钥换钥组合案，XCTest 1 项通过。R3 与 R2 使用同一源提交 `2ccf9a57eba5114cd79849d66d25b114d3763dcc`。

| 运行 | 原始 Actions ZIP | SHA256 | 结果 |
| --- | --- | --- | --- |
| R3 [工件 14531390888](https://github.com/Luck9Star/herdr-pocket/actions/runs/44523800466/artifacts/14531390888) | [四项原件，202,953 字节](ios-encrypted-rotation-editor-r3.zip) | `7e878c1b9b7906fcac94a882e0c576d55ad7d4245956be487e3610c3db05bdb7` | 组合案通过 |
| R2 [工件 14529006528](https://github.com/Luck9Star/herdr-pocket/actions/runs/44520076236/artifacts/14529006528) | [失败原始结果，1,508 字节](../flutter-ios-encrypted-key-r4-20261119/ios-encrypted-rotation-editor-r2.zip) | `37b0cbfe4e67a7f132c6a5145d91e84728c307219a966b837e01f38e43f4c030` | 首次 A 探测超时 |

## 四条连接与原图

| 服务端记录 | 屏幕操作与结果 |
| --- | --- |
| #1，A | 从首页进入普通 SSH，独立核对并确认首次主机指纹 |
| #2，B | 旧信任下拒绝连接及输入。取消核对后保留 A |
| #3，B | 主动重探 B 并独立核对。明确确认前凭据保持锁定 |
| #4，B | 明确确认后以已加密私钥完成一次公钥认证。服务端各记录一次认证尝试、PTY 和 shell，收到一行完整的 9 字节输入，送出 102 字节。主动断开并返回首页，服务端记录 `peer_eof` |

前三条的认证、PTY、shell 和收发均为零。四条连接均关闭，已认证会话在驱动退出前关闭。报告另记录临时凭据、剪贴板、测试私有输入、应用、夹具、Flutter 工具和模拟器清理通过。

R3 ZIP 的两张 828 × 1792 系统原图均绑定 `result.json`。`encrypted-rotation-review.png` 记录被拒、回环目标、`rsa-sha2-512` 主机公钥算法、A/B 指纹与两个明确操作。`encrypted-rotation-terminal.png` 的终端区域由原作业 Tesseract 5.5.4 识别出合成标记及紧接的两行词串，目标区域也通过识别。`encrypted-rotation-terminal-ocr.json` 记录识别区域和原图 SHA256，并与结果中的自身摘要相符。两张原图只显示合成夹具信息，PNG 附加元数据为颜色和尺寸。

[R2 作业 135546116097](https://github.com/Luck9Star/herdr-pocket/actions/runs/44520076236/job/135546116097)停在 `rotation_initial_probe`，界面为 `probe_failed`。唯一 A 连接未完成握手，零认证、零 PTY、零 shell、零收发。口令编辑和换钥均尚未执行。R2 的具体时延原因仍待定位。 R2 原 ZIP 仍保存在独立三案的既有归档，校验清单直接引用该副本。

## 源码和验证范围

本轮整合候选 `6e5480759c9e7986390d1bfa3d04148112db54cd` 相对主线 `01539f4` 的七个专项文件，包含 iOS 工作流、共享普通 SSH 交互步骤、iOS 集成测试、Python 驱动、发布门及其定向测试。这七个文件逐一与官方运行的 `2ccf9a57` 比对，Git blob 均相同。普通 SSH 的 `direct_ssh_page.dart`、回环服务端夹具和终端截图 OCR 门也一致。主线已含 #23 的配对主机关闭改动，影响 `host_catalog_page.dart` 的配对工作台按钮、`host_tabs.dart` 的幸存会话选择，以及 `remote_adapter.dart`、`remote_page.dart` 的配对会话关闭与提示。设备证据仍绑定官方运行源码，整合候选另通过本机 78 项 iOS 保护测试。

在整合候选上用现有 Python 发布门复核原件，R3 的四项文件通过且字节一致，R2 仅保留失败结果并返回失败。图像结论采用官方区域 OCR 和原图。实体设备、物理键盘、系统中文 IME 和真实跨网仍待验证。[手机 SSH 验收快照](../../72-mobile-ssh-auth-snapshot.md#独立加密私钥与主机换钥-r3)

## 校验原件

```sh
set -e
shasum -a 256 -c SHA256SUMS
unzip -t ios-encrypted-rotation-editor-r3.zip
unzip -t ../flutter-ios-encrypted-key-r4-20261119/ios-encrypted-rotation-editor-r2.zip
originals="$(mktemp -d)"
manifest="$PWD/SHA256SUMS.members"
unzip -q ios-encrypted-rotation-editor-r3.zip -d "$originals/r3"
unzip -q ../flutter-ios-encrypted-key-r4-20261119/ios-encrypted-rotation-editor-r2.zip -d "$originals/r2"
(cd "$originals" && shasum -a 256 -c "$manifest")
```
