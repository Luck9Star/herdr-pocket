# Tauri Android 共享 EasyTier 双主机 R2

2026-11-20，R2 在 API 35 x86_64 模拟器通过。设备安装同次运行从 `9916e5a2de80c040cfc656ef4f21280e5a1fb996` 构建的普通 APK，并核对安装副本摘要。Tauri 用可见的产品界面配对两个独立 SSH/herdr 主机，将它们绑定到同一 EasyTier 配置，并逐个打开终端。两个实际 EasyTier 对端通过各自的受控 `adb reverse` 转发到临时 SSH/herdr 服务。[通过作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44649139908/job/136002818212) · [脱敏摘要](summary.json)

| R2 检查点 | A 的 SSH 审计 | B 的 SSH 审计 |
| --- | --- | --- |
| 两侧首帧 | 唯一批准会话活跃 | 唯一批准会话活跃 |
| 关闭 A 后 | 原会话已停，OpenSSH 记录 `client_disconnect` | 原会话仍活跃，显式选回并恢复观察后，终端 tick 由 580 增至 581 |
| 关闭 B 后、主动停节点前 | 原会话仍停 | 原会话已停，OpenSSH 记录 `client_disconnect` |
| 主动停原节点后 | 原会话仍停 | 原会话仍停 |

每侧始终只有 1 次批准认证、1 条 overlay 流、1 个回环 SSH 连接和 0 字节终端输入。两个标签都关闭后，应用仍读到原节点绑定，两路 relay 各有 1 条连接。一次显式停止成功，应用读回原绑定的 `stopped` 历史状态，两路 relay 均归零。应用、调试转发、两条 reverse 映射、宿主进程与临时资源均已清理。独占 AVD 清理时第一次检查即确认 serial 消失。原生绑定序列化省略 EasyTier 的默认 provider 字段，provider 由可见的 EasyTier 配置与原生序列化约定共同确认。[脱敏摘要](summary.json) · [绑定序列化](../../../validation/transport-rust/src/mobile_nodes.rs)

覆盖范围为 Tauri Android 模拟器上同一 EasyTier 节点的只读观察与逐条释放。窄屏需要显式选回 B 并恢复观察。实体手机、Android arm64、真实跨网、同节点主动输入、同 provider 多节点、其他 provider 和其他平台仍须分别验收。证据确认 SSH 传输关闭，远端进程生命周期须独立观察。

## R1 的失败与修复

R1 在 `c71ae7ef81afcb486cb7a39bc8ba54b06c27bc46` 到达 `shared_stop_node`，以 `dual_shared_peer_still_active` 失败。关闭 A 后 B 原认证会话仍在，显式恢复观察使 tick 从 523 增至 525。两个标签分别移除后，两条原 SSH 会话依然活跃且关闭未确认。主动停止原节点返回成功，relay 从各 1 条降到 0 条。当次两个 SSH 服务仍将原会话标为活跃，应用和夹具清理随后通过。独立 SSH 审计因此保留失败结果。[R1 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44644770400/job/135987829934) · [R1 原 ZIP](r1-actions-14589520203.zip)

