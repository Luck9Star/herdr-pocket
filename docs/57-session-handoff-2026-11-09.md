# 2026-11-09 会话交接（自包含）

> 本文档是**本轮最新交接入口**，可脱离其他文档直接接手。历史全量交接见 [56-project-status-and-handoff.md](56-project-status-and-handoff.md)（保留不改其主体）。
>
> 仓库：`/Users/yangyitian/Documents/dev/Agents/herdr-pocket` · remote `Luck9Star/herdr-pocket` · 主干 `main`
> 交接时工作分支：`codex/network-batch/with-emulators-zerotier-0008-c3d3036`（本文档基于 `e3da36e`，其上为本文档自身提交 `4f627f9`）

---

## 一、总体状态（一句话）

**项目未完成。** 本轮产出是 ZeroTier 0009 候选补丁正式入档 + 两端 Android 测试诊断加固；当前只剩 **CI 两个 device-key 作业** 需要收口。**Stage 2 门控（bindNative 激活 + 生产切片反转）严格锁定，等用户明示授权，不得擅自开启。**

| 维度 | 状态 |
| --- | --- |
| ZeroTier 候选链 | 0008 已定稿入档；**0009 已正式入档并经 CI 复验通过** |
| 原生构建/符号 | `-Wl,--no-undefined` + `BOUND_SYMBOLS` 六元组校验在 CI 绿 |
| android-device-key | **失败**（连续 4 轮），根因收敛中，本轮新增 counterContext 判据 |
| flutter-device-key | **失败**（失败点已前移 3 次），本轮需接手者取精确断言 |
| Stage 2 门控 | **锁定**，等用户明示授权 |
| 未跟踪目录 | `graphify-out/`（约 42MB）保持未跟踪，**严禁提交** |

---

## 二、本轮已完成并落地

### 2.1 ZeroTier 0008 候选（B1 UAF + B2 ABBA 死锁）——已闭环

- 三轮独立评审闭环：**REJECT → REJECT → APPROVE**。
- 提交：`c3d3036`（`fix: 关闭 0008 候选 B1/B2 阻断项并定稿三方一致哈希`）。
- 补丁：`validation/native/candidates/zerotier/patches/0008-streams-and-hp-boundary.patch`（终版 911 行，sha256 `ba4654f9…`）。
- CI 中 zerotier / native / transport / flutter-source / apps 相关 job 全绿；本轮 run 42484673979 的 android-device-key 与 flutter-device-key 两个 job 失败（属 Android 端测试，与本补丁无关）。

### 2.2 ZeroTier 0009 候选（N1 closed-port RST / ECONNREFUSED）——本轮正式入档

**提交：`9f6ce91`**（`feat: 正式入档 zerotier 0009 rst 候选补丁并闭环 manifest`）

- 补丁文件：`validation/native/candidates/zerotier/patches/0009-closed-port-rst.patch`
  - 1890 字节
  - sha256 `e2df90f78dbef804777dcc06a93b71706583c95634a214527d78c401d95c898a`（**已复核一致**）
- 修复内容（三处）：
  1. lwIP `pcb == NULL` 时，`tcp_output_control_segment` 改用 `ip_data.current_input_netif` —— RST 从**入站 netif** 应答，不再经全局路由表逃逸到重叠网络（对齐上游 `tcp_rst_netif()` 语义，commit `3666dcc66c8a`）。
  2. `tcp_in.c` 门 `!hp_network || hp_ready` —— drain／teardown 阶段静默，不产生 RST 噪声。
  3. errno 映射：`ERR_RST` → `ECONNRESET`（`errno = 104`），即 closed-port connect 快速失败的应有语义。
- Manifest 三方一致闭环：`validation/native/zerotier-candidate.json`
  - `patches` **5** 项
  - `validationFiles` **21** 项
  - `afterFiles` 更新 lwIP `tcp_in.c`（`df42b49acc01…`）与 `tcp_out.c`（`5135c39b6e7…`）实测哈希
  - `test_zerotier_candidate.py` 锚点测试与 identity-service 补丁集合断言同步适配
