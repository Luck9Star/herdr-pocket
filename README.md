# herdr-pocket

herdr-pocket 是一个手机优先的远端 herdr 图形客户端原型。目标平台为 iOS、Android、Windows、macOS 和 Linux。手机从配对和主机看板进入终端，桌面共享主机、会话和终端模型。项目独立于 herdr 官方，许可证待依赖和分发审查后确定。

**当前进度 · 2026-11-06**　Flutter 与 Tauri 在相同源码提交和 Android API 35 云模拟器上，均已走通**配对 → 主机与会话看板 → 选定 pane → 持续观察**。隔离主机验证了应用实际使用的设备公钥；停止后保留陈旧画面，远端输入为 0。[公开原型分支](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation) · [成功运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/42132730593)

下载同源 Android 测试包：[Flutter debug APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42132730593/artifacts/13464856670) · [Tauri arm64 debug APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42132730593/artifacts/13463534127) · [解包步骤、校验值与设备边界](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/15-mobile-gui-validation.md)。

| 范围 | 已取得的结果 | 待验收 |
| --- | --- | --- |
| 设计 | 已保存新版配色、可点击配对与终端流程 | 真机触控、中文输入法和无障碍 |
| 配对 | 手机保留待授权请求，回到前台后重新核验。POSIX helper 在自建临时 home 验证授权和撤销 | 真实相机、系统锁屏与设备身份跨重启 |
| 看板和终端 | 两套 GUI 已核对 sshd 接受的设备公钥，显示选中 pane 的 full/delta 并主动停止；只读测试输入为 0。Flutter Linux widget 两次改变本地窗口时，远端共享 PTY 的 407 次取样均为 119 × 40 | 真机前后台切换、输入结果核实与长期运行 |
| 交互输入 | 普通 herdr 0.9.5 保持只读。隔离候选扩展已编译，并通过目标绑定测试 | GUI 的逐键、IME、TUI 与结果未知恢复 |
| 分发 | 两套 Android debug APK 已重建并验 SHA。另有 Tauri iOS 模拟器产物、Flutter iOS 无签名构建和独立 POSIX helper 源码包 | 安装、签名与设备运行按平台分别记录 |

[原型和覆盖清单](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/design/README.md) · [最新手机 GUI 验证与失败记录](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/15-mobile-gui-validation.md) · [配对、安装与测试步骤](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/14-mobile-pairing-workbench.md) · [18 项持续观察对照](https://github.com/Luck9Star/herdr-pocket/blob/221a37a14f70eb2a94e81071a00e62758beb1f9f/docs/13-mobile-dashboard-observe.md)

手机开发顺序为配对、主机与会话看板、完整终端、多标签和恢复。桌面分屏紧随其后。Flutter 和 Tauri 继续使用相同 fixture 对照；框架选型以终端正确性和实测为依据。[产品设计](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/05-product-design.md) · [终端绘制与 EasyTier 移植记录](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/10-blocker-repair.md) · [本批手机云验证](https://github.com/Luck9Star/herdr-pocket/actions/runs/42132730593)
