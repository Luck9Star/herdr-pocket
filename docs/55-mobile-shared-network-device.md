# 手机上审查 ZeroTier 共享设备

2026-11-08。Flutter 和 Tauri 都能从手机首页的「网络配置」进入共享设备审查，查看同一个 ZeroTier 设备身份关联了哪些网络和主机。公开测试包来自 `dd02595`，本页记录的 GUI 改动来自后续提交 `542c0db`。[Android 下载与配对观察实测](53-mobile-connection-diagnostics.md) · [手机端源码](https://github.com/Luck9Star/herdr-pocket/commit/542c0db6c6d2c5323d466051d5ffd628f843a9cf)

## 手机能看到什么

| 当前情况 | 页面和操作 |
| --- | --- |
| 公开目录已读，设备服务未绑定、锁定或读取失败 | 显示已核对的相关网络和主机，包含停用配置与旧版 ZeroTier 主机标签。设备状态显示未知，用户可刷新或返回。 |
| 主机或网络目录尚未就绪 | 影响范围显示未知。待重新取得完整目录后才显示数量和名单。 |
| 已绑定的存储报告待定操作 | 页面列出原记录和当前阶段。用户可以按阶段审查恢复或放弃。写入前重新核对范围和原记录。若回执不明，只读回当前状态，原操作不会自动重放。 |
| 希望移除已有身份 | 需要原设备身份、完整影响范围和相关连接的停止证明。当前两条普通入口均禁用缺少停止证明的移除操作。关闭标签保留主机授权与设备记录。 |

默认 Android 构建具备元数据服务与加密存储代码，尚未绑定 ZeroTier 原生身份引擎。用户在该版本可以从公开目录看到影响范围，实际创建可入网身份和连接 ZeroTier 仍待接入。手机专属 **SSH** 设备密钥仍通过已有配对入口创建，两类身份独立保管。[设备存储接口](../validation/network-profiles/native/android/ZeroTierAndroidStore.md) · [手机 SSH 配对流程](45-mobile-pairing-handoff.md)

新版 Penpot 的「完整影响范围」卡片可进入两张状态页。第一张列出仍可核对的关联主机和网络，第二张在目录读取受阻时提供「重新读取」。独立预览中完成 10 次点击，验证了禁用操作、重新读取、返回、原有确认路径和重载后的入口。[打开交互原型](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da&section=interactions&frame-id=2a5fd934-a163-8057-8008-e823088d7aeb) · [画板与点击记录](../design/evidence/mobile-network-device-impact-20261108.json)

## 已运行的检查

| 环境 | 结果 |
| --- | --- |
| Mac Chrome，320 × 740、390 × 740 CSS px | 通过正常网络配置入口打开实际编译的 Tauri 页面。模拟设备服务缺失或读取失败，两种宽度下均能列出两份网络、两台主机；主机目录读取失败时均显示未知。模拟一次恢复已提交但回执丢失，后续刷新未重复写入。关闭后焦点回到网络入口，弹窗和页面横向溢出为 0。原生桥及目录事件为合成数据。 |
| Flutter Kotlin 通道 → 共享 Java 服务 → 存储 | 从本批源码快照编译，在三个独立桌面 JVM 完成 24、18、19 个断言。覆盖普通创建、按原身份删除、活跃租约拒绝删除和两类中断恢复。 |
| Tauri Kotlin 插件 → 同一 Java 服务 → 存储 | 无绑定场景 10 个断言，安装测试存储后的场景 91 个断言。覆盖原身份核验、前后台切换、迟到结果和待定操作恢复。两套宿主均使用测试 Android 接口、临时身份与 JCE provider。 |
| 共享 Java 与公开源码范围 | 加密存储核心 215、Android wrapper 36、共享服务 128 个断言通过。离线 Gradle/JVM 共执行 27 条命令，验证实际同步的 13 个生产文件，包含复用构建目录清除旧源码、拒绝缺失输入及软链。 |
| Mac 原生 ZeroTier 身份 → JNI → Java 存储 | 校验 4,052 个固定来源文件后，仅编译身份算法及测试桥。每次独立运行生成一个临时身份、调用原生校验七次，28 个断言通过。新的存储实例能解密重读，篡改密文与错误实例的删除均被拒绝，显式删除后密钥和临时目录均清空。使用桌面测试 KeyStore，全程没有启动节点。 |
| 其他本地回归 | Tauri 前端 510 项通过，Vite 构建 65 个模块。Tauri 的 Mac Rust 默认特性 67 项通过。两套 GUI 的来源清单读取同一份 Gradle 列表。Flutter 的新 widget 用例、Android Rust 目标编译和 Android 系统 KeyStore 尚未在本批运行。 |

临时浏览器及测试 JVM 已退出，合成身份在各自临时目录中清理。Android 的本地 JVM 测试和设备上的仪器化测试使用不同运行环境。后续设备验收需单独记录硬件状态、锁屏和应用重启行为。[结构化证据](evidence/mobile-pair-gui/shared-network-device-20261108.json) · [Android 本地测试](https://developer.android.com/training/testing/local-tests) · [Android 设备测试](https://developer.android.com/training/testing/instrumented-tests)

## 如何复测

使用已按仓库清单校验的 Kotlin 工具和本机 Gradle，以下命令均从仓库根目录执行。Gradle 输出参数要求一个尚不存在的目录。

```sh
python3 validation/flutter/native/android/tests/run_zerotier_service_bridge_probe.py --kotlin-dir "$KOTLIN_TOOLS_DIR"
python3 validation/tauri/test/android-zerotier-service-plugin-test.py "$KOTLIN_TOOLS_DIR"
sh validation/network-profiles/native/android/tests/run-zerotier-service.sh
python3 validation/network-profiles/native/android/tests/run-production-sources.py --gradle "$GRADLE_BIN" --output "$FRESH_EVIDENCE_DIR"
```

Mac 原生身份试验另需已校验的公共源码缓存。复测说明列有从干净源码导出校验候选、构建并写出结果的命令，产物仅记录计数、清理结果及来源摘要。[原生身份复测步骤](../validation/native/candidates/zerotier/tests/identity-service/README.md)

下一批先编译 Android 原生身份库，并通过手机宿主与 Android 系统 KeyStore 验证创建、重启重读和删除，再验证指定网络上的 SSH 主机核验、看板与持续观察。将本页的不可用与待定操作、看板检索，以及 Flutter 隐藏标签恢复后的十个 TUI 操作并入同一次 Android 构建验收。三种实际网络之间的前台并发按平台分别记录。[观察恢复与手机看板](54-mobile-host-search-and-observer-retirement.md)
