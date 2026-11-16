# 2026-11-16 迭代收口与交接

本页汇总本轮普通 SSH / UI、终端内核评估、Linux 双网与 Android 设备分层结果。它只记录已固定源码、已验证工件及可复跑入口；**未终结的 Tauri / Android 产品启动不写为通过**，也不把桌面 Widget 截图写成 Android 真机证据。

## 三个会话的交付

| 会话 | 交付与固定点 | 证据 | 当前边界 |
| --- | --- | --- | --- |
| Flutter S10（Pi，p9） | [`579e4fa`](https://github.com/Luck9Star/herdr-pocket/commit/579e4fad550de2a2b517558f04a6552e5848da73)：S10 主机指纹变化页阻断认证；重新核对为同目标重探且不离栈；待重审期间锁定凭据、认证方式、私钥粘贴与连接；取消保留旧信任 | 正式 SSH runner 27+2 全通过（[320 图](evidence/design-parity-20261115/flutter-s10-320.png) · [390 图](evidence/design-parity-20261115/flutter-s10-390.png) · [320 JSON](evidence/design-parity-20261115/flutter-s10-320.json) · [390 JSON](evidence/design-parity-20261115/flutter-s10-390.json)）；独立全新 checkout 固定 Flutter 3.47.9，`flutter analyze` 通过、完整套件 562 通过 7 跳过 | 图源是 Flutter 桌面 Widget（API35 字体 / 中文渲染链路），**不是 Android 真机触控或 Tauri UI** |
| Tauri S10（Pi，p9，最后实现） | [`e415f6a`](https://github.com/Luck9Star/herdr-pocket/commit/e415f6a)（整合分支）：S10 审查视图与锁定语义；主按钮用产品 primary，警示浅红卡、核验白卡、两动作竖排；阻断时隐藏通用标题与重复 status | Node 全套 **604/604 通过**；[320 图](evidence/ordinary-ssh-s10-20261116/tauri-320-refusal.png) · [390 图](evidence/ordinary-ssh-s10-20261116/tauri-390-refusal.png) · [来源 JSON](evidence/ordinary-ssh-s10-20261116/tauri-320-390-refusal.json)；macOS 实窗验收见下节 | 仓库两张 PNG 由**实际产品入口 + 本地 mock 桥**在 headless Chrome 产出（JSON 标注 `source=mock-bridge`）；真实 WKWebView 实窗结论由主控在同一提交上执行并记录 |
| Rust / Tauri 初步（Claude） | [`8657bc2`](https://github.com/Luck9Star/herdr-pocket/commit/8657bc2)：上报被拒握手实际出示的指纹（`host_key_change` 事件 + `presentedFingerprint`） | Rust 指定夹具 **103 + 1** 通过；事件契约见 `validation/transport-rust/src/direct_shell.rs` | 只负责上报出示指纹与桥接，未做界面锁定与视觉收口 |
| 原生 / netmon（OMP，p8） | 固定 `45ea7dc` 的 Android 接口 getter + 同 UID 诊断；run [43787376865](https://github.com/Luck9Star/herdr-pocket/actions/runs/43787376865) 与 [43791265216](https://github.com/Luck9Star/herdr-pocket/actions/runs/43791265216) | [plain 脱敏设备 JSON](evidence/dual-overlay-20261115/android-m2-ui-43787376865-plain.json) · [optin 脱敏设备 JSON](evidence/dual-overlay-20261115/android-m2-ui-43787376865-optin.json)，均从原仓 `build/verification/m2-android-ui/run-43787376865/{plain,optin}/result.json` 原样复制 | ABI 枚举已证；产品启动仍 SIGABRT，根因未确证 |

## 普通 SSH 与界面

S10 设计目标为「主机指纹发生变化」时阻断连接与输入，给出旧 / 新完整 SHA256、目标与独立核验提示，只允许「重新核对主机指纹」或「取消连接，保留旧信任」，没有「忽略变化继续」出口。实现见 [direct_ssh_page.dart](../validation/flutter/lib/direct_ssh_page.dart)；设计参照 [v2-S10](../design/evidence/v2-S10.png) 与 [v2-coverage](../design/v2-coverage.md)。

两壳各自实现，语义一致但渲染层不同：

- **Flutter**（[direct_ssh_page.dart](../validation/flutter/lib/direct_ssh_page.dart)）：[320 图](evidence/design-parity-20261115/flutter-s10-320.png) 与 [390 图](evidence/design-parity-20261115/flutter-s10-390.png) 由真实轮换回环 SSH peer 的 `onVerifyHostKey` 指纹产出，JSON 证据含算法、完整指纹与二次换 key 记录，无合成指纹。测试入口 `python3 validation/flutter/tool/direct_ssh_fixture_runner.py --project <prepared-project>`：先跑原 27 项，再跑 2 个 S10 用例；每个轮换用例独立起 peer，二次换 key 用同端口的新 key material（fixture 支持 `HERDR_FIXTURE_PORT` 与 `SO_REUSEADDR`）。
- **Tauri**（[direct-ssh-ui.js](../validation/tauri/src/direct-ssh-ui.js) · [direct-ssh.js](../validation/tauri/src/direct-ssh.js)）：审查视图由 [index.html](../validation/tauri/index.html) 与 [style.css](../validation/tauri/src/style.css) 承载；[320 图](evidence/ordinary-ssh-s10-20261116/tauri-320-refusal.png) 与 [390 图](evidence/ordinary-ssh-s10-20261116/tauri-390-refusal.png) 来自**实际产品入口 + 本地 mock 桥**（来源见 [JSON](evidence/ordinary-ssh-s10-20261116/tauri-320-390-refusal.json) 的 `source=mock-bridge`），未连真实主机。

共同行为：阻断时隐藏表单与通用标题，只留 S10 自己的标题与旧/新指纹；取消返回同目标配置页并保留旧指纹，review、认证方式、凭据与连接保持禁用，直到同目标重新探测且用户主动勾选核对；ready 状态隐藏表单。

**Android 设备验收（Flutter，API 35 x86_64 云模拟器）**：run [43792464010](https://github.com/Luck9Star/herdr-pocket/actions/runs/43792464010)（最终产品 `e415f6a`，结论 success）通过首页入口、独立指纹比对与显式确认、真实终端视图提交与远端回显、UI 断开、凭据清除；协议侧 auth / PTY / shell / marker / 会话关闭均为真，连接 2 次并全部关闭，PTY 尺寸序列记录完整；反向端口、APK 包、自有端口转发、夹具与 Flutter 工具六项清理符合预期。脱敏结果见 [android-ordinary-ssh-43792464010.json](evidence/dual-overlay-20261115/android-ordinary-ssh-43792464010.json)。`physicalImeVerified=false`，且本轮**未执行 S10 设备换钥**。

**macOS 实窗验收（主控在 `e415f6a` 上执行）**：普通 SSH 入口连一次性回环 peer，警示页只显示对应标题，新旧完整 SHA256 均与 peer 的两把真实公钥独立比对相同；取消后实际回到原目标配置并保留旧指纹，复核框、认证方式、密码与连接均锁定；重探同目标获得第二指纹，手动确认前密码与连接仍锁；确认后连接成功、打开键盘、输入 `round-closed-ok` 加 CR，服务端唯一 AUTH 与 PTY、逐字节组合与预期一致，最后断开。该结论来自真实 WKWebView + Rust + SSH；仓库内两张 PNG 另标注为 mock transport。

范围边界：两壳图都不是 Android 真机触控证据，Flutter 图不是 Tauri UI，Tauri 图不是真 Mac 实窗。

## libGhostty 终端内核选择依据

结论沿用 [libghostty-vt 两壳适配评估](64-libghostty-terminal-core-evaluation.md)：只做受控原型，**不替换两壳生产终端**。libghostty-vt `vt-1.0.1` 只解决 VT 字节解析、状态与输入编码的一部分，不是完整 Widget / WebView 界面，也不替代焦点、IME、选择、屏幕阅读、安全输入门槛与远端会话生命周期；1.x 的 C ABI 稳定不等于第三方绑定稳定，官方应用私有 embedder 与可分发的库是不同接口。

现有生产路径保持 Flutter `terminal_view` 与 Tauri `@xterm/xterm` 加 grapheme addon，主机密钥校验、授权门控和帧序由宿主持有；候选适配需单会话单引擎、可回滚，并另行验证写入期间零远端输入。固定版本探针结果见 [native macOS arm64](../validation/ghostty-vt/results/native-macos-arm64-20261115.json) 与 [wasm-node](../validation/ghostty-vt/results/wasm-node-20261115.json)，不把控件实验当作目标 ABI 或五端通过证据。

## Linux 双网

run [43779552028](https://github.com/Luck9Star/herdr-pocket/actions/runs/43779552028)（`45ea7dc`）已验，**两种 stopping order 都跑过**：`et-private/manifest.json` 为 `status=passed`、`stage=complete`、`stopFirst=et`（先停 EasyTier），`ts-private/manifest.json` 为 `status=passed`、`stage=complete`、`stopFirst=ts`（先停 Tailscale）。两例均为 private loopback 传输、isolated namespace、无外部路由、临时凭据已移除、自有进程已停止、TS peer 已清理；停网后旧输入被拒、另一侧仍收到新输入，独立对端字节核验通过，namespace 清理完成。默认配置对照两例（`stopFirst=et` / `stopFirst=ts`）仍为 `status=failed`，单 ET 诊断例亦 failed；`summary.json` 只在 private loopback 口径下判定 `privateLoopbackAcceptancePassed=true`。范围为封闭测试网络与测试配置，不代表物理网络或五端支持；历史与复现见[双网并发验收](65-dual-overlay-validation.md)。

## Android 已知结果

run [43787376865](https://github.com/Luck9Star/herdr-pocket/actions/runs/43787376865)（`aa875b69`，native `45ea7dc`）两腿结果：

- **同 UID 独立 ABI 枚举已证**：Go `net.Interfaces` 为 `errClass=permission`，Bionic `getifaddrs` 成功，Java 接口枚举独立核对；getter 已注册、state 构建成功，normal 3 接口 / 7 地址、QA 4 接口 / 10 地址。证据见 [plain JSON](evidence/dual-overlay-20261115/android-m2-ui-43787376865-plain.json) 与 [optin JSON](evidence/dual-overlay-20261115/android-m2-ui-43787376865-optin.json) 的 `abiEvidence`。
- **产品启动未通过**：plain QA、optin normal、optin QA 三条均在 `lastStage=native-start` 出现 `processCrash=true`、`crashSignals=[6]`（SIGABRT），无 NeedsLogin；key/noise/register/auth 控制面增量为 0。plain normal 腿为 `controlled_variant_probe_failed`，**没有有效 probe 诊断证据**，不得补写为通过。
- 这两份 JSON 是脱敏设备结果原样复制；不输出原始地址、密钥、路径或完整日志。

run [43791265216](https://github.com/Luck9Star/herdr-pocket/actions/runs/43791265216)（`7800f44`）补齐了分阶段标记，四条 ABI 腿（plain normal / plain QA / optin normal / optin QA）的 `abiEvidence.stages` 均为 `library-mapped → abi-version → node-new → node-status → node-start-entered → node-start-returned → node-status-after-start` 全部为真，`store` 为 `reads=3, writes=0, startCode=0`。

因此可以确定：**C ABI 的 `node_start` 已经返回（返回码 0），随后的 `node_status` 也执行完成，SIGABRT 发生在 start 返回之后**，不是发生在 start 调用内部。崩溃根因**仍未确证**，不得写成“崩溃在 start 返回前”，也不得写成已定位到具体函数。最终崩溃归因及修复 SHA 待主控结论。

## 未终结与复跑入口

- Flutter 普通 SSH 的设备侧结果已补入（run 43792464010，success）；Android **双网产品启动** SIGABRT 根因未确证（已排除“崩溃在 start 返回前”）；S10 换钥未在设备执行；物理 IME、物理网络、后台常连与五平台分发均未验证。
- Flutter 复跑入口：固定 Flutter 3.47.9、准备隔离项目后运行 `python3 validation/flutter/tool/direct_ssh_fixture_runner.py --project <prepared-project>`。
- Tauri 前端复跑入口：`cd validation/tauri && npm ci && npm test`（Node 604 项）；Rust 指定夹具 103 + 1 按 `validation/tauri/README.md` 的 cargo 命令执行。
- Linux 双网与 Android ABI 证据按对应 GitHub 固定 run 与仓库 JSON 核对；不要从 Widget 图、mock 桥图或 fixture 通过外推产品启动成功。
