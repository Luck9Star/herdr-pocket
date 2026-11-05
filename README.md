# herdr-pocket

herdr-pocket 是一个手机优先的远端 herdr 图形客户端原型。目标平台为 iOS、Android、Windows、macOS 和 Linux。手机从配对和主机看板进入终端，桌面共享主机、会话和终端模型。项目独立于 herdr 官方，许可证待依赖和分发审查后确定。

**当前进度 · 2026-11-06**　两条候选路线都已把配对审查、设备身份、会话看板和持续观察接入 GUI。日常开发在[公开原型分支](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation)，按批次生成测试包。手机真机与三网运行结果分别验收。

| 范围 | 已取得的结果 | 待验收 |
| --- | --- | --- |
| 设计 | 已保存新版配色、可点击配对与终端流程 | 真机触控、中文输入法和无障碍 |
| 配对 | 手机保留待授权请求，回到前台后重新核验。POSIX helper 在自建临时 home 验证授权和撤销 | 真实相机、系统锁屏与设备身份跨重启 |
| 看板和终端 | 两套传输适配器在隔离 SSH/herdr 环境通过 18/18 项只读对照，接收端输入为 0；Mac 原生应用已验证从首页进入可编辑主机表单 | 两套手机 GUI 的完整配对、选中 pane、首帧与后续增量 |
| 交互输入 | 普通 herdr 0.9.5 保持只读。隔离候选扩展已编译，并通过目标绑定测试 | GUI 的逐键、IME、TUI 与结果未知恢复 |
| 分发 | 已重建并核对 Flutter 和 Tauri 基线 APK；后续 Tauri 配对测试包也已下载验 SHA | 安装、签名与设备运行按平台分别记录 |

[原型和覆盖清单](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/design/README.md) · [最新手机 GUI 验证与失败记录](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/15-mobile-gui-validation.md) · [Android 下载、SHA 和测试步骤](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/14-mobile-pairing-workbench.md) · [18 项持续观察对照](https://github.com/Luck9Star/herdr-pocket/blob/221a37a14f70eb2a94e81071a00e62758beb1f9f/docs/13-mobile-dashboard-observe.md)

手机开发顺序为配对、主机与会话看板、完整终端、多标签和恢复。桌面分屏紧随其后。Flutter 和 Tauri 继续使用相同 fixture 对照；框架选型以终端正确性和实测为依据。[产品设计](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/05-product-design.md) · [终端绘制与 EasyTier 移植记录](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/10-blocker-repair.md) · [本批手机云验证](https://github.com/Luck9Star/herdr-pocket/actions/runs/42128042321)
