# herdr-pocket

手机优先的远端 [herdr](https://github.com/herdrdev/herdr) 客户端原型。首次配对时，手机审查主机指纹并创建专属设备密钥，主机确认后，手机主动连接，从看板选择会话内的终端并持续观察。目标平台为 iOS、Android、Windows、macOS 和 Linux。

**从这里开始**　[原型分支与源码](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation) · [本批验收与复测步骤](https://github.com/Luck9Star/herdr-pocket/blob/343b5b6b0d926044d6884b33ea73bec3a5b6b174/docs/46-android-pairing-handoff-validation.md) · [Penpot 手机配对交互原型](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e8e75ef79937)

**手机端进度 · 2026-11-08**　Flutter 和 Tauri 均已接入主机资料审查和本机设备密钥，原版 herdr 的「配对 → 看板 → 持续观察」已在两套 API 35 模拟器场景走通。源码分支另已修复设备密钥删除失败后的恢复，保留用户最初选择的「仅清身份」或「移除主机」。这项后续修复等待下批设备验收。[配对交接与撤销](https://github.com/Luck9Star/herdr-pocket/blob/343b5b6b0d926044d6884b33ea73bec3a5b6b174/docs/45-mobile-pairing-handoff.md) · [后续源码修复](https://github.com/Luck9Star/herdr-pocket/commit/82b499b562f8203b24640e392f926b58a285e560)

## Android 测试包

两份 arm64-v8a debug APK 均来自 [`7470d5c`](https://github.com/Luck9Star/herdr-pocket/commit/7470d5cc2a9c4b4c5fce0802b6bc7789a8b1e67f)。登录 GitHub 下载归档，在不同目录解压，以 `shasum -a 256 app.apk` 核对。两个包内的 EasyTier、Tailscale、Nerd Font 和诊断样例均已核实。归档于北京时间 11 月 21 日 23:55（Flutter）及 23:57（Tauri）到期。[同源构建](https://github.com/Luck9Star/herdr-pocket/actions/runs/42386109360)

| 路线 | 测试包 | app.apk SHA-256 |
| --- | --- | --- |
| Flutter | [下载 arm64 debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42386109360/artifacts/13580043770) | `420ff2077356116b3556e0bb47d104e1ddfec966660d06bd5df8f221b5ef9745` |
| Tauri | [下载 arm64 debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42386109360/artifacts/13580602396) | `1242e94e0c6cb85995016bb4d11eb58faa88172b9196156512a24ad657e3f20d` |

**本批实测**　两套原版 herdr 只读场景均完成配对、公钥认证、看板、首帧、增量和主动停止，远端收到 0 字节。带输入的 Tauri 场景取得两笔回执、10 字节，最终手机撤销确认失败；Flutter 场景收到 1 字节，应用清理失败，首发原因未知。四场共享 PTY 的采样均为 119 × 40。八项实际云任务中五项成功，arm64 真机安装与真实中文输入法待验证。[逐场验收与已知问题](https://github.com/Luck9Star/herdr-pocket/blob/343b5b6b0d926044d6884b33ea73bec3a5b6b174/docs/46-android-pairing-handoff-validation.md) · [前一批记录](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/43-mobile-viewport-recovery.md)

## 手机端当前进度

| 范围 | 已有证据 | 下一项验收 |
| --- | --- | --- |
| 配对 → 看板 → 持续观察 | Flutter、Tauri 在 API 35 模拟器均验证首次资料审查、设备签名 SSH、看板、所选终端首帧与增量、停止；Tauri 只读场景还走通手机接受撤销回执。[四场设备结果](https://github.com/Luck9Star/herdr-pocket/blob/343b5b6b0d926044d6884b33ea73bec3a5b6b174/docs/46-android-pairing-handoff-validation.md) | arm64 安装、物理相机扫码、锁屏和重启恢复 |
| 终端与阅读位置 | 切回原终端须先校验身份并取得新的完整画面。Mac Chrome 在 320 和 390 像素宽的两个入口共四场恢复到原位置，远端发送及 resize 均为零。[本次测量](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/43-mobile-viewport-recovery.md) | 手机中文 IME、触控选区、长时间观察与跨标签焦点 |
| 终端输入 | 原版 herdr 在手机验证链路中提供只读观察。隔离的守卫扩展支持目标绑定的逐键和草稿输入；不确定是否送达时保留记录，不自动重发。[输入能力与恢复](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/24-target-input-recovery.md) | 主机扩展交付、真实交互式 TUI 和设备输入 |
| 组网与平台 | 两份 APK 包含 EasyTier、Tailscale。ZeroTier 的来源、设备管理及离线原生验证另有记录。[原生验证](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/29-zerotier-managed-device.md) | 三网真实节点、并发及五平台矩阵 |

Flutter 与 Tauri 继续并行验证，物理手机的输入正确性、字形、生命周期和性能仍会影响选型。公开仓库提供源码和测试渠道，项目许可证与原生依赖的分发条件仍在审查。[技术栈复评](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/06-technology-evaluation.md) · [分发与许可](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/17-license-and-distribution-review.md)

[产品设计](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/05-product-design.md) · [设计与验证文档索引](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation/docs) · [云构建与分发](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/07-build-and-release.md) · [历史首页与测试包](https://github.com/Luck9Star/herdr-pocket/blob/cbb419bcf08adbbd4cdc1c47fd02acecfad57320/README.md)
