# 2026-11-09 会话交接·第二棒（自包含）

> 本文档是**当前最新交接入口**，取代 [57-session-handoff-2026-11-09.md](57-session-handoff-2026-11-09.md) 成为第一入口（57 保留为上一棒历史，事实修正版）。历史全量交接见 [56-project-status-and-handoff.md](56-project-status-and-handoff.md)（主体不改）。
>
> 仓库：`/Users/yangyitian/Documents/dev/Agents/herdr-pocket` · remote `Luck9Star/herdr-pocket` · 主干 `main`
> 交接时工作分支：`codex/network-batch/with-emulators-zerotier-0008-c3d3036`（HEAD = `32a77c7`，本地领先远端 **10 个提交，全部未 push**）

---

## 一、总体状态（一句话）

**项目未完成。** 本轮（第二棒）两大核心成果已本地提交：**flutter tap 落点根因定案并修复**（`1a37f17`）与 **android counter 诊断 P0–P2 全量加固**（`32a77c7`）；下一步就是**合并本地栈推 0010 触发分支跑 CI**，用新诊断定案 android-device-key 的 `no_ipc` 三选一根因。**Stage 2 门控（ZeroTier bindNative 新增 + 生产切片反转）S1/S2/S4 已实施并经 CI 定案（S1=`a801c61`、S2=`48f6637`、S4=`64dff79`+`7d6e006`）；仅 S5 真机物理网络入网与多机并发验收未做（需硬件）。**

| 维度 | 状态 |
| --- | --- |
| 本地提交栈 | 10 个提交未推送（`b5ca239 … 32a77c7`），HEAD `32a77c7` |
| CI run `42496318563` | 已终态 failure：7 job 绿 / 2 device-key 败 / 2 input job 跳过 |
| flutter-device-key | 根因已定案（tap 落点），修复 `1a37f17` 待 CI 验证 |
| android-device-key | `no_ipc` 未定案；`32a77c7` 诊断加固待 CI 出证 |
| ZeroTier 0009 补丁 | 已入档（manifest 5/21/31 闭环），**从未进过 CI 编译**，下一轮推送即首次 apply + NDK 编译 |
| Stage 2 门控 | S1/S2/S4 已实施并经 CI 定案（S1=`a801c61`、S2=`48f6637`、S4=`64dff79`+`7d6e006`）；仅 S5 真机验收未做 |
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
  4. 本地验证全量通过：Python Harness 97 项全绿、Blocked GUI 21 项全绿、Helper 15 项全绿；Flutter 全目录 514 项通过 / 1 skipped / 0 失败；同序探针全绿。
- [x] 0019 轮（run `42571118374`，`3a7f7a8`）终态 failure，逐项归因：`native`＝HTTP 504 瞬断；`android-device-key`＝gradle.org 下载 timeout 10s → APK 构建失败 → AVD 未启动（与 0018 的 apps 504 同源）；`flutter-device-key`＝setup-java 步骤失败（job 启动层）；`flutter-source`＝**真实回归**：新增回收用例带 unused import 使 analyze exit 1——已修复（`0eabffd`）。回归用例第二条按审查意见重写为真实覆盖回收路径（`5ac7843`）。核心验证目标（清空/重置阶段拆分 + 三处懒列表修复）因 gradle.org 网络问题未获云端验证，待下一轮。
- [x] 0020 轮与基础设施超时防御（`14e6671`）：
  1. `flutter-source` 在 0020 中因 `0eabffd` 修复 unused import 恢复通过（analyze 无 issue、`+511 ~1` 加 `+10` 项全过）。
  2. 根因定案：Gradle wrapper 默认由模板生成 `networkTimeout=10000`（10秒），在 GitHub Actions 遇到网络抖动或慢速响应时必定超时报 `Downloading from ... failed: timeout (10000ms)`；且 `validateDistributionUrl=true` 严格要求 https。在 `validation/tauri/scripts/wire-android.py` 增补将 `networkTimeout` 调升至 120000（2分钟），保留 https 协议，并在 `pair-copy-packaging-test.py` 增加回归测试（`14e6671`）。
  3. 同时在 `validation/native/tool/probe.py` 针对 `native` 的 protoc 下载增设 4 次重试与退避防御 504（setup-java 的 Temurin 504 属于外部 action 下载，仍依赖 GitHub Releases 恢复）。
