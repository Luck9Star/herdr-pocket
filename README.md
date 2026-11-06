# herdr-pocket

herdr-pocket 是手机优先的远端 herdr 图形客户端原型，目标覆盖 iOS、Android、Windows、macOS 和 Linux。手机从配对和主机看板进入完整终端，桌面共享信息模型并提供分屏。项目独立于 herdr 官方；具体许可证待依赖与分发审查后确定。

**当前进度 · 2026-11-07**　Flutter 与 Tauri 两套手机 GUI 已接入配对审查、设备密钥、持续会话看板、独立终端标签、按目标隔离的未知输入，以及 Tailscale 本机身份与显式登录。本页对应公开原型验证阶段，框架尚未定案。[原型分支](https://github.com/Luck9Star/herdr-pocket/tree/codex/core-prototype-validation) · [本批验证和失败记录](https://github.com/Luck9Star/herdr-pocket/blob/b2c652876d33c9973dbf5af67465dd7fb4c0259f/docs/27-mobile-tailscale-cloud.md)

**最新测试包 · 源码 `750798fe`**　两份 Android arm64 debug APK 已重建，[CI 五个 job 全部成功](https://github.com/Luck9Star/herdr-pocket/actions/runs/42247482105)。两份归档均已实际下载，核对 ZIP／APK 哈希、来源提交、ABI、JNI、动态依赖，以及包内 EasyTier／Tailscale 与独立来源包的原生库字节。

| Android 测试路线 | 下载 | 解压后的 app.apk SHA256 |
| --- | --- | --- |
| Flutter | [arm64 debug 测试归档](https://github.com/Luck9Star/herdr-pocket/actions/runs/42247482105/artifacts/13519144162) | `a82ba20373b978148c3e4e79578762f15fe70db506b042302ba22bba8688d856` |
| Tauri | [arm64 debug 测试归档](https://github.com/Luck9Star/herdr-pocket/actions/runs/42247482105/artifacts/13518524214) | `c9d29debe48e7766938b0e7b9586ceb5d0507bce96194bc58bcc0063be6b5edf` |

解压 ZIP 后保留 `app.apk`、`report.json`、校验和与来源声明，按[测试步骤](https://github.com/Luck9Star/herdr-pocket/blob/b2c652876d33c9973dbf5af67465dd7fb4c0259f/docs/27-mobile-tailscale-cloud.md#手机验收步骤与后续顺序)验收。目标 API 35、arm64-v8a；归档保留至 2026-11-20 16:06／16:08 UTC（北京时间 11 月 21 日凌晨）。调试符号使 APK 约为 484／591 MB，体积不代表正式版本。没有创建 Release、tag 或提交商店。

Flutter analyzer、248 项常规测试和 10 项组合重音绘制回归通过；1 项 opt-in SSH 用例在常规 suite 跳过后单独执行通过。共享 Rust transport 95＋1、Tauri JavaScript 115 通过，两路线 Android target 编译通过；Tauri Rust 测试 suite 未在本批重复执行。首轮 `42243620730` 的 GCC、Flutter analyzer 和测试失败及修复均保留，不用最终成功覆盖失败历史。[完整构建核对](https://github.com/Luck9Star/herdr-pocket/blob/b2c652876d33c9973dbf5af67465dd7fb4c0259f/docs/evidence/mobile-pair-gui/mobile-tailscale-ci-20261107.json)

Flutter 真实 widget 经自建 OpenSSH/herdr 已走通 **配对审查 → 主机／会话看板 → 选定 pane → 持续观察 → 隐藏后保留同一 SSH 并显式恢复 → 主动停止**。远端输入为 0，共享 PTY 始终 119×40。签名和存储使用明确的测试替身；这是 Ubuntu headless 隔离链路证据，当前 APK 的 Android 安装、KeyStore 和真实组网仍未验证。[原始隔离 manifest](https://github.com/Luck9Star/herdr-pocket/blob/b2c652876d33c9973dbf5af67465dd7fb4c0259f/docs/evidence/mobile-pair-gui/mobile-tailscale-flutter-ssh-20261107.json)

| 范围 | 已有结果 | 尚待验证或实现 |
| --- | --- | --- |
| 设计 | Penpot v2 保存 30 个画板，包含新版配色、配对、终端、网络与迁移流程 | 真机交互、无障碍及实测反馈；本批没有新画板 |
| 配对与密钥 | 两套 GUI 接入审查、设备密钥和恢复；Flutter 隔离链路通过 | 当前包的 Android KeyStore、相机、锁屏与重启恢复 |
| 看板与观察 | 持续会话状态、full/delta、独立标签、隐藏暂停、同 SSH 显式恢复及停止已进入新包 | 长期运行和真实设备生命周期 |
| 输入与迁移 | 受保护输入、按目标隔离的未知记录、加密配置迁移；未知结果不重放 | 真实中文 IME、快捷键、TUI、触控及键盘变化 |
| 原生网络 | 两包包含 EasyTier＋Tailscale，原生与手机接线完成构建／静态核对；EasyTier 桌面移植有历史记录 | 真实节点／SSH、Android 动态加载、逐平台并发 |
| ZeroTier 后续源码 | 单设备身份托管、固定来源与原生安全补丁；151 JVM 检查、6 个翻译单元编译和 4 个离线程序通过 | 上游 ECC shift 诊断未解决；manager、KeyStore 包装、JNI、GUI 和实际节点尚未接入 |
| 分发 | 同源两份 debug 包已下载核对 | 安装、签名、真机运行和五端支持分别验收 |

**ZeroTier 基础代码不在上述 APK 中。** [后续源码与证据](https://github.com/Luck9Star/herdr-pocket/blob/b2c652876d33c9973dbf5af67465dd7fb4c0259f/docs/28-zerotier-native-foundation.md)保留 ECC 文件的 UBSan 局部排除，不能称完整 UBSan 或实际节点运行通过。严格 transport Clippy 另有 12 项已有诊断。五个平台、三种网络及并发矩阵继续逐格验收。

历史 `040eb26` 云模拟器结果、`546c3eb` 独立标签包与各次失败保留原 SHA 和范围，不外推为本批设备运行通过。[历史手机结果](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/18-mobile-network-profiles.md) · [前一测试包](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/22-mobile-terminal-tabs.md) · [Penpot 设计与覆盖](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/design/README.md) · [配对与设备密钥](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/14-mobile-pairing-workbench.md) · [终端绘制与 EasyTier 移植修复](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/10-blocker-repair.md)

下一批先消除 ZeroTier ECC 诊断边界，再完成单设备 owner、多网络租约、定向 socket 与 Android／手机 GUI 接线，积累一批功能后集中验证。桌面分屏紧随手机闭环。两路线使用相同字体与 fixture，先判断正确性，再比较性能和维护成本；断线或结果未知不自动重放输入，布局不隐式修改远端共享 PTY。[产品设计](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/05-product-design.md) · [云构建与分发](https://github.com/Luck9Star/herdr-pocket/blob/codex/core-prototype-validation/docs/07-build-and-release.md)
