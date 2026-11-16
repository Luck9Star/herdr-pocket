# 2026-11-16 迭代收口与交接

本页汇总本轮普通 SSH / UI、终端内核评估、Linux 双网与 Android 设备分层结果。它只记录已固定源码、已验证工件及可复跑入口；**未终结的 Tauri / Android 产品启动不写为通过**，也不把桌面 Widget 截图写成 Android 真机证据。

## 三个会话的交付

| 会话 | 交付与固定点 | 证据 | 当前边界 |
| --- | --- | --- | --- |
| Flutter S10（`pocket-flutter-s10`，本机会话） | 提交 [`579e4fa`](https://github.com/Luck9Star/herdr-pocket/commit/579e4fad550de2a2b517558f04a6552e5848da73)：S10 主机指纹变化页阻断认证；重新核对为同目标重探且不离栈；待重审期间锁定凭据、认证方式、私钥粘贴与连接；取消保留旧信任 | 正式 SSH runner 27+2 全通过（[320 图](evidence/design-parity-20261115/flutter-s10-320.png) · [390 图](evidence/design-parity-20261115/flutter-s10-390.png) · [320 JSON](evidence/design-parity-20261115/flutter-s10-320.json) · [390 JSON](evidence/design-parity-20261115/flutter-s10-390.json)）；独立全新 checkout 固定 Flutter 3.47.9，`flutter analyze` 通过、完整套件 562 通过 7 跳过 | 图源是 Flutter 桌面 Widget（API35 字体 / 中文渲染链路），**不是 Android 真机触控或 Tauri UI** |
| 原生 / netmon（`pocket-native-omp`，M2-O） | 固定 `45ea7dc` 的 Android 接口 getter + 同 UID 诊断；在 run [43787376865](https://github.com/Luck9Star/herdr-pocket/actions/runs/43787376865) 跑 plain / optin 两腿 | [plain 脱敏设备 JSON](evidence/dual-overlay-20261115/android-m2-ui-43787376865-plain.json) · [optin 脱敏设备 JSON](evidence/dual-overlay-20261115/android-m2-ui-43787376865-optin.json)，均从原仓 `build/verification/m2-android-ui/run-43787376865/{plain,optin}/result.json` 原样复制 | ABI 枚举通过，三条产品启动均 SIGABRT；不是成功交付，最终修复 SHA 待主控结论 |
| Android 双壳（`pocket-android-clients`，Claude） | 负责 Flutter / Tauri 两壳从已校验产物入口取证；接手后校核旧源码误取、重复步骤与误判通过 | 已归档的前序设备 UI 基线见[双网并发验收](65-dual-overlay-validation.md)；**本轮 Tauri 最终 SHA 与两壳最终图待主控发出后补入** | 不先写通过；不依赖手工端口或先前运行残留 |

## 普通 SSH 与界面

S10 设计目标为「主机指纹发生变化」时阻断连接与输入，给出旧 / 新完整 SHA256、目标与独立核验提示，只允许「重新核对主机指纹」或「取消连接，保留旧信任」，没有「忽略变化继续」出口。实现见 [direct_ssh_page.dart](../validation/flutter/lib/direct_ssh_page.dart)；设计参照 [v2-S10](../design/evidence/v2-S10.png) 与 [v2-coverage](../design/v2-coverage.md)。

- [320 宽实测图](evidence/design-parity-20261115/flutter-s10-320.png)与[390 宽实测图](evidence/design-parity-20261115/flutter-s10-390.png)均由真实轮换回环 SSH peer 的 `onVerifyHostKey` 指纹产出，JSON 证据含算法、完整指纹与二次换 key 记录；无合成指纹。
- 测试入口 `python3 validation/flutter/tool/direct_ssh_fixture_runner.py --project <prepared-project>`：先跑原 27 项，再跑 2 个 S10 用例；每个轮换用例独立起 peer，二次换 key 用同端口的新 key material（fixture 支持 `HERDR_FIXTURE_PORT` 与 `SO_REUSEADDR`）。
- S10 图是桌面 Widget 实际渲染与真实 Paramiko 端点驱动，**不是 Android 设备截图**；Android 真机 UI 未完成。

## libGhostty 终端内核选择依据

结论沿用 [libghostty-vt 两壳适配评估](64-libghostty-terminal-core-evaluation.md)：只做受控原型，**不替换两壳生产终端**。libghostty-vt `vt-1.0.1` 只解决 VT 字节解析、状态与输入编码的一部分，不是完整 Widget / WebView 界面，也不替代焦点、IME、选择、屏幕阅读、安全输入门槛与远端会话生命周期；1.x 的 C ABI 稳定不等于第三方绑定稳定，官方应用私有 embedder 与可分发的库是不同接口。

现有生产路径保持 Flutter `terminal_view` 与 Tauri `@xterm/xterm` 加 grapheme addon，主机密钥校验、授权门控和帧序由宿主持有；候选适配需单会话单引擎、可回滚，并另行验证写入期间零远端输入。固定版本探针结果见 [native macOS arm64](../validation/ghostty-vt/results/native-macos-arm64-20261115.json) 与 [wasm-node](../validation/ghostty-vt/results/wasm-node-20261115.json)，不把控件实验当作目标 ABI 或五端通过证据。

## Linux 双网

run [43779552028](https://github.com/Luck9Star/herdr-pocket/actions/runs/43779552028)（`45ea7dc`）已验。工件 `dual-overlay-herdr-45ea7dc…/ts-private/manifest.json` 显示 `status=passed`、`stage=complete`、`stopFirst=ts`、private loopback / isolated namespace / no external routes / temporary credentials removed 均为真；负向服务器审计计数未变，停止 TS 后 `etAfterStop=true`、`tsStaleRejected=true`，`independentExactInput=true`，namespace 清理完成。范围为封闭测试网络与测试配置，不代表物理网络或五端支持；历史与复现见[双网并发验收](65-dual-overlay-validation.md)。

## Android 已知结果

run [43787376865](https://github.com/Luck9Star/herdr-pocket/actions/runs/43787376865)（`aa875b69`，native `45ea7dc`）两腿结果：

- **同 UID 独立 ABI 枚举已证**：Go `net.Interfaces` 为 `errClass=permission`，Bionic `getifaddrs` 成功，Java 接口枚举独立核对；getter 已注册、state 构建成功，normal 3 接口 / 7 地址、QA 4 接口 / 10 地址。证据见 [plain JSON](evidence/dual-overlay-20261115/android-m2-ui-43787376865-plain.json) 与 [optin JSON](evidence/dual-overlay-20261115/android-m2-ui-43787376865-optin.json) 的 `abiEvidence`。
- **产品启动未通过**：plain QA、optin normal、optin QA 三条均在 `lastStage=native-start` 出现 `processCrash=true`、`crashSignals=[6]`（SIGABRT），无 NeedsLogin；key/noise/register/auth 控制面增量为 0。plain normal 腿为 `controlled_variant_probe_failed`，**没有有效 probe 诊断证据**，不得补写为通过。
- 这两份 JSON 是脱敏设备结果原样复制；不输出原始地址、密钥、路径或完整日志。最终崩溃归因及修复 SHA 待主控结论。

## 未终结与复跑入口

- 待主控补入 Tauri 最终 SHA 与两壳最终图；Android 产品启动 SIGABRT 未闭环；真实物理网络、真机触控、后台常连与五平台分发均未验证。
- 本轮 Flutter 复跑入口：固定 Flutter 3.47.9、准备隔离项目后运行 `python3 validation/flutter/tool/direct_ssh_fixture_runner.py --project <prepared-project>`；界面证据按上文相对链接打开。
- Linux 双网与 Android ABI 证据按对应 GitHub 固定 run 与仓库 JSON 核对；不要从 Widget 图或 fixture 通过外推产品启动成功。
