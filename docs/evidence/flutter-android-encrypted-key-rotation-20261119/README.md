# Flutter Android 加密私钥与主机换钥 R2

**通过 — API 35 模拟器、受控回环。** 2026-11-19，GitHub Actions 作业 `135528754522` 在独占 x86_64 Google APIs Android 35 AVD（系统镜像 revision 9，Emulator 37.2.13.0）上安装 Flutter 应用，从正常首页进入「普通 SSH」。同一次操作使用临时加密 OpenSSH Ed25519 私钥与口令，完成主机换钥、远端回显和主动断开。连接仅限自建临时回环账号与端口。实体设备、物理输入法和真实网络仍待验证。[R2 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44515040529/job/135528754522) · [Actions 工件 14526327095](https://github.com/Luck9Star/herdr-pocket/actions/runs/44515040529/artifacts/14526327095)

## 来源与原件

R2 执行源码 `3fdcae6794ecff0f1b63e0e4f9c3ed8caf7fead3`，通过 `auth_case=encrypted-key-rotation` 单独运行。归档基线 `4056f4155cd9852470f0660be917e1fed0cc9fd6` 的 Flutter 产品树 `validation/flutter/lib` 同为 `1f4828501dbd715551fe72d967a73cfd04a0f30c`。两提交的 Flutter 原生源码、依赖锁定、Android 工作流、Android 驱动、设备入口、协议夹具和 OCR 门禁也一致。共有 Dart 驱动的差异涉及 iOS 的握手文件名、拒绝后截图和回调接线。Android 仍使用相同的文件名及口令编辑结束步骤。相同源码另有常规密码作业通过。[同源常规密码作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44515044000/job/135528765174)

保留官方 ZIP 原字节，共 11 个成员。ZIP 通过完整性校验，SHA-256 与 Actions 工件相同。四张 PNG 的 CRC 和像素尺寸均已复核，未含文本或 EXIF 元数据。可见目标仅为一次性回环夹具。原件不含私钥、口令、原始日志或个人资料。[原 ZIP](r2-actions-14526327095.zip) · [SHA256SUMS](SHA256SUMS)

```sh
shasum -a 256 -c SHA256SUMS
unzip -l r2-actions-14526327095.zip
```

## 四次传输与设备动作

`direct-ssh-public/result.json` 的检查点分别固定首探、拒绝、取消和重新探测。界面首次独立比较 A 指纹，出现 B 时拒绝认证并阻止绕过审查。取消审查后旧信任仍是 A，凭据仍锁定且没有自动连接。用户重新探测并独立核对 B，再显式信任后才进入终端。

| 传输 | 主机钥与动作 | 认证尝试 / 成功 | PTY / shell | 输入 / 输出 |
| --- | --- | --- | --- | --- |
| 1 | A · 首次探测并独立核对 | 0 / 0 | 0 / 0 | 0 / 0 字节 |
| 2 | B · 换钥拒绝，取消后传输计数仍为 2 | 0 / 0 | 0 / 0 | 0 / 0 字节 |
| 3 | B · 显式重新探测并核对 | 0 / 0 | 0 / 0 | 0 / 0 字节 |
| 4 | B · 显式信任后用公钥认证与主动断开 | 1 / 1 | 1 / 1 | 9 / 102 字节 |

四条传输均关闭。第 4 条记录公钥受理、一次完整终端测试行、会话关闭及驱动退出前已确认对端关闭。设备结果另确认私钥粘贴、口令遮蔽、一次正常终端文字提交、远端回显、断开后界面与凭据清理。驱动核对私有输入临时文件及剪贴板已清除。外层卸载应用，验证 ADB reverse 和归本次作业所有的 forward 已移除。夹具、临时密钥及 Flutter 工具均已退出或移除。独占 AVD 进程退出码为 0，序列号也从 ADB 列表消失。

## 原图与 OCR

两张原图均为 1080 × 2340，终端矩形为 `[66, 465, 948, 1479]`。`direct-ssh-public/key-rotation-screen-proof.json` 记录两种图源在第 1 次截图的独立检查。Tesseract 5.3.4 在终端矩形内读到远端回显和该会话的完整八词校验序列，次序符合门禁。归档复核将图像摘要逐一与该 JSON 对上，并在两张原图相同坐标做了独立的本机 Vision OCR，识别出同一顺序。

| `direct-ssh-public/` 成员 | 来源 | SHA-256 |
| --- | --- | --- |
| `rotation-connected-device.png` | Android 系统 `adb exec-out screencap -p` | `13301ad4279b8a0f65c5d64a753dfb4dad50dff3dd1c164f304611a0cf1297a5` |
| `rotation-connected.png` | Flutter 集成测试保留的 Android 渲染表面 | `3b85ffa6da8c30b40d2e6f34b08586529ca8e76b9e5253147faae495b459bbf8` |

首次 R1 已有四条传输、成功公钥认证和远端回显。在截图读取时收到非 PNG，诊断同时记录 ADB offline，未确认主动断开、应用卸载或 reverse 移除。外层确认 AVD 进程退出且设备消失。历史结果不单独证明原图或完整清理，也无法由该诊断单独确定非 PNG 的原因。[R1 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44510452198/job/135513026564) · [R1 工件 14522188245](https://github.com/Luck9Star/herdr-pocket/actions/runs/44510452198/artifacts/14522188245)

R2 官方日志记录 Android 驱动保护 46 项、换钥夹具 5 项、截图与 OCR 门禁 19 项均通过。归档时本地复跑前两组也全部通过。截图门禁本地 6 项通过，依赖同版 Tesseract 的栅格组跳过，原图另用 Vision OCR 复核。[R2 作业日志](https://github.com/Luck9Star/herdr-pocket/actions/runs/44515040529/job/135528754522) · [验收快照](../../72-mobile-ssh-auth-snapshot.md)
