# herdr-pocket

手机优先的远端 [herdr](https://github.com/herdrdev/herdr) 客户端原型。首次配对时，手机审查主机指纹并创建专属设备密钥，主机确认后，手机主动连接，从看板选择会话内的终端并持续观察。目标平台为 iOS、Android、Windows、macOS 和 Linux。

**从这里开始**　[阶段交接：已完成、未完成与恢复顺序](https://github.com/Luck9Star/herdr-pocket/blob/85c150b24dca14412cf01075b832c1014547a3aa/docs/56-project-status-and-handoff.md) · [原型分支与源码](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation) · [最新下载、验收与复测步骤](https://github.com/Luck9Star/herdr-pocket/blob/e9ddfc8d03593e03a6ae539b3f0679a9adf3c84f/docs/53-mobile-connection-diagnostics.md) · [Penpot 手机配对交互原型](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e8e75ef79937)

**手机端进度 · 2026-11-08**　Flutter 和 Tauri 已把身份审查、手机专属密钥、主机授权回执和设备密钥 SSH 接入手机 GUI。从主机看板点选具体终端后，能看到首帧和持续输出，再主动停止。本批 Tauri 在 API 35 模拟器还走通了「两条同名受阻记录 → 重审 → 精确观察 B」，远端收到 0 字节；受保护输入完成十个远端 TUI 操作。Flutter 定向复测也走通配对、看板、持续观察、停止，再从同名记录准确选中 B，远端输入为 0 字节。Flutter 的受保护 TUI 在前两笔共 10 字节后仍因 SSH 通道关闭确认超时，未恢复新首帧，输入保持关闭。[本批设备记录](https://github.com/Luck9Star/herdr-pocket/blob/e9ddfc8d03593e03a6ae539b3f0679a9adf3c84f/docs/53-mobile-connection-diagnostics.md) · [Flutter 定向运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/42417473474)

两条路线均可展开查看本次连接的网络路径、主机指纹、公钥认证、看板和终端首帧。字体诊断使用固定 Powerlevel10k 与 Oh My Posh 样例；手机实体键盘、真实中文输入法和真机性能仍待实测。[受阻窗格交互](https://github.com/Luck9Star/herdr-pocket/blob/d5a6dc06a876d05ef98815759595c042b05b1cfd/docs/51-mobile-blocked-targets.md) · [主题及已保存的 Penpot 原型](https://github.com/Luck9Star/herdr-pocket/blob/d5a6dc06a876d05ef98815759595c042b05b1cfd/docs/52-mobile-theme-prompts.md)

**测试包之后的原型进度**　两套手机看板都能按名称、地址、命名会话及网络类型检索主机，并区分当前待处理和上次受阻。Flutter 修复静默 SSH 观察通道后，在 Mac 隔离的真实 herdr 会话中连续恢复五次，每次均收到新首帧和后续增量，远端输入为 0。修复后的 Android 受保护 TUI 尚待复测。下方两份 APK 对应较早的 `dd02595`。[源码、Penpot 与实测记录](https://github.com/Luck9Star/herdr-pocket/blob/8703b0d37a2497357c5c6c07c6e4f28ce2a3fe1c/docs/54-mobile-host-search-and-observer-retirement.md)

**手机网络配置**　Flutter 和 Tauri 都已接入「审查 ZeroTier 共享设备」。设备服务不可用时，仍可核对关联网络和主机；目录读取失败时显示范围未知。新版 Penpot 已保存两种状态。Mac 已验证临时 ZeroTier 身份经 JNI 加密保存、重新读取和删除。手机系统 KeyStore、实际入网与跨网络并发待测。下方已验证的 APK 来自此前的版本。[原型源码与本批实测](https://github.com/Luck9Star/herdr-pocket/blob/22d53e272a9acbeb2345bbcd0a1201fd7449af52/docs/55-mobile-shared-network-device.md) · [Penpot 设备审查](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=2a5fd934-a163-8057-8008-e823088d7aeb)

## Android 测试包

两份 API 35 arm64-v8a debug APK 来自同一提交 [`dd02595`](https://github.com/Luck9Star/herdr-pocket/commit/dd025952321fb944465a48ec762ae76adc74f830)。登录 GitHub 下载归档，分别解压，用 `shasum -a 256 app.apk` 核对。归档摘要、包内 APK 和原生来源均已核验；两包中的 EasyTier、Tailscale 原生库逐字节一致。下载于北京时间 **11 月 22 日 05:32（Flutter）和 05:33（Tauri）** 到期。arm64 真机安装未验证。[构建记录](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185)

| 路线 | 测试包 | app.apk SHA-256 |
| --- | --- | --- |
| Flutter | [下载 arm64 debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185/artifacts/13591233797) | `027a7881183275e966f602a8a48f0ffc51f4d718476cc9aa1fab151f45499a32` |
| Tauri | [下载 arm64 debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42415286185/artifacts/13591323156) | `569313409cfb7e2b88fe3fa0d267817ca727276866613364824002561a567604` |

[试测步骤、首轮失败和修复](https://github.com/Luck9Star/herdr-pocket/blob/e9ddfc8d03593e03a6ae539b3f0679a9adf3c84f/docs/53-mobile-connection-diagnostics.md) · [上一批安装包与历史验收](https://github.com/Luck9Star/herdr-pocket/blob/71ce10191c2c282bc4d5258f1bfc191a3cbfb882/docs/50-android-paired-tui-validation.md)

## 手机端当前进度

| 范围 | 已有证据 | 下一项验收 |
| --- | --- | --- |
| 配对 → 看板 → 持续观察 | 两壳均有独立设备密钥 SSH、看板、所选 pane 首帧及增量、主动停止的模拟器证据。Flutter 与 Tauri 均确认只读观察全程远端收到 0 字节，两条路线均从同名受阻记录打开 B，Tauri 另验收手机撤销。[配对与闭环](https://github.com/Luck9Star/herdr-pocket/blob/e9ddfc8d03593e03a6ae539b3f0679a9adf3c84f/docs/53-mobile-connection-diagnostics.md) | arm64 安装、物理相机扫码、锁屏和重启恢复 |
| 终端与阅读位置 | 两份包包含三档观察画布。Flutter 与 Tauri 的只读模拟器场景均验收了宽画布、标记及阅读位置恢复。[画布与设备验收](https://github.com/Luck9Star/herdr-pocket/blob/71ce10191c2c282bc4d5258f1bfc191a3cbfb882/docs/50-android-paired-tui-validation.md) | 真机触控、锁屏与长时间观察 |
| 终端输入 | 原版 herdr 保持只读。Tauri 在受保护宿主完成逐键、草稿及十个 TUI 按键。发送结果未知时保留记录，供用户核查。[操作与回执](https://github.com/Luck9Star/herdr-pocket/blob/e9ddfc8d03593e03a6ae539b3f0679a9adf3c84f/docs/53-mobile-connection-diagnostics.md) | Flutter 隐藏标签恢复后的 TUI、真实中文 IME 与实体键盘 |
| 组网与平台 | 两份 APK 包含 EasyTier、Tailscale。ZeroTier 的来源、设备管理及离线原生验证另有记录。[原生验证](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/29-zerotier-managed-device.md) | 三网真实节点、并发及五平台矩阵 |

Flutter 与 Tauri 继续并行验证，物理手机的输入正确性、字形、生命周期和性能仍会影响选型。公开仓库提供源码和测试渠道，项目许可证与原生依赖的分发条件仍在审查。[技术栈复评](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/06-technology-evaluation.md) · [分发与许可](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/17-license-and-distribution-review.md)

[产品设计](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/05-product-design.md) · [设计与验证文档索引](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation/docs) · [云构建与分发](https://github.com/Luck9Star/herdr-pocket/blob/1b7ccf63bd8caafdb54f34fe9b7d3195deeff2f4/docs/07-build-and-release.md) · [历史首页与测试包](https://github.com/Luck9Star/herdr-pocket/blob/cbb419bcf08adbbd4cdc1c47fd02acecfad57320/README.md)
