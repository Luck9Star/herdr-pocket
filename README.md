# herdr-pocket

herdr-pocket 是开源的第三方远端 herdr 客户端。你可以用它查看远端 agent 和会话、选择终端，或通过普通 SSH 打开标准服务器上的交互式 shell。项目处于原型验证阶段，Flutter 和 Tauri 都是候选。目标覆盖 Android、iOS、macOS、Windows 和 Linux，手机优先。

## Android 测试包

公开测试版 [v0.1.2](https://github.com/Luck9Star/herdr-pocket/releases/tag/v0.1.2) 发布于 2026-11-11，源码为 `d333db2`。两套 APK 都是签名的 ARM64（`arm64-v8a`）测试包，Flutter 与 Tauri 使用各自的应用 ID。该版本可用于试用 herdr 配对与观察，普通 SSH 在后续源码中加入。

1. 下载一个 APK 和同版本的校验清单。[Flutter APK](https://github.com/Luck9Star/herdr-pocket/releases/download/v0.1.2/herdr-pocket-flutter-android-arm64-v0.1.2.apk) · [Tauri APK](https://github.com/Luck9Star/herdr-pocket/releases/download/v0.1.2/herdr-pocket-tauri-android-arm64-v0.1.2.apk) · [SHA-256 清单](https://github.com/Luck9Star/herdr-pocket/releases/download/v0.1.2/SHA256SUMS-v0.1.2.txt)
2. 在下载目录运行下方命令，将结果与清单中同名文件的摘要比对。摘要一致后，把 APK 传到手机，用 Android 系统安装器打开。系统如有提示，可为正在打开 APK 的浏览器或文件管理器启用安装权限。
3. 打开应用，按[主机配对说明](helper/README.md)从远端主机生成连接资料并确认设备公钥。成功连接后，可在看板选中一个会话窗格并看到终端输出。

```sh
shasum -a 256 herdr-pocket-*-android-arm64-v0.1.2.apk
```

旧调试包可能因签名不同而无法覆盖安装。卸载会删除该应用在设备上的本地资料。有关签名和包名，参见[首次签名测试批说明](https://github.com/Luck9Star/herdr-pocket/releases/tag/v0.1.1)。

**试用普通 SSH**可从含此入口的源码构建，或登录 GitHub 使用后续的 CI 调试包。工件按周期到期，下载前请核对源码、设备 ABI 和包内 SHA-256。[普通 SSH 调试包及校验值](docs/63-design-parity-and-direct-ssh.md#可下载的同源调试快照) · [源码构建与复测](validation/README.md)

## 选择连接方式

| 你要连接 | 从哪里开始 |
| --- | --- |
| 标准 SSH 服务器 | 从带有该功能的构建进入「普通 SSH」。通过服务器控制台或管理员核对主机指纹，再用服务器账号密码或已有私钥连接。验证成功后打开独立的远端 PTY 终端，无需运行 herdr 或配对助手。[操作与认证范围](docs/63-design-parity-and-direct-ssh.md#从首页选择接入方式) |
| 已有 herdr 会话的远端主机 | 从首页进入配对流程。手机生成设备密钥，由主机用户通过一次性助手确认公钥。连接后从看板选择要观察的终端。逐键输入与草稿发送需要受保护的主机能力和明确的目标。[主机操作与撤销](helper/README.md) · [手机连接与核验](docs/53-mobile-connection-diagnostics.md#手机上怎样核验) |

## 查验证结果或参与开发

Android、iOS 的模拟器与桌面受控环境已有分项结果。实体手机安装、相机扫码、真实输入法以及五端三网组合仍需对应验收。查阅每项结果时，请核对运行环境、源码和产物来源。[普通 SSH 验收矩阵](docs/63-design-parity-and-direct-ssh.md#普通-ssh-验收矩阵2026-11-20-更新) · [路线图与验收门槛](docs/04-roadmap.md)

- [文档导航](docs/README.md)汇总产品、架构、设计、实测和历史交接。
- [贡献指南](CONTRIBUTING.md)说明如何复测、提交改动和脱敏报告问题。
- 项目采用 GPL-3.0-or-later。各组件的原始许可与对应产物材料见[项目许可证](LICENSE)和[第三方声明](THIRD_PARTY_NOTICES.md)。
