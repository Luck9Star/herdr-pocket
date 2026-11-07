# Android 手机配对、看板与持续观察验收

截至北京时间 2026-11-08，Flutter 和 Tauri 均已在独立的 Android API 35 x86_64 模拟器中，从公开主机资料开始，完成设备密钥配对、固定主机公钥的 SSH 认证，从看板选择终端，收到完整帧和增量，并主动停止。两份 arm64 测试包来自同一提交。八项实际运行的云任务中五项成功，三项失败，另有两项正式候选流程按分支条件跳过。[构建与逐项状态](https://github.com/Luck9Star/herdr-pocket/actions/runs/42386109360) · [机器可读验证记录](evidence/mobile-pair-gui/android-handoff-batch-20261108.json)

## 下载与安装

两份 debug APK 对应源码 `7470d5cc2a9c4b4c5fce0802b6bc7789a8b1e67f`。登录 GitHub 下载归档，在不同目录解压，再用 `shasum -a 256 app.apk` 对照下表。Flutter 归档于北京时间 11 月 21 日 23:55 到期，Tauri 为 23:57。已有兼容测试机时可用 `adb install -r app.apk` 安装；本批 arm64 真机安装状态为**未验证**。[固定源码](https://github.com/Luck9Star/herdr-pocket/commit/7470d5cc2a9c4b4c5fce0802b6bc7789a8b1e67f)

| 路线 | 安装归档 | app.apk SHA-256 |
| --- | --- | --- |
| Flutter | [下载 arm64-v8a debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42386109360/artifacts/13580043770) | `420ff2077356116b3556e0bb47d104e1ddfec966660d06bd5df8f221b5ef9745` |
| Tauri | [下载 arm64-v8a debug](https://github.com/Luck9Star/herdr-pocket/actions/runs/42386109360/artifacts/13580602396) | `1242e94e0c6cb85995016bb4d11eb58faa88172b9196156512a24ad657e3f20d` |

已实际下载两个归档，对照 GitHub 的 ZIP digest、APK 内层哈希、构建源码、单一 ABI 及 JNI 依赖。两个包内的 EasyTier 和 Tailscale 库与同批原生构建逐字节匹配。共享 Nerd Font 和字体诊断样例在 Flutter 资产目录直接复核，在 Tauri 原生库中使用与构建一致的 Brotli 编码核对。真实节点路由与物理手机上的字体回退仍待实测。[同批原生库](https://github.com/Luck9Star/herdr-pocket/actions/runs/42386109360/artifacts/13579887420)

## 四场设备结果

四场均由一次性测试主机独立确认请求，sshd 记录的公钥均与手机生成的公钥一致。四场共享 PTY 的采样结果均为 119 × 40，主机 helper 均已撤销其测试公钥，四台临时模拟器最后都已停止。Flutter 带输入场景的应用内清理另行记录如下。

| API 35 x86_64 | 资料、看板与终端 | 输入、恢复与撤销 |
| --- | --- | --- |
| [Flutter · 原版 herdr](https://github.com/Luck9Star/herdr-pocket/actions/runs/42386109360/artifacts/13581085117) | 首配资料字段及指纹匹配，核验前创建次数为 0。重新打开原请求、复查原设备密钥、认证、选定 pane、全帧序号 1 与增量序号 3、停止均通过。 | 远端收到 0 字节。观察时系统键盘隐藏，八行样例标记均在第 15 列。共享 PTY 采样 4,303 次，应用清理通过。 |
| [Tauri · 原版 herdr](https://github.com/Luck9Star/herdr-pocket/actions/runs/42386109360/artifacts/13579454256) | 首配资料和授权分别审查，Android 原生端报告公开请求复制完成。SSH、看板、1 次全帧确认、2 次增量确认、停止均通过。 | 远端收到 0 字节。手机独立接受新鲜撤销回执，目录确认持久化，连接禁用。共享 PTY 采样 816 次。 |
| [Flutter · 受保护输入](https://github.com/Luck9Star/herdr-pocket/actions/runs/42386109360/artifacts/13581040476) | SSH 公钥匹配，远端收到 1 字节。缺少完整设备结果，无法确认最后完成的输入阶段、IME 或输入回执。 | 清理报告未确认移除应用、应用进程及反向端口；驱动记录 `flutter_android_cleanup_failed`，设备失败报告为空。外层记录确认独占模拟器随后停止。共享 PTY 采样 1,777 次。 |
| [Tauri · 受保护输入](https://github.com/Luck9Star/herdr-pocket/actions/runs/42386109360/artifacts/13579614084) | 资料审查、原生复制报告、设备公钥认证、看板、全帧和增量、停止观察均通过。 | 直接输入及草稿共收到 2 笔回执、10 字节。7 个系统输入法窗口检查、粘贴与草稿恢复通过。最后在手机接受撤销回执时无法点按确认按钮，目录撤销未确认。共享 PTY 采样 1,894 次。 |

这些模拟器场景用测试资料经过生产 GUI 入口，使用实际设备密钥桥和隔离 SSH。摄像头扫码、物理键盘及真实中文输入法组合未在此批验收。两个 Flutter widget 测试各等待 10 分钟超时，375 项通过、1 项跳过。静态分析报告三处测试文件重复导入，组合重音绘制专项 10 项全部通过。[Flutter 源测试原始日志](https://github.com/Luck9Star/herdr-pocket/actions/runs/42386109360/artifacts/13580840572)

## APK 之后的修订

- 修复 Tauri 显式删除设备密钥失败时可能丢失持久引用的问题。先保存原句柄、禁用状态及用户选择，再调用系统删除。重新打开后须再次明确确认，重试只执行原来的「仅清身份」或「移除主机」。Rust 库 59 项、前端 382 项通过。Apple 部分只运行内存替身和状态码测试。[设备密钥清理修订](https://github.com/Luck9Star/herdr-pocket/commit/82b499b562f8203b24640e392f926b58a285e560)
- Flutter widget 测试现在在真实时钟预载字体和样例。已用固定 fake_async 复现先前的跨测试缓存等待，修订后的 Dart 模型通过 200 次挂载。下批仍须用 Flutter 引擎复跑。三处重复导入已移除。持续集成会记录卡住的测试并为独立模拟器留出运行时间。[测试修订](https://github.com/Luck9Star/herdr-pocket/commit/2789f9d89b86268f3c9c8094a2e2bb2ef9ebd1ae)
- Tauri 驱动增加了撤销回执有效窗口和控件状态的诊断。已复现设备时钟落后 1 秒时确认按钮持续不可用，但本批证据不足以判定这就是该场失败的原因。Flutter 驱动分别保留首发错误和清理结果。共享驱动 52 项、Flutter Android 驱动 68 项通过，修改后的两场设备验收仍待复跑。[测试修订](https://github.com/Luck9Star/herdr-pocket/commit/2789f9d89b86268f3c9c8094a2e2bb2ef9ebd1ae)

## 复测顺序

1. 在专用测试账号生成公开资料，用两款 App 分别扫码或粘贴。独立核对 SSH 主机指纹、账号、设备指纹及请求编号，主机确认后在手机审查回执。过期、取消或结果未知时按原编号核查。[逐步操作与 helper 命令](45-mobile-pairing-handoff.md)
2. 手机主动连接并选择目标 pane，在主机输出可区分的两次变化，核对首帧、后续更新、停止后的陈旧提示和远端零输入。切换窗口和软键盘时采样远端 PTY 尺寸。
3. 下批同源复测优先拿到 Flutter 受保护输入的首发错误，确认 Tauri 带输入后仍可在手机完成撤销，再测试进程重启后的设备密钥清理。arm64 真机、iOS、中文 IME、三网真实节点及跨组网并发保留为独立验收项。框架选型继续等待可比的正确性结果。
