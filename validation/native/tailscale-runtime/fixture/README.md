# 真实 Tailscale 隔离夹具

仅测试入口；不修改产品 adapter、HTTPS 策略、系统证书或用户身份。固定 `tailscale.com v1.104.1` 与仓库 `ExplicitAuthOnly` 补丁，共用官方内存 `testcontrol.Server`、`integration.RunDERPAndSTUN`，两个真实 userspace tsnet 节点。它不证明 Headscale/商业协调面、物理网络、设备 UI 或双 provider 并发。

## 构建

从仓库根使用现有准备工具；`candidate` 必须不存在，`cache` 是显式隔离的 Go 缓存目录：

```sh
python3 validation/native/tool/tailscale_candidate.py prepare "$candidate" --cache "$cache"
python3 validation/native/tool/tailscale_candidate.py build "$candidate" --cache "$cache"
```

Linux 动态库为 `$candidate/libhp_tailscale.so`，macOS 为 `.dylib`。`build` 的默认检查不会启动真实节点；下述两个测试均要求显式 opt-in，默认 skip。用同一个隔离 Go 环境（`GOTOOLCHAIN=local GOENV=off GOFLAGS=-mod=readonly`，自有 HOME/TMPDIR/GOCACHE/GOMODCACHE/GOPATH）在 candidate 根构建：

```sh
go test -c -o "$out/ts-fixture" ./fixture
go test -c -tags hp_ts_test -o "$out/ts-product-test" .
```

产品 adapter/manager 的实际 HTTPS、显式登录、Dial、读写与 close/release 回归：

```sh
HP_TS_REAL_LOOPBACK=1 "$out/ts-product-test" -test.run='^TestRealHTTPSExplicitLoginAndTCP$' -test.timeout=90s -test.v
```

每次使用新进程；测试根 CA 仅在测试进程中通过 `x509.SetFallbackRoots` 与 `GODEBUG=x509usefallbackroots=1` 生效，不修改 macOS Keychain。普通产品进程不包含这个测试信任入口。重跑使用新进程而非 `-test.count`。

## Rust/Linux 进程协议

在 disposable Linux network namespace 中运行，仅启用 `lo`，不设置公共路由。无需 TUN 或系统 Tailscale 客户端；namespace 的建立由外部 runner 负责。测试进程禁日志上传、所有控制面/DERP/STUN 仅 loopback。macOS 本机验证也应使用仅允许 localhost 出站的进程沙箱。

先启动临时 loopback SSH/herdr 服务，再用唯一、空的 owned 目录启动 fixture：

```sh
HP_TS_FIXTURE_WORK_DIR="$fixture_work" HP_TS_FIXTURE_BRIDGE="127.0.0.1:$sshd_port" \
  "$out/ts-fixture" -test.run='^TestServeFixture$' -test.timeout=180s
```

夹具会先做一次 loopback TCP 可达性检查，不发送认证或应用数据；runner 应在 ready 后采集 sshd 审计基线。此后只有虚拟 TCP `peerIp:2222` 监听接受的流才桥接到该 SSH 服务。省略 bridge 仅供产品 Go 回归回显，不是 SSH 验收。

stdout 为下列 JSON 事件行；Go 测试框架退出时可能另写 `PASS`，只解析 JSON 行并检查最终退出码。任何非零退出码、未知事件、超时、`ok:false` 或清理计数非零都应失败。失败的测试原始日志只留私有工作目录，不直接归档，避免框架错误日志扩大证据内容。

1. `ready`：`controlUrl`（临时 HTTPS origin，不含授权令牌）、`caFile`（测试 CA 公钥绝对路径）、`peerIp`、`peerPort:2222`、`derpPort`、`stunPort`。此时控制面与 DERP/STUN 已启动，真实 peer 已完成本内存控制面的显式授权、处于 Running 且虚拟 TCP 正在监听。fixture peer 的私钥仅在内存。
2. 私有 stdin：`{"op":"complete_auth","url":"<产品本次 HTTPS 授权 URL>"}`。响应 `{"event":"auth_completed","ok":true}`。仅当前 control origin 及已生成 auth path 会成功；不回显 URL，不连接个人 tailnet，不批准真实设备。**完整 URL 不得进入公开日志/manifest。**
3. 私有 stdin：`{"op":"stop"}`，或者关闭 stdin。所有 bridge 流和 peer 关闭后，测试 cleanup 关闭 control/DERP/STUN，最后输出 `{"event":"cleanup","peerClosed":true,"bridgeConnections":0}` 并退出 0。节点启动有 25 秒上限，bridge 连接有 3 秒上限；整个 process 由 `-test.timeout` 限制，runner 仍须在 finally 停止并回收进程。

排查独立 C ABI 进程时，可发送 `{"op":"diagnostics"}`。返回 `event:diagnostics` 与 ready 之后的 `keyRequests`、`noiseRequests`、`registerRequests`、`mapRequests`、`tlsHandshakeErrors`、`secondClientRegistered`、`authCompletions`，只含整数/布尔。注册/map 观察使用上游公开 hook，始终返回不拒绝；不读取请求体或保留地址、身份、授权 URL、TLS 错误文本。`secondClientRegistered` 仅表示节点数超过就绪 peer 基线；注册计数不等于直接观察到 AuthURL 签发。可在登录前、拿不到 URL 时及授权后分别采样，完整结果仍以退出码和真实 TCP 为准。

同进程 Go 回归会共享 fixture 的 `netns.SetEnabled(false)`、禁日志与测试 fallback roots 全局状态；独立 Rust/C 进程不会继承它们，不能仅据该回归排除代理、TLS 或平台拨号差异。对照时只记录代理环境是否存在，不输出值；不得通过关闭生产 TLS 校验制造通过。

收到 ready **之后**启动产品 Rust 进程，仅为该进程设置 `SSL_CERT_FILE=caFile`（Linux Go TLS 根证书加载）。不要更改系统 trust、生产 TLS 校验或主机 pin。仍通过真实 `hp_ts_*` ABI：node_new/start → pre-login status 无 AuthURL/不能 dial → begin_login → 内存读取合法 HTTPS AuthURL → 私有 stdin complete_auth → status Running → OverlayDialer 拨虚拟地址 → 原有 SSH pin/认证/终端/输入。控制面 CA 与 SSH host pin 是两层独立校验。

ready 的端口/测试 CA 公钥可供后续受控 emulator 转发设计使用；这里没有为 Android 预先绑定公共地址、放松信任或声称设备可用。