- [x] 0021 轮（run `42575320672`，`3871f7a`）：全矩阵 11 作业中 8 个成功、2 个跳过（`input-fixture`, `input-host-candidate`）、仅 1 个失败（`flutter-device-key`）；Gradle 包装器 120s 超时使 `android-device-key` 顺利构建并验证通过，protoc 重试使 `native` 通过；全仓 CI 收敛至唯一的最后单点：`flutter-device-key` 在 `board_search_clear_reset_tap` 阶段行 725 超时抛出 `TestFailure`（`clearedKeptState: true`，`resetRestoredList: false` 属于行 717 点击前的初始探针默认值，725 中断导致后续 729 行未执行）。
- [x] 0022 本地修复（`d0c813d`）：分析确认行 720 通过 `enterText` 输入无匹配搜索词后，软键盘保持开启并压缩视口，且 `hosts-filters-reset` 按钮落于底部未前置拉回；依照同文件既有规范发送 `receiveAction(TextInputAction.done)` 结束编辑收起软键盘，并在等待与点击前显式增加 `scrollUntilVisible` 滚动前置，确保稳定指针判定命中。
- [x] 0023 基础设施假失败归因与加固（`9807b0f`）：0023 轮遇 GitHub Releases 偶发 504 断流，`run-ci.py` 在下载 herdr 处抛出网络异常致 `fixture_setup_failed`；已增设 4 次重试与指数退避加固防御，保留 `herdr = root / 'herdr'` 路径定义。
- [x] 0024 轮归因与预防加固（`4685034`）：0024 轮中 `flutter-device-key` 报出 `flutter_android_test_exited_before_install`，日志无显式发行包下载超时的文字证据（纯属测试进程在安装前提前退出）。为防范与 Tauri 同源的 Gradle 包装器缺省 10 秒超时风险，在 `flutter_android_gui.py` 预防性增设 `networkTimeout=120000` 改写，保留原地址与校验，不带出原始日志。
- [x] 0025 外部 504 态势诊断：08:07~08:25 间本地探针证实上游 services.gradle.org 与 adoptium 网关发生持续 504 断流，耐受等待外部恢复。
- [x] 0026 轮（run `42595512698`，`26e34ab`）**本批次目标全绿（conclusion: success，9 成功 / 2 跳过 / 0 失败）**：
  1. `android-pairing / flutter-device-key`: **SUCCESS**（stock 观察路径 `android-native-pairing-observe`：`boardSearchEvidence` 双真值、`deviceImpactEvidence`、`blockedTargetEvidence`、`localIdentityDeleted` 全绿），坐实软键盘收起与滚动前置（`d0c813d`）解决看板重置超时；注意本分支为 stock 路径：`directModeDisabled`/`draftModeDisabled`＝true、`receivedInputBytes`＝0、仅含 `keyboard-observe-hidden` 检查点——**docs/56 第 53 行的隐藏标签恢复新完整帧、同观察代增量与十个 TUI 操作回执属 guarded/TUI 路径验收，本分支未执行，不构成「第一阶段彻底完成」**。
  2. `android-pairing / android-device-key`: **SUCCESS**（第 9 次全绿）。
  3. `apps (flutter)` 与 `apps (tauri)`: **SUCCESS**；`native`, `flutter-source`, `zerotier-android-abi`, `zerotier-keystore`, `transport-source`: 全部 **SUCCESS**；input 两作业按规则跳过。
