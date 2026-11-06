# ZeroTier 设备 owner、网络租约与 Android 托管

2026-11-07，延续[原生基础](28-zerotier-native-foundation.md)。本批修复 ECC 的未定义左移，新增真实 libzt 控制面的设备 owner／多网络租约，以及 AndroidKeyStore 包装。它们是 `b2c6528` 之后的源码，**不在 `750798fe` 两份 Android APK 内**。本批没有触发 Actions 或打开测试应用，继续手机优先、积累功能后集中验证。[本批证据](evidence/mobile-pair-gui/zerotier-managed-20261107.json)

## ECC 修复与证据范围

[`0007-defined-ecc-shifts.patch`](../validation/native/candidates/zerotier/patches/0007-defined-ecc-shifts.patch)仅修改固定 `ECC.cpp`：把有界 limb／carry 的 signed 左移改为常数乘法，32 位相等掩码改用 unsigned 位传播，输出仍为 0 或 −1。没有更换密码算法或用另一个上游版本掩盖诊断。固定调用链中 `|limb| < 2^27`，乘积系数不超过 `14×2^54`，折叠与 carry 的保守界分别为 `280×2^54`、`281×2^54`，均小于 `2^63`。独立审查核对了这些前提和逐步运算。

原先仅 ECC TU 的 `shift-base` 排除已删除。实际测试包含 [RFC 7748](https://www.rfc-editor.org/rfc/rfc7748.txt)、[RFC 8032](https://www.rfc-editor.org/rfc/rfc8032.txt) 公开向量、X25519 1000 次迭代、独立 Python 大整数参考、Ed25519 公钥／完整签名、极端负 carry、模 p 编码和相等掩码。C++11 O0／O2、C++17 O2、C++20 O2 四配置各执行 **5016 项操作、5083 次比较**，均通过；三个精确旧源码负控制均产生预期 UBSan 非零失败，不能把诊断 exit 0 当通过。

另有原四个离线程序通过。该 runner 的六个生产翻译单元先做普通编译；ASan／UBSan 覆盖后续插桩 core 和实际执行的离线路径，不能由此声称整个库所有路径均已运行。后续完整库检查另列于下表。C++11 的负数右移等实现定义边界仍依赖原源码编译前检查；这些结果不是形式化证明、侧信道审计或五平台验收。

## 设备与网络分开管理

[`hp_zt_manager`](../validation/native/zerotier-runtime/README.md)先接受已持久保存的本机私有身份，在触碰 libzt 初始化前保留唯一 owner，再执行内存初始化并关闭身份／网络／peer／root 文件缓存。只有原 owner 能启动和停止该节点；过时 owner 不能操作后来节点。初始化失败或迟到调用仍保留原 owner，不能从 GUI 超时推断已安全释放。

每个 profile 取得独立网络租约。同一 network ID 的租约共享一次实际 join；退出其中一个租约保留其他使用者，退出网络 A 不停止网络 B。配置状态分别保留请求中、已取得配置、拒绝、网络不存在、端口错误、客户端过旧、等待认证和未知。已取得配置不表示 socket 或路由就绪。所有失败／清理未完成租约也占用 32 个配额。

设备停止是明确影响所有网络的维护动作，先禁止新操作，再等待原控制调用、native stop 与 quiescence。成功后还须显式 release 原 owner，宿主保存该次成功结果，才可确认原 vault 的 handle／instance／lease 已退休。单网络 leave、`NODE_DOWN`、超时或未知结果都不能释放设备身份。没有使用会永久禁用进程后续初始化的 native free。

独立反例曾确认两处问题：在线检查迟到后仍发出 join、quiescence 查询过期后仍开始身份初始化；现已在副作用前重新核对关闭状态／deadline。父复核另补 stop／release 的迟到查询门禁，避免超时后悄悄释放 owner。同步上游 init／join／status 仍不能被强制中断，原调用返回前不得释放缓冲或 vault；文档明确区分调用超时与真实退休。

## Android 包装与实际检查

[`AndroidZeroTierDeviceStore`](../validation/network-profiles/native/android/AndroidZeroTierDeviceStore.java)强持有设备 core，显式注入原生身份 factory 和 owner 退休证明；[`AndroidZeroTierEnvelope`](../validation/network-profiles/native/android/AndroidZeroTierEnvelope.java)使用独立 AndroidKeyStore alias、AES-256-GCM、随机 IV、AAD 和设备解锁约束。加密记录在 `noBackupFilesDir`，缺钥／锁屏／损坏不能自动生成替代身份。当前包装要求 API 35，不把它外推为更低系统支持。

私有字节只在同步 native initializer 中短暂借用，返回或异常后尽力清零；不进入 Dart／JS／配置导出。原生管理器必须在 device new 前拿到 RuntimeLease，失败也要等原调用收敛。不可读身份的两步丢弃仍要求同实例曾认证的 handle；跨重启缺少可信引用的恢复尚未解决。[宿主接线契约](../validation/network-profiles/native/android/ZeroTierAndroidStore.md)

| 检查 | 本批实际结果 | 范围 |
| --- | --- | --- |
| Android 包装 | 36 项检查通过 | 实际包装源码＋Android stubs＋测试 JCE provider，不是设备 KeyStore |
| 设备存储 core | 151 项检查通过 | 隔离 JVM、临时目录与合成身份 |
| control-plane manager | 109＋6 项检查通过 | 实际 manager＋固定真实头文件＋替身 C engine；含停止栅栏和失败回收 |
| 完整 Mac 库 | 114 个 TU 编译、动态链接／加载和两轮离线初始化通过 | 所有 TU 插桩；probe 未启动 node，不证明运行节点／网络 |
| Android／JNI／GUI／真实组网 | 未验证或尚未接入 | 本批不改五端十五格和并发矩阵的验收状态 |

完整库构建器镜像固定 CMake 文件的源清单和定义，使用已有 Apple clang，不安装 CMake 或 SDK；仅支持本机 Darwin arm64，所有源文件与构建前后 inventory 均核对。每个 TU 都带 ASan／UBSan，probe 只检查 ABI、临时身份、两轮初始化／离线状态／stop／release。它没有调用 node start、join、dial 或真实授权。初轮报告序列化曾失败，原目录保留；修复后另建目录重跑，不能把初次编译成功说成整个工具成功。

```sh
python3 validation/native/tool/zerotier_candidate.py prepare --cache /absolute/cache --work /absolute/new-work
python3 validation/native/tool/zerotier_candidate.py apply --work /absolute/new-work
python3 validation/native/candidates/zerotier/tests/run_offline.py /absolute/new-work/libzt --output /absolute/new-offline-output
python3 validation/native/zerotier-runtime/tests/run_manager.py /absolute/new-work/libzt --output /absolute/new-manager-output
python3 validation/native/tool/zerotier_macos.py --work /absolute/new-work --output /absolute/new-macos-output
sh validation/network-profiles/native/android/tests/run-zerotier-android.sh
```

## 下一阶段实施顺序

1. 在本 owner／网络租约上加入定向 socket：真实 family、tap／netif generation、地址／路由核验、重叠网络拒绝或可靠绑定、取消与有界缓冲。固定 Heeler glue 的旧 mutex 类型和无 generation 的绑定不能原样复制。现阶段 manager 没有 socket API，不能用于终端拨号。
2. 对接 Android JNI：factory 直接调用已验证 native ABI，RuntimeLease 与原 device owner 一一绑定，profile 只持网络租约；补异步启动失败状态，不把始终离线当成功。
3. 接两套手机 GUI 的共享设备身份审查、受影响网络提示、等待授权和失败恢复，复用配对 → 看板 → 持续观察。再反馈 Penpot v2 的新增状态；本批未修改画板。
4. 累积完整手机功能后再集中云构建与运行验证，随后推进桌面分屏。设备输入、真实网络和其他平台结果继续单独标注，不用本机成功选定最终框架。
