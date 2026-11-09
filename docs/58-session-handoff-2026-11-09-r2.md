# 2026-11-09 会话交接·第二棒（自包含）

> 本文档是**当前最新交接入口**，取代 [57-session-handoff-2026-11-09.md](57-session-handoff-2026-11-09.md) 成为第一入口（57 保留为上一棒历史，事实修正版）。历史全量交接见 [56-project-status-and-handoff.md](56-project-status-and-handoff.md)（主体不改）。
>
> 仓库：`/Users/yangyitian/Documents/dev/Agents/herdr-pocket` · remote `Luck9Star/herdr-pocket` · 主干 `main`
> 交接时工作分支：`codex/network-batch/with-emulators-zerotier-0008-c3d3036`（HEAD = `32a77c7`，本地领先远端 **10 个提交，全部未 push**）

---

## 一、总体状态（一句话）

**项目未完成。** 本轮（第二棒）两大核心成果已本地提交：**flutter tap 落点根因定案并修复**（`1a37f17`）与 **android counter 诊断 P0–P2 全量加固**（`32a77c7`）；下一步就是**合并本地栈推 0010 触发分支跑 CI**，用新诊断定案 android-device-key 的 `no_ipc` 三选一根因。**Stage 2 门控（ZeroTier bindNative 新增 + 生产切片反转）严格锁定，等用户明示授权，不得擅自开启。**

| 维度 | 状态 |
| --- | --- |
| 本地提交栈 | 10 个提交未推送（`b5ca239 … 32a77c7`），HEAD `32a77c7` |
| CI run `42496318563` | 已终态 failure：7 job 绿 / 2 device-key 败 / 2 input job 跳过 |
| flutter-device-key | 根因已定案（tap 落点），修复 `1a37f17` 待 CI 验证 |
| android-device-key | `no_ipc` 未定案；`32a77c7` 诊断加固待 CI 出证 |
| ZeroTier 0009 补丁 | 已入档（manifest 5/21/31 闭环），**从未进过 CI 编译**，下一轮推送即首次 apply + NDK 编译 |
| Stage 2 门控 | **锁定**，范围审计已完成（见第七节），等用户明示授权 |
| 未跟踪目录 | `graphify-out/` 保持未跟踪，**严禁提交** |

---

## 二、本地提交栈（未推送，已 git log 核实）

完整栈（旧 → 新）：

```
b5ca239 → c1addd6 → 9f6ce91 → 241bf39 → e3da36e → 4f627f9 → a414616 → ebd434e → 1a37f17 → 32a77c7
```

| 提交 | 内容 | 备注 |
| --- | --- | --- |
| `b5ca239` | board_search 空 Finder 访问异常与转场稳定性 | 上一棒遗留（docs/57 §2.3） |
| `c1addd6` | board_search 展开竞态与元素访问时序 | 上一棒遗留 |
| `9f6ce91` | **0009 RST 补丁正式入档并闭环 manifest** | manifest 5 补丁 / 21 validationFiles / 31 afterFiles（已复核） |
| `241bf39` | invoke 计数器时序加固 + 错误码拆分 | 上一棒遗留 |
| `e3da36e` | counter 诊断字段首扩（present/count/tallyKeys/lastJsError） | 上一棒遗留 |
| `4f627f9` | docs/57 新增 | 上一棒遗留 |
| `a414616` | board_search_history 阶段竞态修复 | **后被证明无效但无害**（只改等待条件没动点击目标） |
| `ebd434e` | docs/57 事实修正 | |
| **`1a37f17`** | **tap 落点根因修复（改点标题 ListTile）——本轮核心 1** | 见第四节 |
| **`32a77c7`** | **counter 诊断 P0–P2 全量加固——本轮核心 2** | 见第五节 |

---

## 三、CI 现状

### 3.1 run `42496318563`（已用 `gh run view` 核实）

