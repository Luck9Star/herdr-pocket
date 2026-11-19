# Tauri Android 文件选择器与 iOS 手填私钥

这两条验收分别使用 API 35 Android 模拟器的系统文件选择器，以及 iOS 模拟器中的普通 SSH。源码、结果和 GitHub 工件到期时间按实际作业记录。R4 和手填 R7／R8 以主线 `89aeb25a310cae4e2ba486d13e09940f134f871e` 的产品为基线。R5 以合入 #48 后的主线 `a5fe364813fc899aa1472e277fb62a8dbbb04bcc` 为基线。这些轮次与对应基线的差异只涉及验收工作流和驱动／测试。

## Android 系统文件选择器

R3 实际打开系统选择器两次。取消后原配置和临时目录保持不变。随后通过系统选择器保存 126 字节的 v2 加密档案，宿主独立解密成功。切换对照字号时记录 `set_control_preference / catalog_mismatch`，导入确认尝试和点击都是 0。工件确认应用、调试连接、转发、临时下载目录及选择器层级文件均已清理。该工件单独收录应用报告，模拟器进程与传输终局未在其中记录。 [R3 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44612662778/job/135873055745) · [工件 14573782872](https://github.com/Luck9Star/herdr-pocket/actions/runs/44612662778/artifacts/14573782872)

R4 在同一路径再次完成取消、保存和独立解密。切换对照字号时一直等不到对应的保存回执，报告 `set_control_preference / font_save_receipt_unconfirmed`，该次未读回对照字号，导入确认尝试和点击仍是 0。错误口令、篡改档案和正常导入均未进入 UI 验证阶段。应用报告的五项清理全部通过。单独的模拟器生命周期文件确认自有模拟器进程退出码为 0，第 2 次检查时设备传输已消失。作业仍以失败结束。此案仅涉及字号偏好，连接替换与自动重试停止另待验证。 [R4 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44617210333/job/135889007953) · [工件 14576447045](https://github.com/Luck9Star/herdr-pocket/actions/runs/44617210333/artifacts/14576447045)

R5 再次完成选择器取消、保存 126 字节 v2 档案和独立解密。对照字号保存通过两项核验。WebView 监听记录了 CDP 点击产生的受信任目标按钮事件，回执文字节点仍为原节点（`same_success`）。驱动同时从应用私有目录读回配置文件，确认内容匹配本轮对照字号（`catalog=expected`）。第三次打开系统选择器时，错口令用例在 Downloads 根目录未能确认目标（`wrong_passphrase / downloads_root / picker_target_unconfirmed`）。尚未验证应用拒绝错口令、拒绝篡改或确认导入，确认尝试和点击仍是 0。应用报告的五项清理通过。独立生命周期记录显示自有模拟器进程退出码 0，第一次检查已无设备传输，作业仍失败。 [R5 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44621326281/job/135903460824) · [工件 14578975990](https://github.com/Luck9Star/herdr-pocket/actions/runs/44621326281/artifacts/14578975990) · [事件和读盘判据](https://github.com/Luck9Star/herdr-pocket/blob/b3bf32ac170711f7b0dd0f9d6df71901ab808f68/validation/remote-harness/tauri_android_config_document.py#L364-L487)

**R6 通过受控字号偏好的导出与导入。** 运行源码 `db49c57` 以 #49 后的 `7646a2d` 为基线，只增加或修改 Android 验收工作流、驱动和测试。API 35 模拟器上，系统选择器共打开 5 次。取消保持配置文件和临时下载目录不变，保存的 126 字节 v2 档案通过宿主独立解密。驱动记录对照字号保存按钮的受信任目标事件，并从应用私有配置文件读回字号从 19 变为 13。错误口令和篡改档案各被应用拒绝，文件字节均未变化。正确档案的预览默认不勾选应用字号，预览期间文件也未变化。随后确认一次，界面和文件均恢复为字号 19，文件字节与初始状态一致。五项应用侧清理通过。单独的模拟器生命周期报告记录驱动和模拟器进程退出码均为 0，第一次检查已无设备传输。范围限 Tauri API 35 模拟器本地字号偏好。活动连接、多主机、云文档提供方和真机仍待验证。 [R6 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44625071232/job/135916604524) · [工件 14580355474](https://github.com/Luck9Star/herdr-pocket/actions/runs/44625071232/artifacts/14580355474) · [读盘与导入判据](https://github.com/Luck9Star/herdr-pocket/blob/db49c57ed06385fa21b16b93962572525bf5250c/validation/remote-harness/tauri_android_config_document.py#L630-L713)

复跑时选择含该工作流的远端 `codex/` 分支，将示例引用替换成对应分支。

```sh
gh workflow run tauri-android-direct-ssh.yml --ref 'codex/<分支>' -f scenario=config-document
```

## iOS 原生手填加密私钥

手填 R6 从正式首页进入，填写目标、核对主机指纹并验证 PEM 写入。口令步骤的安全检查阻断。脱敏诊断显示同一 WebView 内相对 PEM 编辑器为后代的两条 `staticText` 命中合成 PEM 标头，口令命中数为 0。服务端清理前后均只记录一条已关闭、零认证的探测，尚未进入认证、PTY、回显或主动断开。普通密码和换钥在该作业未运行。模拟器、夹具、私有文件及合成秘密清理均获确认。 [手填 R6 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44609944062/job/135863554949) · [工件 14573950954](https://github.com/Luck9Star/herdr-pocket/actions/runs/44609944062/artifacts/14573950954) · [历史原生粘贴两轮（均未验证）](../tauri-ios-encrypted-key-native-20261119/README.md)

手填 R7 使用当前主线产品。从首页进入后，驱动记录主机地址字段具有 UI 焦点且键盘可见。一次原生输入后，六次实时控件轮询均未与期望值匹配，报告只保留末次分类 `empty`。整树和实时控件的对照只在点击后（`afterTap`）和输入后（`afterInput`）各记录一次，两次均分类为 `empty`。输入后端口和用户名的读回分类为 `unchanged`。驱动将快照未提供的值（`nil`）和空串归为 `empty`，实际 DOM 值仍未知。测试报 `native_input_value_invalid`，对端连接数为 0。这次在目标阶段终止，尚未到指纹、PEM 和编辑器安全复查。普通密码和换钥未运行。四项临时资源清理获确认。 [手填 R7 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44616831107/job/135887674869) · [工件 14576158322](https://github.com/Luck9Star/herdr-pocket/actions/runs/44616831107/artifacts/14576158322) · [值转换](https://github.com/Luck9Star/herdr-pocket/blob/7c201e986fa43a224e155976fb7a8280f1aef675/validation/remote-harness/tauri_ios_direct_ssh.swift#L684-L688) · [快照采样](https://github.com/Luck9Star/herdr-pocket/blob/7c201e986fa43a224e155976fb7a8280f1aef675/validation/remote-harness/tauri_ios_direct_ssh.swift#L1144-L1186) · [实时轮询](https://github.com/Luck9Star/herdr-pocket/blob/7c201e986fa43a224e155976fb7a8280f1aef675/validation/remote-harness/tauri_ios_direct_ssh.swift#L1209-L1225)

手填 R8 沿用 R7 的产品。驱动记录对可命中的首页入口执行一次点击，随后仍报告紧凑空首页，添加方式页和普通 SSH 表单均未获确认。作业停在 `encrypted_key_open_add / native_home_navigation_failed`。报告的 `encrypted_key_form` 检查点发于打开表单之前。此轮未进入主机输入，新增的 AX 缺值／空串分类和局部 OCR 均未产生结果。清理前后对端都为零连接，模拟器、夹具、私有文件和合成秘密的清理通过。 [手填 R8 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44622775619/job/135908548761) · [工件 14578119753](https://github.com/Luck9Star/herdr-pocket/actions/runs/44622775619/artifacts/14578119753) · [首页导航判据](https://github.com/Luck9Star/herdr-pocket/blob/8b05e1cc1f82b3d110815e151a941026f15f40ee/validation/remote-harness/tauri_ios_direct_ssh.swift#L2815-L2839) · [表单阶段顺序](https://github.com/Luck9Star/herdr-pocket/blob/8b05e1cc1f82b3d110815e151a941026f15f40ee/validation/remote-harness/tauri_ios_direct_ssh.swift#L3172-L3178)

手填 R9 以 #51 后的主线 `5ffbbf7` 产品为基线，只改 iOS 验收工作流和驱动／测试。原生报告识别到紧凑空首页并记录 `ready`，随后在点击前报 `native_encrypted_key_home_shortcut_unproven`。报告没有可归属的点击或导航记录，未到普通 SSH 表单、主机字段读回、OCR 或 SSH，对端零连接。快捷入口与添加页选项的同名分类可命中同一节点，计数可重叠。作业结束时四项临时资源均已清理。 [手填 R9 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44628431596/job/135928338818) · [工件 14580874796](https://github.com/Luck9Star/herdr-pocket/actions/runs/44628431596/artifacts/14580874796) · [分类计数](https://github.com/Luck9Star/herdr-pocket/blob/3bf931305cf6808fb783130bea8b52a146ec7aa2/validation/remote-harness/tauri_ios_direct_ssh.swift#L2543-L2559) · [点击前置判据](https://github.com/Luck9Star/herdr-pocket/blob/3bf931305cf6808fb783130bea8b52a146ec7aa2/validation/remote-harness/tauri_ios_direct_ssh.swift#L2747-L2797)

独立本机 WebKit 26.5 用 440×956 视口加载与 R9 同源的 Tauri 前端，以合成 IPC 提供空主机列表。在正式紧凑首页点击 `home-open-ssh` 一次，浏览器记录受信任事件。添加页和同名 `add-ssh` 选项保持隐藏，普通 SSH 的目标表单可见，合成 IPC 未记录 SSH 调用。这个浏览器结果只覆盖前端路由，原生 XCTest 中的控件归属和点击仍待验证。 [本机脱敏测量](ios-r9-local-webkit-shortcut.json)

下次复跑前，先只读辨认可见的首页快捷入口，核对它在同一 App 窗口和 WebView 内的归属、启用、可命中及点击前置条件，再运行定向作业。输入结果未知时保留证据并停止，避免重放输入。

手填 R10 经 workflow_dispatch 手动触发，源码 `e9811be` 在 R9 基线上仅改 iOS 验收驱动的快捷入口尺寸与角色分类。原生报告识别紧凑空首页并记录 `ready`，随后在点击前报 `native_encrypted_key_home_shortcut_unproven`，诊断分类 `button_size_or_role`：快捷候选框与实时框均量得 163×22pt，间距 5pt。这组尺寸是原生点击前的脱敏测量，不能由此断言为产品的实际点击框。报告没有可归属的点击或导航记录，未到普通 SSH 表单、主机输入、OCR 或 SSH，清理前后对端均为零连接。模拟器、夹具、私有文件和合成秘密清理均获确认，原始日志与截图未上传。普通密码和换钥在该作业未运行。 [手填 R10 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44633057494/job/135944465338) · [工件 14584020355](https://github.com/Luck9Star/herdr-pocket/actions/runs/44633057494/artifacts/14584020355) · [尺寸判据](https://github.com/Luck9Star/herdr-pocket/blob/e9811becd8b4d69eee3075c73f19b5fba69f6269/validation/remote-harness/tauri_ios_direct_ssh.swift#L741-L770) · [诊断注入](https://github.com/Luck9Star/herdr-pocket/blob/e9811becd8b4d69eee3075c73f19b5fba69f6269/validation/remote-harness/tauri_ios_direct_ssh.swift#L946-L956)

手填 R11 待验证，尚无结果可报告。

## 证据留存

固定字段摘要保留运行、作业、源码、工件 ID、到期时间、ZIP SHA-256 和所核验成员的 SHA-256。工件到期后可从仓库复核所存计数、状态和摘要哈希。原 ZIP 及原报告的完整字段须另有原工件才能重验。这些工件均未收录截图。校验清单也覆盖独立本机测量。 [脱敏摘要](official-summary.json) · [校验清单](SHA256SUMS)

工件当前到期时间（UTC）

| 原始工件 | 到期时间 |
| --- | --- |
| Android R3 · 14573782872 | 2026-12-03 20:59:58 |
| Android R4 · 14576447045 | 2026-12-03 21:27:24 |
| Android R5 · 14578975990 | 2026-12-03 21:53:02 |
| Android R6 · 14580355474 | 2026-12-03 22:16:04 |
| iOS 手填 R6 · 14573950954 | 2027-02-17 20:33:52 |
| iOS 手填 R7 · 14576158322 | 2027-02-17 21:14:56 |
| iOS 手填 R8 · 14578119753 | 2027-02-17 21:50:27 |
| iOS 手填 R9 · 14580874796 | 2027-02-17 22:25:09 |
| iOS 手填 R10 · 14584020355 | 2027-02-17 22:55:23 |

```sh
shasum -a 256 -c SHA256SUMS
```
