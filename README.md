# herdr-pocket

herdr-pocket 是面向远端 herdr 主机的图形客户端原型。目标覆盖 iOS、Android、Windows、macOS 和 Linux，手机优先。手机上从主机配对和会话看板进入终端，桌面共享同一套主机、会话和终端信息，并支持分屏。项目与 herdr 官方独立。

**当前进度（2026-11-05）**　Flutter 与 Tauri 两条验证路线已推进到手机只读看板。实现、构建脚本和测试入口在[公开原型分支](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation)。项目许可证仍待依赖和分发审查后确定。

| 范围 | 已取得的结果 | 下一项验证 |
| --- | --- | --- |
| 设计 | Penpot v2 已保存手机看板、终端观察和配对审查流程 | 手机触控、中文输入法与无障碍 |
| 只读终端 | 两套 GUI 共用的适配器在隔离 SSH/herdr 主机上通过 18/18 项 CLI 对照，包含选定会话、持续观察、取消和显式重连。远端收到的输入为 0 字节 | 从 GUI 使用设备身份完成真实连接并观察所选 pane |
| 配对和设备密钥 | 配对契约及 helper 已在临时测试目录运行，Apple 内存签名探针和 Android 桥编译通过 | 手机端响应审查、系统密钥存储与 SSH 签名 |
| 测试构建 | 两条路线均已完成五平台云构建，Mac 包已做有限原生检查 | 手机安装、完整交互输入和三种组网的逐平台运行验收 |

[设计原型与覆盖清单](https://github.com/Luck9Star/herdr-pocket/blob/221a37a14f70eb2a94e81071a00e62758beb1f9f/design/README.md) · [手机看板与持续观察验证记录](https://github.com/Luck9Star/herdr-pocket/blob/221a37a14f70eb2a94e81071a00e62758beb1f9f/docs/13-mobile-dashboard-observe.md) · [终端绘制与 EasyTier 移植记录](https://github.com/Luck9Star/herdr-pocket/blob/221a37a14f70eb2a94e81071a00e62758beb1f9f/docs/10-blocker-repair.md) · [逐平台构建与测试证据](https://github.com/Luck9Star/herdr-pocket/blob/221a37a14f70eb2a94e81071a00e62758beb1f9f/docs/evidence/mobile-observe/builds/README.md)

Android 测试包通过 GitHub Actions 分发，下载时请从对应 run 的 Artifacts 区选择应用包并核对随包的 SHA256SUMS。历史验证记录中的临时下载地址可能已失效。[构建记录](https://github.com/Luck9Star/herdr-pocket/actions)

开发顺序为手机配对审查与设备密钥、会话看板、持续观察，再推进逐键输入、草稿、多标签与断线恢复。[产品设计](https://github.com/Luck9Star/herdr-pocket/blob/221a37a14f70eb2a94e81071a00e62758beb1f9f/docs/05-product-design.md) · [路线图](https://github.com/Luck9Star/herdr-pocket/blob/221a37a14f70eb2a94e81071a00e62758beb1f9f/docs/04-roadmap.md)
