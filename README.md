# herdr-pocket

herdr-pocket 是手机优先的远端 herdr 图形客户端原型，目标覆盖 iOS、Android、Windows、macOS 和 Linux。手机从配对和主机看板进入完整终端，桌面共享信息模型并提供分屏。项目独立于 herdr 官方；具体许可证待依赖与分发审查后确定。

**当前进度 · 2026-11-06**　Flutter 与 Tauri 的同源 `546c3eb` Android arm64 测试包已完成云端构建，原生来源、APK 库字节、ABI、JNI 和动态依赖检查通过。两份归档已实际下载，并独立核对 ZIP digest、包内校验和与来源提交。[公开原型分支](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation) · [CI 5 项 job 全部成功](https://github.com/Luck9Star/herdr-pocket/actions/runs/42208702281) · [详细验证与前三轮失败记录](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/22-mobile-terminal-tabs.md)

| Android 测试路线 | 下载 | 解压后的 app.apk SHA256 |
| --- | --- | --- |
| Flutter | [arm64 debug 测试归档](https://github.com/Luck9Star/herdr-pocket/actions/runs/42208702281/artifacts/13498293296) | `0e71db3d2e8bb3799cf5ace33ecf6bf5c5639ed53c62302e57bfd0a2c0166fab` |
| Tauri | [arm64 debug 测试归档](https://github.com/Luck9Star/herdr-pocket/actions/runs/42208702281/artifacts/13498208754) | `f9c75e2608b67afa0ec31b03a687740bb1a6d5a08df322cfbe8449da9512a59f` |

解压 ZIP 后保留 `app.apk`、`report.json` 与来源声明，按[测试步骤](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/22-mobile-terminal-tabs.md#新包的手机验收步骤)验收。当前目标 API 35、arm64-v8a；归档保留至 2026-11-20。包保留调试符号以核对原生字节，大小不代表正式版本；没有发布 Release 或商店版本。

本批 Flutter 真实 widget 经隔离 OpenSSH 和 herdr 0.9.5，已走通 **配对审查 → 主机／会话看板 → 选定 pane → 持续观察 → 隐藏后保留同一 SSH 并显式恢复 → 主动停止**。远端输入为 0，共享 PTY 始终 119×40。签名使用 runner 生成的临时测试身份，catalog 与 journal 为测试替身；这是 Ubuntu headless 证据，不是 Android 安装、KeyStore 或真实组网结果。Flutter analyzer、182 项常规测试、10 项绘制回归通过；1 项 opt-in SSH 用例在常规 suite 跳过后单独执行通过。[原始脱敏 manifest](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/evidence/mobile-pair-gui/mobile-tabs-flutter-ssh-20261106.json) · [构建与下载核对](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/evidence/mobile-pair-gui/mobile-tabs-ci-final-20261106.json)

| 范围 | 已有结果 | 尚待验证或实现 |
| --- | --- | --- |
| 设计 | Penpot v2 保存 30 个画板，包含新版配色、配对、终端、网络与迁移流程 | 真机交互、无障碍及实测反馈 |
| 配对与密钥 | 两套 GUI 源码接入审查、设备密钥和恢复；本批 Flutter 隔离链路通过 | 当前包的设备存储、相机、锁屏与重启恢复 |
| 看板与观察 | full/delta、独立标签、隐藏暂停、同 SSH 显式恢复及主动停止 | 下一批会话状态订阅；长期运行和真实设备生命周期 |
| 输入与迁移 | 受保护输入、加密配置迁移和网络偏好已有实现；未知结果不重放 | 真实中文 IME、快捷键、TUI、触控；按目标隔离未知记录 |
| 原生网络 | EasyTier 三桌面参考桥与隔离生命周期有记录；两 Android 包完成原生接线和静态校验 | 当前包原生加载、真实节点／SSH、Tailscale／ZeroTier 与逐平台并发 |
| 分发 | 同源两份 debug 包已下载核对 | 安装、签名、真机运行和五端支持分别验收 |

历史 `040eb26` 两路线 Android API 35 云模拟器的配对／观察闭环及 Tauri 两笔受保护输入证据单独保留，不外推到本批设备运行。[历史手机结果](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/18-mobile-network-profiles.md) · [设计与覆盖](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/design/README.md) · [配对与设备密钥](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/14-mobile-pairing-workbench.md) · [终端绘制与 EasyTier 移植修复](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/10-blocker-repair.md)

下一批优先手机看板的持续状态更新，再补按目标隔离的未知输入记录与 Tailscale／ZeroTier 原生桥；这些后续改动不包含在本次 `546c3eb` 包中。桌面分屏紧随手机闭环。两路线使用相同字体与 fixture，先判断正确性，再比较性能和维护成本，框架尚未定案。断线或结果未知不自动重放输入，布局不隐式修改远端共享 PTY。[产品设计](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/05-product-design.md) · [云构建与分发](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/07-build-and-release.md)
