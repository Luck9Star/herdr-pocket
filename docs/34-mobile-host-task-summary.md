# 手机主机摘要与持续观察

两套 GUI 从已经核验的会话快照生成主机摘要。在手机上打开主机前可以看到原会话、最后同步时间、已知受阻数和状态未知的窗格数。一个主机重复开标签只显示一份报告。终端全帧和增量帧只更新画面，不刷新会话快照时间。

| 用户动作 | 预期可见结果 |
| --- | --- |
| 首次打开主机列表 | 未收到快照时显示任务状态未知。收到经核验的空快照后才能显示已确认为空。 |
| 审查设备配对响应并主动连接 | 显示来自所选主机、固定公钥和命名会话的摘要。持续更新有效且已确认受阻的主机优先。同级保持目录顺序。 |
| 在 Tauri 从新配对表单直接选 pane | 表单收到一次快照，提示持续更新不可用。选 pane 后继续接收终端画面，摘要标记为上次报告。已保存终端标签支持持续看板。 |
| 隐藏、停止或断开 | 保留上次数量、原会话及时间。返回原标签时先显示旧状态，显式恢复后等待相同目标的新快照和终端全帧。 |
| 更换设备身份、网络配置或删除主机 | 原摘要不能归到新身份或新网络，迟到的旧回调不能恢复为当前。 |

上述表格记录原批行为；新配对表单持续看板的候选修复和本地验证见[新配对后的持续会话看板](39-mobile-paired-dashboard.md)。

## 验收

1. 在测试设备上新增测试主机，核对设备公钥和主机指纹，经 helper 确认后导入响应，再主动连接。
2. 在连接页核对原会话、同步时间和受阻数。含未知状态的窗格应单列；仅在全部状态已知时才能显示确切的受阻总数。
3. 打开一个 pane，观察持续画面。切回主机列表，核对上次报告，再返回原标签显式恢复。终端恢复前保持观察模式，旧输入不自动发送。
4. 重复开同一主机的标签、缩窄窗口或打开系统键盘，检查主机统计没有翻倍，远端共享 PTY 尺寸保持原值。

本批连同手机草稿找回、看板时间及两条 GUI 的入口回归一起验证。云构建使用同一 Git 提交产生两份 arm64 debug APK；API 35 x86_64 模拟器另行走真实设备密钥与隔离 SSH。前台真实三网、物理设备、系统中文输入法及 iOS 签名仍待逐项验收。既有 Android 测试包和上一轮验证可见[固定来源与校验和](27-mobile-tailscale-cloud.md)。

## Android 测试包与实测

源码 `e54f23c` 的 7 项云任务全部通过。两份 arm64-v8a debug APK 及独立原生归档已实际下载。归档 digest、包内校验和、源码提交和 APK 哈希已核对；两份 APK 的 EasyTier 和 Tailscale 库分别与独立原生归档内容一致。[完整 CI](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342) · [验证数据](evidence/mobile-pair-gui/host-board-cloud-20261107.json)

| APK | 解压后的 app.apk SHA-256 |
| --- | --- |
| [Flutter arm64](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342/artifacts/13556637167) | `aad0a4e04b28650dec872a29d4b554a6993350f614b5ae3c8982e5c8581ce994` |
| [Tauri arm64](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342/artifacts/13556314095) | `2217b6d7033e68bb3f9632861efd4597c20a6ec8ae02c56084aab822b2c0a3a6` |

两归档在北京时间 2026-11-21 10:26／10:27 到期。下载后解压，按上表核对 `app.apk`，在单独的 Android arm64 测试设备上安装，再执行上面的验收步骤。安装条件和实际设备型号请单独记录。

- 两条 API 35 **x86_64 云模拟器**分别使用应用端设备密钥和临时主机授权，经 SSH 走通配对、主机看板、选择 pane、full/delta 持续观察和主动停止。两端远端输入均为 0，结束后应用和模拟器已关闭。Flutter 还在真实 AndroidKeyStore 包装的密钥上完成签名、删除和再次读取被拒的验证。[Flutter AVD](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342/artifacts/13556572172) · [Tauri AVD](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342/artifacts/13556263219)
- Flutter 的 Ubuntu 隔离 SSH 测试还验证了返回列表时保留旧摘要、恢复原标签时使用同一连接、等新快照才恢复当前状态。共 7 帧，其中 5 个 delta；两次本地视口变化，234 次采样中共享 PTY 始终 119×40。此路使用测试 signer。[隔离 SSH 证据](https://github.com/Luck9Star/herdr-pocket/actions/runs/42328109342/artifacts/13555994060)
- Flutter analyzer、286 项常规测试、10 项绘制回归通过。常规套件跳过的 1 项 SSH 用例在独立步骤通过。Tauri JavaScript 149 项、共享 Rust transport 95＋1 项通过。模拟器执行 stock 只读场景；当前 arm64 真机安装、物理键盘／中文 IME、相机扫码及三网并发仍未验证。

下载 Actions 归档时请先登录 GitHub。公开仓库允许匿名查看本次构建记录；实际核查中，匿名读取 ZIP 返回 401。

新一批手机源码已修正键盘首次焦点与重复点模式打断组字的问题，Mac 浏览器及本地验证见[手机终端键盘与组字](35-mobile-input-focus.md)。上表两份 APK 对应修复前的源码。下一批云任务将验证输入与恢复，再据此调整 Penpot 终端和键盘状态、比较两候选。

## 前两轮失败与修复

首轮源码为 `c1c040a`。同一提交的隔离副本在 Mac 上通过 149 项 Tauri JavaScript 检查、前端构建和 31 项远端测试驱动单测。Flutter 的 63 个 Dart 文件通过本地语法解析。[提交](https://github.com/Luck9Star/herdr-pocket/commit/c1c040a47712f1e000e2c73aa8356bf69b7dec99)

云端 Flutter analyzer 和 10 项绘制回归通过。常规测试为 281 项通过、1 项跳过、2 项失败，后续的隔离 SSH 测试被跳过。两个失败用例在模拟手工重连时没有重新填写已经清除的临时凭据，适配器只收到了首次连接。API 35 上，Tauri 在生成的 Kotlin 代码编译阶段失败，模拟器未启动。Flutter 测试驱动报 `flutter_android_public_signer_read_failed`，未取得签名探针，主机未授权。[首轮记录](https://github.com/Luck9Star/herdr-pocket/actions/runs/42325603861)

首轮原生库、共享 transport 和 Flutter arm64 构建通过，Tauri arm64 构建失败。修复批让每次手工重连重新填写合成凭据并完成审查，按收到的全帧核对输入日志读取次数。Android 构建将顶层 Java 同步到独立源码目录，Kotlin 的构建输入由此排除了 JVM 测试用的平台桩。Flutter 模拟器驱动先确认测试应用已安装，再读取有界的公开结果文件；首轮没有记录底层 ADB 诊断。

第二轮 `1ba655e` 已通过重连后的看板时间检查。另一个用例成功进入替换后的终端，发现编辑新目标草稿会让旧草稿的清除按钮失效。清除审查现按原目标、可见文字和该草稿的版本核对，其他目标的编辑可独立进行。Android Gradle 插件拒绝直接注册目录 Provider，改为注册具体目录并保留对同步任务的显式依赖。此轮 Flutter 模拟器的测试进程在应用安装前退出。[第二轮记录](https://github.com/Luck9Star/herdr-pocket/actions/runs/42327077924)
