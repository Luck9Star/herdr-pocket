# 手机 ZeroTier 身份与原生安全基础

2026-11-07。本批落地设备级身份托管核心、固定源码准备工具及原生身份／事件／退休补丁。它尚未接入 Android KeyStore 包装、JNI、网络 manager 或 GUI，**不在 `750798fe` 的两份 APK 中**。没有启动 ZeroTier 节点、读取真实身份、安装 SDK 或为此另开 Actions。结果与源文件哈希见[证据](evidence/mobile-pair-gui/zerotier-foundation-20261107.json)。

## 一个设备身份，多条网络租约

固定 libzt 是进程级单节点。多个 ZeroTier profile 应引用同一设备身份，每条连接仍保留自己的 profile、配置版本、network ID 与 device handle；不能把第一个 profile 当作全局身份，也不能为每个 profile 建一个 libzt node。退出网络 A 不能销毁网络 B 共用的身份。

[`ZeroTierDeviceStoreCore`](../validation/network-profiles/native/android/ZeroTierDeviceStoreCore.java)使用独立目录、KeyStore alias 前缀、AAD 和记录版本。显式生成由原生 factory 完成，严格验证并原子加密持久化成功后才能取得运行租约。GUI 只应获得不透明 handle／instance ID；秘密不进入 Dart、JS、配置导出或日志。

运行租约从启动前持续持有跨进程文件锁。释放必须由原 native owner 对 handle、instance、一次性 lease ID 提供真实退休证明；失败、超时、初始化回调未结束或迟到结果都保留所有权，单个 network leave 没有释放入口。当前 `DrainVerifier` 是待接原生实现的接口，Java 不能自行证明 libzt 已退出。

创建与删除分别有精确 handle／密文摘要绑定的持久 intent。崩溃后只返回恢复阶段和公开 handle：记录尚未落盘时可明确放弃原创建；记录已落盘时须核验身份和密钥，再明确恢复 fsync；删除则针对原 handle 重试。普通读取不会自动生成、丢弃或换身份。

密钥失效或密文不可读时，提供单独的两步丢弃审查，但必须是**同一 core 实例此前成功认证过的 handle**；无法认证的文件 header 本身不建立信任。审查绑定原实例、一次性对象及完整记录，确认时再次取得所有权门禁并复核。跨实例、被后续审查取代、重复消费、记录被替换或仍有活动租约都会拒绝。跨重启且没有独立可信 handle 的损坏恢复仍是缺口，不能宣称任意损坏都可恢复。后续 Android 宿主须持有同一 core，并将审查对象留在原生层。

## 固定源码与实际修复

[来源 manifest](../validation/native/zerotier-runtime-source.json)固定 Heeler `6a2817fc…`、libzt `7e5d0f99…`、ZeroTierOne `fc5c3ec2…` 及两个 lwIP 仓库。四份原始归档、`sources.lock` blob 与四个 Heeler 补丁均核对哈希，先得到 4,044 文件的基线；再应用本项目两个补丁与三个 shim，最终核对 4,050 文件。合法的五个归档内符号链接只从同归档 regular file 物化字节，原始归档和转换记录保留。拒绝目录逃逸、链接链、重复路径、额外源文件与哈希变化。

[候选 manifest](../validation/native/zerotier-candidate.json)锁定前后文件哈希与测试输入，[实现说明](../validation/native/candidates/zerotier/README.md)记录来源与调用方约束。新增补丁修复：

