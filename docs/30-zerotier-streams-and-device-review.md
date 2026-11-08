# ZeroTier 流、设备托管与手机审查界面（进行中）

2026-11-07，基于原型分支 `98473a6` 的后续本地工作。**本批尚未形成完整原生候选，未推送或触发新 CI，未生成新 APK。** 可下载 Android 包仍来自 `750798fe`，见[构建与下载记录](27-mobile-tailscale-cloud.md)。框架没有定案，15 格单网及 20 格并发矩阵不新增通过项。

后续[手机宿主接线记录](31-mobile-shared-device-host.md)新增共享 Java 入口、Flutter channel 和 Tauri 命令。本文件及证据 JSON 保留此前阶段的源码快照与测试数量，不视为后续改动的同源验证。

## 已实现的独立部分

- Rust ZeroTier backend 以数字 IPv4／IPv6 和原网络租约调用 stream ABI。多个 profile 可共享设备 owner，各自保留网络和连接；清理按 stream → network → device reservation 顺序执行。取消、迟到结果和清理失败继续保留原对象，未知写入不重放。
- `MobileNodeService` 新增 ZeroTier 入口，分别传递八个网络 phase 与 `deviceOnline`。只有 Configured＋online 才允许尝试原网络拨号；它们仍不代表目标可达或 SSH 认证通过。未 linked 在读取设备存储前拒绝。
- Android native-only JNI 连接设备存储与原 owner；共享设备采用进程级 reservation，最后一个使用者才退休原设备。设备私有身份不进入 Dart／JS。Java 强持有原租约，使 JNI 元数据异常后仍可找回相同对象。
- 修正两处启动恢复细节：设备取得后要使用原 deadline 的剩余时间，不能重新获得完整 join 预算；callback 被认领与真正进入原生初始化分开记录，确定未派发的失败可以回收，尚未返回的原调用不能由 owner 为 0 推断已退休。
- 两套手机前端已加入共享设备审查入口，列出全部受影响网络和主机。目录变化、切后台与迟到结果使旧确认失效。缺少宿主命令／库显示不可用；缺少精确停止确认时禁用设备移除。这里没有启用 ZeroTier 拨号。

上述 Rust／JNI 源码、前端与测试目前仍在工作区。编译、合成 ABI、桌面 JVM 和界面状态测试应分别理解，不能合并成 Android 产品闭环通过。

[本批证据清单](evidence/mobile-pair-gui/zerotier-streams-progress-20261107.json)记录日志 SHA、当前源码快照、未完成项及已有 APK 的线上复核。源码快照是在记录时取得；没有在日志内绑定源码 SHA 的历史结果不能反推为最终源文件通过。

## 已取得的本机证据

| 检查 | 结果 | 证明边界 |
| --- | --- | --- |
| overlay runtime | 默认 5 项；三 fixture 43 项；库目标严格 Clippy 通过 | 独立内存 C ABI；无 ZeroTier 节点／真实网络 |
| Rust transport | 默认 83＋1；三 fixture 98＋1 通过 | 自建临时 SSH peer 和合成 overlay；不是手机、实际 herdr 或 overlay SSH |
| JNI／设备存储 | JNI 100、core 153、Android wrapper 36 项通过 | 实际 JNI／Java 源，桌面 JVM、Android stubs、测试 JCE provider、合成 native engine |
| Flutter Rust host | 13 项通过 | 宿主类型／状态兼容；不是 Flutter 新界面验收 |
| Tauri Rust host | 42 项全量后，新增状态相关 13 项定向通过 | 两组有重叠，不能相加；不代表 WebView 或 Android 安装 |
| JNI → shared transport | 显式 feature `cargo check` 通过 | 使用 fixture link 配置；未证明实际 libzt 与 Android JNI 动态链接 |
| Tauri 前端 | 完整 JavaScript suite 135 项通过，父线程独立复跑一致 | 仓库轻量 DOM 替身；无真实 WebView／GUI 验收 |
| Flutter 前端 | 已写 15 项状态／合同测试与 9 项 widget 测试，尚未执行 | 本机没有 Flutter SDK，不为本任务安装；analyzer／widget 待集中云验收 |

transport 第一次在默认 sandbox 内运行有 24 项回环 bind 被拒；同源代码在授权的 sandbox 外重跑全部通过。一次 core 验证命令误写脚本名返回 127，更正为 `run-zerotier-device.sh` 后通过。原 transport 严格 Clippy 的 12 项历史诊断本批没有重新验收。

