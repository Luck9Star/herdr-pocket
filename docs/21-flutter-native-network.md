# Flutter 手机原生网络通道与 Android 分层构建

> 本文保留该源码批次提交时的证据。后续集中云构建、发现的失败和修复进度见[手机标签验收](22-mobile-terminal-tabs.md)，不要将下文“尚未运行”当作整个项目的最新状态。

2026-11-06，延续[节点接线](20-mobile-node-routing.md)。Flutter 现在也有显式节点启动、状态、停止，以及经实际 overlay 字节流进入设备密钥 SSH、看板和持续观察的源码路径。**本批是源码集成和隔离验证，没有新 APK、Actions 或真实节点结果。** 两套现有 Android 包仍对应 `040eb26`，下载和失败记录保留在[上一集中验收](18-mobile-network-profiles.md)。框架选择不因此收敛。

## 手机路径

Flutter 网络管理先核对保存配置、版本和本机身份，再明确启动节点。连接页冻结这份绑定，交给 [Android 原生通道](../validation/flutter/native/android/NetworkRuntimeChannel.kt)和[共享节点服务](../validation/flutter-network-runtime/README.md)，从实际连接回传的 route 核对网络、版本和身份。默认构建没有候选原生库，显示不可用；显式选中的网络没有系统 TCP 或 DNS 回退。EngineStarted 仍只代表引擎接受启动。

修改网络资料或身份前先关闭受影响的 SSH，再确认旧节点停止。连接页的网络绑定发生变化或失效后，本页永久关闭连接入口，必须关闭重开，防止 State 复用保留旧系统拨号器。停止结果未知会跨页面保留阻止状态，旧状态回复不能解除；单个主机解绑不会停止其他主机共享节点。当前 PRIVATE 模式可进入启动流程，PUBLIC_NO_SECRET 可保存但固定引擎不支持启动。Tailscale、ZeroTier 与其他平台的原生 GUI 通道仍未实现。

输入恢复标记新增 v2 路由身份，格式为 provider、配置 ID、持久配置版本、vault handle；来自实际 socket，不来自页面标签。旧 v1 记录只对应系统网络，读取后保留原始内容用于条件清除。换网络、版本或身份不能确认掉旧目标的未知输入，也不会自动重放。Android 和 Apple 的记录校验同步兼容 v1/v2，不等于 Apple 已有组网桥。

## 字节流和关闭

每个 Flutter engine 拥有私有 native scope。独立审查复现了旧 scope 延迟清理误停同绑定新节点的问题，现以 Rust 内部不可序列化的 NodeAttempt 绑定原 service 和启动编号，副作用前在 registry 锁内核对；尚未入场的启动也保留 owner，不能用历史 Stopped 提前释放。这不改变持久输入恢复路由。启动、状态、停止、连接、读取、写入和快速控制分别调度，空闲读不能占满停止通道；detach 只退休自己的流和节点。有限队列、4 个 scope、8 个未清理节点和 32 个 stream admission slot 都计入迟到操作或清理失败，不能把取消回执当成资源已经回收。

读取有背压，单次 JNI 等待最多 250 ms；空数据且非 EOF 继续等待原操作。写入最多排队 64 KiB，只推进明确接受的前缀；错误或结果未知关闭原流，不再次发送。open ID 不复用，先登记再进入阻塞连接池，取消先到也能绑定原请求。恢复、布局和本机节点变化不发远端 PTY resize。

现阶段 stream slot 回收较保守：原 runtime 的所有 stream reservation 归零后才清理已退休的 ledger。另一个长期连接可能让已关闭 slot 继续占额；达到上限会明确拒绝新连接，不强制停止其他连接。节点服务另保留最多 32 个配置 ID 历史。详细接口、限界和重跑命令见[原生通道说明](../validation/flutter-network-runtime/README.md)。

## Android 原生库与 GUI 分层

新增[显式批次实验工作流](../.github/workflows/android-network-experiment.yml)，计划在一次运行中先构建固定 Heeler／EasyTier 来源与 portable 补丁的 Android arm64-v8a、API 35 库，再由同源 Flutter 和 Tauri job 消费。原生构建固定 Rust 1.95、NDK 28.2.13676358；GUI Rust 1.96。常规构建保持原先 feature 和 ABI，日常分支 push 不启动此实验。

输入工件校验来源 SHA、补丁清单、源码模块、文件 hash、ELF 架构、动态依赖和导出符号；APK 再核对实装 Heeler 字节以及 Flutter 5 个／Tauri 1 个 JNI 导出。审查中补上 LOCAL/HIDDEN/UND 符号拒绝和来源材料交叉绑定，伪造材料后重算自述 hash 仍被拒绝。**这些静态检查不证明二进制确由所附材料构建，更不证明 Android 能加载或入网。** [构建范围与工件说明](../validation/native/ANDROID-BUILD.md)

工作流仅匹配专用 `codex/network-batch/**`，不匹配既有 `codex/batch/**`，避免一批触发两组任务；保留的手动入口须待默认分支注册后使用，不能假定只存在原型分支就可 dispatch。[GitHub 官方触发规则](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)

工作流尚未运行，也未推送专用批次分支；没有新增测试下载链接。将它与 Flutter 既有修正、手机标签／恢复功能积累到下一次集中验收，不逐项触发 Actions，不创建 Release 或提交商店。

## 本地证据与剩余验证

逐项命令、源码摘要和边界记录在 [flutter-network-source-20261106.json](evidence/mobile-pair-gui/flutter-network-source-20261106.json)。新增 Rust 默认 3 项、合成 native ABI 11 项、桌面 JVM JNI 38 项通过；新 crate 的默认和 fixture 严格 Clippy 通过。父代理独立复跑默认和 fixture；源材料检查由独立审查复跑。

Kotlin 2.2.21 在临时 Android／Flutter Java stubs 下编译通过，javap 确认 4 个 static native 签名；固定工具来源与 SHA 记录在 [kotlin-probe-tools.json](../validation/flutter/tool/kotlin-probe-tools.json)，可用[离线探针](../validation/flutter/tool/check-network-kotlin.py)复跑。这不是 Android SDK 编译。Dart tree-sitter 只验证语法；新增 Flutter 单元／widget 测试和类型分析尚未执行。Apple 公共输入标记探针通过也不是 iOS 设备证据。

未验证项仍包括：Android target Rust／Kotlin／Gradle 构建和动态加载、真实 AndroidKeyStore/JNI、节点入网和 overlay SSH、手机中文 IME／触控／扫码／前后台、iOS 签名及三网并发。五端 × 三网验收矩阵没有新增通过格。没有读取真实凭据、修改授权文件或安装完整 SDK；本批未打开 GUI 测试应用。

## 下一阶段顺序

1. 先收敛手机多标签、显式停止与恢复交互，把本批源码和此前 Flutter 失败修正纳入同一集中云验收；失败逐项保留，构建成功与设备通过分开。
2. 在获授权的隔离网络中验证原生加载 → 节点 → SSH host key → 设备签名 → 看板 → 持续观察，先只读再输入，确认迟到数据和跨网络目标隔离。
3. 按相同服务契约逐一接入 Tailscale、ZeroTier，补本机身份恢复和平台差异。已有 Penpot v2 30 画板本批未改，依据实测再修关键状态；桌面分屏和焦点在手机闭环之后。