R1 的关闭按钮走硬取消，触发连接取消后跳过正常的 SSH 断开与传输写半关闭。R2 为显式关闭按标签、所有者和连接代次锁定原连接，复用 SSH 有序退场并确认传输 EOF。超时保留关闭未确认，配置撤权、后台和未确认写入仍按原先的安全边界处理。[修复提交](https://github.com/Luck9Star/herdr-pocket/commit/9916e5a2de80c040cfc656ef4f21280e5a1fb996) · [原生关闭入口](../../../validation/tauri/src-tauri/src/remote_tab_commands.rs)

## 官方原件与摘要

| 轮次 | 设备结果 | 官方工件 | 官方到期时间（UTC） | 归档 |
| --- | --- | --- | --- | --- |
| R1 | 失败 | [14589520203](https://github.com/Luck9Star/herdr-pocket/actions/runs/44644770400/artifacts/14589520203) | 2026-12-04 00:30:28 | [原 ZIP](r1-actions-14589520203.zip) |
| R2 | 通过 | [14590497135](https://github.com/Luck9Star/herdr-pocket/actions/runs/44649139908/artifacts/14590497135) | 2026-12-04 01:03:56 | [原 ZIP](r2-actions-14590497135.zip) |

两个 ZIP 保留 Actions 原字节，外层 SHA-256 与官方元数据逐一匹配。各 ZIP 只含脱敏的 `tauri-dual-result/result.json` 和 `tauri-dual-avd/lifecycle.txt`。成员 SHA-256、客户端和 APK 摘要、输入、连接与关闭检查点见[摘要](summary.json)，本目录的归档校验见 [SHA256SUMS](SHA256SUMS)。R2 普通 APK 来自同次运行的[构建工件 14590551189](https://github.com/Luck9Star/herdr-pocket/actions/runs/44649139908/artifacts/14590551189)，官方到期时间为 2026-11-27 00:59:08 UTC。

```sh
shasum -a 256 -c SHA256SUMS
unzip -p r2-actions-14590497135.zip tauri-dual-result/result.json | shasum -a 256
unzip -p r2-actions-14590497135.zip tauri-dual-avd/lifecycle.txt | shasum -a 256
```

## 本机复测

在 macOS 回环 TCP 上，两个独立 OpenSSH 进程分别桥接两个原版 herdr 0.9.5。使用产品 Rust transport 对两个实际 SSH 对端各认证一次。暂停 A 后主动关闭，A 的 OpenSSH 记录 `client_disconnect`，B 保留原认证并继续出帧。随后暂停并关闭 B，B 独立记录 `client_disconnect`。两端终端输入均为 0 字节，测试进程和临时主机材料均清理。[本机脱敏报告](macos-two-openssh.json)

需要 macOS 自带 OpenSSH、PATH 中的 herdr 0.9.5、Rust 1.96、uv 及可用的 Cargo 构建依赖。由仓库根目录执行，两个临时宿主使用独立目录与回环监听。

```sh
repo=$(git rev-parse --show-toplevel)
r2=9916e5a2de80c040cfc656ef4f21280e5a1fb996
work=$(mktemp -d)
mkdir "$work/source" "$work/replay"
git -C "$repo" archive "$r2" validation helper | tar -xf - -C "$work/source"
cp -R "$repo/docs/evidence/tauri-android-shared-easytier-r2-20261120/local-replay/." "$work/replay/"
ln -s "$work/source/validation" "$work/replay/validation"
cp "$work/source/validation/transport-rust/Cargo.lock" "$work/replay/Cargo.lock"
CARGO_TARGET_DIR="$work/target" cargo build --offline --manifest-path "$work/replay/Cargo.toml"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$work/source/validation/remote-harness" PROBE_SOURCE="$r2" \
  uv run --no-project --python 3.12 --with-requirements "$work/source/validation/pairing/requirements.txt" \
  python "$work/replay/run.py" "$work/target/debug/local-two-sshd-close-probe"
```

结果写入 `$work/replay/result.json`。本机回环验证实际 SSH 传输，对应 Tauri 原生桥及 UI 的回归分别由以下测试覆盖。

```sh
(cd validation/tauri && npm ci --no-audit --no-fund && npm run tauri -- icon icon.svg && npm run build)
node --test validation/tauri/test/tab-workspace.test.mjs \
  validation/tauri/test/desktop-split.test.mjs validation/tauri/test/network-stop-render.test.mjs
cargo test --locked --manifest-path validation/tauri/src-tauri/Cargo.toml --lib
cargo test --locked --manifest-path validation/transport-rust/Cargo.toml --lib controlled::tests
```

R1 对照可在临时目录使用 R2 的测试文件，保留 R1 的产品代码。该用例预期失败，记录没有发出精确的 `remote_tab_close` 调用。

```sh
repo=$(git rev-parse --show-toplevel)
work=$(mktemp -d)
git -C "$repo" archive c71ae7ef81afcb486cb7a39bc8ba54b06c27bc46 validation | tar -xf - -C "$work"
git -C "$repo" show 9916e5a2de80c040cfc656ef4f21280e5a1fb996:validation/tauri/test/desktop-split.test.mjs \
  > "$work/validation/tauri/test/desktop-split.test.mjs"
(cd "$work/validation/tauri" && npm ci --no-audit --no-fund && \
  node --test --test-name-pattern='closing either split panel' test/desktop-split.test.mjs)
```

使用 R2 源码复测，前端 117 项、Tauri 原生 86 项、Rust controlled 30 项通过。

## Android 复跑

[验收工作流](../../../.github/workflows/tauri-android-dual-overlay.yml)在包含受检提交的 `codex/acceptance/tauri-android-shared-easytier-*` 分支上由 `workflow_dispatch` 显式选择场景。R2 的分支名为 `codex/acceptance/tauri-android-shared-easytier-r2`。

```sh
gh workflow run tauri-android-dual-overlay.yml \
  --ref codex/acceptance/tauri-android-shared-easytier-r2 \
  -f scenario=shared-easytier
```

每次工作流重新构建并校验同次运行的普通 APK。固定原生源为 `547106ea172dfd055c3bf9fdb2f4e2a27c9ff2f8`，普通与 QA 工件 [14261768985](https://github.com/Luck9Star/herdr-pocket/actions/runs/43939326685/artifacts/14261768985)、[14261004231](https://github.com/Luck9Star/herdr-pocket/actions/runs/43939326685/artifacts/14261004231) 分别于 2026-11-30 19:36:41 与 19:36:37 UTC 到期。固定宿主源为 `5404adfb3c86f5174edda38f1d0c63c8d81996c5`，工件 [14171011473](https://github.com/Luck9Star/herdr-pocket/actions/runs/43736430859/artifacts/14171011473) 于 2026-11-22 16:46:16 UTC 到期。过期后按固定来源重建对应工件，并核对其来源及摘要后更新工作流引用。
