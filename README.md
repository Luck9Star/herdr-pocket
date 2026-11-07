# herdr-pocket

手机优先的远端 [herdr](https://github.com/herdrdev/herdr) 客户端原型。首次配对时，手机审查主机指纹并创建专属设备密钥，主机确认后，手机主动连接，从看板选择会话内的终端并持续观察。目标平台为 iOS、Android、Windows、macOS 和 Linux。

**从这里开始**　[原型分支与源码](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation) · [最新下载、验收与复测步骤](https://github.com/Luck9Star/herdr-pocket/blob/71ce10191c2c282bc4d5258f1bfc191a3cbfb882/docs/50-android-paired-tui-validation.md) · [Penpot 手机配对交互原型](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e8e75ef79937)

**手机端进度 · 2026-11-08**　手机审查主机指纹并创建设备密钥，主机明确授权后，手机复核回执、主动连接，在看板选择终端，接收首帧及后续增量。Flutter 和 Tauri 的原版 herdr 只读闭环均有 API 35 模拟器记录。本次 Tauri 还完成同一 SSH 连接上的十步远端 TUI 与手机撤销。Flutter 定向复测也走通了只读闭环，首帧序号 1、增量序号 3，停止时远端共收到 0 字节。其带输入场景送达前 10 字节后，在恢复终端观察时超时。[上批双路线只读验收](https://github.com/Luck9Star/herdr-pocket/blob/343b5b6b0d926044d6884b33ea73bec3a5b6b174/docs/46-android-pairing-handoff-validation.md) · [本批逐场结果](https://github.com/Luck9Star/herdr-pocket/blob/71ce10191c2c282bc4d5258f1bfc191a3cbfb882/docs/50-android-paired-tui-validation.md) · [Flutter 定向复测](https://github.com/Luck9Star/herdr-pocket/actions/runs/42407250343)

## Android 测试包

两份 arm64-v8a debug APK 来自同一提交 [`2b497ea`](https://github.com/Luck9Star/herdr-pocket/commit/2b497ea261c33dbf5fafeac2287bad1220ca5166)。登录 GitHub 下载归档，分别解压，用 `shasum -a 256 app.apk` 核对。两个包的摘要、原生库和共享字体资产均已实际核验。下载于北京时间 **11 月 22 日 02:58（Flutter）及 03:00（Tauri）** 到期。arm64 真机安装未验证。[构建记录](https://github.com/Luck9Star/herdr-pocket/actions/runs/42402903055)

| 路线 | 测试包 | app.apk SHA-256 |
| --- | --- | --- |
| Flutter | [下载 arm64 debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42402903055/artifacts/13586616994) | `b9292bed0de3762262ad350abe5dab723ad2375602635c0c5576f0baedaa44b2` |
| Tauri | [下载 arm64 debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42402903055/artifacts/13586094449) | `2d0543d00dfdcbc7a4629eca3bf32d64727e9fcd3330e5cd2237f6d929d0f0ca` |

**本批实测**　Tauri 只读场景远端收到 0 字节。受保护输入场景先收到逐键与草稿两笔，再由手机操作远端 curses，十笔新回执均绑定原目标；手机接受撤销回执并完成清理。两场共享 PTY 均维持 119×40。八个实际构建或验证任务中五个成功，Rust 测试、Flutter 源测试和 Flutter 模拟器准备三个任务失败。[失败、修复与运行边界](https://github.com/Luck9Star/herdr-pocket/blob/71ce10191c2c282bc4d5258f1bfc191a3cbfb882/docs/50-android-paired-tui-validation.md)

## 手机端当前进度

| 范围 | 已有证据 | 下一项验收 |
| --- | --- | --- |
| 配对 → 看板 → 持续观察 | 两壳均有独立设备密钥 SSH、看板、所选 pane 首帧及增量、主动停止的模拟器证据。Flutter 与 Tauri 均确认只读观察全程远端收到 0 字节，Tauri 两场另验收手机撤销。[配对与闭环](https://github.com/Luck9Star/herdr-pocket/blob/71ce10191c2c282bc4d5258f1bfc191a3cbfb882/docs/50-android-paired-tui-validation.md) | arm64 安装、物理相机扫码、锁屏和重启恢复 |
| 终端与阅读位置 | 两份包包含三档观察画布。Flutter 与 Tauri 的只读模拟器场景均验收了宽画布、标记及阅读位置恢复。[画布与设备验收](https://github.com/Luck9Star/herdr-pocket/blob/71ce10191c2c282bc4d5258f1bfc191a3cbfb882/docs/50-android-paired-tui-validation.md) | 真机触控、锁屏与长时间观察 |
| 终端输入 | 原版 herdr 保持只读。Tauri 在受保护宿主完成逐键、草稿及十个 TUI 按键。发送结果未知时保留记录，供用户核查。[操作与回执](https://github.com/Luck9Star/herdr-pocket/blob/71ce10191c2c282bc4d5258f1bfc191a3cbfb882/docs/50-android-paired-tui-validation.md) | Flutter 隐藏标签恢复后的 TUI、真实中文 IME 与实体键盘 |
| 组网与平台 | 两份 APK 包含 EasyTier、Tailscale。ZeroTier 的来源、设备管理及离线原生验证另有记录。[原生验证](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/29-zerotier-managed-device.md) | 三网真实节点、并发及五平台矩阵 |

Flutter 与 Tauri 继续并行验证，物理手机的输入正确性、字形、生命周期和性能仍会影响选型。公开仓库提供源码和测试渠道，项目许可证与原生依赖的分发条件仍在审查。[技术栈复评](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/06-technology-evaluation.md) · [分发与许可](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/17-license-and-distribution-review.md)

[产品设计](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/05-product-design.md) · [设计与验证文档索引](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation/docs) · [云构建与分发](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/07-build-and-release.md) · [历史首页与测试包](https://github.com/Luck9Star/herdr-pocket/blob/cbb419bcf08adbbd4cdc1c47fd02acecfad57320/README.md)