- 本地验证结果：
  - 候选测试 **15/15**
  - Android 测试 **9/9**
  - 官方 prepare → apply → verify 链 **4055 文件**
  - RST 套件 **37 项**真实 lwIP 检查通过（IPv4／IPv6 closed-port 均 **0–1ms 快速拒绝**、`errno = 104`、重叠零泄漏、drain/teardown 静默）
- **CI 复验：run `42501992442` 中 `zerotier-android-abi` / `native` / `keystore` 全绿 → 0009 链已在 CI 环境复验通过。**

### 2.3 Flutter 集成测试竞态修复（两轮）——已提交

- `b5ca239`（`test: 修复 android_pairing 测试 board_search 空 Finder 访问异常与转场稳定性`）
  - `rows.first.hitTestable().evaluate().length == 1` → `rows.hitTestable().evaluate().length == 1`（去掉对 `rows.first` 的提前取用，避免空 Finder 时 `.first` 抛异常）；另加一处 `pumpAndSettle(300ms)` 稳定转场。**注意：`:636` 的 `ensureVisible(rows.first)` 仍是无条件取 `.first`**，只靠上方 `until(rows.evaluate().isNotEmpty)` 间接兜底。
- `c1addd6`（`test: 修复 android_pairing 测试 board_search 展开竞态与元素访问时序`）
  - 展开时序倒置修正：**先** `until(rows.hitTestable().evaluate().isNotEmpty)`，**再** `ensureVisible`
  - `.length == 1` → `isNotEmpty`
- 效果：android 侧 board_search 阶段已通过，失败点前移到 board_search_history。

### 2.4 android_gui invoke 计数器加固 —— 已提交

**`241bf39`**（`test: 加固 android_gui invoke 计数器时序与错误码拆分诊断`）

- 4 个抛出点错误码拆分（见 `validation/remote-harness/android_gui.py:75-76`）：
  - `android_board_search_counter_install_failed`
  - `android_board_search_counter_read_invalid`
  - `android_board_search_counter_no_ipc`
  - `android_board_search_counter_unsettle_timeout`
- 等待逻辑由一次性等待改为 **15s 轮询化**。
- 新增 `counterContext` 诊断字段（复用 systemImeFailure 的「异常属性 → `fail()` 净化关口」模式）。

### 2.5 counter 诊断字段增强 —— 已提交

**`e3da36e`**（`test: 扩展 android_gui counter 诊断字段以定案 no_ipc 根因`）

- `counterContext` 追加字段：`present` / `count` / `tallyKeys` / `lastJsError`
- install 环节回读校验 `i.invoke === patched`（确保拦截补丁真正生效）
- `read_invalid` 不再伪装成 `no_ipc`
- click 前后各采一次上下文 → `counterClickContext`（`before` / `after`）
- 净化关口实现在 `validation/remote-harness/android_gui.py:274`（`_public_counter_context`），白名单字段与 url 截断，避免把无界内容写进产物。
- 验证：**47 tests OK** + 隔离 smoke **9/9 PASS**。

---

## 三、当前阻塞（本轮新增诊断结论）

### 3.1 android-device-key（连续 4 轮失败于 board_search）

**CI run `42501992442`：错误码已是新码 `android_board_search_counter_no_ipc` → 证明 `241bf39` 部署生效。**

counterContext 实测（失败时刻）：

| 字段 | 实测值 |
| --- | --- |
| `internals` | `true` |
| `invokeType` | `function` |
| `readyState` | `complete` |
| `url` | `http://tauri.localhost/` |

→ 失败时刻**页面健康**，但 15s 轮询窗口内 `count` 始终未达 ≥1。

**判定**：

- **H2（读数抖动）基本排除**。
- **H3（应用侧 IPC 未触发）最吻合**，两个子候选：
  - **(a)** click 只验坐标命中，未验 handler 是否真正执行。board_search 阶段是「已在主页上再点一次」（`validation/remote-harness/android_gui.py:747` 处 `browser.click('#host-return-home')`），坐标计算与 CDP dispatch 之间存在**重渲染竞态**。
  - **(b)** `#host-return-home` 的 onclick（`validation/tauri/src/remote.js:763`）中 `saveHostDraft()` / `cancel()` **先抛异常并被吞掉**，导致 `void refreshHosts()` 从未执行。
- **H1（页面重载）在失败时刻被削弱，但点击时刻未排除。**

