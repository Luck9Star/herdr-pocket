# 手机共享设备的待定操作恢复

2026-11-07，`codex/core-prototype-validation`，基于 `98473a6` 后的未提交工作区。接续[Android 宿主接线](31-mobile-shared-device-host.md)，本批补齐 Flutter／Tauri 的共享 ZeroTier 设备恢复界面和存储合同。**没有启用 ZeroTier 节点、提交实现、运行新 CI 或生成新 APK。** 当前可下载包仍是[双网络测试包](27-mobile-tailscale-cloud.md)。

## 手机交互与实现

两套界面均先显示原身份记录、当前阶段及全部受影响网络／主机，再由用户确认恢复或放弃。影响范围包含停用、归档和旧版标签；目录变化、切后台、关闭页面会使旧确认失效。Flutter 使用适合短视口的滚动全屏页、独立勾选确认及读屏状态通知；Tauri 保留对话框焦点恢复。没有启动应用做视觉验收，也没有修改 Penpot 画板。

确认前重读状态，请求携带原 `handle`、`expectedPhase` 与完整目录审查。Flutter 通道、Tauri Rust／Kotlin 及共享 Java service 使用一致的允许阶段：

| 显式动作 | 允许的原阶段 | 存储条件与结果 |
| --- | --- | --- |
| 恢复待定创建 | `record-present`、`finishing` | 原记录已经安装，内容匹配待定记录且可解密验证；恢复原身份，不生成新身份 |
| 放弃待定创建 | `record-pending`、`finishing` | 没有已安装记录；仅清理原待定创建 |
| 恢复待定删除 | `record-present`、`record-removed`、`finishing` | 原删除意图或完成标记仍存在；仅继续原删除 |
| 普通创建／移除 | 不携带阶段 | 普通移除仍需原设备实例匹配及精确停止证明；不能隐式恢复待定删除 |

`finishing` 可能来自已安装创建的最终同步失败，也可能来自未安装创建的清理同步失败。界面不猜测哪一种，更不能因为恢复失败就改做丢弃。存储在同一个 owner／数据锁内重新核对阶段、原记录及存在性；恢复删除时没有原意图就拒绝，不能转成第一次删除正常身份。活跃 runtime lease 仍阻止变更。

未知结果只允许重新读取。创建恢复须同时匹配响应和读回的 handle／instance；删除或丢弃须读回设备及两类待定记录全为空才能确认完成。即使读回是原 handle 的已安装设备，也不能把丢弃显示为成功。关闭重开继续保留原在途操作；Tauri 原操作完成屏障保持不变，仍没有永久 IPC／存储挂起情况下的有界恢复时间保证。

共享 service 现在接收四参 `write(action, handle, instanceId, expectedPhase)`；Tauri 写命令为严格七字段，Flutter pending 请求添加严格阶段字段。设备绑定仍未启用，普通应用显示能力不可用。Flutter 产物来源清单新增这部分 Java、Dart 与 Kotlin 的九份来源记录，不会因此自动启用原生网络。

## 实际验证与边界

父线程在生产文件冻结后独立复跑；完整命令、日志 SHA 与源码快照见[本批证据](evidence/mobile-pair-gui/device-recovery-20261107.json)。未升级依赖，也未安装完整平台 SDK。

| 层 | 本批结果 | 证据范围 |
| --- | --- | --- |
| 共享存储 core | 215 checks 通过 | 临时 JCE／合成身份；包含删除三个阶段、创建 finishing 两分支、旧审查对新身份、无待定操作时拒绝 |
| Java service | 128 checks 通过 | 四个独立 JVM 模式 8／58／40／22；真实 service／wrapper／core，测试侧注入文件故障、合成 Android／KeyStore provider |
| Android wrapper | 36 checks 通过 | JVM stubs，非真机 KeyStore |
| JNI | 100 checks 通过 | 真实 JNI／Java与合成原生引擎，无 libzt 节点或网络 |
| Flutter Kotlin 通道 | 177 checks 通过 | 真实通道／目录，合成 Android／Flutter／service；未与真实 service 做端到端联跑 |
| Tauri JavaScript | 143 tests 通过 | 前端状态与合成 DOM／IPC，包含 phase 变化、关闭重开及丢弃后读回身份的负例 |
| Tauri Rust host | 51 tests 通过 | Mac 默认 features；Android cfg 未在此编译 |
| Tauri Kotlin 插件 | 3360 checks 通过 | 真实插件与合成 SDK／service；包含 1100 轮，不是 3360 个独立设备场景 |
| Flutter 界面 | 24 unit＋14 widget 测试源 | **未执行**，本机无 Flutter SDK；不能以静态检查替代编译／运行 |

Sol 独立只读复核了存储原子检查、各层阶段传递、前台／目录失效、未知结果和读回确认，未发现可复现的新问题；该复核没有运行测试。父线程另检查了 Python 语法、Flutter 来源清单及差异空白。JDK 既有 Unsafe／native-access 警告保留。

## 后续顺序

1. 保持手机「配对审查 → 看板 → 持续观察」主链，继续整合设备管理与配置恢复；把本批可用状态与错误文案纳入同批 UI 验收。
2. 分开处理仍未完成的 ZeroTier 原生候选、绑定及 Android bundle。原生定向流、节点生命周期和重配置没有因本批元数据恢复而通过；不激活未完成草稿。
3. 一批功能冻结后再更新来源清单、运行云端整体验证并构建两套测试包；之后按实际结果反馈 Penpot 高保真，再推进桌面分屏。

真实手机的触控、IME、相机、KeyStore、三网运行与并发仍未新增证据。本批没有访问真实身份或主机授权文件；没有打开测试应用，因此没有留下本批测试窗口。