- headSha `c1addd67e70bfb9dac2c3b08cdb00d7281c9810b`（= `c1addd6`），分支 `codex/network-batch/with-emulators-flutter-test-c1addd6`，终态 **failure**。
- job 结论：`zerotier-keystore` / `zerotier-android-abi` / `transport-source` / `native` / `flutter-source` / `apps (tauri)` / `apps (flutter)` 全 **success**；`android-pairing / flutter-device-key` 与 `android-pairing / android-device-key` **failure**；`input-fixture` / `input-host-candidate` **skipped**。
- 失败的正是本轮 `1a37f17`（flutter tap 落点）与 `32a77c7`（android counter 诊断）要解决的两个 device-key。
- 更早失败脉络（docs/57 §五）：`42491948751`（空 Finder StateError）、`42496318563`（android `counter_unavailable` 第 3 连）、`42501992442`（android 新码 `no_ipc`；flutter 前移至 `board_search_history`，产物 `line=132` = `android_public_ui_phase_timeout` 60s until 超时）。

### 3.2 0009 补丁从未进过 CI 编译

0009 补丁（`validation/native/candidates/zerotier/patches/0009-closed-port-rst.patch`，manifest 5 补丁 21 validationFiles 31 afterFiles）**从未在任何 CI run 中 apply + NDK 编译过**——下一轮推送是首次。静态核对已自洽：0009 hunk 落在 0008 新增块上、tcp_out 两补丁不重叠、afterFiles sha256 全一致。

---

## 四、tap 落点根因定案（本轮最重要成果，三方独立收敛）

### 4.1 根因（Flutter 3.47.9 `ExpansionTile` 结构变化）

Flutter 3.47.9 中 `ExpansionTile` 已重构为 `Expansible > AnimatedBuilder > DecoratedBox > Padding > Column[header, body]`。组键的 `Element.renderObject` 向下取第一个 `RenderObjectElement` = **RenderDecoratedBox**，其尺寸 = header+body 整块。展开态 `tap(group)` 取整块**中心** → 落在 body 第一个子行 → 触发子行 onTap（openBlocked）而非折叠。

- `a414616` 只调等待条件、没动点击目标 → 无效（保留无害）。
- 结论由三方独立收敛：本地探针实证 + 两个独立审查代理源码核对。

### 4.2 修复（`1a37f17`）

`groupHeader(group)` = 组内唯一**无 key 的 ListTile**（子行全带 `host-blocked-target-*` ValueKey）：

```dart
Finder groupHeader(Finder group) => find.descendant(
    of: group,
    matching: find.byWidgetPredicate((w) => w is ListTile && w.key == null)).first;
```

文件 `validation/flutter/integration_test/android_pairing_observe_test.dart`：定义 `:192`；三处调用点 `:653` / `:655`（board_search_history 收起/重开）+ `:1305`（blocked_history 同族隐患），均配合 `tapStablePointer`。

### 4.3 实证与边界

- 本地 3.47.9 SDK 三探针全过（`/tmp/herdr-flutter-probe/test/expansion_tile_arbitration_test.dart`，文件现存；路径在 /tmp，重启后可能消失）：`ARBITRATION_RESULT_MINIMAL=[row1]`、`REALISTIC=[row]`、`FIX=[toggle:false]+rowsInTree:0`、`REOPEN=[toggle:true]`。
- **维护约定**：`groupHeader` 依赖「子行必有 key、header 无 key」——后续 UI 改动必须守住这个不变量。
- **风险**：未在 CI 全流程跑过（仅探针级验证），`1a37f17` 的最终判定以 0010 轮 CI 为准。

---

## 五、counter 诊断加固（`32a77c7`，+283/-51）

对象：`validation/remote-harness/android_gui.py` + `validation/remote-harness/test_android_blocked_gui.py`。

| 级别 | 内容 | 锚点（已核实） |
| --- | --- | --- |
| P0-1 | 捕获阶段 click 探针：`+clickSeen`/`+lastClickTarget`、`__herdrClickHook` install-once 守卫、白名单清洗钳制 | `:284`、`:507-510`、`:306-309` |
| P0-2 | 错误前缀 `sync:`（window error）/ `async:`（unhandled rejection）+ `errorCount` | `:514`、`:516` |
| P0-3 | 失败时读 `#host-home-status` 文本 → `homeStatus`（截断 120 字符） | 读 `:863`、字段 `:138` |
| P1-1/2/3 | 清理 finally 保护 / CDP 断连 fail-fast（`read_invalid`、`cdp_transport_failed`、`cdp_command_failed` 直接 re-raise）/ 所有失败路径统一附证 | |
| P2 | `no_ipc` 判据收紧：tally 必须含 `host_list` 或 `network_list` 命令 | |

