# 双网络隔离验收进展

更新：2026-11-15。本文记录 [M2 的 Tailscale + EasyTier 前台并发要求](04-roadmap.md#m2--按-provider--平台集成三网络)的分层证据。当前已完成 **Mac 本机单 Tailscale 产品 Go 链路与夹具生命周期**；本页尚未记录 Linux 双网或 Android 通过结果。

## 已通过的单 TS 原生链路

源码 `1476597`，固定 Tailscale `v1.104.1`（`9a522a9786c97eb7910c01ccb7bd66557b04c910`）及既有 `ExplicitAuthOnly` 补丁。在 macOS 27.2.1 arm64、Go 1.27.3 上，用三个独立进程运行实际产品 manager/adapter；节点经真实 `tsnet.Server.Dial` 传输 TCP，并非 C fixture。原始阶段结果、模块/补丁/源码/二进制哈希见[脱敏 JSON](evidence/dual-overlay-20261115/tailscale-product-local-macos.json)。

三次均完成：节点启动但未登录时，底层 engine 不返回 AuthURL，产品 Dial 被拒绝；显式 begin login 后取得本次可核对的 HTTPS URL；仅临时内存控制面完成该授权；节点 Running 后往返 37 字节（含中文和 emoji），完整等值；最后 close/release 后产品 node、stream 与对端连接均为 0。测试还执行上游 `ResourceCheck`。

控制面、DERP/STUN 和真实对端来自同版官方 `testcontrol`/集成测试组件。控制面使用单次生成的 CA 与 loopback HTTPS 证书，身份使用内存 store；Mac 进程受仅允许 localhost 出站的沙箱限制，关闭日志上传。测试 CA 只在测试进程生效，没有修改 Keychain 或系统 trust。授权 URL 不进入归档。

独立夹具进程检查还验证：ready 时对端已 Running 且虚拟 TCP 2222 已监听；未签发的授权 URL 被拒绝；stop 后清理事件连接计数为 0、进程退出 0；退出后控制面/DERP 的 TCP 端口拒绝连接，STUN UDP 端口可重新绑定。

标准候选构建的补丁测试、Go race 检查（30 passed，两个显式真实网络入口默认 skip）、c-shared 链接及 ABI 未启动加载检查均通过。**动态库加载检查没有启动节点；上述真实 TCP 是 Go 产品 manager/adapter 回归，没有跨 C ABI。**

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

## 待补的双网及平台结果

Linux 的 [可选双网 runner](../validation/overlay-runtime/dual-overlay-loopback/README.md)与[工作流](../.github/workflows/dual-overlay-herdr-validation.yml)已实现同一个 `OverlayRuntime` 下两套真实 provider、两台临时 SSH/herdr 主机与受保护输入。验收须同时保留：pre-login 拒绝；两边实际完整帧与准确输入；独立 case 分别停 EasyTier、停 Tailscale，旧输入拒绝且另一网下一次输入仍成功；独立远端字节记录；两个观察任务退出以及节点、流、夹具进程与 namespace 清理。**代码存在不计为运行通过。** 后续在本节补运行/工件及脱敏 manifest，单方向结果只按该方向记录。

交叉 provider 的不同虚拟 IP 与可用系统 loopback 被拒绝，不等于重叠虚拟地址已验证。Android 两壳的正常 UI、存储桥及会话切换须另验；本页目前不新增平台支持格。所有本地控制面结果均不证明 Headscale/商业协调面互通、个人 tailnet、物理网络或后台常连。
