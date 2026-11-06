# 手机 Tailscale 身份、登录与路由

2026-11-06，延续[原生状态托管](25-tailscale-native-custody.md)。Flutter 与 Tauri 的 Android 宿主、手机身份入口、显式登录及原节点路由已接入源码，复用配对审查 → 看板 → 持续观察。隔离验证和剩余项见[证据记录](evidence/mobile-pair-gui/tailscale-mobile-source-20261106.json)。本批没有运行 Actions、生成新 APK 或启动真实网络；当前下载包仍来自 `546c3eb`，不能用它验收本页新增功能。

**后续更新 · 2026-11-07：** 本页记录的是源码阶段。随后 `750798fe` 双网络云构建、Flutter analyzer／widget、隔离 SSH 和两份 APK 静态校验通过，下载与失败历史见[集中云验收](27-mobile-tailscale-cloud.md)。下表中的“待 CI／未编译 Android”保留该源码阶段的历史边界；设备运行与真实组网仍未验证。

## 手机操作和状态

先保存 Tailscale 的公开控制服务器与主机名，再创建本设备身份。GUI 只持有 profile、revision、provider 与不透明 handle，状态为 `DEVICE_STATE`；完整 StateStore 留在 Android 原生加密存储中，不进入 Dart／JS，也不接受 auth key。身份创建、删除和配置变更需停止受影响的原节点与主机连接；停止失败或结果未知时不继续替换身份。

启动节点后区分 NeedsLogin、NeedsMachineAuth 和 Running。用户核对控制服务器、本机名和身份后，明确请求授权，再单独点击打开系统浏览器。返回应用只重新读取原节点，不重新发起登录、连接 SSH 或发送终端输入。Running 是 provider 状态，SSH host key、设备签名和 herdr 目标仍须通过原有审查。EasyTier 的 EngineStarted 不被解释为 Running。

授权 URL 和 reviewToken 只留在内存，后台或关闭审查时清除界面资格；轮询串行且有界，不因超时自动重发登录。原生审查保留原 NodeAttempt；同一个公开 Binding 停止后再启动，也不能使用旧 token 打开授权页。打开前只读复核原 attempt 和原 URL，不能将后来节点的状态补到旧请求上。

终端 socket 的路由保留 provider、profile、配置版本和本机身份；缺少正确原生库、身份或 Running 状态就拒绝连接，不回退系统 TCP。Android 输入日志已接受独立的 Tailscale 路由键，同 pane 的 EasyTier 和 Tailscale 未知输入不会互相清除。布局仍不改变远端 PTY；未知输入不自动重放。

## 共享合同与并发修复

两路线使用[同一配置 fixture](../validation/shared/tailscale-settings-v1.json)：4 个正向向量和 21 个拒绝向量。空配置采用固定默认值，公开 networkName 为 `ts1:` 加配置 SHA-256；摘要绑定控制 URL 的原始字节和有效主机名，不把敏感身份加入摘要。保存、导入与原生启动采用相同规则，IPv6 控制服务器和非法 DNS 名在保存时即拒绝。控制 URL 上限 2048 字节，授权 URL 单独允许 4096 字节。

共享 runtime 将只读登录状态与显式登录拆开；旧 attempt 在调用原生授权前校验。登录占用从准入持续到原生调用返回，stop 先关闭准入并等待已有占用，超时保留节点和配额。取消在准入前阻止调用；已准入的原操作不能被假装撤回，其退休结果不发布，也不重放。对应反例涵盖暂停中的授权、并发请求、停止超时和随后显式清理。

审查实际发现并修复：Android journal 只认 EasyTier；GUI 与 native 的控制 URL 规则不一致；Flutter 授权 URL 上限过小；停止未等待已准入登录；外层取消到 worker 的传播窗口。失败和复验均保留在证据记录中。Flutter Apple journal 仍只接受 EasyTier，待 Apple Tailscale 宿主接线时处理；本页不宣称 Apple 支持。

## 隔离验收与边界

| 检查 | 结果 | 证明范围 |
| --- | --- | --- |
| 共享 Rust transport | 95 library + 1 CLI 通过 | 双 C fixture、自建 loopback；不使用真实主机 |
| overlay runtime | 33 项、严格 Clippy 通过 | 合成 ABI，不代表真实两网并发 |
| Flutter 原生 Rust | 双 fixture 13 项通过 | provider、route、身份和旧授权隔离 |
| Flutter JNI／Kotlin | 48 JNI 断言；登录 gate 15、身份 14、journal 64 个检查通过 | 桌面 JVM、合成 Android／存储，非手机 KeyStore |
| Flutter Dart | 57 个文件语法检查；新增 29 条待 CI 场景 | 未运行 analyzer、Flutter tests 或 widget |
| Tauri | Rust 42、Node 115、Vite build、Kotlin 26 个检查通过 | 宿主方法类型检查、伪 DOM、合成 SDK；非 Android target |
| 原生构建工具 | 29 项通过；真实已有 Go 缓存归档校验通过 | 编译参数／归档／APK 负例；未编译 Android 库 |
| Flutter 构建工具／共享校验和 | 8 项／46 个文件通过 | 复制与来源规则；不等于实际 Gradle 装包 |

transport 严格 Clippy 本轮仍失败：12 个去重诊断，明细见证据。依赖与默认 Tauri check 还有原有 warnings。完整 transport 首轮在沙箱内遇到 loopback 限制，终止该自有测试后在沙箱外重跑；新增停止测试首轮错误码期望不符，按实际合同修正后通过。不将这些失败或语法检查算作设备通过。

## 后续 Android 集中批次

[组网工作流](../.github/workflows/android-network-experiment.yml)已增加 Tailscale 与 EasyTier 同源装包。Tailscale 固定 v1.104.1，Go 1.27.3；Android NDK 28.2.13676358、API 35、arm64-v8a。构建参数先经 Context7 查询，再用 [Go cgo 文档](https://pkg.go.dev/cmd/cgo)和 [NDK 外部构建说明](https://developer.android.com/ndk/guides/other_build_systems)核对。16 KiB 链接对齐参数依据 [Android 页大小文档](https://developer.android.com/guide/practices/page-sizes)，不代表实际整包已通过 16 KiB 设备验收。

原生 bundle 包含两个库、固定 Go module zip、补丁后的上游 tar、模块源码、锁和日志。验证从仓库固定 go.sum 重算上游 `h1`，逐文件核对补丁后的 tar；缺失、额外、重复、链接和逃逸项拒绝。不能通过同时改 tar 和产物 manifest hash 伪造固定来源。两 GUI 包再核对两个库的原始字节、JNI 导出和 DT_NEEDED。

一个同时链接两 provider 的宿主库需要完整 DT_NEEDED 集合；缺任何库，整个宿主不可加载，不能宣称另一 provider 仍可用。单 provider 构建另有 feature，但不冒充双网包。构建只使用云端固定工具链，本机没有安装 SDK／NDK。工作流仍只在显式批次分支或手动入口运行，不随日常开发提交启动。

下一阶段先完成 ZeroTier 的状态托管、逻辑 socket 与并发隔离，再集中验证累积的两套手机 GUI 和 Android 包。随后补桌面分屏和其他平台安全存储。三网 15 格与并发 20 格不因本批隔离结果变绿。真实登录往返、Android loader／KeyStore、SSH 经实际 Tailscale、相机、IME、触控、长时运行、iOS 签名与完整分发许可仍需独立验收；没有这些证据就不收敛最终框架或高保真。
