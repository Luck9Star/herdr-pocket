# 手机共享设备审查的 Android 宿主接线

2026-11-07，原型分支 `98473a6` 后续工作区。接续[前端与原生草稿记录](30-zerotier-streams-and-device-review.md)，本批接通两套 GUI 的设备元数据命令与共享 Java 存储合同。**尚未提交或生成新 APK；ZeroTier 原生拨号未启用。** 当前 Android 下载仍见[双网络测试包](27-mobile-tailscale-cloud.md)。

后续[待定操作恢复](32-mobile-device-recovery.md)已补齐界面、阶段匹配与新验证记录。本文下列检查数和来源快照保留为本批历史证据，不代表后续修改也已由这些旧日志验证。

## 已实现

- 共享 Java 入口只返回设备记录、待定创建／删除和可用性。一个数据锁内取得完整快照，避免分别读三个字段得到互相矛盾的状态。没有安装固定 native store 时返回不可用，不创建目录或身份；安装后读取错误不会当成“没有身份”。这不是后台 Android Service，也不会启动节点。
- 创建、恢复待定创建、放弃待定创建和移除均为显式操作。普通移除在原 owner／数据锁内校验 handle 与 instanceId；活跃 runtime lease 阻止删除。待定删除须走独立恢复，不能用一次旧的普通删除确认隐式重试。私有身份不进入 Flutter／JS。
- Flutter 新通道校验精确字段、目录版本和全部受影响网络／主机。持有与保存目录相同的文件锁执行操作，排队上限为 8；暂停、关闭或版本变化使尚未派发请求失效。已派发请求继续完成一次，迟到回复报未确认。恢复操作还核对返回 handle 为原请求，不能仅凭 UUID 格式正确宣告成功。
- Tauri 注册严格的状态／写入命令，Rust 在整个操作期间保留目录锁及设备操作租约。Kotlin 单工作线程不排队；支持 Activity 已恢复后才注册插件的情况。明确写出三个 JSON null，避免序列化省略字段被误解为空状态。
- 两套前端继续使用相同的设备级影响模型，包含停用、归档及旧版标签主机。关闭重开不重放在途变更，布局不改变远端 PTY。当前没有精确停止证明时，GUI 移除按钮仍禁用。

设备服务只由原 native 应用绑定安装同一个 store，不接受前端安装或替换。此批未将 ZeroTier feature／库加入应用 bundle，正常应用仍会显示该能力不可用；命令源码存在不代表实际 Android 已可创建身份。

## Tauri 未确认调用的完成边界

固定 `tauri 2.12.5` 的同步 `run_mobile_plugin` 没有内部超时，但 JNI 报错没有证明 Java 自定义 worker 未开始或已结束。直接收到错误就退出 Rust closure 会提前释放目录锁。

本批增加内部单调序号和 Java 进程级完成记录：只保留一个 active、完成标志和已封闭序号上界，空间恒定。查不到原操作时，确认结束会同时封闭该序号；迟到原请求因此不能再执行。其他操作仍 active 时不能推进上界；原操作未结束时继续持锁。超过 1024 次操作不会耗尽记录，序号达到整数上限时拒绝且不回绕。

这项确认只证明原存储调用已退出或旧操作永不再准入，不是 worker 线程 join，也不是重放许可。若 IPC 永久不可达或存储调用永久挂起，当前仍保留目录锁，**没有有界恢复时间保证**。进程退出、Activity 重建、异常或等待超时均不能单独当作完成证明。

单 producer 由 Rust Operations 租约、唯一内部命令入口及当前 `core:default` 权限共同保证。固定 Tauri 存在 mobile fallback，不能仅因未添加 Rust plugin handler 就认为原生命令无法从 JS 调用；今后扩大 `devicekeys` 权限必须重新验收该前提。独立 Sol 只读复核了固定包及最终实现，未替代 Android 运行验证。

## 实际验证

父线程独立执行以下检查，命令、日志 SHA 和源码快照见[本批证据](evidence/mobile-pair-gui/shared-device-host-20261107.json)。

| 层 | 结果 | 范围 |
| --- | --- | --- |
| 共享 Java service | 89 checks | 真实 service／store、临时目录、合成身份与测试 JCE provider；包含并发拒绝、实例错配、活跃 lease 和待定恢复 |
| 设备 core／Android wrapper | 153／36 checks | 既有隔离回归；无 AndroidKeyStore 设备证明 |
| JNI | 100 checks | 真实 JNI／Java、合成引擎及 Android stubs；无真实 libzt 网络 |
| Flutter Kotlin 通道 | 119 checks | 真实 channel／目录文件，合成 Android／Flutter／service；未与真实 Java service 做端到端联跑 |
| Flutter 原宿主 | 64 checks | 既有 journal／MainActivity 隔离编译回归 |
| Tauri Rust host | 50 tests | Mac 默认 features，含目录锁、操作租约、完成确认及溢出；Android cfg 不在此编译范围 |
| Tauri Kotlin 插件 | 3358 checks | 真实插件与协调器、合成 SDK／service；包含 1100 轮操作，非 3358 个独立设备场景 |
| Flutter 界面 | 16 状态／合同＋9 widget 测试源 | 尚未执行；本机无 Flutter SDK，不为此安装 |

未重跑未改动的 Tauri JS suite；上一批 135 项保留原来源。Python 脚本语法、差异空白和新文件检查另行执行。父线程第一次 Flutter probe 命令遗漏必需 `--kotlin-dir`，在 argparse 阶段返回 2；补齐已校验的缓存路径后通过，没有安装 SDK。JDK 的 Unsafe／native-access 警告保留在日志，不改写为测试错误或设备通过。

## 固定来源与下一步

Context7 先解析 Android Developers，再查询 application context、后台线程及 Activity 生命周期；实现沿用现有工具链，没有升级依赖。[Android application context](https://developer.android.com/reference/kotlin/android/app/Activity#getApplicationContext())与[主线程约束](https://developer.android.com/topic/performance/anrs/diagnose-and-fix-anrs)用于核对边界，不采用文档示例中的常驻后台 Service。

独立复核检查了本机 `tauri 2.12.5`、`wry 0.57.1` 归档与 Cargo.lock checksum，所读调度／插件源逐字节匹配。JSON null 行为另对照[固定 AOSP JSONObject](https://android.googlesource.com/platform/libcore/+/e4ac325990e11c266cef45366fa9b2aefd145b5d/json/src/main/java/org/json/JSONObject.java)。Kotlin fixture 使用固定 `org.json 20250517` jar，不能替代 Android SDK。

下一步仍手机优先：补齐待定设备操作的可用恢复界面及宿主集成验收；原生草稿未消除的生命周期／重配置问题独立处理。只有固定原生候选、设备绑定与 Android bundle 完整后，才集中构建两份测试包。配对 → 看板 → 持续观察继续作为主验收链，随后推进桌面分屏。

本批未更新 Penpot、未启动测试应用、未触发 Actions、未访问真实凭据或授权文件。实际安装、相机、IME、KeyStore、真实三网及逐平台并发均未新增通过项；框架未定案。
