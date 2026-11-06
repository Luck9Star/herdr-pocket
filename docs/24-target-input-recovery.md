# 按目标隔离的未知输入记录

2026-11-06，延续[持续会话看板](23-mobile-session-watch.md)。旧版所有终端共用单条未决记录：A 的发送结果未知时，B 的独立输入也会被阻止。本批改为有界的多目标存储，同时保留“写入前持久记录、未知不重放”的规则。本批源码尚未包含在已下载的 `546c3eb` Android 包中。

## 目标、请求与活动写入

持久目标由实际网络路由身份、SSH 主机／端口／用户、主机公钥、socket、命名会话、pane 与稳定 terminal 共同区分。标签 ID、界面主机名称、连接 generation 和输入 epoch 不构成新的远端目标。同一目标的不同标签共享未决锁定；不同目标可独立准备输入，不能相互清除记录。

Rust 原有身份还包含 herdr 可执行文件路径；Flutter 历史 v1/v2 marker 没有该字段，本批保留这一边界，不用当前配置给旧记录补值。设备身份、组网秘密和输入正文均不进入 journal。

每个目标最多一条未决记录，共最多 32 个目标；每条最多 8192 UTF-8 字节、总文件最多 262144 字节。超限拒绝新写入，不能淘汰未知记录。坏 JSON、重复目标、未知版本、越界或存储不可读均是不可用状态，不能当成空表。

活动写入另有本进程的所有权：原始记录、request ID 和精确租约必须一致。超时不等于原操作已经结束，取消后仍要处理原 Future 的迟到结果。正常回执只清原请求；旧回执、旧租约或旧人工确认不能清掉同目标后来创建的记录。

## 迁移与两路线实现

Rust 在原 `pending.json` 路径内从 version 1 单 marker 升级为 version 2 ledger，以原子替换完成首次成功变更。既有 owner lock 保持跨进程互斥，活动集合按目标与 request ID 区分。新 full 创建的输入句柄冻结当时待核实的 request ID，人工确认不会临时改为清除另一个请求。

Flutter 保留原 Android／Apple journal namespace，将单 marker 迁入 `{schemaVersion:3, records:[原始字符串...]}`。旧 v1/v2 的原始字符串保留，第一次成功变更才写表；读取本身不重新绑定目标。原生层以进程生命周期 owner lock 和进程内共享协调器保护活动租约；Activity 或对象重建不能把另一笔仍在途的请求当成已经结束。

| 原生操作 | 用途 |
| --- | --- |
| `readAll` | 有界读取原始公开 marker 列表，Dart 严格验证后筛选当前目标 |
| `prepare(record)` | 原子持久化且取得该目标的活动租约，成功后才能发送 |
| `complete(record, lease)` | 匹配回执或确知未发送后，清理本次精确记录 |
| `abandon(record, lease)` | 只退役原活动租约，保留磁盘上的未知记录 |
| `resolve(record)` | 用户明确核实原记录后清除；目标仍有活动发送时拒绝 |

Flutter 对已持久化但随后取消的 prepare 保留原 marker，即使本地能确认尚未发送，也只退役租约，等待人工核实；不把超时当成持久化失败。

GUI 恢复入口必须绑定用户实际审查的原始记录，并要求原目标的新 full。异步确认期间发生的新记录不能替代该意图。已知服务器回执但本地清理失败时，界面保留“结果已知、记录仍锁定”的事实，不能改称服务器没有收到。

Flutter 同一页面的输入队列也按目标分开：A 的原 Future 未结束时，B 可以开始；同一目标跨连接仍保持串行，最多 32 个活动队列。另一页面已人工解决记录后，旧页面只在接受新 full 时协调旧锁定状态，必须核对读序号、连接、观察代际和原记录。迟到的 A 错误不能撤销 B 的模式或队列。

Tauri 恢复按钮此前先进入失焦观察，而后端人工确认要求聚焦观察，导致确认一直被拒绝。本批增加仅用于人工核实的 `review: true`；它保持观察模式，并携带原 `input_epoch`，不授予直接输入能力。正常失焦仍撤销确认权限。

## 升级与生命周期边界

