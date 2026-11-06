# 手机输入、恢复与配置迁移

2026-11-06。本批基于 Android 配对与持续观察的已验收版本继续开发，保留两条五端候选。手机输入、组合键、隐藏恢复与配置迁移已接入两套 GUI。Tauri API 35 的只读与受保护输入用例通过，Flutter 最新普通 APK 构建和回归通过，Android GUI 仍有失败。完整来源、摘要和三轮结果见[批次记录](evidence/mobile-pair-gui/input-config-builds.json)。

## 已接入产品入口

- 手机终端展示已核对的主机回执，包括请求 ID、pane、稳定 terminal ID 与受理字节数。观察、逐键和草稿使用同一输入许可；离焦、隐藏与停止会撤销许可。
- 两条路线提供 Ctrl、Alt 的保持、组合与取消，显式选择一次基础键后释放。组合键状态与输入法组合文字分别处理。方向键遵循终端报告的光标键模式，编辑草稿通过预览确认后发送。
- 已提交草稿从可发送区域移出。主机明确拒绝时可保留草稿，结果未知时锁定输入。重新查看原目标的新 full 后，还需人工确认才能继续。窗口与软键盘布局变化沿用共享 PTY 尺寸约束。
- 主机看板接入加密导出与导入审查，迁移所选公开定位和网络类型元数据。新记录取得新的本机 ID，设备独立配对；替换旧配对记录时保留原目标和密钥引用，退役停用后供撤销核查或明确清理。

配置文件格式、库、上限与系统文件通道见[迁移实现规格](../validation/config-transfer/README.md)。网络 profile 参数与 UI 偏好尚待对应产品模型接入，当前迁移入口覆盖主机资料。

## 本地实际证据

Mac 上的生产 Rust 传输适配器通过自建 loopback SSH 验证了两种写入故障。每次新连接先消费 full，再进入生产输入路径。临时密钥只用于测试账号和端口，没有操作真实授权文件。

| 用例 | 观察与结果 |
| --- | --- |
| 主机收到输入但丢失回执 | 返回 Unknown；重开 journal 后错误目标不能确认，原目标在明确确认前不能写，确认后没有自动重放 |
| 主机回执匹配但本机记录损坏 | 保留受理回执并返回 RecoveryLocked；旧许可失效，重新打开的损坏存储继续拒绝确认和写入 |
| 加密文件 | Rust 加密字节与独立 Python 样例一致；错误口令、篡改、长度、版本和秘密字段拒绝 |
| 导入事务 | 旧版目录可读；过期 revision、重叠替换、容量和提交故障受到检查；原配对身份独立保留 |
| Apple 文件 I/O | 共享 Swift 和 Tauri 完整链接通过；自建临时文件的后台协调读写、取消门禁与主线程回调通过 |
| 浏览器界面 | 实际看板入口在 360px 无整页横向溢出；模拟原生依赖的表单与冲突预览在 360px／800px 均无溢出，修复单选按钮与预览焦点；只作界面证据。本次浏览器和服务已关闭 |

完整 Rust 本地回归为 transport 29 项加 CLI 1 项，Tauri 原生 9 项；Tauri JavaScript 52 项及前端构建通过。Python harness 为 26 项，Flutter Android 准备／证据门禁为 36 项，Flutter 工具为 8 项。首次并行运行出现短暂文件锁竞争。测试进程 fork/exec 期间可能继承尚未关闭的描述符，现采用有界等待核验释放；完整重跑通过。

Flutter 在 `007e20d` 的云回归中通过 analyzer、100 项单元／widget 测试和 10 项渲染测试，另有 1 项 opt-in SSH widget 测试跳过。加密互读和迁移回归包含在上述测试中。Android GUI 结果见下文。

### 首轮结果与定向修复

