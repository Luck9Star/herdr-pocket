# macOS Tauri 原生包 smoke

测试日期：2026-10-30（工具内诊断时钟约 01:01–01:04；不作性能时间基准）。

- 来源：GitHub Actions [40982357480](https://github.com/Luck9Star/herdr-pocket/actions/runs/40982357480)，commit `c33cb573f56cc091082eeb46711e986a2344c2ae`。
- 包：`herdr-pocket-tauri-probe.app.zip`，SHA256 `6e77c666c9ec912b82207a7c64719b4371d7badf002f5a27f2b848e13deba897`。
- Mac17,3，arm64，macOS 26.6.2 (25G83)，直接运行 CI 解包 `.app`；没有安装 SDK、变更签名或绕过系统安全设置。
- 原生窗口截图为 2880×1800 px（含标题栏），未独立读取内容区 CSS logical viewport，不能作为精确同视口 A/B 基准。终端固定 80×24。
- Tauri core 2.12.5/API+CLI 2.12.4；xterm.js 6.0.0；原生 WebView `tauri://localhost`。UA 仅报告兼容性 macOS 10_15_7，实际 OS 以 sw_vers 为准。
- 字体 SHA256 `f01031f40e48dc29e1112e6b0b0450a2c6cd097f3f35cfff05c55cb311f8034c`；fixture SHA256 `ad2eca3667445764d501ecb6ab53079232850c913626f433b167d1cdb97d7ab3`。

## 已观察

| 操作 | 实际观察 | 边界 |
| --- | --- | --- |
| 启动 App | 原生窗口正常显示完整 fixture；默认观察，输入控制禁用 | 本机原生启动，不是安装器或签名验收 |
| CUA 逐个 pressKey a/b/c 后 Return | 一次捕获 `61 62 63`，共 3 字节 | 工具事件注入；不能宣称真人逐键或中文 IME 通过。前三键显示组合态，Return 后提交 |
| 点击辅助 Ctrl+C | 捕获 `03`，1 字节 | 辅助按钮；不代替物理键盘 Ctrl+C 验证 |
| 1 MiB 有界负载 | 原生二进制 Channel 完成 1048576 bytes，UI 显示 1952.0 ms；最终待消费 0/65536 | 单次功能 smoke，非统计性能结论，也非真实 SSH 流 |
| 注入发送结果未知 | 模式被切回观察并锁定，辅助键／聚焦／粘贴禁用，明确未回填草稿 | 本地 gate 模拟，不代表网络故障实测 |
| 新全量→核实 | full 后仍锁；明确点击已核实后解锁模式，仍默认观察；记录没有重放旧输入 | 恢复正确性只在本地 fixture |
| 注入迟到帧 | 诊断显示拒绝旧代／暂停／待全量／超限帧 | 这里只测试注入入口，不归因于每种拒绝原因 |
| 草稿粘贴 `fixture-A 中文` | 预览目标 A、16 bytes；确认后一次捕获 `66 69 78 74 75 72 65 2d 41 20 e4 b8 ad e6 96 87`，没有 CR/LF | CUA paste 注入；证明 UTF-8 文本、预览与一次提交，不证明 IME |
| 桌面分屏与切焦点 | 两个目标可见；A 草稿 `keep-A`，切 B 时为空并默认观察，切回 A 保留 keep-A；日志只有本地布局变化 | 未测所有快捷键或后台恢复时序 |
| fixture 字形 | ASCII、CJK、Nerd 图标、emoji、组合字符、ANSI 属性可见 | 仅目视 smoke，未逐格量测或判断列宽正确性 |

## 未验证

真实中文 IME 组合／候选／取消；物理键盘逐键与快捷键；终端选区复制；触控滚动／选择；手机软键盘；实际 TUI 程序；系统后台恢复；真实 SSH/herdr/host key/session；三网络。当前没有足够证据选定终端引擎或 UI 框架。

CUA 已展示原生窗口和 unknown 锁定状态截图，保存在本次工具会话的图像记录中；尚未导出为仓库图片，不虚构本地截图路径。Penpot 导出图片位于 `design/evidence/`，不能替代本页运行证据。

收尾：本次启动的测试 App 已通过 Cmd+Q 退出，随后按测试应用进程名与云产物目录精确检查，无运行进程；未关闭其他应用。
