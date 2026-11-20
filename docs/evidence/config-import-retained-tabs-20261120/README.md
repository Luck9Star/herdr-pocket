# M1-05 导入替换保留标签证据（2026-11-20，最终批）

确认导入替换在用主机后的产品决定：立即关闭该主机旧连接、停止自动重连、将已打开标签永久停用但保留最后已显示的画面供阅读和手动关闭；其他主机标签与连接保留；新目标须重新核对、显式连接；目录保存时未知/已撤权的不重启。ADR 记录见 [0007 导入段](../../adr/0007-pairing-and-config-transfer.md)。

本目录为最终证据批，取代早期中间批（Flutter `ce94b49`、Tauri `5ffbbf7`→`f751f05` 前后对照），仅以下归档文件为正式证据。

## Flutter 真实回环（主要证据，最终源）

- 源码：`e74c7ec1346ef0abd6f8111dad662f0d0f8b0810`。
- 测试：671 passed / 41 opt-in skipped，`flutter analyze` 无问题。
- 运行：Widget 桌面 1440×1000 + 两个真实 SSH peer，widget/driver 均在 macOS。拓扑（按 `replay/replay_flutter_m105.py` 核对）：**stock 两个独立 SSH peer 都在 macOS 宿主**（本机 `127.0.0.1` 临时端口）；**guarded 两个独立 peer 在同一临时 Linux 容器**（`Dockerfile.s06-m105`，ubuntu:24.04 + openssh-server，`docker exec` + 发布到 `127.0.0.1` 的独立端口）。guarded 报告中 B b 为导入前、s 为导入后采样；`receiptByteCounts` 为两 peer 各自收到的字节数。
- 归档文件：
  - `flutter/guarded-report.json`（guarded，`status: passed`）
  - `flutter/stock-report.json`（stock 对照，`status: passed`）
  - `flutter/import-before.png` / `import-after.png`（guarded，原尺寸 1440×1000，仅存一份等价对）
  - `flutter/mobile/import-review.png`、`import-retained.png`、`import-closed.png`（390×844）
- 关键事实：guarded 代数和 `receiptByteCounts` `[9,1] → [9,2]`（`[9,1]`＝导入完成后、尚未向幸存 B 显式发送时的采样；`[9,2]`＝在 B 显式发送 1 字节后的采样；替换 peer 收到 9 字节后关闭）；stock 对照全程 `[0,0]`——stock 构建输入被拒，`inputAccepted:false` 是对照语义而非缺陷。两组均含 `replacedTabRetainedAndPeerAdvanced`、`singleInputFocus`、`focusDoesNotRestoreInput`、`lateInputRejected`、`stoppedBoth`、`separatePeerListeners`、`exactExpectedReceipts: true`；peer 生命周期为导入后 1 关 1 开、最终双关。
- 手机三图：review = 导入审查页；retained = 替换后旧标签保留最后画面（A 保留）；closed = 手动关闭旧标签后其余不受影响。

## Flutter 集成候选独立复跑（主代理）

- 集成候选源码：`e4a898765026b9a1c8ebbf3df4b404501a024b33`；两份独立复跑报告 `status: passed`、`preparedSourceMatched: true`，与最终源 `e74c7ec` 批同一重放脚本与拓扑（stock 双 peer 在 macOS，guarded 双 peer 在同一 Linux 容器）。
- 采样语义：guarded 确认导入替换后，手工向原 B peer 新写 1 字节——导入前 `[9,1]`、导入后 `[9,2]`，证明幸存 B 连接仍活着并收到字节；stock 对照（输入被拒）前后均 `[0,0]`。
- 归档文件（`flutter/integration-e4a8987/`）：`stock-report.json`、`guarded-report.json`（真实产物原样拷贝，SHA 见 SHA256SUMS）、`import-before.png` / `import-after.png`（guarded，1440×1000 原图；stock 同尺寸截图不重复归档）。
- 复跑来源：与最终源同套 `replay/replay_flutter_m105.py` + `Dockerfile.s06-m105`（命令见 `replay/REPLAY.md`）。


## Tauri Linux 原生正式导入（主要证据，本地容器实机）

- 源码：`4541a805007d56c0eed2251c401638439a38b836`；本地隔离 Ubuntu 24.04 arm64 容器，原生 GTK/WebKit 应用直连 WebKitWebDriver，x86_64 stock herdr 经转译执行；同一 OpenSSH 监听、两个配对身份、两条独立认证连接（单 sshd 多身份，非多 sshd 实例）。真实 WebView 文件输入（`input type=file`，无系统 GTK 选择器参与）；测试身份为临时随机 ASCII 口令的进程内存注入身份。
- 归档文件（`linux/`）：
  - `manifest.json`（`status: passed`，S06-two-real-ssh-herdr-targets，含窗口缩放、共享 PTY、清理等完整事实）
  - `s06-tauri-import-replace.json`（导入替换专项计数）
  - `password-input.json`（非 BMP 本地自动输入的脱敏结果：17 字符读回 16、丢非 BMP 后匹配、ASCII 完整——实际人工输入未验证）
  - `s06-tauri-import-preview.png`（导入审查页）
  - `s06-tauri-import-old-retained.png`（A 旧标签保留最后画面，tick 199）
  - `s06-tauri-import-survivor-advanced.png`（B 在原连接上推进，tick 185→211）