[集中运行 42141054727](https://github.com/Luck9Star/herdr-pocket/actions/runs/42141054727) 的 Tauri Android 两种主机用例通过。原版接收 0 字节；扩展候选在隐藏后主动恢复同一目标、预览确认草稿，收到两笔匹配回执和精确的 10 字节。814 次共享 PTY 取样均为 119×40，最大采样间隔 97ms，未观测到尺寸变化。临时授权已撤销，进程与密钥已清理。[原版报告](evidence/mobile-pair-gui/gui-8daf1bc/tauri-android-stock.json) · [受保护输入报告](evidence/mobile-pair-gui/gui-8daf1bc/tauri-android-guarded.json)

[Tauri ARM64 普通测试包](https://github.com/Luck9Star/herdr-pocket/actions/runs/42141054727/artifacts/13466854945) 的源码为 `8daf1bc`，APK SHA-256 为 `2dcfa4474655e5f80604612cb183b35dac24ba1e248037d1dc1e7f57aa1b7828`。已核对包内 ABI、三份原生声明、终端与配置样例摘要及校验和。

同批 Flutter 的 `inputGate` 初始化出现循环类型推断，阻断应用编译及 GUI 用例。脱离页面的 50 项测试实际通过，包括配置加密样例互读与 12 项迁移测试；13 个依赖页面的测试文件无法加载。修复提交 `226b101` 显式声明类型，[定向运行 42143460447](https://github.com/Luck9Star/herdr-pocket/actions/runs/42143460447) 产出普通 APK。该轮测试为 98 通过、1 跳过、1 失败，analyzer 有 3 项冗余导入提示，渲染 10 项通过。失败 widget 的配对时钟与目录时钟不一致；原版 AVD 停在响应审查，受保护 AVD 停在逐键输入。

`007e20d` 统一配对时钟、清理导入并调整真实终端焦点驱动，[运行 42147341123](https://github.com/Luck9Star/herdr-pocket/actions/runs/42147341123) 的 analyzer 无诊断，100 项测试和 10 项渲染回归通过，1 项跳过。普通 APK 构建成功；原版 AVD 在 `response_authorized` 等待超时，临时主机已批准请求，手机侧接受响应和后续 SSH 尚未完成。该轮受保护 lane 在 harness 前被“存在设备”保护拒绝，缺少 GUI 报告；日志未记录设备 serial 和归属，保持未运行状态。[原版失败报告](evidence/mobile-pair-gui/gui-007e20d/flutter-android-stock.json) · [安全阶段诊断](evidence/mobile-pair-gui/gui-007e20d/flutter-android-test-failure.json)两轮定向运行均整体失败。

[最新 Flutter 普通 APK](https://github.com/Luck9Star/herdr-pocket/actions/runs/42147341123/artifacts/13472225200) 来自 `007e20d`，SHA-256 为 `22d29a726ecc63c0e7e6cb50815fdf3f1fdc350dc6e46187f11c6efffdb0ccfa`。下载 artifact 后解开 `flutter-appmain-package/flutter-android-debug.zip` 取得 `app-debug.apk`。已核对来源、两份共享样例、包校验和、三种 ABI 及字体的 35 份文件，其中 32 份是本批新增来源／声明。Tauri APK 来自较早的 `8daf1bc`，两包各自保留实际源码版本，性能对照需另取同源构建。

Mac 另运行独立标识的 Tauri 应用，实际打开原生选择器并验证取消后回到“未选择文件”。正向导入在本次自动化中未完成，随后观察服务返回 ScreenCaptureKit 错误；原因待定位。已退出应用，并按确切可执行文件检查进程结束。[Mac 记录](evidence/mobile-pair-gui/macos-config-picker.json)

## 本批云端验收

原版 herdr 用例保持零输入。扩展候选主机用例在同一 API 35 基线中依次执行单键 `k`、保留草稿并隐藏标签、回到原目标取得新 full、预览确认 `Pocket测`。两笔回执需要不同请求 ID，并与主机独立快照对应。临时终端最终必须恰好收到 10 个 UTF-8 bytes，不附加回车，不包含隐藏或停止后的试探按键。两种主机使用独立 AVD 和证据目录。

Flutter 普通 `app.main` APK 与集成测试变体分开，Tauri 手机 arm64 包与模拟器 x86 包各有来源。每条路线复用已准备的 SDK 和工程；公开测试包清单需同时记录共享终端、配置迁移样例和实际 APK 的摘要。本批不创建正式 Release。

## 后续顺序

先修正 Flutter 手机授权与测试驱动的具体失败，将修复并入下一批集中验收；随后验证系统文件选择器的完整交互及跨候选文件搬运。真实手机 IME、触控、摄像头、iOS 安装与三网并发继续单列未验证。随后接入完整网络 profile／偏好迁移和前台跨网络标签，再完善桌面真实分屏与独立焦点，最后以正确性与设备性能收敛框架。

Tauri 的 macOS 文件桥编译目标与包最低版本统一为 11.0。Android、iOS 和 macOS 系统选择器已有接线；物理设备及云文件提供方仍需实测。iOS 强杀或崩溃后的临时加密导出残留清理仍待完成。Windows/Linux 文件控件与下载路径也需要独立系统验收。

## 云运行后的源码修复

本轮未追加 Actions。Flutter 配对页改为先核验候选状态，待目录 CAS 保存成功后才发布授权状态。保存回复丢失、审查期间离页或取消时，旧页锁定并要求重新读取；晚到的设备身份回调也需匹配当前对象。新增 3 项 widget 回归定义，覆盖保存未知、迟到提交和窄屏编辑结束后的真实确认控件，这些新用例尚待下一批 Flutter 执行。

Android 驱动先结束响应编辑，再核对真实来源复选框与接受按钮，并以固定阶段区分拒绝、保存未确认和页面失效。`007e20d` 的 `response_authorized` 超时根因仍待后续实测定位，当前源码审查发现的状态提交问题独立记录。

模拟器包装脚本保留既有设备拒绝规则，在自启进程退出后有界等待对应 ADB serial 消失。查询或注销未确认会使成功用例转为失败，原失败码保留。5 项隔离假命令测试通过，覆盖延迟注销、超时、查询失败和既有设备保护，真实 AVD 需随下一批验证。更新后 Python harness 共 31 项通过，Flutter Android 门禁 36 项通过；Flutter 新源码语法检查与工具 8 项通过。