- **判读边界**：`sync:` 前缀证明捕获了 window error，但归因到 handler 需结合 click 邻近 `errorCount` 比较，前缀单独不构成绝对证明。
- 若 `homeStatus` 显示「本机资料不可用；仍可打开手动连接表单。」即证明 `refreshHosts` 吞错。
- 4 处有意偏离已报备：真解绑 click 监听 / error hook install-once / after_click 提前采样 / 前缀解释边界。
- 验证：unittest 21+37=**58 项全绿**；Node 沙箱实测注入 JS（双装不累积、remove 后 0 监听器）。
- **目的**：CI android-device-key 若再挂，`counterContext` / `counterClickContext` / `homeStatus` + 拆分错误码（`no_ipc` / `_unsettle_timeout` / `_install_failed` / `_read_invalid`）足以定案 `no_ipc` **三选一**根因：① `refreshHosts` 吞错（`validation/tauri/src/remote.js:763` onclick 先抛被吞）② revision 早退 ③ native false。

### 5.1 独立 diff 审查结论（已闭环）

**GO / APPROVE**——零 CRITICAL/HIGH/MEDIUM 发现，58 项 unittest 全绿无 skip。2 条信息级观察不阻断：

- tally 64 键上限存在理论遮蔽，但 app 命令面远小于 64，实际不可达；
- `_counter_count_reached`（`android_gui.py:739`）语义并入 `_counter_probe`（`:728`），仅剩 device-impact 调用方。

审查另确认：**P2 `no_ipc` 判据收紧无 false negative 风险**——新门严格窄于旧门，原判 `no_ipc` 的场景不可能变绿。

### 5.2 `no_ipc` 三分支互斥定案签名（照此判读）

| 根因分支 | 签名（字符串均已在源码核实） |
| --- | --- |
| ① `refreshHosts` 吞错 | `homeStatus` = 「本机资料不可用；仍可打开手动连接表单。」 |
| ② revision 早退 | `homeStatus` 停留初始「正在读取本机资料…」（`validation/tauri/index.html:12` 的 `#host-home-status` 初始文本）+ `clickSeen ≥ 1` + tally 无 `host_list` |
| ③ native false | `homeStatus` = 「浏览器预览不读取本机主机资料。」（`validation/tauri/src/remote.js`）+ `counterContext` 佐证 |

click 未落地（`clickSeen = 0`）盲区也已由 P0-1 探针补齐。

---

## 六、下一轮推送方案（已核验，直接照做）

### 6.1 分支与推送

- 分支名：`codex/network-batch/with-emulators-zerotier-0010-<最终 HEAD 7 位短 sha>`。当前栈 HEAD 为 `32a77c7`；若审查后追加修复提交，以推送时实际 HEAD 为准。
- 命名已核验：该前缀 9 job 跑 / 2 input job 跳过，concurrency 按分支隔离；0008 run `42484673979` 同型实证。
- 本地栈为线性栈，新分支直接建于 HEAD 即可，无需合并提交。

### 6.2 取证速查

```bash
gh run download <run_id> --name android-emulator-pairing-<完整40位sha>   # tauri-android-progress.json → counterContext / counterClickContext / homeStatus / 拆分错误码
gh run download <run_id> --name flutter-android-emulator-pairing-<完整40位sha>  # flutter-android-test-failure.json（上一轮 board_search_history 卡 line=132）
```

### 6.3 CI 操作纪律

1. 一轮只推**一个**触发分支。
2. **不 force push**；**不删远端分支**；**不用 workflow_dispatch**。
3. CI 监控用**单个后台 until 循环**（`sleep 90`），禁止前台重复 `gh run view`：

```bash
until gh run view <run_id> --json status --jq '.status' | grep -qE '^(completed|failure|cancelled)$'; do sleep 90; done
```

4. 提交守卫（严禁 `git add -A` / `git add .`，逐路径 add）：

```bash
git diff --cached --name-only | grep graphify-out   # 必须为空
```

### 6.4 风险预告

- **0009 首次 CI 编译**：若 `zerotier-android-abi` 挂，优先查 patch rejected / afterFiles 哈希不符。
- 0009 行为测试（`rst_closed_port_test.cpp` / `run_rst.py` / `test_zerotier_candidate.py`）不在任何 CI 执行范围，属**已知盲区**。

---

