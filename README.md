# herdr-pocket

手机优先的远端 [herdr](https://github.com/herdrdev/herdr) 客户端原型。首次配对时，手机审查主机指纹并创建专属设备密钥，主机确认后，手机主动连接，从看板选择会话内的终端并持续观察。目标平台为 iOS、Android、Windows、macOS 和 Linux。

**从这里开始**　[原型分支与源码](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation) · [本次验收与复测步骤](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/43-mobile-viewport-recovery.md) · [Penpot 手机可点击原型](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e8c46842cb06)

**原型分支最新进度 · `23dd7fd`**　主机 helper 可生成公开连接资料二维码。Flutter 与 Tauri 都已接入资料预览、指纹核对及设备授权审查。声明覆盖网络的主机首次连接前须绑定本机同类型网络。Mac 已验证二维码解码与窄屏扫码审查；这批改动的 Android 构建和真机相机仍待验收。下方测试包保留各自的实际源码与验证结果。[本批源码和分层实测](https://github.com/Luck9Star/herdr-pocket/blob/23dd7fd3ac579c4faef3dcd18c8d3d1cf74fa280/docs/44-mobile-connection-profile.md) · [Penpot 手机配对预览](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e8dca4d84f9b)

## Android 测试包 · 2026-11-07

两份 arm64-v8a debug APK 来自同一[源码提交](https://github.com/Luck9Star/herdr-pocket/commit/cb0fd1c7ad3137a09dd92dbd72e2df168379ce88)。登录 GitHub 下载归档，解压后用 `shasum -a 256 app.apk` 核对下表。已逐包核验 ZIP、APK、EasyTier 和 Tailscale 原生库，以及两端共用的字体和诊断样例。[构建与模拟器运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/42374975205)

| 路线 | 测试包 | app.apk SHA-256 |
| --- | --- | --- |
| Flutter | [下载 arm64 debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42374975205/artifacts/13575935931) | `ab0c06233be2c74e5ad591c6cafb5e90aa384e2f0785526641371bc542e70a96` |
| Tauri | [下载 arm64 debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42374975205/artifacts/13575986671) | `088b8bc6e562b02432bc9d87889f48eebdd95413bacaddf01b317d436f4950b4` |

**本批实测**　Flutter 在 API 35 x86_64 模拟器走通配对、看板和持续观察；远端收到 0 字节，八行字体诊断标记均在第 15 列。四场均完成设备公钥匹配的 SSH 认证，共享 PTY 均保持 119 × 40。Flutter 受保护输入与 Tauri 两场停在系统输入法目标窗口校验，另有 5 项 Flutter widget 测试失败。本批云任务 5/8 通过。arm64 APK 尚待真机安装，两份归档于北京时间 11 月 21 日 21:15／21:16 到期。[逐场验证记录](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/43-mobile-viewport-recovery.md) · [上一批四场完整通过的结果及安装包](https://github.com/Luck9Star/herdr-pocket/blob/3877f6cd2988b23888a48a8ccb118ff682baadca/docs/40-android-paired-dashboard-validation.md)

## 手机端当前进度

| 范围 | 已有证据 | 下一项验收 |
| --- | --- | --- |
| 配对 → 看板 → 持续观察 | 两套 GUI 均已在 API 35 x86_64 云模拟器完成主机审查、设备签名 SSH、选定终端、收取完整画面和后续变化、停止观察。[四场通过的基线](https://github.com/Luck9Star/herdr-pocket/blob/3877f6cd2988b23888a48a8ccb118ff682baadca/docs/40-android-paired-dashboard-validation.md) | arm64 真机安装、相机扫码、锁屏与重启恢复 |
| 终端与阅读位置 | 切回原终端须先校验身份并取得新的完整画面。Mac Chrome 在 320 和 390 像素宽的两个入口共四场恢复到原位置，远端发送及 resize 均为零。[本次测量](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/43-mobile-viewport-recovery.md) | 手机中文 IME、触控选区、长时间观察与跨标签焦点 |
| 终端输入 | 原版 herdr 在手机验证链路中提供只读观察。隔离的守卫扩展支持目标绑定的逐键和草稿输入；不确定是否送达时保留记录，不自动重发。[输入能力与恢复](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/24-target-input-recovery.md) | 主机扩展交付、真实交互式 TUI 和设备输入 |
| 组网与平台 | 两份 APK 包含 EasyTier、Tailscale。ZeroTier 的来源、设备管理及离线原生验证另有记录。[原生验证](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/29-zerotier-managed-device.md) | 三网真实节点、并发及五平台矩阵 |

Flutter 与 Tauri 继续并行验证，物理手机的输入正确性、字形、生命周期和性能仍会影响选型。公开仓库提供源码和测试渠道，项目许可证与原生依赖的分发条件仍在审查。[技术栈复评](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/06-technology-evaluation.md) · [分发与许可](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/17-license-and-distribution-review.md)

[产品设计](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/05-product-design.md) · [设计与验证文档索引](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation/docs) · [云构建与分发](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/07-build-and-release.md) · [历史首页与测试包](https://github.com/Luck9Star/herdr-pocket/blob/cbb419bcf08adbbd4cdc1c47fd02acecfad57320/README.md)
