# Tauri Android 文件选择器与 iOS 手填私钥

这两条验收分别使用 API 35 Android 模拟器的系统文件选择器，以及 iOS 模拟器中的普通 SSH。源码、结果和 GitHub 工件到期时间按实际作业记录。R4 和手填 R7 以主线 `89aeb25a310cae4e2ba486d13e09940f134f871e` 的产品为基线，运行提交的差异限验收工作流和驱动／测试。

## Android 系统文件选择器

R3 实际打开系统选择器两次。取消后原配置和临时目录保持不变。随后通过系统选择器保存 126 字节的 v2 加密档案，宿主独立解密成功。切换对照字号时记录 `set_control_preference / catalog_mismatch`，导入确认尝试和点击都是 0。工件确认应用、调试连接、转发、临时下载目录及选择器层级文件均已清理。该工件单独收录应用报告，模拟器进程与传输终局未在其中记录。 [R3 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44612662778/job/135873055745) · [工件 14573782872](https://github.com/Luck9Star/herdr-pocket/actions/runs/44612662778/artifacts/14573782872)

R4 在同一路径再次完成取消、保存和独立解密。切换对照字号时一直等不到对应的保存回执，报告 `set_control_preference / font_save_receipt_unconfirmed`，该次未读回对照字号，导入确认尝试和点击仍是 0。错误口令、篡改档案和正常导入均未进入 UI 验证阶段。应用报告的五项清理全部通过。单独的模拟器生命周期文件确认自有模拟器进程退出码为 0，第 2 次检查时设备传输已消失。作业仍以失败结束。此案仅涉及字号偏好，连接替换与自动重试停止另待验证。 [R4 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44617210333/job/135889007953) · [工件 14576447045](https://github.com/Luck9Star/herdr-pocket/actions/runs/44617210333/artifacts/14576447045)

## iOS 原生手填加密私钥

手填 R6 从正式首页进入，填写目标、核对主机指纹并验证 PEM 写入。口令步骤的安全检查阻断。脱敏诊断显示同一 WebView 内相对 PEM 编辑器为后代的两条 `staticText` 命中合成 PEM 标头，口令命中数为 0。服务端清理前后均只记录一条已关闭、零认证的探测，尚未进入认证、PTY、回显或主动断开。普通密码和换钥在该作业未运行。模拟器、夹具、私有文件及合成秘密清理均获确认。 [手填 R6 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44609944062/job/135863554949) · [工件 14573950954](https://github.com/Luck9Star/herdr-pocket/actions/runs/44609944062/artifacts/14573950954) · [历史原生粘贴验收](../tauri-ios-encrypted-key-native-20261119/README.md)

手填 R7 使用当前主线产品。从首页进入后，驱动确认普通主机地址字段获得焦点且键盘可见。一次原生输入后，该字段的整树和实时控件读回仍为空；端口及用户名保持原值，6 次读回也仍为空。测试报 `native_input_value_invalid`，对端连接数为 0。这次在目标阶段终止，尚未到指纹、PEM 和编辑器安全复查。普通密码和换钥未运行。四项临时资源清理获确认。 [手填 R7 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44616831107/job/135887674869) · [工件 14576158322](https://github.com/Luck9Star/herdr-pocket/actions/runs/44616831107/artifacts/14576158322)

## 证据留存

固定字段摘要保留运行、作业、源码、工件 ID、到期时间、ZIP SHA-256 和所核验成员的 SHA-256。工件到期后可从仓库复核所存计数、状态和摘要哈希。原 ZIP 及原报告的完整字段须另有原工件才能重验。四份工件均未收录截图。 [脱敏摘要](official-summary.json) · [校验清单](SHA256SUMS)

工件当前到期时间（UTC）

| 原始工件 | 到期时间 |
| --- | --- |
| Android R3 · 14573782872 | 2026-12-03 20:59:58 |
| Android R4 · 14576447045 | 2026-12-03 21:27:24 |
| iOS 手填 R6 · 14573950954 | 2027-02-17 20:33:52 |
| iOS 手填 R7 · 14576158322 | 2027-02-17 21:14:56 |

```sh
shasum -a 256 -c SHA256SUMS
```
