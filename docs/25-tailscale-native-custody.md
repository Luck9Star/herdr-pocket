# Tailscale 原生运行时与 Android 状态托管

2026-11-06，延续[按目标隔离的输入恢复](24-target-input-recovery.md)。本批完成固定来源的 Go 原生候选、共享 Rust 节点接入，以及 Android 完整加密 StateStore 与 JNI 状态源。它们尚未接通 Flutter／Tauri 宿主和登录页面，不是可用的手机 Tailscale 功能，也未包含在当前 `546c3eb` Android 下载包中。本批不触发 Actions 或发布；继续累积手机功能后集中验收。

## 固定来源与显式授权

实际依赖保持 **Tailscale v1.104.1 / `9a522a9786c97eb7910c01ccb7bd66557b04c910`**，复用 Heeler 锁定来源的完整 go.mod／go.sum，只修改本项目 module 名。当前 Context7 的 v1.104.4 文档用于背景核查，没有据此升级依赖。原 fd shim 使用 Unix Socketpair／SCM_RIGHTS，不能直接作为五端实现；本批使用 opaque `net.Conn` 句柄。原始观察保存在 [audit](../validation/native/tailscale-adapter-audit.json)，精确源码与补丁 SHA 在 [来源清单](../validation/native/tailscale-runtime-source.json)。

新增 `ExplicitAuthOnly` 源码补丁：不读取环境中的 auth key、OAuth／WIF 凭据或 control URL，不因 NeedsLogin 自动发起授权；强制登录环境开关也不能越过显式策略。未开启新字段的上游行为保留。原生构造器设置独立目录、完整 StateStore 和明确 control URL，禁用日志上传，不输出原始登录日志。没有产品 auth-key 输入入口。

状态明确区分 Starting、NeedsLogin、NeedsMachineAuth、Running、Closing、Stopped。开始运行不等于入网成功；只有 Running 才允许原节点拨号。登录是单独的显式操作，返回经过 HTTPS 策略检查的 URL，不自动打开浏览器。真实授权、管理员审批和登录 URL 的设备交互仍未验证。

## 所有权、取消与关闭

[`hp_ts` ABI v1](../validation/native/tailscale-runtime/hp_ts.h) 使用单调 u64 句柄，最多 8 个节点和 32 条流，每次 IO 最多 64 KiB。等待超时不会将底层 Start／Dial／IO 当成已结束；迟到结果仍属于原节点，并继续占用配额。写入结果未知时不重放。读超时只有在原 Read 已返回且未消费字节时才可重试；不具备半关闭能力时明确拒绝，不能用完整关闭假装半关闭。

Close 失败保留原对象、句柄、存储 context 和配额，只允许显式重试。每节点的 StateStore gate 覆盖所有宿主读写回调和返回缓冲区的 release：成功关闭后等待已有回调结束，拒绝后来的回调，最后才允许 node release。它不依赖上游 Close 隐式保证全部后台回调已经退出。Rust 同样只在 native release 成功后释放进程级 context；失败不会变成已清理。

Tailscale 和 EasyTier 共用现有 Rust NodeEntry、owner／revision、取消与清理流程。Binding 增加显式 provider，历史省略值仍为 EasyTier；完整 spec 与本机身份引用必须匹配。独立 fixture 需要显式 feature，缺少真实库时仍拒绝，不回退到系统 TCP、系统 VPN 或合成实现。C fixture 的跨 provider 隔离不代表实际两网并发。

## Android 状态与 JNI

每 profile 使用独立 AndroidKeyStore AES-256-GCM 密钥，完整键值表加密写入 noBackup 下专用 namespace。key 最多 1024 bytes、value 最多 262144 bytes；任意二进制 key、缺失、存在的空值和删除分开处理。旧严格 UTF-8 字符串键与原磁盘格式兼容，不通过 Base64 扩容或散列改写键。进程锁、文件锁、原子替换、fsync 和原密文比较保护并发更新。

删除先持久化绑定原 profile、handle 与密文 hash 的 intent，再删钥和文件；中途失败可继续删除原身份，不能转向后来替换的身份。损坏、悬空链接、已观察文件丢失或密钥不可用均不能解释成空表。非空历史 runtime 目录不会被递归删除。系统突然断电、备份恢复、硬件密钥及所有内存副本擦除不在本次证明范围内。