**已排除「拦截补丁无效」**：tauri 2.12.5 `scripts/bundle.global.js` 中 `window.__TAURI_INTERNALS__.invoke = async function(...)` 是**普通赋值**，`@tauri-apps/api/core` 调用时读取该属性 → **拦截点有效**。

**下一轮判读矩阵（照此定案）**：

| counterContext 观测 | 结论 |
| --- | --- |
| `present = false` | **H1** —— 页面在轮询窗口内被重载，注入对象已失效 |
| `present = true` 且 `count = 0` 且 `tallyKeys = []` | **H3** —— 应用侧 IPC 未触发；此时 `lastJsError` 非空即为 onclick 抛错的**直接证据** |
| `present = true` 且 `count > 0` | **H2** —— 读数抖动（计数已到但读取时机偏晚） |

### 3.2 flutter-device-key

**CI run `42501992442`：失败于 `stage = board_search_history`，错误码 `flutter_android_test_exited_board_search_history`。**
TestFailure 记录在产物 `flutter-android-test-failure.json`（**line 132**）。

**历史形态变化（连续前移）**：

| run | 失败点 | 性质 |
| --- | --- | --- |
| `42491948751` | 测试内部空 Finder StateError | 已由 `c1addd6` 修复 |
| `42496318563` | harness 级 `flutter_android_adb_failed` | 基础设施 flaky（详见下） |
| `42501992442` | `board_search_history` | **本轮待接手** |

**run `42496318563` 的 adb 瞬态定性**：`wait_public` 每 0.15s 轮询 `adb shell pm list packages`，`check=True`，**单次非零即全局终止、零重试**；cleanup 阶段 adb 已恢复 → 判为**基础设施 flaky**，非应用缺陷。

**待接手者需要自己确认的**：

1. `board_search_history` 的**精确失败点** —— 产物已给出：`stage=board_search_history`、`errorClass=TestFailure`、`line=132`，即 `android_pairing_observe_test.dart:132` 的 `fail('android_public_ui_phase_timeout')`（`until()` 的 60s 等待超时，**不是**元素访问 StateError）。在 `c1addd6` 版本下超时的是 `:643` 的 `until(rows.hitTestable().evaluate().isNotEmpty)`：无条件第二次 `tap(tester,group)` 把仍展开的 group 又关掉了。
2. 同类竞态模式的既有教训（见 `validation/remote-harness/flutter_android_gui.py`）：
   - Finder 为空时取 `.first`；
   - 在异步树重建完成前 `ensureVisible` / `tap`。
3. **Flutter 3.47.9 生命周期转态强约束**：回前台必须依次 `paused → hidden → inactive → resumed`；断言需适配**每次转态**（参见 commit `4143bca`）。
4. `board_search_history` 是 `BOARD_SEARCH_STAGES` 成员（`flutter_android_gui.py:64-65`）。

---

## 四、待办与下一步（按序执行）

### 步骤 1 —— 取 `board_search_history` 精确失败断言并修复 Flutter 侧

- 取证：CI run `42501992442` → `flutter-device-key` job → 产物 `flutter-android-test-failure.json`（line 132 附近）+ job log。
- 定位 Flutter 测试源码中 `board_search_history` 对应断言，实施**最小修复**（同类竞态模式修正：先等 Finder 非空再取元素、先等树重建完成再 `ensureVisible`/`tap`、`.length == 1` → `isNotEmpty`）。
- 本地提交（**只提测试脚本文件**）。
- **本轮进展（已确认事实）**：失败点已定位，本地已提交 `a414616`（`test: 修复 android_pairing board_search_history 阶段竞态`）修复该竞态；详见下节「五之后」的「本轮新增事实」。

### 步骤 2 —— 推一轮新 CI

本地提交栈（按序）：

```
c1addd6 → 9f6ce91 → 241bf39 → e3da36e →（步骤 1 的 Flutter 修复）
```

合并推到一个**新触发分支**，命名沿用既有约定：

```bash
# 例：先建分支并合并本地栈
git checkout -b codex/network-batch/with-emulators-zerotier-0010-<newsha>
# ...合并上述提交...

# 推送前必须自检（严禁 git add -A / git add .）
git diff --cached --name-only | grep graphify-out   # 必须为空
```

