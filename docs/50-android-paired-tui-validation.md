# 手机配对、观察与远端 TUI 的 Android 验收

2026-11-08。Flutter 和 Tauri 的手机 GUI 已接入首次主机资料审查、设备密钥、授权回执、看板和持续观察。两条路线在上一批均用 Android API 35 模拟器完成过原版 herdr 的只读闭环。本批 Tauri 进一步在同一配对目标上完成远端 curses 的十个按键和撤销。Flutter 在模拟器启动前遇到依赖检查失败。[上批闭环](46-android-pairing-handoff-validation.md) · [本批逐项数据](evidence/mobile-pair-gui/android-paired-tui-batch-20261108.json)

## 下载与核验

两个 arm64-v8a debug APK 来自同一公开提交 `2b497ea`。登录 GitHub，分别下载并解压，用 `shasum -a 256 app.apk` 核对。Flutter 和 Tauri 归档分别于**北京时间 11 月 22 日 02:58、03:00** 到期。arm64 手机实际安装未验证。[构建源码](https://github.com/Luck9Star/herdr-pocket/commit/2b497ea261c33dbf5fafeac2287bad1220ca5166) · [构建记录](https://github.com/Luck9Star/herdr-pocket/actions/runs/42402903055)

| 路线 | 安装包 | APK 的 SHA-256 |
| --- | --- | --- |
| Flutter | [下载 Flutter](https://github.com/Luck9Star/herdr-pocket/actions/runs/42402903055/artifacts/13586616994) | `b9292bed0de3762262ad350abe5dab723ad2375602635c0c5576f0baedaa44b2` |
| Tauri | [下载 Tauri](https://github.com/Luck9Star/herdr-pocket/actions/runs/42402903055/artifacts/13586094449) | `2d0543d00dfdcbc7a4629eca3bf32d64727e9fcd3330e5cd2237f6d929d0f0ca` |

两个下载归档的大小和 ZIP 摘要与 GitHub 一致。已校验内部 APK、单一 ABI、原生清单及两包相同的 EasyTier、Tailscale 库。两条路线使用相同的 Nerd Font 和字体诊断样例。Flutter 可从 APK 直接提取这两项，Tauri 的宿主 ELF 各包含一次构建时 Brotli 编码后的同一份资产。[原生构建](https://github.com/Luck9Star/herdr-pocket/actions/runs/42402903055/artifacts/13585963954)

## API 35 x86_64 模拟器

| 场景 | 配对 → 看板 → 持续观察 | 输入、撤销与清理 |
| --- | --- | --- |
| [Tauri · 原版 herdr](https://github.com/Luck9Star/herdr-pocket/actions/runs/42402903055/artifacts/13585878798) | 手机先审查资料、发出本机设备公钥请求。隔离主机确认，sshd 认证的公钥匹配。看板打开目标 pane，确认 1 个全帧、2 个增量，主动停止后显示已停止状态。宽画布标记和阅读位置恢复通过。 | 主机收到 0 字节。手机接受撤销回执，helper 撤销临时授权。共享 PTY 采样 1,163 次均为 119×40。 |
| [Tauri · 受保护输入](https://github.com/Luck9Star/herdr-pocket/actions/runs/42402903055/artifacts/13586098075) | 同一配对身份完成 SSH 认证、选定 pane、渲染全帧和增量。首两笔输入和后续十个 TUI 按键均绑定同一 pane 与 terminal，共 12 个不同请求 ID。 | 逐键与草稿分别受理 1、9 字节。十个 TUI 操作的程序状态、逐笔回执、退出后的终端属性均符合预期。退出后的短时尾随读取为零。手机撤销、应用关闭和临时模拟器清理通过。共享 PTY 采样 1,899 次均为 119×40。 |
| [Flutter · 原版及受保护输入](https://github.com/Luck9Star/herdr-pocket/actions/runs/42402903055/job/128495368572) | 两场均未运行。设备测试准备将生成项目的 `pubspec.yaml` 与原始清单逐字比较，拒绝了构建流程自身生成的、指向固定来源的依赖路径。 | 两份诊断归档只有候选清单和依赖锁。该源码 SHA 没有 Flutter AVD 的 SSH、输入、撤销或清理结果。 |

Tauri 的十个按键依次为下移、Tab、Backspace、Shift+Tab、Insert、Delete、F1、F1、F5、F10。主机确认选中项、详情焦点、编辑、插入与删除、帮助页面、刷新次数及正常退出。普通 herdr 保持只读。Tauri 的两场字体记录均有八行，但本次诊断区域无法测量列宽。七个系统键盘窗口检查通过的范围是展开、隐藏与焦点；真实中文 IME 仍待验证。[按键与主机验收约定](49-mobile-paired-tui.md)

## 本批三个失败及修复

源码构建共运行八项任务，五项成功、三项失败；另有两项发布候选任务按条件跳过。隔离宿主候选已编译，四次只改变输入模式的更新都抵达 CLI 观察者，132 个 PTY 采样没有尺寸变化。该证据与 Tauri 的设备密钥 SSH 场景分别取得。[宿主产物](https://github.com/Luck9Star/herdr-pocket/actions/runs/42402903055/artifacts/13586650814)

- Rust 传输库 106 项通过、1 项超时。测试等待看板刷新时可能丢弃先到的“可选择终端”事件。Mac 上按协议允许的顺序复现超时，修订后的等待器保留未匹配事件，同 feature 的 108 项库测试及 1 项二进制测试通过。原始云日志无法还原当次线程调度。[云测试](https://github.com/Luck9Star/herdr-pocket/actions/runs/42402903055/job/128494333913)
- Flutter 静态分析通过，组合重音绘制专项 10 项通过。widget 等测试 399 项通过、1 项跳过、1 项失败。共享样例中两行都正确标为三列，原测试只允许整页出现一次。修订后逐行核对八个样例，Mac 终端核心探针八行的标记均在第 15 列。[Flutter 云测试](https://github.com/Luck9Star/herdr-pocket/actions/runs/42402903055/job/128495368395)
- Flutter 设备测试准备与实际生成项目共用同一份依赖转换，并检查候选路径、覆盖及锁定内容。Mac 隔离测试复现原错误并通过修订后的准备流程，Android 驱动 78 项通过。修订没有改动 App 的生产依赖。[修复提交](https://github.com/Luck9Star/herdr-pocket/commit/b16478ec59ee5dce601017ea725f50baf6140fd6) · [Flutter 定向云复测](https://github.com/Luck9Star/herdr-pocket/actions/runs/42404613387)

## 在测试环境复测

1. 使用隔离测试账号和临时 herdr 会话。手机扫码或粘贴公开资料，独立核对主机指纹、账号、会话及设备指纹，主机确认原请求，再由手机审查回执并主动连接。[配对、核查和撤销步骤](45-mobile-pairing-handoff.md)
2. 从看板选择目标 pane，让主机产生两次可区分的输出，确认首帧、增量和停止。普通 herdr 应收到零输入。窗口、键盘或标签变化后，采样共享 PTY 尺寸。
3. 有受保护输入候选时，在同一 pane 运行隔离 TUI，用十个按键并逐笔核对受理及画面。结果未知时核查原操作。停止观察后由主机显式撤销，再在手机审查原设备的撤销回执并关闭测试应用。

手机仍优先验收真实 IME、触控、字体列宽和锁屏恢复。iOS、三个实际组网节点与跨网络并发仍为未验证。Flutter 与 Tauri 继续保留，框架选择等待可比的设备正确性和性能结果。
