# Flutter M1a 云构建与下载核验（2026-10-30）

源提交 `d15da12a4fc7d60313b3c253a315c001e7290b5e`。候选 [run 41048094396](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094396) 全部通过：20 项常规测试、Linux 10 项绘制测试、macOS 14 项绘制／UI 测试，以及 Android、iOS、macOS、Linux、Windows 五端编译。完整 job 和 artifact 来源见 [results.json](results.json)。

普通 baseline [run 41048094630](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094630) 的常规检查与五端构建通过，但官方 `terminal_view 0.5.0` 组合重音诊断仍失败：buffer 保留字符，画面与无重音文本相同。候选的修复受独立归档／补丁 hash 和 path override 控制，不将官方版本标为已修复。两组原始 headless JSON 和 PNG 分目录保存；日志以 gzip 保留原字节。[前两次失败](failed-attempts.json) 仍保留，不能被最终通过覆盖。

已下载 [Android 候选包](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094396/artifacts/12974335322) 和 [macOS 候选包](https://github.com/Luck9Star/herdr-pocket/actions/runs/41048094396/artifacts/12973502337)，校验 GitHub ZIP digest、包内 SHA256SUMS、源提交、固定字体、fixture、tokens、remote contract 与补丁 hash。[下载核验](download-verification.json) 包含精确 SHA 和本机临时路径。`android/` 与 `macos/` 仅保存原包 manifest 与原 SHA 清单，实际二进制在下载链接／临时目录，不提交到仓库。其余三端只记录 CI 构建与 artifact 元数据，没有本地下载或设备运行证据。Actions 产物按工作流保存 14 天。

同一 Dart adapter 的真实 SSH 6 项只读检查见 [41048094519](../41048094519/probe/manifest.json)，仅云端临时 loopback 主机；手机、真实 IME、连续观察、组网、远端输入均未验证。新包原生 Mac 的入口／无效资料恢复 smoke 与应用关闭见 [独立记录](../macos/flutter-verification.json)，没有用真实凭据或完成 GUI SSH 接入。iOS 包未签名，不能直接安装真机；没有框架定案或正式发布。