### 手机界面收尾

Tauri 修正了关闭后重开页面可能重复发起在途变更的问题：写入门闩跨页面保留到原操作返回，重开先只读，结束后重新读取状态，不重发原操作。关闭、Escape 和再次打开会清理旧监听器并恢复焦点；重绘保留可用按钮焦点，原按钮消失时回到带名称的标题。目录变化、失焦和切后台使旧确认失效。已有样式限制对话框高度并允许短视口滚动，但本轮没有浏览器或手机视觉验收。

Flutter 同样增加跨页面的共享操作协调，关闭页面或创建新的 store 对象不解除原操作；移除前的停止检查也包含在其中。原 Future 返回后仅重新读取，不自动重发。页面返回立即撤销审查，阻止返回动画期间迟到的停止结果继续派发移除。另补关闭／系统返回的测试源、忙碌与结果的无障碍语义，并修正测试中从底部回查已回收卡片时的滚动定位。这些 Flutter 改动尚未编译或执行测试，不能由 Tauri 的通过结果代替。

宿主的共享设备命令尚未注册；界面不得把缺少桥接解释为“没有身份”，也不能凭关闭标签宣布原生连接已停止。待定记录的读取、操作返回与后续读回是三个独立证据；未确认结果继续只读恢复。

## 原生部分未完成，不能计为通过

原生实现和独立审查子代理被运行环境自动安全审查中断，提示 `possible cybersecurity risk`。没有继续执行该原生路径。临时目录中已写出的 15 个源文件变更保存为[未激活草稿](../validation/native/candidates/zerotier/drafts/README.md)，附前后 SHA；它未进入 `zerotier-candidate.json`。本机当前 manager 仍有未提交修改，正式候选锁也尚未为这些修改更新。

中断前的历史结果包括 manager 109＋6 项、stream 198 项合成 boundary 检查，以及 v6 的 114 项真实 lwIP 内存网络检查。后者经过 IPv4／IPv6 重叠网络握手、收发、半关闭、EOF、网络 A 移除不影响 B 和旧 generation 拒绝；没有运行 ZeroTier Node、身份或主机网络 socket。**这些日志未绑定最终源码 SHA，且 v6 后源码继续变化，不能据此宣布当前草稿通过。** 新 `tap_reconfig_test.cpp` 没有执行证据；本批也没有完成新的整库重建。

已定位的问题和证据边界：

1. 固定 lwIP 的地址变更通知只按本地 IP 处理连接，重叠网络中可能误关另一网络。草稿改为原 netif 范围；最终源码仍须重新运行实际反例。
2. IPv6 控制器源地址、额外 SLAAC 地址槽与前缀需要正确关联。最初的“双 controller add”举例不符合固定 VirtualTap 的单 family 限制，已撤回该触发序列；不能把它当作已复现路径。
3. IPv6 地址移除后，残留 netif 对象需要重新挂载和新 generation。生产 VirtualTap 的实际 add → remove → add 恢复尚未验证，不能只用人工 netif 测试替代。
4. 异步帧回调的借用数据及原节点生命周期仍有未完成修复项。关于其中一个局部数组按值捕获仍保留栈指针的说法已经撤回；其余生命周期结论需继续核对并修复。当前不能声称节点停止已覆盖所有异步工作。
5. 历史 generation 测试曾在 netif 移除释放 PCB 后继续保存指针，引发 ASan；这是测试自身错误，已与产品问题分开记录。Darwin host 与 lwIP 错误码域的分类也曾发生实际接线错误。

## 后续顺序

1. 继续完成手机共享设备界面及宿主元数据命令：创建／读取／原身份审查／明确移除、待定结果只读恢复、完整受影响范围；已有配对 → 看板 → 持续观察仍为主流程。当前不可用的操作如实展示，不以关闭标签冒充原生连接已退休。
2. 原生工作恢复后，完成未修生命周期问题与网络重配置回归，固定最终补丁／源码清单，再独立做 manager、真实 lwIP 和完整 Mac 库复验。
3. 增加第三网络的 Android native bundle 与来源清单；手机宿主接通后集中构建两份测试包，不逐项启动 Actions。实际 KeyStore、安装、相机、IME 和真实三网继续单独标注未验证。
4. 根据手机实测再更新 Penpot v2 的共享设备状态和高保真规格，随后推进桌面分屏。本批没有修改 Penpot 文件，没有打开测试应用。
