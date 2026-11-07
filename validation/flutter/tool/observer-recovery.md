# 只读观察的五次暂停／恢复诊断

`remote_probe.dart --case observe-recovery` 是显式诊断模式，不加入自动 CI case，也不新建 fixture。它使用与页面相同的 adapter，在同一条 SSH 连接上暂停／恢复五次；每次必须获得比上一次更大的 observation epoch、新 full，以及该 full 之后同 epoch 的 delta。帧必须属于选定时固定的 generation 与 paneId。旧 full、旧 delta、只有 full、跨代／错 pane、连接替换或通道清理失败均不能通过。单阶段最多 12 秒，总观察最多 55 秒，结束时取消观察。

仅在维护者正在运行的 `validation/remote-harness/run-ci.py` **非 paired GUI、非输入模式**的临时 fixture 生命周期内调用。该 harness 先创建隔离 herdr server、workspace 和 `capture_input.py` 窗格，后者自行每 200ms 输出 tick；因此观察器不用向 pane 写入来制造 delta。沿用当前 runner 的 `GITHUB_ACTIONS`、`GITHUB_RUN_ID`、`GITHUB_REF`，在 Flutter 已准备应用目录内运行：

```sh
dart run tool/remote_probe.dart \
  --config "$FIXTURE_ROOT/dart-positive-config.json" \
  --case observe-recovery \
  --output "$FIXTURE_ROOT/dart-observe-recovery-result.json"
```

`FIXTURE_ROOT` 必须由正在运行的 harness 的 `root` 提供，是本次 `/tmp/hp-mobile-<run>-…` 目录；配置必须已经由 harness 写出，输出文件须尚不存在。不要复制配置或 keys，不要通过伪造 CI 环境把普通远端改成 fixture。原有真实路径、run ID、loopback 和非特权端口检查保持生效。harness 正常退出即删除配置；之后不可重跑该命令，也没有保留／延长 fixture 的新开关。维护者需在自己管理的 fixture 作用域内、清理前显式调用；本模式不是可独立启动 SSH 环境的命令。

成功报告的 `observerRecovery` 三个整数 `resumeCount`、`freshFullCount`、`sameEpochDeltaCount` 都必须为 5，且顶层 `status` 为 `passed`。最后主动取消也必须确认完成，因此成功报告的 `errorCode` 为 `cancelled`。只发布该报告；配置、私钥和终端内容不得收集。harness 自己仍须核验 `received.bin` 为 0 字节、原 PTY 尺寸未变及全部进程／授权清理；本 probe 的帧门槛不能替代这些宿主侧断言。

paired GUI 路径的配置故意没有 `privateKeyPem`，设备密钥属于 native vault，不能用本 CLI 读取，也不能将配对凭据导出。手机真实生命周期、GUI 可见性和缺 peer CLOSE 的负例仍由对应 GUI／adapter 回归验证。

专项合成回归（已安装仓库固定 Flutter SDK 的准备应用中）：

```sh
flutter test test/observer_recovery_probe_test.dart
```

本机无完整 Flutter SDK 时，可用锁定 Dart／dartssh2 和仅替换 `RoutedSSHSocket` 接口的隔离 adapter 副本验证核心；这不等同于上述 Flutter 命令或 Linux runner CLI 正向验证。