- 关键事实：`realFileImport`、`oldFrameRetained`、`oldConnectDisabled`、`oldTabManuallyClosed`、`survivorAdvancedOnOriginalConnection`、`peersClosedBeforeDriverExit` 全为 true。A 侧 1 次认证后导入触发 1 次认可关闭、0 reset；B 侧保持原认证（185→211 推进），最终两侧各 1 次认可关闭、0 reset、0 输入字节。
- 边界：Ubuntu 24.04 arm64 容器为本地隔离环境；物理 IME/真实键盘输入未验证；非 BMP 自动输入读回存在丢字（见 `password-input.json`），以脱敏 JSON 呈现而非宣称通过。
## Tauri WebKit 390×844（补充证据，模拟 IPC，最终源）

- 源码：`ad0d70e384be5877b191840530cc179271ec210c`。
- 范围：生产 Tauri 前端，Playwright WebKit 26.5，390×844，模拟 native IPC；真实 xterm 渲染 + `config_apply` 时的**模拟 native stop（合成迟到撤权 IPC，非真实 native 调用）**。无 SSH、无原生文件选择器、无连续活动会话。
- 测试：JS `node --test` 731/731；Rust `cargo test` 89/89；配置专项 15/15。
- 归档文件：
  - `tauri/report.json`（`passed: true`，含逐条断言与命令账本）
  - `tauri/old-retained.png`（A 旧标签保留最后画面，原尺寸 390×844）
  - `tauri/survivor-resumed.png`（B 新帧：显式恢复后 `BETA-D2-RESUME-1`）
  - `tauri/replay/late-probe.mjs`（探针，仓库相对路径，无私人路径）
  - `tauri/replay-wrapped-report.json`（wrapper 实跑产出，`passed: true`，见下节复跑说明）
- 关键事实：旧标签 Connect 禁用、旧画面 `ALPHA-D2-START` 且终端计数保持 1；保留区域键盘可达（`tabindex=0`、`role=region`、无编辑元素、非 inert）、可滚动；幸存标签 `fixture-beta` 画面保留，显式恢复得 `BETA-D2-RESUME-1`；恰好一次 `config_apply`、一次幸存者 reserve、一次 native stop；无 `remote_tab_input_send`、无页面错误。
- 措辞边界：探针在 `config_apply` 时对被替换主机发合成迟到撤权并验证停用/保留；**未**投递迟到陈旧 dashboard 快照，因此本证据不证明“迟到陈旧快照会被拒绝”。系统读屏（屏幕阅读器）未测。

## 复跑

- Flutter：`replay/replay_flutter_m105.py` + `Dockerfile.s06-m105`（容器 peer）+ `replay/REPLAY.md`（占位符路径说明，仓库基础命令 `python3 validation/flutter/tool/ci.py prepare --destination "$fixture_root/app"`）。
- Tauri：`tauri/replay/late-probe-replay.sh`（在仓库内任意 checkout 执行，无需切换分支）：
  ```sh
  HERDR_D2_PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs \
    bash docs/evidence/config-import-retained-tabs-20261120/tauri/replay/late-probe-replay.sh
  ```
  wrapper 用 `git archive ad0d70e validation/tauri validation/shared validation/vendor` 解入 `mktemp -d` staging，在 staging 内 `npm ci && npm run build`，再以探针约定布局运行——不切换 checkout、不在 checkout 内安装依赖；要求 Node ≥22.12.0（`ad0d70e` package.json engines）与可启动的 Playwright WebKit；强制 `HERDR_D2_BROWSER=webkit`（外部 chromium 环境不会让报告目录漂移或漏复制），且在宣告成功前校验输出 `report.json` 存在、`passed=true`、`sourceSHA=ad0d70e`，不满足即按失败退出。输出落在独立 `/tmp/herdr-late-probe-out-XXXXXX/`（`report.json` + `shots/`），失败时目录保留供诊断。归档的 `tauri/replay-wrapped-report.json` 即本 wrapper 一次实跑产出（`passed: true`，`sourceSHA=ad0d70e`）。
- 裸探针 `tauri/replay/late-probe.mjs` 依赖其旁边的 `./current/validation/tauri/dist` 且固定 `sourceSHA=ad0d70e`，仅在自建 staging 后于 staging 根目录运行；不要在任意干净 checkout 直接执行，以免读不到 `dist` 或错标源码。

## 已验证边界

- 已验证：真实回环下的替换行为（旧连接关闭、停重连、旧标签保留最后画面且不可输入、其他标签/连接不受影响、新目标须显式连接）；Tauri 模拟链路的保留/可达/恢复与单次 native stop。
- 未验证：真机、跨网、五端文件提供方、原生文件选择器、连续长时间活动 SSH、系统读屏；五端逐端覆盖未完成。
- Tauri Linux 正式导入：本地容器原生 GTK/WebKit 实机验证通过（见上文「Tauri Linux 原生正式导入」与 `linux/` 归档）。官方云 Linux x86 路径：R1（run `44640288215`，工件 `14587227607`）首台设备空看板错误；R2（run `44644564603`，工件 `14589381339`）首台配对已过但输入焦点 stale；R3（run `44647186980`，工件 `14589018074`）停在 wide_before 缩放检查——R2/R3 均未执行导入，失败结论保留；PR54 草稿已开，Linux 专项独立 R4 将更新。

哈希见 [SHA256SUMS](SHA256SUMS)。