## 七、Stage 2 门控范围审计（本轮新产出；等用户明示授权，严格锁定）

### 7.1 术语澄清

文档所谓「bindNative 激活」对 ZeroTier 是**新增**不是拨开关——ZeroTier **无** bindNative 方法；Rust `bind_zerotier()`（`validation/android-network-source/src/zerotier.rs:105-165`）已实现但生产宿主零调用、零 JNI 导出；EasyTier / Tailscale 的 bindNative 已激活且 CI 绿。

### 7.2 三层结构性排除（当前为何 ZeroTier 不可达）

1. **清单排除**：`android-production-sources.txt` 13 文件不含 `AndroidZeroTierNative.java`（该文件在 `validation/network-profiles/native/android/`），Gradle Sync 构建时清除清单外文件。
2. **服务降级**：`available` 恒 false，5 个写操作 fail-closed。
3. **宿主不加载**：两壳 Kotlin 只 `loadLibrary` easytier / tailscale（已核实 `validation/flutter/native/android/NetworkRuntimeChannel.kt:84-89`、`validation/tauri/android/DeviceKeysPlugin.kt:78-79`）。

反向断言钉死：`validation/network-profiles/native/android/tests/run-production-sources.py:41,52,95-99,146-147` + `validation/native/tool/test_android_zerotier.py:53-58`。

### 7.3 改动清单（行号锚点均已核实）

| 项 | 内容 |
| --- | --- |
| A bindNative 新增 | `AndroidZeroTierNative.java:8-21` 加声明；`validation/flutter-network-runtime/src/native.rs:73` 后与 `validation/android-network-source/src/lib.rs:67` 后加 JNI 导出；`validation/native/tool/android_bundle.py:30-31` `ZERO_TIER_JNI` 加项 |
| B 切片反转 | 清单追加 + `validation/network-profiles/native/android/network-secrets.gradle:5-8` 注释 + `run-production-sources.py` 四处断言翻转 + `validation/flutter/tool/ci.py:219,230` + `validation/network-profiles/native/android/README.md:19-28` + 同目录 `ZeroTierAndroidStore.md:51-56` |
| C 宿主接线 | `NetworkRuntimeChannel.kt:84-89` / `DeviceKeysPlugin.kt:78-79` 加 loadLibrary+bindNative；两壳 Cargo.toml 加 `network-zerotier` feature；`.github/workflows/android-network-experiment.yml:153,222,250` 加 `--zerotier` |

### 7.4 验证顺序 S1→S5 与授权建议

- **S1** 只加入口不接线（零行为变化）→ **S2** 切片反转（离线 Gradle 验证）→ **S3** CI 打包（`zerotier-android-abi` 绿 + 产物含 `libhp_zerotier.so`）→ **S4a/S4b** 双壳接线（可并行两 PR）→ **S5** 真实设备验收。
- **最小授权建议**：先批 S1+S2（纯离线、零设备风险）；S4（唯一不可逆面）二次授权。
- 风险：JNI 链 Android 零运行记录；**不可逆点在设备状态**（AndroidKeyStore + noBackupFilesDir 身份记录）；`bind_zerotier` 是 OnceLock 进程级单例、绑定后无运行时回滚；私钥经 JNI 进出；反向断言翻转语义最敏感。
- 完成判据：设备 `status()` `available:true` 且 GUI 能建真实身份；5 个相关 CI job 绿；APK 内 `.so` 哈希与已验证 bundle 一致。

---

## 八、本地环境资产

- Flutter 3.47.9 SDK 装在 `~/flutter-3.47.9`（Dart 3.13.7，commit `c197ca5199`，与 `validation/flutter/README.md:29` 固定值一致）。
- **关键坑**：不能在仓库 `validation/flutter/` 直跑 flutter test/analyze——pubspec 声明的 `assets/` 目录不存在（CI 由 `ci.py prepare` 组装）；且源仓库 pubspec 无 integration_test 依赖（harness 在生成的 runner/app 动态注入，本地 analyze 报的 2 个 `uri_does_not_exist` error 是环境既有非缺陷）。正确路径：`python3 validation/flutter/tool/ci.py prepare --destination /tmp/<工程>` 再在临时工程跑。
- 本机无 Android SDK/NDK/AVD，设备级验证只能靠 CI 产物。
- `graphify-out/` 未跟踪不入库；本轮已跑过 `graphify update .`。

