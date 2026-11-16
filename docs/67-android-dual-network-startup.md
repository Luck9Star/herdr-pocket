# Android 双网启动与会话阶段证据

截至 2026-11-17，**Flutter / Tauri × 先停 TS / 先停 ET，4/4 个设备案例全部通过**，两壳采用同一原生源码 `547106ea172dfd055c3bf9fdb2f4e2a27c9ff2f8`。两种顺序均证明幸存网络在原 SSH 认证会话继续输入，被停网络输入不变并关闭，最后显式关闭另一端且受检清理通过。此前交接见[第 66 页](66-iteration-handoff-2026-11-16.md)。

这是 **API 35 x86_64 Android 模拟器**与**两个实际运行的受控 SSH 服务**上的验收，使用临时隔离控制面；不是物理真机或用户生产网络验收，不能外推到 Android arm64、真实中文 IME、三网或五平台。

## 当前已通过的设备证据

| 客户端与来源 | 先停 TS | 先停 ET | 结果与清理 |
| --- | --- | --- | --- |
| Flutter：[43942704918](https://github.com/Luck9Star/herdr-pocket/actions/runs/43942704918)，客户端 / 驱动 `23a6bd9`，native `547106e` | ET 原认证 `ordinal=1` 精确续输 `Ee`；TS 输入不变且 inactive | TS 原认证 `ordinal=1` 精确续输 `Tt`；ET 输入不变且 inactive | 两案例 `passed / complete`，设备 job success，最终双方 inactive，受检清理通过 |
| Tauri：[43941511775](https://github.com/Luck9Star/herdr-pocket/actions/runs/43941511775)，客户端 / 驱动 / APK `b0f1df6`，native `547106e` | ET 原认证 `ordinal=1` 精确续输 `Ee`；TS 输入不变且 inactive | TS 原认证 `ordinal=1` 精确续输 `Tt`；ET 输入不变且 inactive | build / paired-device job 均 success，两案例 complete，最后分别显式停网并确认 SSH 关闭，受检清理通过 |

两壳均经过显式授权、双端配对 / 绑定及不同目标输入审查。Tauri 两方向 `after_second_ack` 的双端审计均为 `acceptedSessions=1 / newSessions=0`：幸存端原会话 active、精确 2 字节，被停端 inactive、精确 1 字节；每次显式 stop 均仅发送 1 次、resolved 1 次、rejected 0 次。停 TS 返回后活动状态为 `[TS=false, ET=true]`，反向为 `[TS=true, ET=false]`；从基线到第二 ACK 分别为 12,137ms / 12,406ms，**不代表底层在该间隔完全无包**。`capturedBytes` 是受检终端输入，不是 SSH 协议总流量。

[合并脱敏证据](evidence/android-dual-startup-20261116/dual-session-stage-20261117.json) 记录完整源码、APK、manifest、native、host 来源，以及结果 ZIP / 解包 JSON 各自的 SHA-256。当前 Flutter 结果工件 `14265290882`、Tauri 结果工件 `14263169661` 均已重下官方小型 ZIP，核对官方 digest，解包报告与本地 JSON 逐字节一致。Tauri 同源 normal / QA / auth APK 工件 `14263595863` 的包摘要由主控独立下载复算；APK 和结果 ZIP 不混作同一种摘要。

两壳固定 host 来源均为 `5404adfb3c86f5174edda38f1d0c63c8d81996c5`；客户端源码分别为 Flutter `23a6bd9816681cec6ba7292a3e080d0a8acf9d81`、Tauri `b0f1df672fb304a86e3bb56dc2cf11c64856576a`。最终共享脚本回归 **435 项：430 通过、5 跳过**；Tauri 精确已验 APK 的回放配置已固定在 `afac8f21a4a1e2114ed591a7a42c2c8f5f935eaa`。这些本机回归与配置固定不增加设备覆盖范围。

GitHub 工件保留有限，APK 保留 7 天；过期后须按记录的完整源码与固定构建配置重建，再核对来源和包摘要。历史失败、Go 启动 gate、半关闭 / EOF、空闲读期限及真实页面 A/B 的证据与边界保留在下方；环境清理不替代产品连接关闭审计。

<details>
<summary>修复过程与上一阶段设备快照（历史，不替代当前结果）</summary>

以下保留正式双向成功报告到达前的阶段记录；“尚未”“待验”等仅描述各自历史快照，不回退顶部已通过的结果。

### Flutter 新原生库验收器前置失败与修正

首轮新原生库 Flutter [43941511771](https://github.com/Luck9Star/herdr-pocket/actions/runs/43941511771) 因驱动仍钉旧 native SHA 报 `native_source_invalid`，实际执行 0 个设备案例。驱动修正为 `23a6bd9816681cec6ba7292a3e080d0a8acf9d81`，新增 4 项来源反例后专项 35/35 通过，再实际运行顶部 [43942704918](https://github.com/Luck9Star/herdr-pocket/actions/runs/43942704918)，两案例均通过。前置失败仍按失败记账，不放宽来源或成功门槛。

截至 2026-11-17，**Flutter 已在 API 35 x86_64 AVD 上通过两个停网顺序的完整设备验收**：最新 [43926204997](https://github.com/Luck9Star/herdr-pocket/actions/runs/43926204997) 两案例均 `status=passed`、`stage=complete`，设备作业成功，双方最终关闭及环境清理均通过。Tauri 最新旧 APK 复跑 [43936402002](https://github.com/Luck9Star/herdr-pocket/actions/runs/43936402002) 两方向均完成配对及初始 `E` / `T` 输入；先停 TS 后原会话 `Ee` 续输、再停 ET 关闭已完整证明。先停 ET 后尚未发出第二字节，失败时两端均无活动 SSH，TS 后续 `t` 尚未证明，整轮仍失败。新的独立原生读取修复已构建并校验下载；采用它的新两壳设备结果尚未验证。此前交接见[第 66 页](66-iteration-handoff-2026-11-16.md)。

范围限于独占 Android 模拟器、临时隔离控制面和两个真实 SSH 服务。它们不是用户真实主机或生产网络；不能外推到物理手机、Android arm64、真实中文 IME、三网或五平台。

## 当前设备证据：功能与工作流分别判断

以下来自 GitHub 官方结果工件；重新下载后核验官方 ZIP SHA-256，解包报告与本地 JSON 逐字节一致。来源、两种摘要及最小审计字段见[合并脱敏证据](evidence/android-dual-startup-20261116/dual-session-stage-20261117.json)。ZIP 摘要和 JSON 文件摘要标识不同字节，不能互换。

| 客户端与顺序 | 已观察到的请求功能 | 最后收尾与本轮结论 |
| --- | --- | --- |
| Flutter，先停 TS；[43926204997](https://github.com/Luck9Star/herdr-pocket/actions/runs/43926204997)，源码 `14ecb4f` | 就地显式批准 TS 授权，两端各一次批准认证；TS 停后输入不变且 `inactive`，ET 保持原 `ordinal=1`，精确收到 `Ee`；没有新增认证会话 | 最后两端均 `inactive`，精确字节及原序号仍匹配；案例 `passed / complete`，设备作业 success，受检清理全部通过 |
| Flutter，先停 ET；同一运行、独立案例 | 就地显式批准 TS 授权，两端各一次批准认证；ET 停后输入不变且 `inactive`，TS 保持原 `ordinal=1`，精确收到 `Tt`；没有新增认证会话 | 最后两端均 `inactive`；案例同为 `passed / complete`，设备作业及受检清理均通过 |
| Tauri，先停 TS；[43936402002](https://github.com/Luck9Star/herdr-pocket/actions/runs/43936402002)，驱动 `fd9f0d0`、APK `ca8637c`、native `a9be92d` | 显式授权、双端配对 / 绑定及不同目标初始输入均已证；TS 停后输入不可用且字节不变，ET 在原认证会话精确收到 `Ee` | 两次显式 stop 均各发送 / resolved 1 次、rejected 0 次；最后 ET 关闭确认通过，案例 `complete`。同轮反向失败，整轮设备作业仍为 failure |
| Tauri，先停 ET；同一运行、独立案例 | 双端配对 / 绑定及各一次批准 SSH 认证、初始 `E` / `T` 已证；ET stop 发送 / resolved 各 1 次 | `post_stop / dual_peer_evidence_timeout`，仍留网络页，未发第二字节；两端各 `acceptedSessions=1 / capturedBytes=1 / activeSessions=0`。未证明幸存 TS 原会话后续 `t`，也不能从这一采样断言唯一关闭原因 |

Flutter 两方向的 `auditProgress` 均为 `interimClosePending=false`、`stoppedCloseConfirmed=true`、`survivorSecondInputConfirmed=true`；最终审计两侧各只保留原批准认证序号、`newSessions=0`、无错误端新增字节且活动会话均为 0。`capturedBytes` 是终端输入审计，不是 SSH 协议总流量。未知、未到达的检查点不能填成 0 或通过。

两份当前报告各自记录受检安装包、forward/反向映射、私有目录、relay、控制服务和 namespace 清理成功。**实验环境清理成功不替代产品连接关闭证据**；Flutter 的最终关闭由前面的宿主审计另行证明，Tauri 的不足仍保留。Flutter 本次源码已包含下面的 EOF 回执竞态小修。

本轮四次配对的 `sawFutureIssuance` 均为 false，响应与设备时间窗口、精确线格式及五行预览均匹配；两方向都越过了旧配对卡点。这不反证旧轮次不存在时间边界，也不证明旧失败由时钟或 IME 引起。两方向的受检环境清理均成功；环境清理与产品 SSH 关闭仍分开判断。

最新 Flutter 工件为 `14257552054`，ZIP SHA-256 `85faff50ce4f11a5df14d91a56ff2bbd3367e6c9d53d8c460ae8be6afe9c75d6`；解包报告 SHA-256 `b986b9a952167a58370139408f8fd1045fa29eafe365d493e285ae273769bdf8`。客户端 / 驱动源码为 `14ecb4f9903db04119282e4b79d8db64ba38c32c`，native 和 host 继续采用下文固定来源。

## 启动 panic 与正确能力判断

[43873881946](https://github.com/Luck9Star/herdr-pocket/actions/runs/43873881946) 的 normal/QA 包均捕获到同一 panic 消息摘要 `7ccfbfe94828331c4bc8b556780ccf9f78afb3ad9c9228f4c7b80ed43c880758`，与 Tailscale v1.104.1 [`logpolicy.go:282`](https://github.com/tailscale/tailscale/blob/v1.104.1/logpolicy/logpolicy.go#L282) 的固定字面量一致；两条摘要均为 `origin=null`、`frames=[]`、`truncated=true`、`currentExit.available=false`，不能据此写成完整调用链或退出原因已取证。

固定上游 [`NewLocalBackend`](https://github.com/tailscale/tailscale/blob/v1.104.1/ipn/ipnlocal/local.go#L656) 在调用 `sockstatlog.NewLogger` 前先求值 `logpolicy.LogsDir`。正确修复把**相同能力条件 `sockstats.IsAvailable && buildfeatures.HasLogTail` 前移**：无能力的构建不探测日志目录；有能力分支保持原 logger 调用和错误处理。局部隔离 A/B 已证明旧顺序会探测目录并触发同摘要 panic，新顺序零探测正常返回；这不是 Android 文件系统或真实身份验证。

原生修复固定为 [`a9be92d`](https://github.com/Luck9Star/herdr-pocket/commit/a9be92d98b8c26b15ccbc7f6faa240ed3d674929)，normal/QA 构建及重下载校验见 [43877918495](https://github.com/Luck9Star/herdr-pocket/actions/runs/43877918495)。启动控制点 [43880234995](https://github.com/Luck9Star/herdr-pocket/actions/runs/43880234995) 两包均 `startOk=true`、`needsLoginReached=true`、`stopOk=true`、`passed=true`，状态为 `needs-login`，未 login 或 dial；同 UID 私有 stderr 摘要为空，受检 scope、identity、安装包、会话及 AVD/namespace 清理通过，见[启动短摘要](evidence/android-dual-startup-20261116/startup-probe-43880234995.json)。预登录控制点与上表授权、SSH、双网会话是不同证据层。

## Flutter 关闭顺序、真实 EasyTier EOF 与修复边界

修复前 [43917953870](https://github.com/Luck9Star/herdr-pocket/actions/runs/43917953870)（UI `624359c`）已证明先停 TS 后 ET 原会话收到 `Ee`，但附加停止 ET 的 **10 秒**等待以 `host_audit_close_timeout` 结束。该案例共 82 条两端审计，其中关闭等待 38 轮、76 条；ET 始终 `ESTABLISHED`，原序号和累计 2 字节不变。反向案例也完成两端初始输入，但首次 ET 停止审计发现仍活动即退出，未执行 TS 后续 `t`。这是当时的真实失败；不是配对失败，也不能推成远端永不关闭。

两处产品缺口有独立反例：真实 `HostCatalogPage → PairingPage → RemotePage` Widget 链路旧顺序为 `[provider.stop, A.cancel.started]`，因为页面销毁在下一帧才启动异步取消；另一个缺口是虚拟流强制退役不等于远端 FIN。固定 EasyTier 的 [smoltcp handle Drop](https://github.com/EasyTier/EasyTier/blob/728ba94b5029240add6204eed591f22e4e039e6b/easytier-core/src/gateway/smoltcp/tokio_smoltcp/socket_allocator.rs#L118-L122) 直接移除 socket，而[显式 shutdown](https://github.com/EasyTier/EasyTier/blob/728ba94b5029240add6204eed591f22e4e039e6b/easytier-core/src/gateway/smoltcp/tokio_smoltcp/socket.rs#L199-L214) 请求 FIN。真实 smoltcp 0.14.0 回环 A/B 分别得到对端 `Established / EOF=false` 与 `CloseWait / EOF=true`。

更直接的**真实 EasyTier C ABI** A/B 使用 macOS arm64 原生库、两个自有节点和用户态 TCP 转发到自有回环 echo：两组精确字节均匹配；旧 `stream_close` 没有 peer/return EOF，`shutdown_write` 则两向 EOF 均成立。库 SHA-256 已与结果独立核对，载于合并摘要。它不是 SSH、Android 或该 Android 原生库的验收；不能以本机 native A/B 替代上表设备结果。

产品修复立即封住受影响标签的输入，只等待这些标签的本地清退，外层最多 5 秒；显式用户停网还在 `dartssh2 4.1.0` 取消原读订阅前，排空原队列、复用已有 `streamShutdown`，最多 1 秒等待原读泵 EOF，随后完成本地退役。超时/失败仍允许停节点并保留“SSH 清退未确认”，不重放写或停止；另一网与原会话不变，硬取消/标准直连合同保持。原生二进制无需变更。`closed:true` 只确认本地退役；远端关闭仍必须看宿主审计。新一行修复另覆盖“原读 EOF 比 shutdown 回执早”的误判，预算外晚完成仍不能翻转未知结果。

## Tauri：真实页面触摸对照，不预填 Android 修复通过

旧产品 `4215dcf` 的真实 Chrome 157 对照中，正常 mouse 点击为 1 次原生确认 / 1 次准确 ET stop；按住后完成一次相同状态刷新再释放，按钮 DOM 已替换，确认 / stop 均为 0。新产品 `9c774137`（工作提交 `3fe0862`）在**真实 touch 和 mouse** 下，相同刷新保留同一受审查按钮，各为 1 次确认 / 1 次准确 ET stop；绑定改变则必须生成不同节点，旧手势保持 0 / 0。已独立回放同一产品模块与原生浏览器确认，后端是隔离替身，不是 Android WebView/设备证据，也不保证上述每个旧设备错误只有同一原因。

本机 Flutter 完整 `test/`：`624359c` 为 **576 通过 / 7 跳过 / 0 失败**；设备源码 `16792660f` 为 **587 / 7 / 0**；含 EOF 回执竞态小修的 `8cd02a0` 为 **589 / 7 / 0**，三份 JSON 事件均 `done.success=true`。7 项是另行运行的真实 GUI/SSH、双会话或旋转用例，不能计作通过。Tauri 最新本机测试为 transport **125 通过 / 1 既有忽略 / 0 失败**、后端 **81 通过 / 0 失败**、前端 **630/630**，Vite 构建通过。transport 的忽略项是另需隔离 Paramiko 环境的 RSA SSH 用例，不能计作通过。对应候选为 `0b4b665`、`ca8637c`（工作提交 `81097f4`、`ffb2d7e`）；这些本机测试不补写 Android 缺失方向或工作流绿灯。

主控另独立运行 `ca8637c` 的共享 remote-harness 全量 414 项（5 跳过、0 失败）与 helper 15 项全部通过；它们是本机回归，不替代设备结果。

Tauri 新的显式 stop 先封住完整绑定的新尝试，只退休本次捕获的 owner / generation；最多 12 秒优雅退出，再对相同目标有界强制清退 2 秒。实际 I/O 未退休时保留停止围栏并报未确认，只有用户再次显式操作才重试；不自动重连或重放。成功完成的旧 stop 准入在同一锁内解除，不能释放下一代同绑定 stop。该源码 `ca8637cc29a429b1bab78a35746dae9bc6858679` 的 [43928408381](https://github.com/Luck9Star/herdr-pocket/actions/runs/43928408381) 同源 normal / QA APK 构建成功；设备中先停 TS 的案例已完整通过这些检查，反向因更早的配对卡点未执行 stop。当时后续的 `43933099218` 同 APK 复跑也未越过配对前置条件；更晚 `43936402002` 已越过配对，但反向停网后续输仍未证明，不能追加反向或整轮通过结论。

Tauri 此轮仍复用源码 `ca8637cc29a429b1bab78a35746dae9bc6858679` 的 QA APK（SHA-256 `7cd284ae5aa6969f033acee29cc82f7ba1b3b5d394c1337289c49a887a7efb72`），驱动为 `fd9f0d052b580709ab6d927eb5f9ab0fc65bde94`。结果工件 `14262236647` 的 ZIP SHA-256 为 `a04dbc120bec37cd99554b90fa1bf72bdd0019b0e73fb9b8b1b4b42e4bdaf2f2`，解包报告为 `4ec5116d4d99c6f82064d226dbaf928bcf8e9af7c47b646af73941ce8ad60950`；已重新下载小型 ZIP 核对官方 digest，报告与本地 JSON 逐字节一致。未重复下载大型 APK。

## 独立原生读取修复：已构建，尚无新设备结论

[`547106e`](https://github.com/Luck9Star/herdr-pocket/commit/547106ea172dfd055c3bf9fdb2f4e2a27c9ff2f8) 修复 TS 原生流读取的期限竞争：Tauri 请求的 10 秒空闲读取与同期限硬看门狗竞争，可能强制退役仍正常的 SSH 流。受控相同用例旧版失败，新版连续 3 次空闲后仍在原连接收到后续字节；另覆盖真实 TCP、挂死读取的硬期限、结果未知写及 Go race。本次设备采样没有完整原因链，**这项独立可复现缺陷不能被写成上述双端关闭的唯一原因**。修复为正常读提前最多 100ms 留出完成发布窗口，在释放单次读槽后发布结果，硬期限处仅接受已经发布的读结果；挂死读仍有界关闭，未知写不重放。

[43939326685](https://github.com/Luck9Star/herdr-pocket/actions/runs/43939326685) 的 normal / QA 原生构建和独立下载复验均 success：normal 工件 `14261768985`、ZIP SHA-256 `23bdd1d79ded537d64fec25e9926f56a75c7ac3bf0f6f1b71e517bf67e8e0f3d`；QA 工件 `14261004231`、ZIP SHA-256 `ac4fbf7c5c5de8d6aa1c0f695fdf0e5f43a1e7a9afa98a1b3a57e47695f1c769`。下载复验报告明确为 `androidLoad=not run / node=not run`；不能替代新两壳的 Android 加载、授权、SSH 或两向停网验收。此前 Flutter 通过和 Tauri 部分结果使用的仍是 `a9be92d`。

驱动 `fd9f0d0` 的完整共享脚本回归为 423 项：418 通过、5 跳过。真实 Chrome 与产品按钮的独立时间边界对照中，同一响应在签发前查看显示无效；时间生效后仅轮询不改变预览，再次明确“查看”才显示五行，未产生原生授权写入。这是受控浏览器证据，不是前次模拟器失败的原因证明。

新两壳候选 `b0f1df672fb304a86e3bb56dc2cf11c64856576a` 对应 Flutter [43941511771](https://github.com/Luck9Star/herdr-pocket/actions/runs/43941511771) 与 Tauri [43941511775](https://github.com/Luck9Star/herdr-pocket/actions/runs/43941511775)，设备结果待正式报告核对，未计入通过。主控比对确认相对旧 Tauri APK 源码 `ca8637c`，Flutter `lib`、Tauri 与 transport-rust 无产品差异；本轮产品变化是共享 Go core。最新本机共享脚本 431 项（426 通过、5 跳过）及 92 项专项通过，不替代这两次设备结果。

GitHub 运行工件保留有限，当前 APK 工件保留 7 天；过期链接不能充当长期下载承诺。复验须按记录的完整客户端、native、host 提交及固定构建配置重建，再分别校验来源和包摘要，不以旧工件代替新源码。

## 固定来源与历史参考

Android 两壳的 `HOST_SOURCE=5404adf` 与已校验 ZIP 继续固定：工件 `14171011473`，ZIP SHA-256 为 `4bdc54843a9f438896db3717bd002859021fab51cbe60339c35e8a62a5bd6698`。它们标识 herdr / peer / ts-fixture 二进制与对应 bundle verifier 的来源，不代表运行期所有 Python 都来自旧 host checkout。

[android_dual_overlay_session.py](../validation/remote-harness/android_dual_overlay_session.py) 的 bundle 校验调用旧固定 `source_checkout`，随后实际启动的是当前 `HERE/android_dual_overlay_hosts.py`；[当前 controller](../validation/remote-harness/android_dual_overlay_hosts.py) 再导入当前 `paired_dual_demo.prepared_pairing_hosts`。所以本次权限修复随新的客户端 / 驱动源码进入两壳设备执行，无须更换固定 host ZIP 或重复编译 native。应分别记录运行期客户端源码 SHA 与固定 host 二进制来源；旧结果中的 `hostSourceSHA=5404adf` 不能被解读为全部运行期 Python 的源码 SHA。

两壳共用的隔离 sshd 原先设置 `AllowTcpForwarding no`。Flutter 产品通过 `direct-streamlocal` 读取 herdr Unix socket；固定 OpenSSH **9.6p1** 的 [`session.c:320–333`](https://github.com/openssh/openssh-portable/blob/V_9_6_P1/session.c#L320-L333) 显示，该设置会关闭共同的本地 channel 权限；[`channels.c:4591–4618`](https://github.com/openssh/openssh-portable/blob/V_9_6_P1/channels.c#L4591-L4618) 对 Unix path 也检查该权限。因此这是已确认的夹具权限缺陷，可解释“SSH 公钥认证成功但无法打开 herdr socket”的链路；它不单独证明每轮设备失败只有这一原因。

夹具原始修复提交 `bb24534` 将策略收窄为 `AllowTcpForwarding local`、`AllowStreamLocalForwarding local` 和 `PermitOpen [本次唯一 herdr Unix socket 完整路径]:*`。方括号是配置解析所需语法；并未开放任意 TCP 目标。实现与可选真实回归见 [paired_dual_demo.py](../validation/remote-harness/paired_dual_demo.py) 和 [test_paired_dual_streamlocal.py](../validation/remote-harness/test_paired_dual_streamlocal.py)。

完全自有的临时密钥、授权文件、known_hosts、Unix echo 与仅监听 `127.0.0.1` 的 sshd 冷启动 A/B 已通过，见[脱敏摘要](evidence/android-dual-startup-20261116/shared-host-streamlocal-20261117.json)：旧配置目标 Unix socket 接受数 0；新配置唯一目标接受数 1 且回显字节相等；另一个真实存在的 Unix socket 与真实 TCP 监听目标在两轮均接受 0，TCP 明确返回 `administratively prohibited`。两轮分别完成 3 次临时公钥认证，避免将未认证误当作权限拒绝。**实测版本是本机 OpenSSH 10.5p1，不是 Linux OpenSSH 9.6p1 实测**；9.6p1 结论来自上面的固定源码。该实验没有使用用户 `.ssh`，也不是 herdr `session.snapshot` 或 Android 设备通过证据。

这里的双端输入证据来自隔离验收链路，不扩展为 stock herdr 所有版本的输入能力。独立源码/逻辑反例核查确认：原会话判据拒绝新认证、序号变化和错字节；它支持判据，不替代实际设备检查点。

</details>

<details>
<summary>历史前置证据与早期 UI 诊断（不替代当前结果）</summary>

以下段落保留当时检查点、局部实验与未完成范围；其中“尚未取得”只描述各自历史运行，不回退本页顶部的新设备证据。

### Tauri 旧 APK 的配对前置阶段：43928408381 / 43933099218

| 客户端与顺序 | 已观察到的请求功能 | 最后收尾与本轮结论 |
| --- | --- | --- |
| Tauri，先停 TS；[43928408381](https://github.com/Luck9Star/herdr-pocket/actions/runs/43928408381)，驱动 / APK `ca8637c` | 显式系统授权、双端配对 / 绑定及不同目标输入均已证；TS 停后输入不可用且字节不变，ET 在原认证会话精确收到 `Ee` | 两次显式 stop 均仅发送 1 次、resolved 1 次、rejected 0 次；最后 ET 关闭确认通过，案例到达 `complete`。同轮反向失败，因此整轮设备作业仍为 failure |
| Tauri，先停 ET；同一运行、独立案例 | 两节点启动及 TS 显式授权已证；尚未取得双端配对和 SSH 输入证据 | `pairing / dual_driver_failed`，安全细分为 `control_missing`；失败时两侧批准 SSH 会话数、输入字节均为 0。未执行停 ET 或幸存 TS 后续 `t` |

同一 Tauri APK 的新驱动复跑 [43933099218](https://github.com/Luck9Star/herdr-pocket/actions/runs/43933099218)（驱动 `4603e304`，APK 仍为 `ca8637c`）两方向均为 `pairing / dual_pair_step_timeout`，未进入 SSH。先停 TS 的方案已先完成 TS 配对，随后 ET 来源审查超时；先停 ET 的方案在 TS 来源审查超时。两者均已完成响应预览，但 `pair_source_review` 的 `checked=false`、`asyncReady=false`、`ready=false`；控件在场、可见、可用且命中目标。**这是配对审查前置条件未满足的记录，不能证明时钟或 IME 是当时原因**，也不能把未执行的停网方向写成产品失败或通过。两份新报告均记录受检环境清理成功。

Tauri 固定 APK 来源为 `ca8637cc29a429b1bab78a35746dae9bc6858679`，已执行 QA APK SHA-256 `7cd284ae5aa6969f033acee29cc82f7ba1b3b5d394c1337289c49a887a7efb72`；构建工件 `14258256260` 的官方 ZIP SHA-256 `d811fa432ee26033081095413b7267254079053b7ab273c2d182e5b47dd75b6b`。结果工件 `14257894041` 的 ZIP / JSON 摘要分别为 `f5931f79b3ddb9253dfa9610a63868b1bfff80d9aea99a38e8ed2f65b6050ecd` / `f78bac32150ddecd7b0ec74691163a5fbe93033e7a44cace6aad2a954356e3bd`；新驱动复跑结果工件 `14259867977` 分别为 `a04b138d6a67126329e475cb7b7b1a47ab494aaa9142376e376d1e304d9c8e92` / `172dbedfef20f3d36bc8973c3c00a4f8bed202efd3340c9f1fecca494e7b3341`。两份小型结果 ZIP 均重新下载核对官方 digest，报告与本地 JSON 逐字节一致；未因此重复下载大型 APK。完整客户端 / 驱动 / native / host 来源载于合并 JSON。

### Tauri 早期部分结果：43914151903

以下保留旧驱动 `2ba07d0`、APK `372430f` 的原结论，供区分旧停止确认卡点与后续配对卡点；不替代顶部新版结果。

| 客户端与顺序 | 已观察到的请求功能 | 最后收尾与本轮结论 |
| --- | --- | --- |
| Tauri，先停 TS；[43914151903](https://github.com/Luck9Star/herdr-pocket/actions/runs/43914151903)，驱动 `2ba07d0`、APK `372430f` | 显式系统授权、双端配对/绑定、不同目标输入均已证；TS 累计 1 字节后活动会话为 0，ET 在原认证会话累计精确 2 字节；`survivorSameAuthenticatedSession=true`，停止侧输入不可用且无新增 | 到附加 `stop_survivor`，报 `dual_confirmation_not_observed`；没有最后 ET 关闭证据。运行及修复 APK 驱动回放 job 均失败 |
| Tauri，先停 ET；同一运行、独立案例 | 双端配对/绑定及不同目标输入已证；两侧各一次批准认证、各 1 字节 | 在首次停网确认处报 `dual_confirmation_not_observed`，阶段仍为 `connect_and_input`；失败采样时两侧各 1 条活动会话。未证明 ET 停止及幸存 TS 原会话后续 `t` |

### Flutter 上一轮：功能及关闭已证，严格回执失败

[43923493989](https://github.com/Luck9Star/herdr-pocket/actions/runs/43923493989)，源码 `16792660f`，两个案例均已取得原认证序号 1 的精确 `Tt` / `Ee`、被停端不增字节和双方最终 `inactive`；但案例停在 `both_stopped_audit / device_result_invalid`，设备作业 failure，历史失败结论不改写。工件 `14255930995` 的 ZIP SHA-256 为 `9a236434e67c9b1fc868eda80a399028cec12ae5294c124cf73dbba41f32abae`，报告 SHA-256 为 `325d9806a047bd51be3d765aaf79c745cca4fd2b0cb29f85a45d4e3fa79ed402`。

后续 `14ecb4f` 修正的是 ADB 私有结果读取：使用携带远端退出状态的 shell 通道，先核对固定 `PRESENT / MISSING` 分帧，再读取内容，失败或非预期帧仍拒绝；全部检查点完成后，针对进程退出与原子发布结果之间的竞态，仅补一次只读读取。没有放宽授权、原认证序号、精确字节或双方关闭门槛；顶部最新结果来自重新实际运行。

### f65ac16 阶段与授权接收器前置检查

较早两壳对照均来自 `f65ac16`、API 35 x86_64 模拟器，原生仍为 `a9be92d`；公开字段见[阶段摘要](evidence/android-dual-startup-20261116/stage-boundary-20261117.json)。表中的“两方向”是两个独立案例，实际停网尚未执行。

| 已完成运行 | 确实取得的证据 | 尚未取得的证据 |
| --- | --- | --- |
| Flutter [43907454734](https://github.com/Luck9Star/herdr-pocket/actions/runs/43907454734)，两个案例均失败于 `ts_remote_marker` | 每例 ET / TS 各 1 次批准认证、各 1 个活动会话；ET 精确输入 `E` 已由原会话序号 1 审计；TS 真实终端、首帧及 marker 均已出现 | 栈停在 `dual_overlay_ui_steps.dart:427` 的单标签数量断言；TS 尚未发送 `T`，两网均未停。不能把双机同时认证写成完整双网输入或断网通过 |
| Tauri [43907454400](https://github.com/Luck9Star/herdr-pocket/actions/runs/43907454400)，两个案例均停于 `device_auth_handler` | `onlyLoopbackApproved=true`、`linkHandlingAllowed=true`；查询为系统 `resolver`；候选 2 含自有 receiver，其他域仅 browser 且不含 receiver | 产品尚未启动。旧预检要求 handler 必须直接等于 receiver，误拒了该 resolver；后续仅允许确切自有 receiver 或经系统包验证的已知 ResolverActivity，真实前台 / 端口 / 单次同意仍须另验 |

Flutter 本机真实双标签 A/B 已校验按新主机标签限定观察对象的测试修复（`b38e366`）；这不回填设备 `T` 输入或停网结果。Tauri 单次诊断 [43905996068](https://github.com/Luck9Star/herdr-pocket/actions/runs/43905996068)（`9093dcb`）仅观察到窗口由产品转为系统桌面，activity 为歧义 `null`、窗口不稳定、未见本次回环端口；**不能据此确证退出原因或把桌面当接收器**，该次没有点击 chooser / 同意按钮。

接收器修复 `1a02edf` 已在真实 Android35 `android.jar` boot API 下通过 4 项本机 API / DEX smoke：旧代码使用的 `Files.readString/writeString` 在编译负例中被拒绝，新代码的受限文件流、同意监听器和 DEX 引用通过检查。此项不等于设备运行成功。当时修复后候选 `165a0476` 尚待设备复验，已接入实际 native 打开计数及清理前白名单失败诊断；后续已取得的结果以本页当前表为准。

### 首轮双网 UI 设备结果（历史）

首轮两壳均使用 API 35 x86_64 自有模拟器及隔离端点，源码 `04800eb`、原生源码 `a9be92d`；两次运行都失败，尚未证明双会话或停网方向通过。

- **Flutter**：[run 43880235321](https://github.com/Luck9Star/herdr-pocket/actions/runs/43880235321) 先停 ET 案例进入 `ts_pair_profile` 后测试失败。走到该步骤意味着授权对话框已实际读到 `running` 并关闭；报告中的 `needs_login` 是创建节点阶段的旧快照，不代表此时产品仍处于该状态。控制面记录一次授权完成及注册，但不单独证明 SSH 可用。先停 TS 案例在 `ts_identity_open` 测试失败，未发起授权；两方向都没有到 SSH host 审计。旧报告阶段过粗，不能断言失败唯一原因。
- **Tauri**：[run 43880235735](https://github.com/Luck9Star/herdr-pocket/actions/runs/43880235735) 先停 TS 案例在 `device_setup` 未完成原生树 / UI 就绪验证，具体原因未知。先停 ET 案例完成普通 WebView 首页核验，随后在 `network_ts_start` 因 `dual_action_unavailable` 失败，未进入双会话验收。首次设备摘要本身不能单独证明该失败由下述缺陷引起。

后续本地检查发现两个具体风险：Flutter 的主机绑定保存是异步的，原测试未等待绑定持久化和下一按钮启用；身份入口也可能在按钮尚未启用时点击。针对性修复等待真实绑定与控件就绪、只点击一次，并清除跨阶段旧状态快照；本机 Flutter 定向测试 2 项和 Python 检查 16 项通过。两次设备失败是否全部由这些竞态造成，仍需设备复验。

Tauri 另有可独立复现的产品缺陷：同源码真实 Chromium 中，`needs-login` 触发 `NetworkLoginPoll` 默认定时器时出现 `Illegal invocation`。完整真实产品面板对照使用**模拟节点读数**：旧版 `cards=0`、`loginVisible=false`、`readFailed=true`；修复后 `cards=1`、`loginVisible=true`、`readFailed=false`；两版均 `statusReads=1`。这是浏览器产品面板对照，不是 Android 设备验收；后续设备复验见下节。

### 后续 UI 设备复验与本机修复（历史）

下列运行均使用修复后的原生 `a9be92d`，保留[脱敏短摘要](evidence/android-dual-startup-20261116/ui-followup-20261116.json)。这些运行仍未到达双会话、停网与另一网续传验收点。

- **Flutter**：[run 43884776566](https://github.com/Luck9Star/herdr-pocket/actions/runs/43884776566)（UI `a741d67`）的先停 ET、先停 TS 两例均到 `et_pair_review`；[run 43887559248](https://github.com/Luck9Star/herdr-pocket/actions/runs/43887559248)（UI `38ae715`）两例均到 `et_response_preview`，且 `responseReceived=true`。后者脱敏栈指向 `dual_overlay_ui_steps.dart:324` 的预览存在性断言。响应已经收到，设备摘要没有证明设备时钟导致失败。两轮 `hostAudits=[]`，不能据此写成 SSH 或双网会话通过；两方向的受检清理均成功。
- **Tauri**：[run 43884776658](https://github.com/Luck9Star/herdr-pocket/actions/runs/43884776658)（源码与 APK 均为 `a741d67`）两个方向均实际解析到本应用原生 WebView 树，并完成普通 WebView 首页核验；失败时均保留一张网络卡片。先停 TS 案例在 `network_ts_start` 的 start 为 sent 1、resolved 0、rejected 1；先停 ET 案例的 TS start 为 sent 1、resolved 1、rejected 0，但随后在 `network_et_save` 返回 `dual_profile_missing`。因此不能把卡片保留、原生树可见或单次 start 成功写成双网启动与编辑全流程通过；两个方向的受检清理均成功。

后续本机真实 Chromium 使用隔离后端，独立重现 Tauri 状态轮询重建面板、摧毁 EasyTier 未保存草稿，以及后台身份读取与人工启动并发竞争。修复后继续读取状态，草稿输入框保持同一个 DOM 节点，人工启动只发出一次写操作；本机前端全套 **614/614 通过**。这是本机产品界面与隔离后端证据，不是 Android 双会话证据。发布候选固定于 [`372430f`](https://github.com/Luck9Star/herdr-pocket/commit/372430fe94459ad2cd7fd1e04eb61c2c45d9d99c)，其设备验收须以独立结果为准。

### 第四轮与后续已完成设备结果（历史）

下表均为 API 35 x86_64 模拟器上**已完成且失败**的运行，原生固定为 `a9be92d`，短摘要见 [ui-progress-20261117.json](evidence/android-dual-startup-20261116/ui-progress-20261117.json)。每轮均独立执行先停 ET、先停 TS 两个案例；到达某个测试阶段不代表实际停网步骤已经执行。

| 运行与来源 | 两方向实际到达的阶段 | 主机认证、输入与界面边界 |
| --- | --- | --- |
| Flutter 第四轮 [43891123475](https://github.com/Luck9Star/herdr-pocket/actions/runs/43891123475)，UI `372430f` | `et_response_saved`；响应已收到，输入与响应相等、页面在前台、响应分类 `valid`、`futureSeconds=0` | `hostAudits=[]`，没有可用 SSH 主机审计；不能将响应有效写成已保存配对或 SSH 成功 |
| Tauri 第四轮 [43891123962](https://github.com/Luck9Star/herdr-pocket/actions/runs/43891123962)，驱动 / APK `372430f` | 两方向均保留两张网络卡片，每方向 start 累计 sent 2、resolved 2、rejected 0；停在 `network_ts_authorize`，错误 `dual_authorization_receiver_missing` | Tailscale 控制面 `authCompletions=0`；没有 SSH 双端输入或双会话证据。节点启动不等于授权完成 |
| Flutter [43898262011](https://github.com/Luck9Star/herdr-pocket/actions/runs/43898262011)，UI `f8aa7ff` | 两方向均到 `et_remote_pane`；网络、主机密钥与认证检查为 `passed`，随后 `connection_failed`，面板数 0、首帧仍等待 | 每个方向 ET 均有 1 次已批准 SSH 公钥认证，`capturedBytes/newInputBytes=0/0`、活动会话 0；TS 认证 0、输入 0。不是两网会话通过 |
| Tauri [43897860683](https://github.com/Luck9Star/herdr-pocket/actions/runs/43897860683)，驱动 `3936905`，复用 APK `372430f` | 两方向在 `device_auth_handler` 停止，错误 `dual_auth_handler_scope_mismatch` | 实际验证只选中了受控 `127.0.0.1`，域外 URL 仍交给浏览器；但前后均为 `resolver`，没有执行授权审批，控制面授权完成数为 0 |

Flutter 的 0 字节来自主机端**终端输入审计**，不是 SSH 协议传输总字节。Tauri 缺少的 SSH 审计不能补写为 0；它的控制面授权计数也不能替代 SSH 认证计数。第四轮 Flutter 的响应检查没有证明设备时钟是失败原因；后续 Flutter 已确实走到一次 SSH 认证，仍未取得面板。

</details>

为保留追溯而不重复整轮时间线，早期失败的来源与边界保留在以下链接：

- 首轮 UI：[Flutter 43880235321](https://github.com/Luck9Star/herdr-pocket/actions/runs/43880235321)、[Tauri 43880235735](https://github.com/Luck9Star/herdr-pocket/actions/runs/43880235735)。
- 后续 UI：[Flutter 43884776566](https://github.com/Luck9Star/herdr-pocket/actions/runs/43884776566)、[43887559248](https://github.com/Luck9Star/herdr-pocket/actions/runs/43887559248)、[Tauri 43884776658](https://github.com/Luck9Star/herdr-pocket/actions/runs/43884776658)，见[后续短摘要](evidence/android-dual-startup-20261116/ui-followup-20261116.json)。旧前端候选 [`372430f`](https://github.com/Luck9Star/herdr-pocket/commit/372430fe94459ad2cd7fd1e04eb61c2c45d9d99c) 的本机浏览器结果不等于设备通过。
- 授权/SSH 前置阶段：[Flutter 43891123475](https://github.com/Luck9Star/herdr-pocket/actions/runs/43891123475)、[43898262011](https://github.com/Luck9Star/herdr-pocket/actions/runs/43898262011)、[Tauri 43891123962](https://github.com/Luck9Star/herdr-pocket/actions/runs/43891123962)、[43897860683](https://github.com/Luck9Star/herdr-pocket/actions/runs/43897860683)，见[阶段短摘要](evidence/android-dual-startup-20261116/ui-progress-20261117.json)。
