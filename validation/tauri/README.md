# Tauri + xterm.js 验证壳

状态：2026-10-30，最小**离线终端/原生 IPC 验证壳**。使用真实 xterm.js 6.0.0 组件和 Tauri 2.12.5 Rust 后端，输入只到本地字节记录；没有读取 SSH 凭据或连接真实主机。纯 Rust `SessionGuard` 测试不是 SSH 握手、herdr 或 overlay 验收。

## Penpot v2 视觉接入

2026-10-30 将用户认可的 Tech Indigo / Slate 配色接入本壳：主操作、选中标签和活动焦点用靛蓝，终端背景使用 `#0B0F17`。从 `../shared/design-tokens-v2.json` 读取语义颜色、组件圆角与固定 16 色 ANSI 工程基线；与 Flutter 使用同一字节 fixture、字体、80×24 网格和选择高亮透明度。ANSI 16 色是共享比较约定，不宣称是 Penpot 导出值。

桌面侧栏与双分屏、窄屏单目标、三模式切换、草稿预览和未知结果恢复已有可操作布局。`view-state.js` 只控制可见状态和禁用原因，实际输入仍经 `ViewGate` 核验。获取新全量画面不会解开未知结果锁定；核实后仍需显式选择输入模式。验证工具默认折叠，页面始终标注离线边界。配对和真实网络仍未接线。

[本轮浏览器验收](../../docs/evidence/tauri/2026-10-30-ui-v2.md)覆盖共享四视口和核心安全交互；这些截图来自 Mac 上的 Chromium 浏览器预览，不是 Android、iOS、Tauri 系统 WebView 或手机触控证据。

后续独立审阅发现 `45b96d6` 的窄屏截图仍展示已开启的“桌面分屏”按钮，虽然实际只有单目标。已在 `<900px` 的现有窄屏 CSS 中隐藏此入口；保留分屏选择，回到宽窗可恢复双视图，不改输入 gate。原浏览器截图、记录与 SHA 保留为修复前证据，不能据此声称这处后续修复已有原生运行验收。

## 本地轻量检查

在本目录，使用 Node 22.22.2（或已安装且满足 `engines` 的兼容 Node）与已有 Rust 1.96.0：

```sh
npm ci
npm test
npm run build
cargo test --locked --manifest-path core/Cargo.toml
npm run dev
```

浏览器访问 `http://127.0.0.1:1420`。浏览器预览不代表 Tauri 系统 WebView，更不代表手机真机。无需为这些检查安装 Flutter、Android SDK、Xcode 或 Visual Studio。原生 App 构建交 GitHub Actions；只有已具备完整目标工具链时才本地运行 `npm run tauri -- icon icon.svg` 和 `npm run tauri -- build`。

## 当前可执行

- 同一字体、80×24 fixture、ANSI 与备用屏幕；观察、逐键、目标独立草稿、辅助键、粘贴预览、选区复制入口。
- 手机标签、桌面双视图、明确单输入焦点。窄于 900 logical px 退为单可见目标；字体/网格保持固定，横向滚动查看。未实现自动拟合字号，布局和软键盘从不发远端 resize。
- 旧 generation/epoch、迟到 IME 目标、隐藏恢复、结果未知与 UTF-8 输入上限在 gate 中检查；隐藏/回前台后需主动取得 full，并回到观察。原生键盘/IME 是否在每个系统按预期发事件仍需真机。
- 1 MiB 负载在浏览器走同一字节 fixture，在原生壳通过 Rust `Channel<Response>` 发送原始二进制，xterm write 消费回调后才 ack。每流 65,536 bytes、总计最多两个流；取消旧 lease。
- Rust 不提供文件、shell、凭据、任意远端网络或 PTY resize 命令，前端不加载远端页面/字体。此限制适用于验证壳，不是完整产品已实现的声明。

输入记录限最近 100 条，仅供测试；不要在验证壳中粘贴真实秘密。记录“本地捕获”不代表服务端接收。草稿为内存状态，退出不保存；真实安全存储、加密配置迁移与配对 helper 尚未接入。

## 云端测试包

[工作流](../../.github/workflows/tauri-validation.yml) 仅在 `codex/**` 分支相关改动或手动触发运行，不创建 Release、不合并、不调用商店。固定 JS 依赖 `package-lock.json`、Rust `Cargo.lock`、Rust 1.96.0、Node 22.22.2；外部 actions 固定提交 SHA。runner 镜像随 GitHub 更新，实际镜像/工具链写入 manifest。

| 构建目标 | 预期 artifact | 边界 |
| --- | --- | --- |
| Android arm64 | 临时 debug 签名 APK | 可用于侧载测试；不能保证跨 run 原地升级，未安装即未验证 |
| iOS arm64 simulator | unsigned simulator `.app`/archive | 仅模拟器构建；没有真机签名/账户，不能当作手机安装包 |
| macOS runner 架构 | 未签名 `.app.zip` | Gatekeeper/签名/公证和实际运行未验 |
| Windows x64 | 未签名 NSIS 安装器 | 需 WebView2；签名信誉/目标系统运行未验 |
| Ubuntu 24.04 x64 | `.deb` | 需相应 WebKitGTK 运行依赖；不外推其他发行版 |

每个 artifact 同带 `build-manifest.json`、`SHA256SUMS`、共享fixture/字体许可及锁文件；v2 manifest 另记录 `designTokensSHA256` 和视觉基线名称。工作流失败仍上传诊断材料；**必须看 manifest 的 buildOutcome 和真实安装文件，不能把存在 artifact 当构建成功**。保留 14 天，下载需要 GitHub 仓库读取权限。

## 验收与已知缺口

使用[共享步骤](../shared/README.md)和[结果模板](../shared/result-template.json)，同一设备先正确性、再性能。当前合成备用屏幕不替代 vim/htop/herdr TUI；终端组件的 SGR/列宽正确性、中文 IME/触控复制、后台生命周期、真实 SSH/herdr、三网及并发均保持未验证。

终端 full 恢复会销毁并重建 xterm 实例，以隔离旧异步写入；此壳不保存完整滚动历史或隐藏期间历史。移动系统可能缺少 `navigator.clipboard` 权限，预览框支持系统粘贴；这不是已完成的五端剪贴板适配。native Channel 延迟/吞吐和整 App 内存必须在原生包中测，不使用浏览器数字判胜负。

来源与本地执行证据：[2026-10-30 核查](../../docs/evidence/tauri/2026-10-30-sources.md)。
