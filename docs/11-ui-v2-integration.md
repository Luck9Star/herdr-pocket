# 新版视觉与验证壳集成

2026-10-30。用户认可 Penpot 第二页面的靛蓝／Slate 配色，本轮将其作为视觉基准，继续 Flutter 与 Tauri 并行验证。视觉方向的确认不改变框架选型状态；终端正确性、手机 IME 与真实网络链路继续按实测判断。

## 来源与改动边界

- [Penpot 新版编辑页](https://design.penpot.app/?screen=workspace&team-id=c514c1fb-1cda-8125-8008-a57c5bd4a25d&project-id=9a0c44dc-8874-81e7-8008-ddd20c193c16&file-id=b55064db-d93d-80f9-8008-ddd22e6d398f&page-id=7a22df08-251d-8016-8008-de03541c11da)。原核心流程页保留，具体对象及交互核验见[设计记录](../design/README.md)。
- 本轮起点为 `d92b5c021b067f623d09488933b1602e7ffdef65`，分支 `codex/core-prototype-validation`。开始时已有 `design/README.md` 的新版说明及未跟踪的 `design/penpot/build-v2.js`，保留并审阅；该脚本只有建稿辅助函数，不能当作完整页面重建入口。
- 品牌／操作主色 `#4F46E5`、状态绿色 `#10B981`、终端底色 `#0B0F17`。小字号状态文字需要独立深色文字 token，不能直接把亮绿色用在浅色底上并宣布可访问性通过。
- 两条壳继续使用相同固定字体文件、fixture、80×24 终端和输入预算。新版界面中的主机／网络名称仍是示例数据，不表示已连接对应 provider；诊断入口明确标为本地 fixture。
- Flutter 绘制修复通过单独的受控候选流水线应用；官方 `terminal_view 0.5.0` 与旧基线结果不改写。修复来源与范围见[阻断修复记录](10-blocker-repair.md)。

## 本轮验收范围

验证视觉 token 的两端消费、默认观察、显式模式切换、单一输入焦点、草稿预览不附加回车、未知结果锁定、恢复全量后仍需人工核实、窄窗口与隐藏标签的状态提示。每项分别记录自动化检查、构建和 Mac 原生观察，未执行项不记通过。

终端字体仍以测试资源为准，不把 Penpot 中的 JetBrains Mono 排版当作已验证的 Nerd Font/CJK/emoji 渲染。浏览器前端运行不替代 Tauri 原生 WebView，headless Flutter 测试不替代真实手机输入法。

## 已保存与已执行的结果

Penpot 新版从接手时 7 个画板／18 条交互扩展为 **16 个画板、91 条原生点击交互、53 个 v2 tokens、4 个新增库组件**。独立 MCP 读回确认没有悬空目的地或孤立临时对象；旧 V1 的 57 画板／205 交互保留。新增页面覆盖未知发送、人工恢复、指纹变化、窄窗口、独立连接验证、helper 确认与撤销指引、草稿预览、隐藏标签恢复及组件规格。

实际预览点击了 6 条关键边，包括配对审查至指纹拒绝，以及未知状态至新画面再明确核实；其他边通过对象／目的地检查，不称逐条手动通过。原 S07 提前按手机／桌面拆分技术栈与本地 PTY 的描述已改为两条五端远端候选。[设计覆盖清单](../design/v2-coverage.md)与[独立核验](evidence/ui-v2/independent-review.json)保留范围。

Tauri `45b96d6` 已在本机通过 18 个 JavaScript 测试、6 个 Rust core 测试和 Vite 构建。独立浏览器预览验证 Ctrl+C 为 `03`、草稿 `echo 中文` 为 11 bytes 且无回车、未知状态取得 full 后仍锁定，以及 A/B 草稿隔离。390／360／720／1440 四个视口无整页水平溢出；窄窗单目标、宽窗双目标。源码 `224d143` 另隐藏窄窗的桌面分屏按钮，保留旧截图并标注差异。[完整本地记录](evidence/tauri/2026-10-30-ui-v2.md)。

Flutter 加入相同 token 消费、状态面板、桌面侧栏及小屏工作区滚动；窄窗下隐藏分屏标签会失效旧画面。新增 4 项实际 Widget 测试，检查未知恢复、隐藏标签、缩小窗口、键盘占用和文字放大；5 项候选材料化／锁定 Python 检查已通过。本机没有 Flutter SDK，本轮不安装；Widget、分析与构建以云端结果为准。

## 云构建记录与获取方式

本轮继续使用仓库现有测试工作流。源提交 `45b96d6`、`68db4a0`、`224d143` 分别记录视觉接线、小屏滚动和窄窗入口修正；`7daa8a2` 将 Widget 字体／asset 的真实 I/O 移出假时钟。先前被更新版本取消的 run 单独标为 cancelled，不作为通过或失败。

推送过程遇到 SSH 22 超时和 HTTPS HTTP/2 错误。HTTPS 重试还被现有 OAuth 的 workflow scope 限制拒绝；最终使用既有 SSH 身份经官方 443 端点推送成功，保留严格 host key 校验，未改全局配置、远端地址或凭据权限。官方方法见[GitHub SSH 443 文档](https://docs.github.com/en/authentication/troubleshooting-ssh/using-ssh-over-the-https-port)。测试包来源、结果和下载入口须按实际最终 run 的 manifest 与校验和核对，不能用前阶段包替代新版。

| 候选 | 实际 CI | 结果与产物 |
| --- | --- | --- |
| Tauri / `224d143` | [41014249412](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014249412) | Linux、Windows、macOS、Android、iOS simulator 五项构建成功；每项实际执行 18 JS + 6 Rust 测试。[五平台下载台账](evidence/tauri/v2-20261030-ci/README.md) |
| Flutter patched / `7daa8a2` | [41014495508](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014495508) | 7/7 jobs 成功：Ubuntu 10 项常规／Widget＋10 项绘制检查，macOS headless 14 项；五端候选包均生成。[下载台账与 baseline 对照](evidence/flutter/2026-10-30-ui-v2.md) |

Tauri Mac 新包已完成实际原生复验：默认观察、`03` 辅助键、11-byte 中文草稿、未知 → full 仍锁定 → 明确核实、分屏焦点与原生 1 MiB 通道均符合本轮预期。[设备记录与截图](evidence/ui-v2/macos/tauri-native.md)。随后退出 App 并确认进程结束。此处不推导真实中文输入法、手机触控或 overlay 通过。

Flutter Mac 候选也已完成原生复验：`03` 辅助键、未知恢复锁定与人工核实、ASCII 草稿预览及无额外 CR、分屏 B 独立计数与观察恢复。自动化中文粘贴未生效，已如实记录；真实 IME 与辅助技术仍未验证。[设备记录与截图](evidence/ui-v2/macos/flutter-native.md)。两款测试 App 均已退出，临时预览／MCP 服务已停止。相同源码的官方 Flutter baseline 只有原组合绘制诊断失败，其余 gate 与五端构建成功；因此仍采用明确标识的 patched candidate 进行后续试验，不宣布上游已修复。

## Mac 测试步骤

1. 从上表对应 run 下载 Mac artifact，按下载台账核对源码、manifest 与 SHA256，解包 `.app`。Flutter 选择 `flutter-candidate-*`，不要把已知绘制缺陷的 baseline 当成修复包。按正常系统安全策略打开，不要求绕过保护。
2. 初始应为观察模式；明确选逐键，再点 Ctrl+C，验证工具应只记录一次 `03`。
3. 注入未知／断线，取得新 full 后仍应锁定，旧输入不重放。人工核实后先回观察。
4. 草稿输入普通测试文字，预览目标后确认，检查 UTF-8 字节和无额外末尾 CR。切换 A/B、分屏及窄窗，确认只有明确选中的目标可输入；不要填入凭据或真实主机资料。
5. 退出测试应用。当前各包仍是离线壳；Android 包可下载但未进行手机验收，Flutter iOS unsigned 和 Tauri iOS simulator 不构成 iPhone 安装证据。

## 下一阶段顺序

1. 在这套视觉基准下继续将 V1 三网配置与导入冲突迁到 v2，补足组件状态及图标按钮的无障碍名称；保留已经验证的配对／未知／指纹分支与可靠性契约。
2. 将已经独立通过隔离 SSH/herdr 测试的传输接入 GUI 连接状态，先在自建临时测试目标验证 host key、session/pane 绑定、取消、未知写入和重连；不使用维护者真实授权文件。
3. 消费 EasyTier 新 opaque-handle ABI，验证专用工作线程、读写背压、取消和资源释放；再执行真实 overlay 入网。Linux 旧 fd 调用方仍需安全写入策略，Windows 不回退成 Unix fd。
4. 按平台逐项补三网络与并发矩阵。当前只能进行云端和 Mac 验证；Android 触控/中文 IME、iOS 签名安装及其他桌面设备运行继续标未验证。
5. 完成正确性证据后，再比较性能和维护成本，更新框架 ADR 与高保真实现规格，进入“配对／接入 → 看板 → 完整终端 → 多标签与恢复”的真实闭环。