- 触发分支前缀 `with-emulators-` 会激活 android-pairing 云端模拟器矩阵。
- 本轮 CI 同时验证三件事：
  1. **0009 链**（预期绿）
  2. **android 拆分错误码 + counterContext 定案**
  3. **Flutter 修复**
- 监控方式见「第六节 CI 操作纪律」。

### 步骤 3 —— 依 counterContext 判读矩阵定案 android-device-key 根因

- 读步骤 2 的 run 产物里的 `counterContext` / `counterClickContext`。
- 按第 3.1 节矩阵定案 H1 / H2 / H3，再对症修复。
  - 若判 H3(b)：修 `validation/tauri/src/remote.js:763` 的 onclick —— `saveHostDraft()` / `cancel()` 应各自 try/catch 兜底，不得吞掉 `refreshHosts()`。
  - 若判 H3(a)：在 harness 侧点击后**显式验证 handler 已执行**（而非只验坐标命中）。
  - 若判 H1：延长注入有效期或在点击后**重新注入**计数器。

### 步骤 4 —— 收口 Flutter 测试脚本加固待办

两个 device-key 全绿后，再做「Flutter 测试脚本加固」这条待办（adb 轮询零重试导致的全局终止等基础设施问题）。

### 步骤 5 —— Stage 2 门控（等用户明示授权）

- `bindNative` 激活 + 生产切片反转。
- **必须等用户明示授权才可推进。** 不得擅自开启。

### 步骤 6 —— 持续更新历史交接文档

- 每个里程碑更新 `docs/56-project-status-and-handoff.md`（历史全量文档）。

---

## 五、CI 运行历史（简表）

| run | 触发内容 | 结论 |
| --- | --- | --- |
| `42484673979` | 0008 候选 | 7 绿 / 2 败 / 2 跳过；失败项为 android-device-key 与 flutter-device-key |
| `42491948751` | `b5ca239` | flutter-device-key 死于测试内部空 Finder；android-device-key 死于 `counter_unavailable` |
| `42496318563` | `c1addd6` | 7 项绿；flutter-device-key 死于 harness 级 adb 瞬态；android-device-key 仍 `counter_unavailable`（第 3 连） |
| `42501992442` | `241bf39`（含 0009 入档） | native / transport / zerotier-keystore / zerotier-android-abi / flutter-source / apps 全绿；两个 device-key 失败（flutter 前移至 `board_search_history`；android 新码 `no_ipc`） |

### 本轮新增事实（交接文档生成之后）

- 本地已提交 `a414616`（`test: 修复 android_pairing board_search_history 阶段竞态`）。
- 根因：`android_pairing_observe_test.dart` 收起/重开逻辑里的**无条件第二次 tap** 把仍展开的 ExpansionTile 收起，导致 `until(rows.hitTestable().isNotEmpty)` 的 60s 等待永不满足。
- 修复方式：收起判据改 `evaluate().isEmpty`、重开 tap 移入 if 分支、展开顺序改为「等树重建 → ensureVisible → 等可命中」。
- 当前本地提交栈（**未推送**）：`c1addd6 → 9f6ce91 → 241bf39 → e3da36e → 4f627f9 → a414616`。
- 下一轮 CI 触发分支名仍为 `codex/network-batch/with-emulators-zerotier-0010-<newsha>`。

---

## 六、CI 操作纪律（务必成文）

1. 一轮只推**一个**触发分支。
2. **不 force push**；**不删远端分支**；**不用 workflow_dispatch**（该触发器在 `.github/workflows/android-network-experiment.yml:5` 确实存在，但本项目一律靠推送触发分支来跑 CI）。
3. **504 基础设施故障** → 最多 **1** 次重跑。
4. **board_search 应用层失败** → 视为独立缺陷，**不重跑**。
5. 触发分支前缀决定 CI 路由：
   - `codex/network-batch/with-emulators-*` → 激活 android-pairing 云端模拟器矩阵
   - `codex/network-batch/with-emulators-input-*` → 跑 input-fixture
   - `codex/network-batch/with-emulators-input-recheck-flutter-tui-*` → 单独激活 Flutter TUI 模拟器复测
   - 另有若干 skip 前缀用于规避 504 高发外依赖
   - `zerotier-keystore` / `zerotier-android-abi` **无条件运行**