---

## 九、新会话第一步清单（按序）

1. 复核工作树干净（`git status` 应仅 `?? graphify-out/`）。
2. `32a77c7` 独立 diff 审查**已闭环：GO / APPROVE，零 CRITICAL/HIGH/MEDIUM 发现**，无修改要求，可直接推送（结论与三分支签名见 §5.1 / §5.2）。
3. 合并本地栈推 0010 分支（命名规则见 §6.1）+ 单个后台 until 循环监控终态（§6.3）。
4. 预期焦点：android-pairing 两 job——
   - **android-device-key**：靠新 counter 诊断定案 `no_ipc` 三选一根因（§5）；
   - **flutter-device-key**：靠 `1a37f17` 过 board_search_history（§4）。
5. Stage 2 保持锁定等用户授权（建议用户先批 S1+S2，§7.4）。
6. OpenViking 项目目录：`viking://user/hadyenvip/resources/herdr-pocket/`（`notes/` 有本轮多份笔记；本文档亦已归档为 `notes/2026-11-09-handoff-doc-58.md`）。

---

## 十、关键文件路径速查

| 用途 | 路径 |
| --- | --- |
| Flutter pairing 测试（groupHeader） | `validation/flutter/integration_test/android_pairing_observe_test.dart`（定义 `:192`；调用 `:653`/`:655`/`:1305`） |
| ExpansionTile 探针 | `/tmp/herdr-flutter-probe/test/expansion_tile_arbitration_test.dart`（易失） |
| android GUI harness（counter） | `validation/remote-harness/android_gui.py` |
| android GUI 测试 | `validation/remote-harness/test_android_blocked_gui.py` |
| Flutter GUI harness | `validation/remote-harness/flutter_android_gui.py` |
| Tauri 主页 onclick | `validation/tauri/src/remote.js:763` |
| 0009 补丁 / manifest | `validation/native/candidates/zerotier/patches/0009-closed-port-rst.patch` · `validation/native/zerotier-candidate.json` |
| ZeroTier Rust bind | `validation/android-network-source/src/zerotier.rs:105-165` |
| JNI 候选 Java | `validation/network-profiles/native/android/AndroidZeroTierNative.java` |
| CI 工作流 | `.github/workflows/android-network-experiment.yml` |
| 上一棒交接 | `docs/57-session-handoff-2026-11-09.md` |
| 历史全量交接 | `docs/56-project-status-and-handoff.md` |

---

## 十一、交接清单（勾选项）

