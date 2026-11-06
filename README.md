# herdr-pocket

herdr-pocket 是手机优先的远端 herdr 图形客户端原型，目标覆盖 iOS、Android、Windows、macOS 和 Linux。手机从配对和主机看板进入完整终端，桌面共享信息模型并提供分屏。项目独立于 herdr 官方；具体许可证待依赖与分发审查后确定。

**当前进度 · 2026-11-06**　Flutter 与 Tauri 两条路线已在同源 `040eb26` 的 Android API 35 云模拟器走通 **配对 → 主机与会话看板 → 选定 pane → 持续观察 → 主动停止**，只读用例远端输入为 0。Tauri 的受保护输入取得两笔匹配回执；Flutter 输入／新增回归仍有失败，后续源码修复待集中复验。框架尚未定案。[公开原型分支](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation) · [实际结果与失败记录](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/18-mobile-network-profiles.md)

当前可下载的 Android 测试包仍来自 `040eb26`：[Flutter debug APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42158644225/artifacts/13476846146) · [Tauri arm64 debug APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42158644225/artifacts/13475774527) · [解包、校验值与测试步骤](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/18-mobile-network-profiles.md)。该批总运行最终取消，已完成的构建和已下载核对的产物分别保留；不能把总运行或所有用例称为通过。

后续已发布源码 `d6c4285` 接入 Android 本机网络身份、共享节点生命周期，以及两套 GUI 的显式 EasyTier 路由和 Flutter 原生字节流通道。**当前下载包不包含这些源码增量**；隔离 Rust／JVM 检查不等于 Android 加载、真实入网或 SSH 组网闭环已经验证。[最新已提交的原生通道与构建记录](https://github.com/Luck9Star/herdr-pocket/blob/d6c4285d4ccacd38fb8a43452ee447143f0ce4d3/docs/21-flutter-native-network.md)

| 范围 | 已取得的结果 | 尚待验证 |
| --- | --- | --- |
| 设计 | Penpot v2 已保存 30 个画板，包含新版配色、配对、终端、网络与迁移流程 | 真机触控、中文输入法、无障碍与实测反馈 |
| 配对与密钥 | 两条 Android 云模拟器路线核对实际 SSH 接受的设备公钥；helper 仅在隔离临时目录验证授权和撤销 | 真实相机、锁屏、重启恢复及各平台身份保护 |
| 看板与观察 | 选定 pane 的 full/delta、主动停止和旧画面标记通过隔离 GUI 用例 | 长期运行、跨网络多标签和真实设备生命周期 |
| 输入与迁移 | Tauri 隔离主机收到精确的 1 与 9 字节两笔输入；两套源码接入受保护输入、配置迁移和网络偏好 | Flutter 失败复验、真实 IME、TUI、结果未知恢复 |
| 原生网络 | EasyTier 参考桥的三桌面编译／链接／符号加载与隔离生命周期检查有记录；Android GUI 接线已提交 | Android 原生加载、真实节点、Tailscale／ZeroTier 及逐平台并发 |
| 分发 | 两份 Android debug 测试包与各自 SHA 可获取 | 新源码集中重建、签名、安装及设备运行分别验收 |

[设计与覆盖清单](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/design/README.md) · [配对审查与设备密钥](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/14-mobile-pairing-workbench.md) · [终端绘制与 EasyTier 移植修复](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/10-blocker-repair.md) · [三桌面原生候选运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/42159392366)

下一批继续手机独立终端标签、保留连接与显式恢复，再集中重建两套 Android 包；桌面分屏紧随手机闭环。两路线保持相同字体和 fixture，以正确性、实测和维护成本收敛技术选择。断线或结果未知不自动重放输入，布局不隐式修改远端共享 PTY。真实三网与五端验收矩阵仍保留未验证项。[产品设计](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/05-product-design.md) · [云构建与分发](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/07-build-and-release.md)
