# ZeroTier 原生安全基础候选

状态：2026-11-07。这里只提供固定源码的身份／事件内存／退休基础补丁与离线检查，尚未接入 ZeroTier managed backend、JNI、GUI 或实际网络。没有调用 node start、join、dial，也没有读取真实身份文件。

固定输入为 [Heeler `6a2817fc…` sources.lock](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/sources.lock)、[libzt `7e5d0f99…`](https://github.com/Ylarod/libzt/tree/7e5d0f99a2de81c45faa28e44289bcd19d933bf2)、其 gitlink [ZeroTierOne `fc5c3ec2…`](https://github.com/zerotier/ZeroTierOne/tree/fc5c3ec22090b5b2a0f274e863651fe9ca489bf4)、lwIP `32708c0a…` 与 contrib `4fd612c9…`。先按锁验证并应用 Heeler 原四补丁，再依序应用本目录 `patches/0005-native-safety.patch`、`0006-strict-offline-identity.patch`。保留每个上游原始许可和 Heeler 修改归属；本候选不作整体分发许可证结论。旧三桌面 compile／四符号解析不证明这些新增代码或节点运行。

## 修复范围

- **事件数组。** 固定 core 的地址／route 数组为 32／128，libzt 事件投影只有 16／32；原 `NodeService::sendEventToUser` 按 core count 写入。新真实生产 helper 同时限制源、目的容量，逐项转换并终止名称字符串。multicast 的实际数组两侧均为 1024；不把另一个 `NETWORK_MULTICAST_* = 4096` 常量误当该数组界限。投影是有界展示，不是完整路由表，后续路由／重叠检测必须读取实际 core 数据。
- **异步事件。** STORE cache 原先引用 core 借用指针；现在入队即复制，最多 4096 字节，消费后尽力 wipe。producer／consumer 在同一 gate 下维护精确 pending 数；最多 1024 个排队事件，另最多一个在途 callback。disable 阻止新入队，退休前排空既有队列。实际 `NodeService` producer 使用 typed RAII owner：disable／满队列拒收或 enqueue 异常时释放自己的投影对象，四种地址事件不再泄漏；成功入队才将所有权交给 `Events::destroy`，STORE 原始输入仍为借用，不能误删。callback 的原 message 仍只允许借用读取，不得保存指针或修改其所有权字段。
- **可核验退休。** 原 stop 最多轮询约 30 秒仍返回 OK，原 free 也可能继续删除 Events。新 stop／free 使用 1–60000 ms deadline，服务 mutex 等待也计入，TIMEOUT／BUSY 不代表完成。worker 创建失败由真实路径使用的 launch guard 退回自己的 admission；service、callback、outer driver 分别记录最后一次对象访问。NODE_DOWN 事件不替代退休判定。callback 内只请求退休并返回 BUSY，必须由外部继续核对和停止。异常清理未证明完成时保留 reservation。
- **对象寿命。** frame gate 阻止退休后的 core frame 进入，销毁 Node 前等待已准入 frame；虚拟接口退休时清除 state，迟到 lwIP work 不得引用已销毁 tap。pending start 收到停止后不会重新把 run 打开。身份缓冲保留到原 service 收敛，随后尽力 wipe；memory-only 模式不探测 `/roots`、`/networks.d` 或 `/peers.d`。
- **严格身份。** 新 native ABI 使用 pinned core 离线生成、解析和验证；type-0 私钥文本固定 270 个小写 ASCII 字节，无 NUL，包含 64 字节 public 与 64 字节 private。工作缓冲为 384 字节。必须含 private、通过 public/address proof，并由两个 private 半部分重新派生 DH／Ed25519 public 对比。旧 `zts_id_pair_is_valid` 只验证 public/address，不能代替该校验。`setIdentity` 同时修复 NULL、长度、padding 与无限 strlen／memcpy 边界；native 临时私钥副本尽力 wipe，未改密码算法。

普通 stop 保留 process-global lwIP 栈供以后启动。free 永久禁止重新初始化，并退休 Node／Events／外层 driver；固定 lwIP 的内部 tcpip 线程没有 join API，因此不声称“所有线程和全局资源都已释放”。初始化但尚无 service worker 的同步析构路径要求 Node 为空且 frame gate 已 quiet；真正活动 service 的析构始终由 worker 完成。

## ABI 与后续调用方约束

公开签名见 [`shim/hp_zt.h`](shim/hp_zt.h)。`hp_zt_identity_create` 输出 native 私有 270-byte buffer、长度和公开 40-bit node ID；`hp_zt_identity_validate` 只返回校验结果与公开 ID。失败时长度／ID 清零。生成和验证包含内存硬 hash，须在原生 worker 调用，不能阻塞 GUI。秘密不可进入 IPC、日志、Debug 或配置导出。

native vault 必须先完成原子加密持久化，再允许初始化／start；已有身份缺失、损坏、锁定或读失败均须先失败。低层 libzt 仍有未初始化时自动生成身份的旧行为，本批没有提供 managed start API；后续 manager 不得依赖该隐式生成或异步 STORE 事件补救持久化事务。

低层 `hp_zt_node_stop/free/quiescent` 是 process-global 维护函数，**不是 profile／session 句柄**。后续 manager 必须提供不可复用的 device-node owner／epoch，串行处理退休，先撤销受影响 streams／API admission，再检查原 node 的 stop 成功及在途调用收敛；超时、未知或原 future 未收敛时不得换身份／释放 owner。进程只有一个实际 libzt node，应在其上管理各网络的 join leases，不能每 profile 起独立节点。普通最后一个网络退出使用 stop，不能用永久 free 作为可重启清理。

私有 `service_m` 已改为 `std::timed_mutex`。若后续采用固定 Heeler `native/zerotier/heeler_zerotier.cpp`，必须适配其 `extern Mutex service_m` 声明；不能未经适配混用私有锁布局。既有 `heeler_zt_bind_network`／`heeler_zt_network_reaches` 提供 per-netif 路径，但旧 native probe 没有拷入这些 glue 文件。本批不实现 socket shim；后续须补网络定向、netif generation／配置变化、重叠地址拒绝及真实返回 stream 的 route 身份。

`zts_node_is_online` 只表示存在可达 upstream；`zts_net_transport_is_ready` 在固定源码中仅检查 assigned count，不能单独作为 dial 权限。后续应同时核对实际网络 status、对应 family 的真实 tap/netif up/link/address、原 lease 和路由。core authentication-required 状态 6 没有完整 libzt event 投影，应明确 fail closed／待授权，不能映射成 ready。

## 插入点与复验

来源准备、archive／gitlink／Heeler patch hash、完整树清单和主构建入口由上层 `zerotier_candidate.py` 与来源 manifest 管理。本目录构建插入顺序：

1. 固定完整 libzt＋三个 gitlink，验证并应用原四 Heeler patches。
2. 依序应用本目录 `0005`、`0006`、`0007` 三个 patch。
3. 将 `shim/hp_zt.h`、`hp_zt_identity.cpp`、`hp_zt_lifecycle.cpp` 复制到 libzt `src/`。现有 CMake `src/*.cpp` glob 会纳入它们；源码目录内不得留下 binary、object、日志或构建目录。
4. 运行离线 runner，输出必须为源码树外一个尚不存在的目录：

```sh
python3 validation/native/candidates/zerotier/tests/run_offline.py \
  /private/tmp/herdr-zt-ecc-20261107/libzt \
  --output /private/tmp/herdr-zt-ecc-offline-repeat
```

runner 不下载工具或 SDK，使用已有 clang++。它编译实际 Controls／Events／NodeService／VirtualTap 与两个 shim 翻译单元，再执行四个 native-only 离线程序：严格身份 ABI、真实 projection helper、worker/frame helper、实际 Events TU（仅未使用的 NodeService 查询边界为显式 stub）。事件反例运行实际队列的 disable／满 1024 拒收，调用生产 RAII helper 的可计数 typed deleter 检查四种地址各仅释放一次；成功 transfer 不执行 sender deleter，实际消费销毁路径保留，borrowed STORE 不误删。这不等于执行真实 NodeService 节点。身份临时值仅在 native 内存中，不输出 secret。环境显式固定 `UBSAN_OPTIONS=halt_on_error=1`、`ASAN_OPTIONS=abort_on_error=1`，诊断必须失败，不能靠默认 exit 0 计 pass。

`0007-defined-ecc-shifts.patch` 修复固定 `ECC.cpp` 的 signed-negative shift：历史运行观察到 27 个诊断位置，补丁覆盖 28 个潜在的 signed 左移表达式（23 个 limb／carry、5 个 equality mask），不改变 26／25-bit limb 表示、Montgomery ladder、clamping、SHA512 派生或 96-byte 签名布局。runner 已删除原 ECC TU 的 `-fno-sanitize=shift-base`；五个 crypto TU 和全部执行的 C++ 离线测试使用 ASan＋UBSan，无 sanitizer 排除。前述六个 production TU 仍是编译接线检查，不是完整节点运行。

算术依据与边界：

- 输入 limb 的绝对值小于 `2^27` 时，`fproduct`／`fsquare_inner` 每个系数小于 `14*2^54`。degree reduction 的原 `16x + 2x + x` 改用有符号常数乘法，每一步及最终 low＋19×high 的绝对值小于 `280*2^54 < 2^63`，没有用 unsigned wrap 掩盖 signed 溢出。
- coefficient reduction 保留原截零除法／进位顺序。后续输入上界 `281*2^54 < 2^63`，carry 乘 `2^25`／`2^26` 在 `int64_t` 中可表示。固定 [Chromium Donna 参考源码](https://chromium.googlesource.com/chromium/src/+/32352ad08ee673a4d43e8593ce988b224f6482d3/crypto/curve25519-donna.c)（blob `f141ac028b0f7bba419c218aad66275b507eb8c3`）已有相同常数乘法 carry 写法；本补丁保留本项目固定算法及轮次。
- equality 使用 `uint32_t` 执行相同的 AND／shift 位传播，最高位为全部 32 个原始相等位的 AND；最后仅将 `0/1` 转为 `s32` 再取负，严格得到 `0/-1`。不增加按 secret 分支或表查询。原 two's-complement／arithmetic-right-shift 前提及编译检查保留，本批没有改写右移，也不构成机器码 constant-time 证明。

新增 `ecc_driver.cpp` 直接包含实际 patched `ECC.cpp` 来测试其 private helpers，没有新增生产 crypto API。`ecc_reference_test.py` 用 Python 无界整数作为独立 oracle，代码注明 RFC 来源及许可，先用公开 [RFC 7748 §5.2／6.1](https://www.rfc-editor.org/rfc/rfc7748.txt) 和 [RFC 8032 §7.1](https://www.rfc-editor.org/rfc/rfc8032.txt) 向量校验 oracle，再比较 native 输出。Python oracle 是可变时间离线测试代码，不能用于产品。

每个配置执行 5016 个公开、确定性操作／5083 次比较：equality 全符号及每一位差异、degree／carry 极值、模 p 两侧 canonical encoding、26／27-bit limb 乘法与平方、非 canonical X25519 输入、RFC 1000 次迭代每一轮、额外 128 个 X25519 差分，以及 67 个 Ed25519 公钥＋完整 ZeroTier 签名差分及 native 篡改拒绝。ECC 分别使用 C++11/O0、C++11/O2、C++17/O2、C++20/O2；其他链接的 crypto 对象保持 C++11/O1。测试不输出 seed／scalar／临时身份，失败日志也脱敏 UBSan 操作数。

runner 另在输出目录反向应用 `0007`，用 SHA256 `9a9aa9ce6d15745f22babfad7e9905661532f67e9d87fc2518ca75e43cfc581b` 确认精确原始 `ECC.cpp`，以同一 C++11 ASan／UBSan 配置执行三项公开负控制（equality、degree、carry）。每项必须非零退出并出现预期负移位诊断；只有崩溃、放宽 flag 或误用另一源码都不能算通过。反向恢复和故意失败均在输出目录，已验证的源码树不被改动。

本轮在 macOS arm64、Apple clang 21 上已有六个实际翻译单元实编、四组 ECC 差分和上述四个离线程序执行证据；它们不证明全部输入的形式化密码学等价、其他编译器／架构、实际 node lifecycle、完整共享库链接／加载、Android／Windows／iOS、设备存储、授权、真实 ZeroTier／SSH／herdr、GUI 或跨 provider 并发。本轮没有启动节点、入网、GUI 或 CI，也没有安装 SDK。

补丁文本 whitespace 边界：`0005-native-safety.patch` 有两处固定上游 preimage／context 空白行空格；`0006-strict-offline-identity.patch` 有 15 处标准 diff context 前缀空格＋原源码 tab，以及一个末尾空 context 行；`0007-defined-ecc-shifts.patch` 有 29 处 context 前缀空格＋原源码 tab、9 处空 context 行。`git diff --no-index --check` 会报告这些 patch 文本行，不为通过文本检查而改变被验证的 preimage。实际 ECC source diff 和其余候选文件没有 whitespace 诊断；源码 fresh-apply、postimage hash 与离线检查单独验收，不能将 patch 文本检查报告为全绿。
