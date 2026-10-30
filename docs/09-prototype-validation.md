# 核心原型与并行技术验证

> 2026-10-30修复进展：旧baseline结果和下载包保留原结论；本项目实验补丁的最新验证与候选包入口见[阻断修复记录](10-blocker-repair.md)。官方terminal_view 0.5.0原包未修复，实验补丁不是官方发布，UI框架尚未定案。

更新：2026-10-30。当前已完成可审阅的 Penpot 低／中保真核心原型、两条离线验证壳、云端构建及 macOS 有限原生 smoke。**尚无依据锁定 Flutter 或 Tauri；高保真定案与首个真实远端闭环仍待正确性验证。**

## 1. 实际保存的设计交付

[Penpot 可点击原型](https://design.penpot.app/?screen=viewer&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=b55064db-d93d-80f9-8008-ddd22e6d3990&section=interactions&frame-id=c1974894-3caf-8067-8008-ddd4b0a14f71)位于独立 herdr-pocket 项目，沿用账户权限，未开启公开分享。保存后重载确认：56 状态画板 + START 导航、205 条原生交互、18 个组件、25 个语义 tokens、650 个可编辑文本对象。详见[设计入口与准确文件ID](../design/README.md)、[覆盖清单](../design/coverage.md)、[重载证据](../design/evidence/penpot-final-after-reload-20261030.json)。

J1 已实际点击走完手机请求→主机确认→手机扫码→身份审查→主动连通演示→loading→看板；J2 已点击观察→逐键→结果未知；J3 已点击跨网络标签→隐藏恢复→新全量。P1–P7、D1/D2、取消/过期错配/拒绝/指纹变化/目标失效/导入冲突和提交失败均有原生画板及连接。独立只读复核确认J1十条/J2三条/J3三条关键边存在，所有跳转无悬空目标；并未逐一手动点击全部205条边，不宣称全量交互验收。终端和网络画面只作示意。

官方 MCP 2.15.4 与应用 2.19.0 有版本警告，实际对象保存已核验；createFlow兼容问题通过已有流程起点属性完成。设计文件中的终端不是字体、IME或性能证据。

## 2. 可执行壳与公平比较边界

| 路线 | 固定候选 | 已执行 | 尚缺 |
| --- | --- | --- | --- |
| [Flutter壳](../validation/flutter/README.md) | Flutter版本及锁文件见构建manifest；terminal_view 0.5.0 | 云构建、模型/模拟IME WidgetTest、macOS原生有限smoke | 真人中文IME、触控、逐格字形、系统后台、真实网络 |
| [Tauri壳](../validation/tauri/README.md) | Tauri core2.12.5、API/CLI2.12.4、xterm.js6.0.0、Rust1.96.0 | gate/core测试、五目标云构建、macOS原生有限smoke | 真人中文IME、触控、逐格字形、系统后台、真实网络 |

共享[fixture、字体与哈希](../validation/shared/README.md)：80×24、JetBrainsMono Nerd Font Mono Regular，同一ANSI/Unicode/负载文件。两个macOS包使用相同Mac17,3/arm64/macOS26.6.2；窗体均对齐到2880×1800物理px（含标题栏），但终端所在布局和真实内容区尺寸还未完全校准，因此没有性能胜负。包源码SHA不同，结果必须绑定对应manifest。

- [Tauri原生smoke](evidence/device/2026-10-30-macos-tauri-smoke.md)：启动、辅助Ctrl+C=03、native Channel1MiB、未知输入锁/full后显式核实、UTF8草稿16B一次无CR、分屏焦点和草稿隔离、迟到帧拒绝。
- [Flutter原生smoke](evidence/device/2026-10-30-macos-flutter-smoke.md)：启动、工具单键x=78、辅助Ctrl-C=03、paced1MiB、本地unknown锁、草稿test一次无CR、标签恢复及目标草稿隔离。
- CUA键事件、paste、AX setValue与真人物理键盘／中文输入法不同。模拟IME WidgetTest也不能替代原生IME。两路线真实中文IME均未验证。
- terminal_view 0.5.0 在本机的 ASCII 组合重音渲染正确性失败：目视 e/A/n 没有重音，源码定位到 ASCII 批量绘制忽略 combined，而buffer保留组合内容；[真实painter诊断](evidence/flutter/combining-ed35d84/combining-render.json)已在[CI 40985723032](https://github.com/Luck9Star/herdr-pocket/actions/runs/40985723032)失败复现：buffer/getText保留全部组合码点、cursorX=5，而基字符与组合字符图片像素完全相同，两图均138个非透明像素，排除空白图假象。原生复制结果尚未取得有效证据，不宣称数据丢失。已反馈到Penpot P7待修状态；这是候选引擎渲染问题，不等于整个Flutter路线失败。Powerlevel10k、Oh My Posh真实主题均未运行，仅有PUA fixture。
- Tauri1952ms为一次native Channel负载时长；Flutter只记录解析提交而非绘制完成，二者不构成公平性能比较。

## 3. 云构建、安装与设备结果分开

| 路线 / 平台 | CI构建 | 可获取产物 | 安装／启动 | 设备正确性 |
| --- | --- | --- | --- | --- |
| Flutter iOS | be3a585成功 | unsigned device app；不是可直接安装的IPA | 未验证 | 未验证 |
| Flutter Android | c8d70abf / be3a585成功 | c8d70abf debug APK已下载验hash；新版未另做设备测试 | 未验证 | 未验证 |
| Flutter Windows | c8d70abf失败；be3a585修复后成功 | be3a585测试构建产物已确认存在 | 未验证 | 未验证 |
| Flutter macOS | c8d70abf / be3a585成功 | c8d70abf app.tar.gz已下载验hash；新版未另做设备测试 | c8d70abf本机直接启动通过；安装器未验 | 有限fixture smoke；其余未验 |
| Flutter Linux | be3a585成功 | be3a585测试构建产物已确认存在 | 未验证 | 未验证 |
| Tauri iOS | 第二run成功 | simulator构建；非真机签名包 | 未验证 | 未验证 |
| Tauri Android | a2ecd24第二run成功 | universal debug APK，14项清单全部验hash | 未验证 | 未验证 |
| Tauri Windows | 第二run成功 | 测试构建；最终清单核验待填 | 未验证 | 未验证 |
| Tauri macOS | 首/第二run成功 | 首轮app.zip已下载核验 | 首轮本机直接启动通过；安装器未验 | 有限fixture smoke；其余未验 |
| Tauri Linux | 第二run成功 | 测试构建；最终清单核验待填 | 未验证 | 未验证 |

可下载测试产物入口：

| 层 | 实际run / source | 证据与结果 |
| --- | --- | --- |
| Tauri GUI 首轮 | [40982357480](https://github.com/Luck9Star/herdr-pocket/actions/runs/40982357480) / c33cb573 | macOS包已验hash并运行；部分平台失败；首轮总清单遗漏隐藏文件问题已修，不能称首轮总清单全通过 |
| Tauri GUI 第二轮 | [40983116129](https://github.com/Luck9Star/herdr-pocket/actions/runs/40983116129) | 五目标构建成功；具体manifest和产物清单核验详见路线证据后续补录 |
| Flutter GUI / Mac实测来源 | [40983264890](https://github.com/Luck9Star/herdr-pocket/actions/runs/40983264890) / c8d70abf | lock/analyze/gate/模拟IME测试成功、macOS包已运行；Windows构建失败，后轮修复 |
| Flutter GUI / 五端构建 | [40984387029](https://github.com/Luck9Star/herdr-pocket/actions/runs/40984387029) / be3a585 | analyze、6项测试及五端构建全部成功，产物已确认存在；本轮不将c8d70abf设备结果套用新版 |
| 三网络原生探针 | [40983432877](https://github.com/Luck9Star/herdr-pocket/actions/runs/40983432877) /015153e | macOS tsnet/libzt编译加载、EasyTier check成功；Linux tsnet/libzt成功、EasyTier SO_NOSIGPIPE编译失败；Windows tsnet/libzt编译加载成功、EasyTier check失败；见[原始矩阵](../validation/native/evidence/2026-10-30-desktop-matrix.json) |
| helper fixture | [40985075937](https://github.com/Luck9Star/herdr-pocket/actions/runs/40985075937) /51e0771 | Ubuntu/macOS 15项fixture测试均成功；不是可用的真实授权helper |
| SSH/herdr 隔离集成 | [40985722900](https://github.com/Luck9Star/herdr-pocket/actions/runs/40985722900) /ed35d84 | Linux loopback OpenSSH +真实herdr 0.9.5七项通过；[下载验hash与分项证据](evidence/tauri/2026-10-30-ssh-results.json)。GUI接线、overlay与用户主机仍未验证 |
| Flutter 组合重音诊断 | [40985723032](https://github.com/Luck9Star/herdr-pocket/actions/runs/40985723032) /ed35d84 | 真实TerminalPainter测试按可见差异断言失败；确认当前terminal_view 0.5.0 ASCII组合重音绘制缺陷，非build失败 |

隔离SSH harness使用临时测试密钥、临时授权文件和独立herdr进程。已实测错误host key在认证前拒绝、固定key认证、direct-streamlocal快照、明确session的80×24 observe且不申请PTY、错误session拒绝、取消与重连。目标收到`A中文`+Up/Ctrl-C/Enter共12字节，两次原始输入RPC，重连获取新full后仍为12字节，未重放。这仅证明独立Linux harness，尚未把两GUI、三overlay或用户主机串成产品闭环。

测试构建不等于正式发布。Actions artifact保留期14天；过期后需从对应codex分支重跑，下载时用manifest与SHA256SUMS核查来源。iOS simulator包不可当作iPhone可安装包。未创建release、提交商店或合并主分支。

## 4. 原生库编译与加载

| 平台 / provider | 编译结果 | 加载结果 | 连接／字节流 |
| --- | --- | --- | --- |
| macOS / tsnet v1.104.1 | 015153e成功 | 成功 | 未验证 |
| macOS / patched EasyTier | cargo check成功，非最终链接包 | 未验证 | 未验证 |
| macOS / libzt | 015153e共享库构建成功 | 4符号加载成功 | 未验证 |
| Windows / tsnet、libzt | 015153e成功 | 成功（libzt仅4符号解析） | 未验证 |
| Windows / EasyTier | 015153e失败：UnixStream、socket常量、fd类型共7项编译错误 | 未验证 | 未验证 |
| Linux / tsnet、libzt | 015153e成功 | 成功 | 未验证 |
| Linux / EasyTier | 015153e失败：上游无条件引用SO_NOSIGPIPE | 未验证 | 未验证 |
| iOS / 三者 | 未验证 | 未验证 | 未验证 |
| Android / 三者 | 未验证 | 未验证 | 未验证 |

上表仅为相应commit的阶段证据，不代表用户态桥已可用于UI，也不将cargo check等同最终链接或入网。

## 5. 五端 × 三网络运行矩阵（15格）

每格需独立记录节点入网、正确主机定向、SSH字节流、取消/断开、恢复与身份隔离；当前所有格均未验证。

| 平台 | Tailscale | EasyTier | ZeroTier |
| --- | --- | --- | --- |
| iOS | 未验证 | 未验证 | 未验证 |
| Android | 未验证 | 未验证 | 未验证 |
| Windows | 未验证 | 未验证 | 未验证 |
| macOS | 未验证 | 未验证 | 未验证 |
| Linux | 未验证 | 未验证 | 未验证 |

## 6. 五端 × 四种并发组合（20格）

必须证明前台同时运行和隔离，不用切换代替并发；包含重叠地址/目标绑定、单网停用影响、迟到数据、不隐式PTY resize、不重放输入。

| 平台 | TS + ET | TS + ZT | ET + ZT | TS + ET + ZT |
| --- | --- | --- | --- | --- |
| iOS | 未验证 | 未验证 | 未验证 | 未验证 |
| Android | 未验证 | 未验证 | 未验证 | 未验证 |
| Windows | 未验证 | 未验证 | 未验证 | 未验证 |
| macOS | 未验证 | 未验证 | 未验证 | 未验证 |
| Linux | 未验证 | 未验证 | 未验证 | 未验证 |

## 7. 当前结论与实施顺序

两条路线均进入原生运行阶段，仍保留候选。当前先推进可执行的云端与本机 Mac 正确性验证；手机输入法、触控和软键盘等验收保留到有设备时，不阻塞这一阶段。只有各目标平台的正确性关口通过后，才在相同终端视口、字体、负载、设备与功耗条件下比较延迟、帧率、内存和维护成本。

1. 继续核验每个云端下载包与manifest；保留不同源码commit的构建和设备结果绑定。helper的15项fixture测试已在Ubuntu/macOS通过，尚无真实授权实现。
2. 根据已确证的组合重音painter失败，在云端修复／验证候选渲染路径；修复包可用后，在本机Mac以同fixture复测。补充Mac可执行的选择复制、快捷键、焦点与恢复证据。
3. 将已通过的独立SSH/herdr harness契约接入两GUI验证壳，并补网络桥与运行隔离；处理EasyTier的Linux/Windows编译阻断。单网络15格与并发20格在具备隔离运行条件后逐格验证。
4. 将已定位的约束反馈到Penpot P3/P4/P7及组件状态；关键页可局部细化，整体高保真与UI框架/终端/核心组合仍待正确性结果。
5. 后续取得设备与签名条件后，执行手机真实IME、软键盘、触控、后台以及Windows/Linux设备脚本，不以云构建或Mac结果替代。
6. 通过相应关口后，按配对／接入→看板→完整终端→多标签与恢复实现产品闭环。

用户确认当前可用验收环境为云端与本机Mac；手机、Windows/Linux真机及iOS签名条件目前不可用，无需再次询问。相关格保留未验证。继续可执行的云端/本机工作；本轮不读取真实凭据、不操作真实主机授权文件。

## 8. 已核验的 Android 下载入口

- [Tauri artifact](https://github.com/Luck9Star/herdr-pocket/actions/runs/40983116129/artifacts/12946301580)：内含 `app-universal-debug.apk`，123911176 bytes，SHA256 `249f939df5b169da4fc51b370c1a1e0a688f0ceb7c0de7fd456f9bb05b6df4fe`。
- [Flutter artifact](https://github.com/Luck9Star/herdr-pocket/actions/runs/40983264890/artifacts/12945822669)：解开artifact后再解 `flutter-android-debug.zip`（SHA256 `647f6613e1201ede2f3f4c3dadbea5338ad178f9840ebab09eecd0b2331f7c9c`），内含 `app-debug.apk`，152284772 bytes，SHA256 `f03eb792fc8a0fc406ada97d765d9a7b6fb5fe2fc53275958cd44cc0907e7955`。

需要仓库访问，artifact保留14天。将APK传入测试机，通过系统安装器安装；已有adb时可用 `adb install -r APK绝对路径`，无需本机装完整SDK。本轮已下载并核验文件，**未在Android设备安装或运行**。
