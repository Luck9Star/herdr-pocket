# 双网络隔离验收进展

更新：2026-11-15。本文记录 [M2 的 Tailscale + EasyTier 前台并发要求](04-roadmap.md#m2--按-provider--平台集成三网络)的分层证据。当前已验证 **Mac 本机单 Tailscale 产品链路**与 **Linux 测试用隔离 relay**；Linux 双网和 Android 应用尚未通过验收。

## 已通过的单 TS 原生链路

源码 `1476597`，固定 Tailscale `v1.104.1`（`9a522a9786c97eb7910c01ccb7bd66557b04c910`）及既有 `ExplicitAuthOnly` 补丁。在 macOS 27.2.1 arm64、Go 1.27.3 上，用三个独立进程运行实际产品 manager/adapter；节点经真实 `tsnet.Server.Dial` 传输 TCP，并非 C fixture。原始阶段结果、模块/补丁/源码/二进制哈希见[脱敏 JSON](evidence/dual-overlay-20261115/tailscale-product-local-macos.json)。

三次均完成：节点启动但未登录时，底层 engine 不返回 AuthURL，产品 Dial 被拒绝；显式 begin login 后取得本次可核对的 HTTPS URL；仅临时内存控制面完成该授权；节点 Running 后往返 37 字节（含中文和 emoji），完整等值；最后 close/release 后产品 node、stream 与对端连接均为 0。测试还执行上游 `ResourceCheck`。

控制面、DERP/STUN 和真实对端来自同版官方 `testcontrol`/集成测试组件。控制面使用单次生成的 CA 与 loopback HTTPS 证书，身份使用内存 store；Mac 进程受仅允许 localhost 出站的沙箱限制，关闭日志上传。测试 CA 只在测试进程生效，没有修改 Keychain 或系统 trust。授权 URL 不进入归档。

独立夹具进程检查还验证：ready 时对端已 Running 且虚拟 TCP 2222 已监听；未签发的授权 URL 被拒绝；stop 后清理事件连接计数为 0、进程退出 0；退出后控制面/DERP 的 TCP 端口拒绝连接，STUN UDP 端口可重新绑定。

标准候选构建的补丁测试、Go race 检查（30 passed，两个显式真实网络入口默认 skip）、c-shared 链接及 ABI 未启动加载检查均通过。**动态库加载检查没有启动节点；上述真实 TCP 是 Go 产品 manager/adapter 回归，没有跨 C ABI。**

## Mac 单 TS C ABI 独立进程

[脱敏结果](evidence/dual-overlay-20261115/tailscale-c-abi-local-macos.json)记录 macOS arm64、Go 1.27.3 的真实 c-shared C ABI 验证。产品侧与 fixture 分属新进程，仅通过 `SSL_CERT_FILE` 信任测试 CA；观察到 NeedsLogin → Starting → Running。登录前无 URL、拨号返回码 7；显式 begin 返回 0，取得本次授权后真实 TCP 数据往返等值，stream/node 的 close、release 均返回 0，未归还读缓冲为 0。该项不依赖 fixture 进程的全局状态，也不代表 Linux 或双网通过。

## Linux 单 TS C ABI 正负对照

[62fc7ea 运行 43723332026](https://github.com/Luck9Star/herdr-pocket/actions/runs/43723332026)以不同的新进程和临时 fixture 分别测试两种封闭 namespace，整体[比较记录](evidence/dual-overlay-20261115/linux-ts-cabi-62fc7ea/comparison.json)通过。仅 `lo` 的[负例](evidence/dual-overlay-20261115/linux-ts-cabi-62fc7ea/loopback/result.json)显示 `AnyInterfaceUp=false`，显式 begin 返回成功但没有 URL；控制面仅有健康检查的基线 key 请求，未收到第二客户端注册。[dummy 正例](evidence/dual-overlay-20261115/linux-ts-cabi-62fc7ea/dummy/result.json)的 `AnyInterfaceUp=true`，真实 C ABI 完成显式授权、Running 和中文/emoji TCP 字节等值，控制面收到产品节点的 key、noise、register 与 map 请求，TLS 错误数为 0；stream/node 关闭和释放均成功。两个 fixture、私有目录、进程和 namespace 均清理；另有[空闲 fixture 对照](evidence/dual-overlay-20261115/linux-ts-cabi-62fc7ea/idle/result.json)。这是不同进程的单网络对照，不证明同一节点随接口变化的恢复，也不证明双网或 Android。原始工件为 [14165522757](https://github.com/Luck9Star/herdr-pocket/actions/runs/43723332026/artifacts/14165522757)。

[0199351 运行 43723761543](https://github.com/Luck9Star/herdr-pocket/actions/runs/43723761543)使用严格有效的测试证书再次得到一致结果：[比较记录](evidence/dual-overlay-20261115/linux-ts-cabi-0199351/comparison.json)、[idle](evidence/dual-overlay-20261115/linux-ts-cabi-0199351/idle/result.json)、[lo 负例](evidence/dual-overlay-20261115/linux-ts-cabi-0199351/loopback/result.json)与 [dummy 正例](evidence/dual-overlay-20261115/linux-ts-cabi-0199351/dummy/result.json)均为原始脱敏输出。dummy 侧完成真实授权和 TCP 等值，控制面 key 2、noise 1、register 2、map 5、TLS 错误 0；清理通过。原始工件为 [14166185694](https://github.com/Luck9Star/herdr-pocket/actions/runs/43723761543/artifacts/14166185694)。此前故障对照中额外请求未支持的控制路径曾使 helper panic；该脚本问题已修复，不能作为产品节点授权失败的证据。

## Linux 双网首轮与修复

[bb8d4d3 运行 43716686689](https://github.com/Luck9Star/herdr-pocket/actions/runs/43716686689)的两个停网方向都在准备 fixture 时超时（[先停 ET](evidence/dual-overlay-20261115/linux-bb8d4d3-stop-et.json)、[先停 TS](evidence/dual-overlay-20261115/linux-bb8d4d3-stop-ts.json)），当时尚未建立双网会话。定位为将 herdr Unix socket 当普通文件等待；`9b9f781` 改为对应调用只接受真实 socket，普通 ready 文件仍检查文件类型，并加正反回归。该轮临时目录与自有进程已清理，但最终 namespace 收尾被只读 Go module cache 的删除错误中断；后续修复限定于本次私有缓存的自有目录，不跟随符号链接。

[9b9f781 运行 43718309246](https://github.com/Luck9Star/herdr-pocket/actions/runs/43718309246)已完成两种原生候选和 peer 构建，并启动两个临时 SSH/herdr pane 与两个真实网络 peer。两个独立 case 的产品节点在登录前均没有 URL、拨号被拒绝；显式登录后在等待期内未得到 URL（[先停 ET](evidence/dual-overlay-20261115/linux-9b9f781-stop-et.json)、[先停 TS](evidence/dual-overlay-20261115/linux-9b9f781-stop-ts.json)）。两例都未完成授权、未取得 full 帧，也未执行停网及输入步骤，不能记为双网功能失败或通过的判定。两个结果的节点/流与自有进程、临时凭据目录均已清理，namespace 无残留进程且已删除；TS peer 未走成功路径的 cleanup 握手，不将其 false 解读为已证实泄漏。

[3ccb3d4 运行 43720063786](https://github.com/Luck9Star/herdr-pocket/actions/runs/43720063786)增加了 begin 前的真实状态等待和不含 URL 的状态记录。两例均到达 NeedsLogin，显式 begin 已提交且返回成功，但此后仍停在 NeedsLogin、等待期内无 URL（[先停 ET](evidence/dual-overlay-20261115/linux-3ccb3d4-stop-et.json)、[先停 TS](evidence/dual-overlay-20261115/linux-3ccb3d4-stop-ts.json)）；未到 full、输入或停网。节点/流、临时目录与自有进程均清理，namespace 无残留进程且已删除。因此“没有先等 NeedsLogin”不足以解释失败；其具体原因仍须由后续独立对照确认。

上游生产进程会依据非 loopback 接口状态决定是否暂停控制连接；纯 `lo` 环境下，Go 测试进程的测试豁免和独立生产 C ABI 进程并不相同。后续 `affab12` 验证工作流为测试专用 namespace 加入单个无对端 dummy 和 TEST-NET `192.0.2.1/32`，并严格限制仅本机路由、不允许默认路由、网关或额外接口；不改变生产节点环境或启用自动授权。[运行 43721709449](https://github.com/Luck9Star/herdr-pocket/actions/runs/43721709449)的 Ubuntu namespace 预检已通过。两例均成功显式授权并到达 Tailscale Running，但观察输入尚未就绪（[先停 ET](evidence/dual-overlay-20261115/linux-affab12-stop-et.json)、[先停 TS](evidence/dual-overlay-20261115/linux-affab12-stop-ts.json)）；没有获得 full 帧、发送输入或执行停网，双网目标仍未通过。两侧观察任务、TS peer、节点/流、临时目录和进程均已清理，namespace 无残留并删除。

[7209b9d 运行 43723946869](https://github.com/Luck9Star/herdr-pocket/actions/runs/43723946869)补充两侧独立诊断（[先停 ET](evidence/dual-overlay-20261115/linux-7209b9d-stop-et.json)、[先停 TS](evidence/dual-overlay-20261115/linux-7209b9d-stop-ts.json)）。两套临时主机的本地、只读健康检查均通过 SSH pin/认证、snapshot 与输入能力；这些直连检查仅证明夹具健康。两例 Tailscale 已通过真实 overlay 的 SSH pin/认证、snapshot 和 full 并取得输入就绪，随后因另一侧失败而取消；EasyTier 在 SSH 握手阶段失败，peer 记录未接受任何 overlay 流。没有发送输入或执行停网；清理记录通过。后续通过真实 `OverlayDialer` 有界等待被动 SSH banner，并单独记录尝试及连接数，以检查 ET peer 路由是否需要收敛；这不是 Android 用户连接已验证的结论。

[c38b3de 运行 43726117143](https://github.com/Luck9Star/herdr-pocket/actions/runs/43726117143)在两个独立 case 中尝试有界、被动的 overlay SSH banner 就绪检查（[先停 ET](evidence/dual-overlay-20261115/linux-c38b3de-stop-et.json)、[先停 TS](evidence/dual-overlay-20261115/linux-c38b3de-stop-ts.json)）。Tailscale 两例均首次读到 banner；EasyTier 两例各尝试 246 次、产品接口返回 246 条已打开流，但 25 秒内未读到 banner，独立 peer 的接受流及后端连接均为 0。EasyTier 节点仅报告 engine_started，不能证明 peer 或路由就绪。两例本地 SSH/snapshot/capability 健康检查、显式授权和清理通过；本轮没有进入受保护观察、输入或停网，未证明双网成功。

## Linux 测试专用 relay

[614b295 运行 43719537144](https://github.com/Luck9Star/herdr-pocket/actions/runs/43719537144)在 Linux 隔离 namespace 的 relay 测试中 6/6 通过，覆盖三路并发 loopback 回显、拒绝错误所有者/非受控端口、关闭活动连接及 namespace 清理。它仅验证测试转发设施，没有运行真实 Tailscale/EasyTier peer 的联合会话，也没有安装、驱动 Android 应用或验证设备网络。

## 复现单 TS 回归

需要现有 Go 1.27.1 或更高兼容工具链、C 编译器、Python 3 和 Git；以下为实际验证过的 Mac 路径，临时目录可重新生成，无需原机器目录或个人账号。Go 下载阶段访问固定模块仓库；节点执行阶段仅允许 loopback。

在仓库根准备固定源码并构建候选：

```sh
scratch="$(mktemp -d)"
mkdir -p "$scratch/home" "$scratch/tmp"
python3 validation/native/tool/tailscale_candidate.py prepare "$scratch/candidate" --cache "$scratch/cache"
python3 validation/native/tool/tailscale_candidate.py build "$scratch/candidate" --cache "$scratch/cache"

isolated() {
  env -i PATH="$PATH" HOME="$scratch/home" TMPDIR="$scratch/tmp" \
    GOTOOLCHAIN=local GOENV=off GOFLAGS=-mod=readonly CGO_ENABLED=1 \
    GOCACHE="$scratch/cache/build" GOMODCACHE="$scratch/cache/modules" \
    GOPATH="$scratch/cache/gopath" GOPROXY=https://proxy.golang.org \
    GOSUMDB=sum.golang.org TS_NO_LOGS_NO_SUPPORT=true "$@"
}
(cd "$scratch/candidate" && isolated go test -c -tags hp_ts_test -o "$scratch/product.test" .)
cat > "$scratch/localhost-only.sb" <<'PROFILE'
(version 1)
(allow default)
(deny network-outbound)
(allow network-outbound (remote ip "localhost:*"))
PROFILE
for attempt in 1 2 3; do
  isolated env HP_TS_REAL_LOOPBACK=1 sandbox-exec -f "$scratch/localhost-only.sb" \
    "$scratch/product.test" -test.run='^TestRealHTTPSExplicitLoginAndTCP$' -test.timeout=90s -test.v \
    > "$scratch/attempt-$attempt.private.log"
done
```

每次退出码须为 0，阶段 JSON 须显示 pre-login 两项拒绝、显式 HTTPS 授权、Running、TCP 等值均为 true，node/stream/bridge 均为 0。每轮使用新进程，不用 `-test.count` 复用一次性测试 CA。测试超时或任一阶段失败即失败，不以随后成功覆盖失败记录。

控制面 + 对端的进程启动、私有授权交换、SSH bridge 与停止协议见[夹具说明](../validation/native/tailscale-runtime/fixture/README.md)。Linux 产品 Rust 进程在启动前仅通过 `SSL_CERT_FILE` 信任本次测试 CA；不会放松生产 HTTPS 或 SSH host pin。完整授权 URL 只经私有 stdin/临时文件交换，禁止发布原始日志和私有请求文件。

## 本机两目标配对夹具

[e86448e 的本机脱敏记录](evidence/dual-overlay-20261115/macos-two-paired-hosts.json)在 macOS loopback 使用两套真实 OpenSSH/herdr 与临时内存设备密钥：独立 host 指纹相符，交叉 request/response 和设备 SSH key 均被拒，两个已认证会话各收到准确的 10 字节，随后完成撤销和清理。配对请求本身并未签名，设备持有证明来自 OpenSSH 公钥认证。该项不经 overlay，也不覆盖 GUI、平台保险库或移动端受保护输入，不能代替双网络任务。

## Android x86_64 原生构建

[e2c19b8 运行 43720964247](https://github.com/Luck9Star/herdr-pocket/actions/runs/43720964247)构建并静态检查 EasyTier、Tailscale 与独立 Flutter JNI 桥的三个 Android x86_64 ELF；三者均为 `ET_DYN` / `EM_X86_64`。原始[原生构建工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/43720964247/artifacts/14164119259)的外层 ZIP digest 和清单 87/87 文件已独立核验；另一个 job 从下载工件重放验证成功（[脱敏结果](evidence/dual-overlay-20261115/android-native-e2c19b8-download-replay.json)，[原始工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/43720964247/artifacts/14164424875)）。这仅是 API 35 目标的 native 构建和 ELF 静态证据，没有加载 Android 库、启动节点、构建或操作 App，也没有设备双网结果。此前 `b250c58` 的三 ELF 已构建，但首次归档缺少一个源码文件，不能替代此轮完整归档。

## 待补的双网及平台结果

Linux 的 [可选双网 runner](../validation/overlay-runtime/dual-overlay-loopback/README.md)与[工作流](../.github/workflows/dual-overlay-herdr-validation.yml)已实现同一个 `OverlayRuntime` 下两套真实 provider、两台临时 SSH/herdr 主机与受保护输入。验收须同时保留：pre-login 拒绝；两边实际完整帧与准确输入；独立 case 分别停 EasyTier、停 Tailscale，旧输入拒绝且另一网下一次输入仍成功；独立远端字节记录；两个观察任务退出以及节点、流、夹具进程与 namespace 清理。**代码存在不计为运行通过。** 后续在本节补运行/工件及脱敏 manifest，单方向结果只按该方向记录。

交叉 provider 的不同虚拟 IP 与可用系统 loopback 被拒绝，不等于重叠虚拟地址已验证。Android 两壳的正常 UI、存储桥及会话切换须另验；本页目前不新增平台支持格。所有本地控制面结果均不证明 Headscale/商业协调面互通、个人 tailnet、物理网络或后台常连。