状态源先接收公开 profile／revision／network／identity 引用；运行时分配私有 attempt 后，首次合法 load 才原子冻结完整 NodeSpec。错误公开字段不能抢占绑定，后续不同 attempt 在访问存储前拒绝；GUI 无须预测内部 attempt。JNI 只在原生 worker 中读写状态，缓存 application Context 和原 class loader；不把秘密方法注册到 Dart／JS 通道。只将明确的缺键异常映射为 Missing，其他异常按不可用处理且不打印内容。Java 借用数组和短期 Rust 副本尽力清零。

目录复核纠正了一个实际兼容问题：[Android 15 的 ContextImpl](https://github.com/aosp-mirror/platform_frameworks_base/blob/android-15.0.0_r1/core/java/android/app/ContextImpl.java) 为 `no_backup` 使用 0771，不能要求所有框架目录都是 0700。现在保留系统目录权限，校验其类型与 UID；应用自建 namespace／runtime／handle 以 0700 原子创建，已有宽权限或符号链接目录直接拒绝。临时 POSIX 目录测试与 Android lstat 桩分别验证这些规则，尚无手机目录实测。

## 独立验收

主代理重新执行的结果和命令、日志 SHA 见[本批记录](evidence/mobile-pair-gui/tailscale-native-source-20261106.json)。

| 层 | 结果 | 实际边界 |
| --- | --- | --- |
| 固定 tsnet 补丁 | 3 项通过 | 合成环境变量；不启动节点 |
| 完整 Go 模块 | 30 项 race 通过 | 26 项生命周期／字节流、4 项 cgo StateStore；fake engine、自建 loopback |
| 真实 macOS arm64 动态库 | 编译、加载、保留节点退休通过 | new/status/拒绝未启动 login 和 dial/close/release；没有 Start，宿主 store 回调为 0 |
| Rust 与真实 Go 动态库 | 符号链接、ABI version、无效 node status 通过 | 不启动节点；不是实际组网或持久身份验证 |
| Rust overlay | 默认 3、双 ABI fixture 33；严格 Clippy 通过 | 独立合成 C ABI，含跨 provider 隔离 |
| 共享 Rust transport | 89 library + 1 CLI 通过 | 双 ABI fixture、自建 loopback SSH；没有真实 overlay |
| Android 加密存储 | 211 项与接口检查通过 | 临时 JCE 密钥、真实临时 POSIX 文件，Android 包装为桩 |
| Android JNI | Tailscale 1090 个断言、EasyTier 52 项通过 | `-Xcheck:jni`、生产 bridge、合成 vault；断言数含逐字节清零，不是 1086 个场景 |
| Tauri Rust 宿主 | 32 项通过 | 补齐新状态的 wire 映射及序列化回归；未运行 GUI |
| Flutter 原生 Rust 宿主 | 默认 3 项通过 | 共享状态扩展的编译兼容；不是 Dart／Flutter GUI 测试 |
| 构建工具 | 13 项通过 | 固定锁、准备目录、复制内容漂移、symlink 与环境隔离 |

保留三次实际失败：cgo 测试夹具直接引用 static C 变量导致 macOS 链接缺符号，已改 getter 后完整重跑；`cargo run` 启动时未找到动态库，改为构建后带显式 loader path 运行已通过。Tauri 原四态 exhaustive match 也实际编译失败，补齐新状态后 32 项通过。不是忽略失败或将编译等同加载。transport 严格 Clippy 仍有 12 项诊断，本批未修复、未声明通过。

原 `546c3eb` [两套 Android 包和 CI](22-mobile-terminal-tabs.md)保持独立来源；本批没有新 APK、没有打开测试 GUI。所有真实 Tailscale 登录／流量、AndroidKeyStore、两套应用 JNI 宿主、iOS／Windows／Linux 新运行时、15 格单网络及 20 格并发矩阵仍未验证。框架、许可证和产品支持等级没有因此定案。

## 下一步顺序

1. 手机宿主导出并调用 `bind_tailscale`，补本机身份生命周期、显式登录／等待授权状态和原 provider 路由；私密状态不经过 GUI IPC。
2. 两套手机界面接通配对 → 看板 → 持续观察，覆盖 profile 修改、授权撤销、迟到状态、隐藏恢复及原目标输入撤销。
3. 增加固定来源 Android 原生库分层构建与同源装包检查，与后续 ZeroTier 集成累积成集中 CI 批次；此之前不沿用旧库或旧 APK 结果。
4. 继续 ZeroTier 状态／socket／并发隔离，再推进桌面分屏和各平台安全存储；可用设备再补真实交互与组网证据。

[`TS01–TS12` 共享合同](../validation/shared/tailscale-managed-v1.json)对应上述验收与剩余设备项。文件存在不是通过记录，完整平台矩阵保持原状态。