- [x] tap 落点根因定案（三方独立收敛）+ 修复 `1a37f17`（探针级验证过，CI 待验）
- [x] counter 诊断 P0–P2 加固 `32a77c7`（unittest 58 项全绿 + Node 沙箱实测）
- [x] Stage 2 门控范围审计（三层排除 + A/B/C 改动清单 + S1→S5）
- [x] 本文档 + docs/56 指针更新
- [x] `32a77c7` diff 独立审查结论：**GO**（零 CRITICAL/HIGH/MEDIUM，58 项全绿无 skip）
- [x] 复核工作树干净（仅 `?? graphify-out/`）——第三棒核实
- [x] 推 0010 触发分支（`codex/network-batch/with-emulators-zerotier-0010-3a3b86a`，run `42543432734` 已终态）
- [x] 后台 until 循环等 run 终态（0010 failure：7 绿 / 2 device-key 败 / 2 input 跳过；`zerotier-android-abi` 绿＝0009 首次 CI 编译通过）
- [x] 读 `counterContext` / `counterClickContext` / `homeStatus`——**三选一签名表全部不成立，前提已推翻**：真实根因是 harness 插桩缺陷（tauri 2.12.5 `internals.invoke/ipc/postMessage` 全为不可写 defineProperty，赋值静默无效；旧版脚本假成功路径 → 前几轮 `no_ipc` 同源）。修复 `f7b8e9c`（插桩改挂 `window.ipc` 原生桥）+ `f074a70`（失败上报 ipcProbe 描述符探测）。
- [x] 验证 flutter-device-key 过 board_search_history——`1a37f17` 生效；新败点 `board_search_clear`＝懒 ListView 回收（滚动后清除按钮出 viewport），修复 `505eba6`（点击前 `jumpTo(0)` 回顶）。
- [x] 分支整理（第三棒）：本地删 16 支 + main 追平 + 释放 pairing-retry worktree；远端删 39 支（43→3，删前核实无 in-progress run/PR）。待用户裁决：本地 `codex/zerotier-apk-wiring-20261108`（独有 0ab7f76）与远端 `codex/android-baseline-20261105`（独有 b086299）。
- [x] 0011（run `42548234405`）终态 9 绿/1 败：**android-device-key 首次全绿**（`window.ipc` 桥 counter 真计数，board gate 过；后三连绿）；flutter 前进为 StateError line 668（jumpTo finder 写法）→ `b8331af` 修正（descendant Scrollable）。
- [x] 0012（run `42549882281`）终态 9 绿/1 败：flutter errorClass other + line 141（tap 时 finder 已空，FlutterError）→ `2fb8cf1`（clear/reset 改 `tapStablePointer` + 白名单收录 FlutterError）。
- [x] 0013（run `42552265165`）**adb 基础设施假失败定案**：failure null、cleanup primaryFailure `flutter_android_adb_failed`、signer not_completed、app 未装上、集成测试未开始；非代码回归，按假失败判据原 HEAD 重推 `0013b`（run `42553557053`）验证。
- [x] 0013b（run `42553557053`）终态 9 绿/1 败：干净环境，flutter 停在 `board_search_clear`（until 10s 超时 line 132）。
- [x] 0014（run `42554866937`）：flutter 报 `TestFailure`、行 132（`board_search_clear`）；`apps (tauri)` 因 crates.io 网络瞬断失败；`android-device-key` 绿。
- [x] 0015~0017 轮次：flutter 产物报 `failure: null`、errorCode 报 `flutter_android_test_exited_board_search_clear`；排查证实 Python harness 的 `safe_board_search` 存在失败路径硬性要求布尔全为 True 导致丢弃未决快照的代码缺陷（0017 云端真实退出路径是否走到该分支未定案）；`android-device-key` 在 0015 绿、0016 因 CDP 握手抖动报 `android_driver_failure`@pairing 挂、0017 恢复全绿。
- [x] 0018 轮（run `42565205720`，`0bc3b52`）：`android-device-key` 第 7 次全绿；`apps (tauri)` 因 gradle 下载 HTTP 504 瞬断失败；flutter 产物**首次带出完整 boardSearch 快照**（诊断通道打通，`failure: null` 现象消除）——errorClass TestFailure + 行 132 ＝ `until()` 超时而非清空按钮缺失，两处超时（tapStablePointer 10s 落点 / 等空结果 60s）原行号不可区分。
- [x] 本地批次完成并提交（`acfac95` / `f4d9241` / `fbf419d` / `846ac40`）：
  1. 拆分 `board_search_clear_reset_visible` / `_reset_tap` 阶段名（Python 与 Dart 白名单同步），失败快照改真实步进值，失败行号改为按函数名过滤 helper 帧取首个业务帧（匹配不到时退回首个含本文件行号的帧）。
  2. 本地深滚探针坐实**三处同族懒列表缺陷**并修复：`device_impact_enter` 的 hosts-networks、`delete_local_identity` 的完成提示（列表顶部）、设备审查返回后的 hosts-add —— 深滚后均在树中被回收（实测 in tree = 0），裸 until 只会空等 60 秒。
  3. 新增 `validation/flutter/test/host_catalog_scroll_recycling_test.dart` 把回收行为固化为仓库正式回归用例（CI 的 flutter-source 与 flutter-device-key 跑整目录 flutter test）。
- [x] 0019 轮（run `42571118374`，`3a7f7a8`）终态 failure，逐项归因：`native`＝HTTP 504 瞬断；`android-device-key`＝gradle.org 下载 timeout 10s → APK 构建失败 → AVD 未启动（与 0018 的 apps 504 同源）；`flutter-device-key`＝setup-java 步骤失败（job 启动层）；`flutter-source`＝**真实回归**：新增回收用例带 unused import 使 analyze exit 1——已修复（`0eabffd`）。回归用例第二条按审查意见重写为真实覆盖回收路径（`5ac7843`）。核心验证目标（清空/重置阶段拆分 + 三处懒列表修复）因 gradle.org 网络问题未获云端验证，待下一轮。
- [ ] **等用户明示授权**后才动 Stage 2 门控（建议先批 S1+S2）