6. 监控方式：**单个后台 until 循环**（`sleep 90`）等待 run 终态；**禁止前台重复 `gh run view`**（会触发循环检测）。

参考实现（单个后台循环，等 run 终态）：

```bash
until gh run view <run_id> --json status --jq '.status' | grep -qE '^(completed|failure|cancelled)$'; do sleep 90; done
```

---

## 七、安全边界（提交前必查）

- `graphify-out/`（约 42MB，未跟踪）**绝不可暂存**。
- **禁止** `git add -A` / `git add .`；必须**逐路径 add**。
- 提交前自检：

```bash
git diff --cached --name-only | grep graphify-out   # 必须为空
git diff --cached --name-only                        # 只应含本次目标的文档/测试文件
```

---

## 八、OpenViking 归档索引（本轮已存，供接手者查证）

全部位于 `viking://user/hadyenvip/resources/herdr-pocket/notes/` 下：

| 文件 | 内容 |
| --- | --- |
| `2026-11-08-0008-b2-review-reject.md` | 0008 B2 评审否决记录 |
| `2026-11-08-0009-draft-rst.md` | 0009 RST 草案 |
| `2026-11-08-0009-review-approve.md` | 0009 评审通过记录 |
| `2026-11-08-ci-run-42484673979-summary.md` | run 42484673979 摘要 |
| `2026-11-08-flutter-test-c1addd6-and-android-gui-diag.md` | Flutter c1addd6 + android_gui 诊断 |
| `2026-11-09-invoke-counter-unavailable-diag.md` | invoke counter unavailable 诊断 |
| `2026-11-09-0009-formalized.md` | 0009 正式入档记录 |
| `2026-11-09-android-gui-hardening-and-run-42496318563.md` | android_gui 加固 + run 42496318563 |
| `2026-11-09-run-42496318563-third-round-diag.md` | run 42496318563 第三轮诊断 |
| `2026-11-09-android-device-key-no-ipc-diagnosis.md` | android device-key no_ipc 诊断 |
| `2026-11-09-counter-diagnostics-enhancement.md` | counter 诊断字段增强 |

---

## 九、关键文件路径速查

| 用途 | 路径 |
| --- | --- |
| ZeroTier 候选 manifest | `validation/native/zerotier-candidate.json` |
| 0009 补丁 | `validation/native/candidates/zerotier/patches/0009-closed-port-rst.patch` |
| 0008 补丁 | `validation/native/candidates/zerotier/patches/0008-streams-and-hp-boundary.patch` |
| 候选锚点测试 | `validation/native/**/test_zerotier_candidate.py` |
| android GUI harness（counter 逻辑） | `validation/remote-harness/android_gui.py`（错误码表 `:75-76`；净化 `:274`；install `:508`；board_search `:737-782`） |
| android GUI 测试 | `validation/remote-harness/test_android_blocked_gui.py`（`:162`、`:168`、`:189-190`） |
| Flutter GUI harness | `validation/remote-harness/flutter_android_gui.py`（阶段表 `:33`、`:64-65`） |
| Flutter GUI 测试 | `validation/remote-harness/flutter_android_test.py` |
| Tauri 主页实现（onclick） | `validation/tauri/src/remote.js:763` |
| CI 工作流 | `.github/workflows/android-network-experiment.yml` |
| 历史全量交接 | `docs/56-project-status-and-handoff.md` |

---

## 十、交接清单（勾选项）

- [x] 取 `board_search_history` 精确失败点（`stage=board_search_history` / `errorClass=TestFailure` / `line=132`）
- [x] Flutter 侧最小修复并本地提交（`a414616`）
- [ ] 合并提交栈 → 新触发分支 `codex/network-batch/with-emulators-zerotier-0010-<newsha>`
- [ ] 提交前 `git diff --cached --name-only | grep graphify-out` 为空
- [ ] 推分支（单分支、不 force push）
- [ ] 后台 until 循环等 run 终态
- [ ] 读 `counterContext` / `counterClickContext`，按判读矩阵定案 android 根因
- [ ] 对症修复 android device-key
- [ ] 两个 device-key 全绿 → 收口 Flutter 测试脚本加固
- [ ] **等用户明示授权**后才动 Stage 2 门控
