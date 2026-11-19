# Flutter Android 共享 EasyTier 双主机 R5

2026-11-20，R5 第 2 次运行通过。Flutter 在 API 35 x86_64 模拟器中用同一受审查的 EasyTier 节点连接 A、B。两个实际 EasyTier 对端通过测试专用 `adb reverse` 转发，各自桥接到受控 SSH/herdr 服务。客户端与驱动为 `481e63c21216f9c201113e8e2da310164c5c2b1c`，原生构建为 `547106ea172dfd055c3bf9fdb2f4e2a27c9ff2f8`，宿主构建为 `5404adfb3c86f5174edda38f1d0c63c8d81996c5`。[通过作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44569648650/job/135725621442) · [脱敏摘要](summary.json)

| 检查点 | A 的 SSH 审计 | B 的 SSH 审计 |
| --- | --- | --- |
| 两侧首帧 | 唯一批准会话活跃 | 唯一批准会话活跃 |
| 关闭 A 后 | 原会话关闭，对端确认 `peer_eof` | 原会话仍活跃，原终端显示新帧 |
| 关闭 B 后、主动停节点前 | 原会话关闭，对端确认 `peer_eof` | 原会话关闭，对端确认 `peer_eof` |
| 主动停原节点后 | 原会话仍关闭 | 原会话仍关闭 |

每侧累计 1 条 overlay 流、1 个回环 SSH 连接、1 次批准认证。两侧在首帧后都没有新增 SSH 会话，受检终端从始至终各收到 0 字节输入。关闭两标签后，应用仍读到了原节点绑定。用户显式停止后，原节点绑定消失，两个活动转发连接各由 1 降至 0。测试进程、应用包、两条 reverse 映射、转发基线及独占宿主资源均已清理。APK 构建副本和安装副本分别通过固定原生库校验，各自的 SHA-256 见摘要。

覆盖范围为 Flutter Android 模拟器上的同节点双主机只读观察与逐条释放。实体手机、真实跨网、主动输入、同 provider 多节点和其他 provider 组合须分别验收。

## 两次运行的原件

| 次数 | 结果 | 官方原件 |
| --- | --- | --- |
| 1 | 准备 NDK `28.2.13676358` 时解压报 `ZipFile unknown archive`，设备步骤跳过。保底报告的错误码为 `device_manifest_missing`。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44569648650/job/135720886765) · [工件 14552604296](https://github.com/Luck9Star/herdr-pocket/actions/runs/44569648650/artifacts/14552604296) · [原 ZIP](attempt-1-actions-14552604296.zip) |
| 2 | 同一源码通过，末阶段为 `shared_node_stopped`，用例状态为 `passed / complete`。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44569648650/job/135725621442) · [工件 14555006892](https://github.com/Luck9Star/herdr-pocket/actions/runs/44569648650/artifacts/14555006892) · [原 ZIP](attempt-2-actions-14555006892.zip) |

两个 ZIP 均保留 Actions 原字节，外层 SHA-256 与官方元数据匹配，各含一份脱敏 `manifest.json`。[SHA256SUMS](SHA256SUMS)

```sh
shasum -a 256 -c SHA256SUMS
unzip -p attempt-2-actions-14555006892.zip manifest.json
```

## 本机复现 R4 到 R5 的变化

R4 关闭 A 标签后，宿主的 39 次 A 采样均显示原会话活跃、关闭未确认。关闭按钮原先移除标签并由销毁路径取消适配器，跳过了已注册的正常关闭回调。R5 在移除标签前启动原传输的关闭，并让随后发起的节点停止等待同一次进行中的关闭。设备验收的对端 EOF、原会话、零额外输入和清理门槛继续生效。[R4 失败原件](../flutter-android-shared-easytier-r4-20261120/README.md) · [修复提交](https://github.com/Luck9Star/herdr-pocket/commit/481e63c21216f9c201113e8e2da310164c5c2b1c)

在仓库根目录使用 Flutter `3.47.9` 和已缓存的 pub 依赖。下面把 R5 的回归测试放入临时 R4 应用，保留旧版产品代码。

```sh
repo=$(git rev-parse --show-toplevel)
r4=0d22d9f8c9169b7bd4c117ef73dc86a0b0850235
r5=481e63c21216f9c201113e8e2da310164c5c2b1c
work=$(mktemp -d)
mkdir "$work/source"
git -C "$repo" archive "$r4" validation | tar -xf - -C "$work/source"
python3 "$work/source/validation/flutter/tool/ci.py" prepare --destination "$work/app"
cd "$work/app"
flutter pub get --offline
for test in host_tabs_test.dart host_shared_node_close_widget_test.dart network_graceful_close_test.dart; do
  git -C "$repo" show "$r5:validation/flutter/test/$test" > "test/$test"
done
flutter test --no-pub --reporter expanded \
  test/host_shared_node_close_widget_test.dart test/network_graceful_close_test.dart \
  --name 'closing (hidden A in the mobile|tab A sends real TCP EOF)'
```

预期两项失败。390 × 844 的 EasyTier 窄屏用例观察到 A 的正常关闭回调为 0 次。双实际回环 TCP 用例等不到 A 的 EOF。将临时应用的 `host_tabs.dart` 换成修复版再验证。

```sh
git -C "$repo" show "$r5:validation/flutter/lib/host_tabs.dart" > lib/host_tabs.dart
flutter test --no-pub --reporter expanded \
  test/host_tabs_test.dart test/host_shared_node_close_widget_test.dart \
  test/host_tabs_widget_test.dart test/network_graceful_close_test.dart
```

31 项本机测试通过。窄屏用例确认 B 在原终端获得新帧。回环 TCP 用例确认 A 收到 EOF、B 继续在原连接接收数据且双方输入均为零。该回环用例以真实 TCP socket 承接平台通道调用。上面的 Android 作业提供原生 EasyTier 与实际 SSH 对端的证据。