- [ ] **下一步（docs/56 第 53 行余项）**：用 `with-emulators-input-tui-<批次>-<SHA>` 前缀分支跑两端同批输入/恢复验收（隐藏标签恢复原目标新完整帧、同观察代增量、十个 TUI 操作回执），保持 Stage 2 锁定。
- [x] guarded/TUI 停止失败的取证化（`a801c61` → `f70ebcb`）：0021 轮报 `board_search_clear_reset_tap` 行 725 的 `TestFailure`（`manifest.json` 的 `checks[0].errorCode` 即 `android_stale_marker_missing`，说明点击本身成功、失败在点击后 25 秒内未出现「陈旧」）；0022 轮同一代码路径却失败在 TUI 首键回执缺失，**两次结果不同证明是设备侧时序抖动而非单一根因**。据此撤回 `a801c61` 中未经证实的「TUI 后先切回观察模式」绕行（该绕行把失败点从停止阶段前移到 TUI 首键），改为在 harness 中对 TUI 十个辅助键与停止按钮采集**真实指针诊断**（控件矩形、视口尺寸、焦点元素、焦点是否落在辅助键面板内、控件禁用/隐藏、输入状态、是否已有回执；不含终端文本或主机标识），只保留最后两条以守住 16 KiB 产物预算；错误码白名单补齐并透传 `android_control_missing_` 前缀，不再把真实失败点降级为 `android_driver_failure`。**下一轮 CI 给出真实设备上的指针证据后再据此定案并修复。**
- [x] Stage 2 S1（`a801c61`，用户已授权直接开发）：`AndroidZeroTierNative.java` 增加 `bindNative(Context)` 声明与 JNI 导出（后经 0005 定案修正为壳侧唯一转发，见 `7ad16ae`）；`flutter-network-runtime` 与 `tauri` 各加 `network-zerotier` feature（默认关闭）。S2/S4 已于本日获用户授权「持续开发整个 Stage 2」后完成（见下）。
- [x] **0003 轮定案与静止门修复**（run `42617523564`，`7c8e69b`→`9ca7056`→`a74830a`）：真机指针 trace 证实 TUI 首键命中检查与 CDP 事件派发之间布局漂移约 600px（按钮 rect y=1319 而视口 h=851，焦点在 xterm-helper-textarea、hasReceipt 为 direct 旧回执）——点击按旧坐标落空致 `android_input_receipt_missing`；0001 停止失败与 0002/0003 首键失败同为该机制的不同落点，stock 路径布局静止故一直全绿。修复：`browser.click` 派发前加静止门（坐标两次读数一致，量化 1/4px），错误码透传 `android_control_unstable_*`；无条件「派发后命中等待」经审查指出会误杀成功路径（关闭对话框、隐藏面板）已撤回为仅诊断记录 postHit。0004 因该必败问题取消。
- [x] **分支整理与合并**（2026-11-09 深夜，用户指令）：187 提交栈 rebase 到 origin/main（README 冲突首次误取栈侧旧版致主页回退，已以 main 版为基底叠加栈侧增量恢复，`3dfa791`），快进合并推 main（`182411b`）；删除 22 个已并入的 `codex/network-batch/*` 远端触发分支；本地参考分支 `codex/zerotier-apk-wiring-20261108` 确认全部吸收后随遗留 worktree（/private/tmp/herdr-zt-wire，5.2G 构建产物）一并删除。远端保留 `codex/android-baseline-20261105`（2 个独有 patch 为历史 CI 基线）。
- [x] **Stage 2 S2 切片反转**（`48f6637`，用户授权后执行）：`android-production-sources.txt` 13→14 文件纳入 `AndroidZeroTierNative.java`；`ProductionSliceTest` 语义反转（`Class.forName` 必须成功、`createStore(null)` 必须 IllegalStateException 拒绝、未绑定时 available:false 与五个写 fail-closed 断言不变）；`ci.py` 反向断言翻转 + `sharedZeroTierDevice` 溯源改 STAGE 2 表述；README/ZeroTierAndroidStore.md 同步；`run-production-sources.py` 离线 Gradle 闭包 28 命令全绿。
- [x] **Stage 2 S4 宿主接线**（`64dff79` + `7d6e006`，用户授权后执行）：双壳 `System.loadLibrary("hp_zerotier")` + `bindNative`（失败静默、服务保持不可用）；Tauri `network_nodes.rs` 的 `provider_name`/`provider_available`/`initialized`/`binding_for`/`start` 补 Zerotier 分支（match 保留 `_ => Err` 兜底）；Flutter runtime 的 `available_for`/`create_zerotier`/`StartSource::ZeroTier`/`start_node` 与启动 match 全链接入；两壳 Cargo feature `network-zerotier` 补 `herdr-readonly-transport/android-zerotier`（transport-rust 的 `android_zerotier` 模块门控）；workflow `--zerotier` 打包、`HP_ZT_LIB_DIR`、`keepDebugSymbols` 接入。所有 ZeroTier 分支 cfg 对称门控：feature 关闭报 `overlay_provider_unavailable`。本机验证边界：Tauri `start()` 带 `#[cfg(any(test,target_os="android"))]`，须 `cargo check --all-targets` 才编译 test cfg；「0 errors (0 crates)」是假绿，须 touch 源码后见 `Checking <crate>` 行；macOS 不链接 Android C ABI（`hp_zt_*` 桩不完），真 NDK 链接由 CI 承担。
- [x] **0005 轮定案**（run `42625173216`，`64dff79`）：`native`/`zerotier-android-abi`/`zerotier-keystore`/`flutter-source`/`transport-source` 全绿（**S3 打包验证通过，产物含 libhp_zerotier.so**）；`apps (flutter)`/`apps (tauri)` 真链接失败：`ld.lld: duplicate symbol: Java_org_herdr_network_AndroidZeroTierNative_bindNative`——S1 在 provider crate 导出了 bindNative，两壳又各转发一次。修复 `7ad16ae`：删 provider 侧导出（`bind_zerotier` 函数保留），符号表拆 `ZERO_TIER_PROVIDER_JNI`（4 个数据面入口）与 `ZERO_TIER_JNI`（壳库 5 个），新增壳侧转发唯一性测试。
- [x] **0006/0027/0028 三轮定案**：0006（run `42628829429`，`7ad16ae`，input-tui 路径）三失败——①`apps (flutter)` 丢行：`64dff79` 编辑 jniLibs 复制行时吞掉 `libherdr_flutter_network_runtime.so` 的独立复制行，`d891e09` 补回；②Tauri guarded pairing 阶段 `android_control_missing_pair-accept`（命中检查 25s 超时）：已排除六个假说（pair-preview 纯同步 JS、pair_accept 同步纯内存 lib.rs:356、ZeroTier UI 不在配对路径、x86 APK 无 zerotier 模块、disabled 不产生 missing_、静止门失败报 unstable_ 前缀），同字节代码在 0027/0028 两轮 stock+apps 全绿 → **环境抖动定案**，已埋 `pairingPointerTrace`（`7c3b042`）供复现时定案；③Flutter guarded `tui_erase_character`（TUI 第三键 dart 测试进程提前退出，stage 标签透传自 stage 文件）：dart 测试最后改动 `16f9a6e` 在 0001（TUI 十键全过）之前，0001→0006 间零相关改动 + 0027 同码 stock 全绿 → 同抖动谱系。0027（run `42629736390`，`6b0eb99`）与 0028（run `42632587131`，`d891e09`）**全矩阵全绿**（9 成功/2 跳过/0 失败）——重复符号修复与丢行修复均经真 NDK 验证，**Stage 2 S1-S4 证据链完整**。另 `7f34102` 补齐 progress 白名单 TUI 八码并放宽前缀透传为 `android_control_`（0002/0003 的降级掩盖问题收口）。
- [x] **0007 轮终态与定案**（run `42636373928`，`7c3b042`，input-tui 路径）：apps 双绿、native/zerotier 链全绿。Tauri pairing 顺利通过（pairingPointerTrace 记录 `postHit: true`），0006 的 pair-accept 超时未复现，**配对抖动定案坐实**；Flutter guarded 失败于 `tui_erase_character`，`flutter-android-test-failure.json` 证实 failure 为 `{stage: "tui_erase_character", errorClass: "TestFailure", line: 570}`——570 行是功能键等待启用循环（默认 60s），即 backspace 键 `onPressed` 持续 null 超时；树 diff 证实 0001 与 HEAD 的测试逐字节一致，排除代码回归。Tauri guarded TUI 首键回执成功收到（`tuiReceiptsVerified=1`），第二键 `postHit: false`，因白名单修复未合入该分支降级为 `android_driver_failure`。据此提交 `2642efd`：`until()` 增设 `onTimeout` 诊断回调采集按钮计数、`remote-auxiliary-ime-blocked` 提示条状态及输入状态文本，随 `boundedFailure.untilTimeout` 写入失败快照。
- [x] **0008 轮终态与外部断流定案**（run `42642332002`，`2642efd`）：`input-fixture / build` 因 `deps.files.ghostty.org/wuffs-*.tar.gz` 遭遇 `ConnectionResetByPeer` 失败；`paired-android-emulator.yml` 的 `download-fixture` continue-on-error 导致 `GUARDED_INPUT` 为 false，两端 device-key 作业必红且只写「同轮夹具下载失败」；Flutter 与 Tauri stock 真机路径双 `passed`、apps 双绿、ZeroTier 链全绿。
- [x] **0009 轮终态与加固**（run `42645757381`，`2642efd`）：同树重推，`input-fixture / build` 再次因同一 CDN 报 `504 Gateway Timeout` 失败；已主动 cancel 释放 runner。提交三连加固：`9c64f94`（actions/cache 增补 `~/.cache/zig` 并 bump key 后缀）、`5fc220f`（cargo 构建前 grep 枚举所有 `.zon` 依赖，以 180s 超时 × 8 轮指数退避显式 prefetch 进入全局缓存）、`f1d9f7e`（正则放宽至 `.tgz` 与 `.tar.zst`）。
- [x] **0010 轮终态与定案**（run `42648406089`，`5fc220f`，input-tui 路径）：预热步骤穿透 CDN 抖动，夹具全量构建成功并上传。Tauri guarded 在 TUI 首键 `down` 遭遇 `android_control_unstable_remote-input-keys_[data-remote-key="down"]`：原实现将居中滚动与静止门分离，导致布局漂移后缺少 re-scroll 触发 25s 假超时；Flutter guarded 失败于 `tui_erase_character`，`safe_test_failure` 因白名单缺少 untilTimeout 将 Dart 产出的超时快照静默丢弃。定点提交 `9466e70`：Tauri `click` 统一为单循环居中静止门，Flutter 补齐 `safe_until_timeout` 校验器，并在 Dart 测试中增加功能键展开及 `ensureVisible` 预滚动。
- [x] **0011 轮终态与 Flutter 阶段彻底完成**（run `42659301059`，`9466e70`，input-tui 路径）：**Flutter guarded TUI 十键全过、十项回执全数验证（`actionCount: 10`, `applicationStateMatched: true`，全部 checks 通过），彻底达成 docs/56 第 53 行在 Flutter 端的全部验收指标**；`apps (flutter)` 与 `apps (tauri)` 双绿，`native`/`transport-source`/`zerotier-keystore`/`zerotier-android-abi`/`input-fixture`/`flutter-source` 全部成功；Tauri `android-device-key` 仅因构建阶段拉取 `kotlin-compiler-embeddable` jar 遭遇外部 GitHub Releases 500 瞬时错误致 AVD 未启动。
- [x] **0012 轮终态定案**（run `42663394215`，`09914e7`，input-tui 路径，cancelled）：预热 8 轮中 33 个依赖仅 `codeberg.org/vancluever/translate-c` 一个 URL 全败（每轮挂满 180s 超时），其余 32 项 ghostty CDN 全绿；指数退避（15→960s）+ 180s 超时累计拖满 job 60 分钟墙被强制取消。根因链：GitHub Actions 缓存按分支 ref 作用域，0010/0011 的 zcache 存于各自触发分支下，0012 新分支不可见（日志 `Cache not found`），被迫裸拉外网。结构修复 `d6d7ea7`：① 预热降级为限时非致命加速器（`continue-on-error` + 8 分钟步骤限 + 单 URL 60s 超时 + 6 轮固定 15s 退避），真门禁交还构建步骤（独立 40 分钟限时，失败签名可分）；② `restore-keys` 前缀回退使新分支可命中任意历史 key；③ 新增 `cache_seed` 输入支持 main ref 预置全分支可命中的缓存。契约测试同步改语义断言（`618d0c9`）。另查明 `translate_c` 仅被 ghostty 自身测试路径（`!emit_lib_vt` 分支）引用，herdr 的 `-Demit-lib-vt` 构建不依赖它。
- [x] **0013 轮终态定案**（run `42677139938`，`d6d7ea7`，input-tui 路径，failure 单点）：预热降级修复生效——`input-fixture / build` 全绿（33 依赖 round 1 全过仅 46 秒，codeberg URL 本轮直接成功，坐实其为间歇性挂死非封锁）；**Tauri guarded TUI 十键全过**（`tuiReceiptsVerified: 10`、`tuiCompleted: true`，0010 静止门修复坐实）；stock 路径 passed、apps 双绿、其余全链绿。唯一失败点：`stop_observation` 阶段 `android_stale_marker_missing`。根因（stopPointerTrace 三证）：mousedown 落在 `remote-cancel` 上并夺焦 → 终端失焦（同帧 `inputStatus: 焦点已离开`）→ 软键盘收起 → 视口回流 → 布局移位后 mouseup 落到别的元素（`postHit: false`）——press/release 不同元素，浏览器把 click 派发给共同祖先，`cancel()` 从未执行，画面永不标陈旧。修复 `bb2538b`：`click()` 在 mouseup 前重取控件 rect，release 派发到控件新中心保证同元素命中；重读失败（控件已隐藏等成功路径）退回原坐标；postHit 诊断改用实际释放坐标。
- [x] **0014 轮终态：Tauri 端收口**（run `42681783874`，`bb2538b`，input-tui 路径）：**Tauri `android-pairing / android-device-key` 全绿**——释放跟点修复（mouseup 前重取控件位置）生效，停止观察后画面正确标记「陈旧」，docs/56 第 53 行的 Tauri 端 guarded/TUI 指标达成；产物 `tauri-android-progress.json` 坐实 `status: passed` / `stage: complete` / `stoppedStale: true` / `tuiCompleted: true` / `tuiReceiptsVerified: 10` / `stopPointerTrace.postHit: true`。`input-fixture / build`、`native`、`apps (flutter)`、`apps (tauri)`、`flutter-source`、`transport-source`、`zerotier-keystore`、`zerotier-android-abi` 全部成功。失败翻转到 Flutter 端：`flutter-device-key` 报 `flutter_android_adb_failed`，且 **stock 与 guarded 双红**（`stock=1 guarded=1`）。证据链：模拟器**正常启动**（生命周期 `startup: boot ready=true`）→ 设备密钥阶段**已达成**（manifest `matchedDeviceKeyInSshd: true`、`revokedFixtureKey: true`，签名探针 `signatureVerified: true`）→ 后续 adb 操作失败 → 清理时 `cleanup: owned serial absent on attempt 1`（设备中途消失）。故为 runner 侧模拟器/adb 瞬断，非代码回归：Flutter 驱动代码与 0011（run `42659301059`，绿）/0013 同树一致，本轮 diff 只动 `android_gui.py`（DOM/CDP 路径），`flutter_android_gui.py` 未触碰；同批 Tauri 作业全绿。
- [ ] **0015 轮进行中**（run 待查，`d8cf4fd`，分支 `codex/network-batch/with-emulators-input-tui-0015-d8cf4fd`）：给 Flutter adb 失败补有界归因诊断（命令类别 / 退出码 / stdout·stderr 字节数，绝不含输出内容；命令类别走固定词表不复读参数值），把「adb 失败」细化到具体调用以便定案；若 Flutter 复绿则双壳 guarded/TUI 全量收口。
