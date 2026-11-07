# herdr-pocket

herdr-pocket 是手机优先的远端 herdr 图形客户端原型，目标覆盖 iOS、Android、Windows、macOS 和 Linux。手机从配对和主机看板进入完整终端，桌面共享信息模型并提供分屏。项目独立于 herdr 官方；具体许可证待依赖与分发审查后确定。

**最新 Android 测试包 · 源码 `a9914fe` · 2026-11-07**　两套路线的 API 35 arm64-v8a debug APK 已构建并实际下载，归档与 APK 哈希、来源和包内 EasyTier／Tailscale 库已离线核对。登录 GitHub 后下载并解压，保留 `report.json` 和校验文件；两包尚未在 arm64 手机上验收。GitHub 显示两份归档于 2026-11-21 12:51（北京时间）到期。[本次集中运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/42339225239) · [原型分支](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation) · [输入与测试步骤](https://github.com/Luck9Star/herdr-pocket/blob/33d416bb949e09069a0de5b61c1534fa2cd79919/docs/36-mobile-paste-and-auxiliary-input.md)

| 路线 | 下载测试归档 | 解压后的 `app.apk` SHA-256 |
| --- | --- | --- |
| Flutter | [arm64 debug 归档](https://github.com/Luck9Star/herdr-pocket/actions/runs/42339225239/artifacts/13561835087) | `dbbf5a01a27ea800fdb0199f3a406a65a0027e4ad7b55754ac9d33639a85e820` |
| Tauri | [arm64 debug 归档](https://github.com/Luck9Star/herdr-pocket/actions/runs/42339225239/artifacts/13561422120) | `0dd3ae7d013ecceb66873b9f032f152a5ea416b206bfa8c6362571fedf493668` |

**Android 手机闭环**　[定向复验 42351694649](https://github.com/Luck9Star/herdr-pocket/actions/runs/42351694649) 的四个 API 35 x86_64 模拟器场景全部通过。Flutter 与 Tauri 都经设备密钥完成配对、SSH、看板、持续观察与停止，两条只读路线远端输入为 0。隐藏后主动恢复，受保护输入夹具在同一目标分别收到 1 和 9 字节，四场景的共享 PTY 始终为 119×40。[逐场记录与复测步骤](https://github.com/Luck9Star/herdr-pocket/blob/33d416bb949e09069a0de5b61c1534fa2cd79919/docs/36-mobile-paste-and-auxiliary-input.md#android-定向复验)

这次定向工作流总状态为失败。Flutter analyzer 报告测试文件的一项多余导入；314 项 unit/widget 和 10 项绘制回归通过，1 项环境限定用例跳过。多余导入已在后续源码中移除，等待下一批 analyzer。初次集中运行中 Tauri 普通观察通过，其他三个模拟器场景失败；两批的运行、SHA 和 artifact 各自保留。[首轮运行](https://github.com/Luck9Star/herdr-pocket/actions/runs/42339225239) · [原始数据](https://github.com/Luck9Star/herdr-pocket/blob/33d416bb949e09069a0de5b61c1534fa2cd79919/docs/evidence/mobile-pair-gui/mobile-paste-20261107.json)

**手机使用与试测**　主机侧确认手机专属公钥后，手机审查连接和主机身份，进入主机看板并选定 pane，开始或停止持续观察。输入提供逐键与草稿；粘贴先审查内容和目标，可追加、替换或取消，发送须另行确认；结果未知时保持锁定，不自动重放。建议先在隔离测试主机按[配对、设备密钥与观察步骤](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/34-mobile-host-task-summary.md)操作，再按[粘贴与辅助键步骤](https://github.com/Luck9Star/herdr-pocket/blob/33d416bb949e09069a0de5b61c1534fa2cd79919/docs/36-mobile-paste-and-auxiliary-input.md)测试。测试包为原型：真机触控、系统剪贴板、输入法、相机、arm64 运行和真实三网并发均待验收，Flutter 和 Tauri 均仍是候选。

[手机原型 · 选择终端文本](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e88156484822) · [手机原型 · 粘贴超限](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=ff7bd149-6597-80a5-8008-e881ed74ebc9)

**原型分支新进度 · 手机选区与复制**　两个 GUI 都已接入只读选区。两套真实终端缓冲区在相同的 10 组字符上复制一致，后续标记的列位置也一致。Tauri 在 Mac 浏览器的两个入口、两种手机视口通过复制与裁剪检查。Flutter 新选区仍待 widget 和手机运行验收。上面的两份 APK 均早于此项改动。[选区实测与复核步骤](https://github.com/Luck9Star/herdr-pocket/blob/6ffab0606ce88f404cada602b8330f0ce69f2411/docs/37-mobile-terminal-selection.md) · [Penpot 四个新增状态](https://github.com/Luck9Star/herdr-pocket/blob/6ffab0606ce88f404cada602b8330f0ce69f2411/design/evidence/v2-mobile-text-and-paste-20261107.json)

## 历史绿批及既有记录

以下记录保留了 `e54f23c` 上一批只读观察和 7 项云任务通过时的下载与验收入口。

**上一批进度 · 2026-11-07**　Flutter 与 Tauri 的手机 GUI 均已在 Android API 35 x86_64 云模拟器走通配对审查、设备密钥 SSH 认证、看板、选定 pane 的持续观察与停止。主机摘要支持当前、单次及上次快照，按来源保留会话和最后同步时间。[原型分支](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation) · [验证记录与测试步骤](https://github.com/Luck9Star/herdr-pocket/blob/e6d2fc5903adc78f3cf5642a7e4bc3ed0f75ad22/docs/34-mobile-host-task-summary.md)

**历史绿批测试包 · 源码 `e54f23c`**　[7 项云任务全部通过](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342)。两份 arm64 debug APK 已实际下载，归档 digest、APK SHA-256、来源提交、ABI 和两份包内 EasyTier／Tailscale 库已与独立原生归档核对。

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

**较早的键盘焦点验证**　Flutter 已修正重复点击当前输入模式打断组字的问题，对应回归已随本批 Flutter 常规套件运行。Tauri 刚配对的表单和已存主机标签已在 Mac Chrome 的 390×844 视口验证首次可编辑焦点、许可前组字不发送、许可后中文提交一次。本地 159 项 JavaScript 检查和前端构建通过。这些改动随后进入了上方 `a9914fe` 集中构建。[键盘与组字验证](https://github.com/Luck9Star/herdr-pocket/blob/694b5431760440548c6feac10fefc02713950f12/docs/35-mobile-input-focus.md)

手机下一步验证系统选区、输入法与生命周期。真机触控、相机与实网切换单列验收。Flutter 与 Tauri 仍保留为候选。桌面分屏随后验收。[本批实现与未验证项](https://github.com/Luck9Star/herdr-pocket/blob/e6d2fc5903adc78f3cf5642a7e4bc3ed0f75ad22/docs/34-mobile-host-task-summary.md) · [云构建与分发](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/07-build-and-release.md)