- core 地址／route 数组分别为 32／128，事件对象只有 16／32，原按 core count 写入会越界。现在同时按源与目的容量投影；实际 multicast 两侧均为 1024，不把不同名字的常量当作该数组界限。投影不是完整路由表。
- STORE 事件复制借用 cache 后再异步交付，消费后尽力清零；队列使用精确计数，最多 1024 个等待事件和一个正在回调的事件。独立审查另发现地址事件拒收后泄漏，现由实际生产 RAII owner 在拒绝／异常时释放，成功入队才转交所有权。
- stop／free 明确区分超时、忙与真实退休，不能在等待约 30 秒后继续报告成功或释放 Events。service、callback、外层 driver 各有完成条件；迟到 frame 在销毁 Node 前被拒绝／排空。普通 stop 保留全局 lwIP 栈；永久 free 也不声称已 join 固定 lwIP 不提供关闭接口的内部 tcpip 线程。
- 身份必须是固定 type-0 私有文本，270 字节，含 private，并分别从 DH／Ed25519 私钥部分重新派生 public 核对。旧 public/address 校验会接受混配私钥，不能代替新校验。`setIdentity` 的 NULL、长度、padding 和复制边界一并收紧。

修改私有 `service_m` 为 timed mutex 后，不能原样复制 Heeler 对其旧类型的声明。后续 socket shim 必须适配，并核对真实 network status、netif generation／地址／链路状态与原网络租约；单凭 assigned count 不能宣称可拨号。相同地址落在多个网络时，无法证明定向就拒绝。

## 验收与未消除项

| 检查 | 实际结果 | 边界 |
| --- | --- | --- |
| 来源工具 | 43 项工具测试通过，其中 14 项是新归档负例；真实归档与最终树通过 | 另实际注入额外源文件确认拒绝，随后恢复独立临时树 |
| 设备身份核心 | 151 项隔离 JVM 检查通过；严格 javac 通过 | JCE、假 native factory、临时目录与自建 JVM 子进程；没有 Android KeyStore |
| 原生源 | 六个实际翻译单元编译通过 | Controls、Events、NodeService、VirtualTap、两个 shim；没有完整共享库链接／加载 |
| 四个离线 native 程序 | 身份、投影、worker/frame helper、实际 Events TU 通过 | Events 未使用的 NodeService 查询边界为显式 stub；未启动真实节点 |
| 独立审阅 | 地址拒收泄漏已修复并重新测试 | 其余退休推理依赖原 owner、API／stream drain 和串行维护，不能代替实际竞争测试 |

ASan 与 UBSan 环境设置为遇错退出。**固定上游 ECC.cpp 已出现 27 条 signed-negative shift 诊断，尚未解决**；只有该文件暂排除 `shift-base`，其余检查保留。因此不能将本批写成“完整 UBSan 通过”或原生密码实现已完成跨平台验收。初轮摘要已去掉临时计算标量，保留诊断位置和来源哈希。下一步应先核实并修复该算术／语言标准边界，或验证有依据的固定来源更新，再进入产品链接。

补丁文本保留上游 context 空白和 diff 前缀；Git attributes 仅对这两个 patch 的相关空白诊断作限定处理，所有候选文件以 `-text` 保持 Windows checkout 的固定字节。它不关闭 C／C++、Java 或 Python 源码检查。

复跑使用现有编译器和 JVM，无需安装完整手机 SDK：

```sh
python3 validation/native/tool/zerotier_candidate.py fetch --cache /absolute/source-cache
python3 validation/native/tool/zerotier_candidate.py prepare --work /absolute/fresh-work --cache /absolute/source-cache
python3 validation/native/tool/zerotier_candidate.py apply --work /absolute/fresh-work
python3 validation/native/tool/zerotier_candidate.py verify-candidate --work /absolute/fresh-work
python3 validation/native/candidates/zerotier/tests/run_offline.py /absolute/fresh-work/libzt --output /absolute/fresh-offline-output
sh validation/network-profiles/native/android/tests/run-zerotier-device.sh
```

后续顺序：消除 ECC 诊断边界 → 单设备 owner 与多网络 join 租约、定向 socket／取消／有界缓冲 → Android KeyStore 与 JNI → 两套手机身份审查／等待授权／配对到看板及持续观察 → 一次集中云构建和独立运行验证。十五个平台／provider 格及并发矩阵保持原有未验证标记；真实节点生命周期、Android／iOS／Windows、新库分发材料和五端支持不能由本页的 Mac 离线检查外推。