Flutter 新版的进程锁不能约束没有实现该锁的旧二进制；旧版和新版并存时，不能证明旧进程已无活动发送。当前按应用升级替换旧进程的方式使用，不声明支持二者同时写同一存储。进程内不同目标可独立操作，跨进程使用整表独占锁。

进程已经看到记录文件后，文件意外消失按存储故障处理；首次使用时真正不存在文件才为空表。进程重启后若文件已被外部删除，仅凭该文件无法还原丢失的历史，本批不宣称覆盖这种情况。原生进程锁在 Activity／engine 对象重建时保留，但真实系统回收、设备锁屏、备份恢复及 KeyStore 生命周期仍未验证。

## 验收范围

[共享 IJ01–IJ12](../validation/shared/target-input-journal-v1.json)覆盖 A/B 隔离、同目标互斥、迟到回执、活动所有者、旧记录迁移、路由与指纹变化、损坏存储、容量、迟到 prepare 和原子冲突。文件是验收合同，存在本身不表示通过。

以下由主代理独立执行，源码与日志摘要见[验收记录](evidence/mobile-pair-gui/target-input-journal-source-20261106.json)。两个框架的 GUI 运行边界分别列出，不将共享 Rust 测试作为 Flutter 执行结果。

| 检查 | 实际结果 | 范围 |
| --- | --- | --- |
| Rust 默认测试 | 76 library + 1 CLI 通过 | 临时文件、自建密钥和 loopback SSH；最终新增 review 断言在下一行重跑 |
| Rust 合成原生 ABI | 85 library + 1 CLI 通过 | 冻结源码；含真实 loopback SSH 的 A/B、同目标别名、旧回执和人工确认；overlay ABI 为合成替身 |
| Tauri | Rust 31、Node 106、Vite 构建通过 | 原生接线和合成 DOM；未打开 GUI、未安装 Android 包 |
| Swift 原生存储 | journal 59 + host catalog 14 通过 | macOS 临时目录和子进程，真实文件锁；Flutter channel 为桩，未测试 iOS |
| Kotlin 原生存储 | 52 通过 | JVM、临时目录和子进程，编译真实 MainActivity；Android／Flutter 为桩，`Os.fsync` 未执行 |
| Flutter 工具与共享文件 | Python 8、共享 SHA-256 44 通过 | 构建辅助逻辑、固定 fixture 文件 |
| Dart 语法 | 53 文件无语法错误 | tree-sitter；不是 analyzer、类型检查或测试运行 |

独立复核还修复了 Apple 悬空 `catalog.json` 符号链接被当成空表，以及两端当前进程内已见文件被删除后被当作首次空表的问题。子代理在临时目录对旧实现复现失败，主代理对修复后的全部原生探针独立重跑通过。

严格 Clippy **未通过**：子代理执行 `cargo clippy --locked --offline --all-targets -- -D warnings` 得到 12 个去重诊断，主代理检查了机器可读输出；未建立旧提交的独立对照，不将其全部归因为历史。它与上述测试通过分别记录。

Flutter 本机仍无 SDK，本批 analyzer、widget、真实 Flutter SSH 测试均未执行。新增输入队列和读 ticket 的反例已写入测试，但运行结果待集中 CI。真实手机、系统存储生命周期、原生 MethodChannel、Windows 存储替换与真实三网仍未验证。现有 `546c3eb` APK 不包含本批或前一批持续看板源码，不能继承它的 Flutter 测试成绩。本批没有发起 Actions、打包、创建 Release 或提交商店，也没有打开测试 GUI。

复跑原生探针使用现有 Swift 工具和本地 Kotlin 2.2.21／org.json 20250517 缓存；脚本不下载工具链：

```sh
python3 validation/flutter/native/apple/tests/run_input_journal_probe.py
python3 validation/flutter/native/android/tests/run_input_journal_probe.py --kotlin-dir /path/to/existing-kotlin-jars
```

两个脚本只创建自己的临时目录。Android 探针的 `fsync` 桩和 Flutter 通道桩限制不能由检查数量消除。native journal 的 load→save 窗口尚未单独注入 CAS 竞争；共用 catalog 的旧 revision 拒绝和同目标并发已有隔离反例。

下一步实现 Tailscale 的完整原生状态存储、明确授权和可取消字节流，再接 ZeroTier，逐平台验证并发；桌面分屏与键鼠适配随后推进。
