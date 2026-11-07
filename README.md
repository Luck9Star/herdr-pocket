# herdr-pocket

herdr-pocket 是手机优先的远端 herdr 图形客户端原型，目标覆盖 iOS、Android、Windows、macOS 和 Linux。手机从配对和主机看板进入完整终端，桌面共享信息模型并提供分屏。项目独立于 herdr 官方；具体许可证待依赖与分发审查后确定。

**当前进度 · 2026-11-07**　Flutter 与 Tauri 的手机 GUI 均已在 Android API 35 x86_64 云模拟器走通配对审查、设备密钥 SSH 认证、看板、选定 pane 的持续观察与停止。主机摘要支持当前、单次及上次快照，按来源保留会话和最后同步时间。[原型分支](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation) · [验证记录与测试步骤](https://github.com/Luck9Star/herdr-pocket/blob/e6d2fc5903adc78f3cf5642a7e4bc3ed0f75ad22/docs/34-mobile-host-task-summary.md)

**最新测试包 · 源码 `e54f23c`**　[7 项云任务全部通过](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342)。两份 arm64 debug APK 已实际下载，归档 digest、APK SHA-256、来源提交、ABI 和两份包内 EasyTier／Tailscale 库已与独立原生归档核对。

| Android 测试路线 | 下载 | 解压后的 app.apk SHA256 |
| --- | --- | --- |
| Flutter | [arm64 debug 测试归档](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342/artifacts/13556637167) | `aad0a4e04b28650dec872a29d4b554a6993350f614b5ae3c8982e5c8581ce994` |
| Tauri | [arm64 debug 测试归档](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342/artifacts/13556314095) | `2217b6d7033e68bb3f9632861efd4597c20a6ec8ae02c56084aab822b2c0a3a6` |

登录 GitHub 后点击上表的测试归档；匿名访问下载端点返回 401。解压后核对 `app.apk` 哈希，保留 `report.json`、校验和及来源声明。归档在北京时间 2026-11-21 10:26／10:27 到期。测试包面向 API 35、arm64-v8a；本轮设备验收使用同源 x86_64 调试构建。物理设备安装和正式分发仍待后续验收。[下载与设备验收步骤](https://github.com/Luck9Star/herdr-pocket/blob/e6d2fc5903adc78f3cf5642a7e4bc3ed0f75ad22/docs/34-mobile-host-task-summary.md)

Flutter analyzer、286 项常规测试和 10 项绘制回归通过，常规套件跳过的 1 项 SSH 用例已单独执行。Tauri JavaScript 149 项、共享 Rust transport 95＋1 项通过。前两轮暴露的手工重连测试、跨目标草稿确认及 Android 构建问题均保留在记录中。[完整数据及失败记录](https://github.com/Luck9Star/herdr-pocket/blob/e6d2fc5903adc78f3cf5642a7e4bc3ed0f75ad22/docs/evidence/mobile-pair-gui/host-board-cloud-20261107.json)

Flutter 真实 widget 经隔离 OpenSSH/herdr 验证了同一 SSH 连接上的隐藏和显式恢复。实测收到 7 帧，其中 5 个 delta；两次本地视口变化中远端输入为 0，234 次采样的共享 PTY 始终是 119×40。两套云模拟器另行验证了应用端设备密钥、配对和只读观察。[Flutter 隔离 SSH](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342/artifacts/13555994060) · [Flutter AVD](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342/artifacts/13556572172) · [Tauri AVD](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342/artifacts/13556263219)

| 范围 | 已有结果 | 尚待验证或实现 |
| --- | --- | --- |
| 设计 | Penpot v2 已保存 38 个画板，重载核对到 212 个交互对象。新增 S31–S38 覆盖手机草稿找回、观察恢复和设备操作待核实。[打开新版手机原型](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=2a5fd934-a163-8057-8008-e8230835dfbd) | 手机触控、输入法和无障碍仍需真机验收 |
| 配对与密钥 | 两套 GUI 在 API 35 x86_64 云模拟器经设备密钥完成 SSH 认证。Flutter 签名、删除及删除后拒绝读取均通过 | arm64 物理设备、相机扫码、锁屏与重启恢复 |
| 看板与观察 | 按主机展示受阻／未知数与旧快照，选定 pane 后持续观察。Flutter 的隔离 SSH 还验证隐藏和显式恢复 | 物理设备长时间运行、各平台生命周期 |
| 输入与迁移 | 受保护输入、按目标隔离的未知记录、加密配置迁移；未知结果不重放 | 真实中文 IME、快捷键、TUI、触控及键盘变化 |
| 原生网络 | 两包包含 EasyTier＋Tailscale，原生与手机接线完成构建／静态核对；EasyTier 桌面移植有历史记录 | 真实节点／SSH、Android 动态加载、逐平台并发 |
| ZeroTier 后续源码 | ECC 未定义左移已修复；共享设备 owner／多网络租约和 AndroidKeyStore 包装；115 项 manager、36＋151 项 JVM 检查，以及 Mac 114 TU 整库／离线初始化通过 | 定向 socket、JNI、GUI 和实际节点仍未接通；设备 KeyStore 与逐平台运行未验证 |
| 分发 | 同源两份 arm64 debug 包完成构建和下载校验，x86_64 云模拟器完成安装与实际运行 | arm64 真机、正式签名及五端支持分别验收 |

本批两份 APK 集成 EasyTier 与 Tailscale，ZeroTier 设备管理仍在独立验证中。Mac 整库和离线初始化的历史验证见[固定来源与范围](https://github.com/Luck9Star/herdr-pocket/blob/98473a699a055006e60b8c5c92ecdd54a28c13d3/docs/29-zerotier-managed-device.md)。[上一批 `750798fe` 双网络包与校验和](https://github.com/Luck9Star/herdr-pocket/blob/b2c652876d33c9973dbf5af67465dd7fb4c0259f/docs/27-mobile-tailscale-cloud.md)

历史 `040eb26` 云模拟器结果、`546c3eb` 独立标签包与各次失败保留原 SHA 和范围，不外推为本批设备运行通过。[历史手机结果](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/18-mobile-network-profiles.md) · [前一测试包](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/22-mobile-terminal-tabs.md) · [Penpot 设计与覆盖](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/design/README.md) · [配对与设备密钥](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/14-mobile-pairing-workbench.md) · [终端绘制与 EasyTier 移植修复](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/10-blocker-repair.md)

**原型分支后续进度**　Flutter 已修正重复点击当前输入模式打断组字的问题，新增的 3 个 widget 场景待云端运行。Tauri 刚配对的表单和已存主机标签已在 Mac Chrome 的 390×844 视口验证首次可编辑焦点、许可前组字不发送、许可后中文提交一次。本地 159 项 JavaScript 检查和前端构建通过。这些改动将在下一批集中构建时进入 APK。[键盘与组字验证](https://github.com/Luck9Star/herdr-pocket/blob/694b5431760440548c6feac10fefc02713950f12/docs/35-mobile-input-focus.md)

手机下一步在云模拟器验证输入与恢复，将结果反馈到 Penpot。真机触控、相机与实网切换单列验收。Flutter 与 Tauri 仍保留为候选。桌面分屏随后验收。[本批实现与未验证项](https://github.com/Luck9Star/herdr-pocket/blob/e6d2fc5903adc78f3cf5642a7e4bc3ed0f75ad22/docs/34-mobile-host-task-summary.md) · [云构建与分发](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/07-build-and-release.md)
