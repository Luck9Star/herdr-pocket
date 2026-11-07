# Android 配对、看板与持续观察验收

2026-11-07。Flutter 与 Tauri 在同一提交 `1d604fa` 重建，八项云任务全部通过。四个 API 35 x86_64 模拟器场景分别从手机配对进入 SSH、主机看板和终端持续观察。下表供下载的两包为 arm64-v8a debug 构建，实际 arm64 手机尚未安装验收。[修订批 Actions](https://github.com/Luck9Star/herdr-pocket/actions/runs/42362291867) · [逐项数据与来源](evidence/mobile-pair-gui/paired-dashboard-cloud-20261107.json)

## 下载

| 路线 | 测试包 | 解压后 app.apk SHA-256 |
| --- | --- | --- |
| Flutter | [下载 arm64 debug 归档](https://github.com/Luck9Star/herdr-pocket/actions/runs/42362291867/artifacts/13570467817) | `97c8fcf23dd4476753e44e72287eab31ca95c475b63c63b604bdea21038c692b` |
| Tauri | [下载 arm64 debug 归档](https://github.com/Luck9Star/herdr-pocket/actions/runs/42362291867/artifacts/13570522730) | `0ca78544ac0064529260177ca0761cb174e8ad37a7ad00a284b07bfb89bdae4d` |

登录 GitHub 后下载并解压。保留 `report.json` 及 `SHA256SUMS`，可在 Mac 上对包运行 `shasum -a 256 app.apk`。两份归档于北京时间 2026-11-21 18:16（Flutter）和 18:19（Tauri）到期。两份 ZIP 和原生库归档已实际下载并核对 GitHub digest，包内 APK、ABI、源码提交、EasyTier 和 Tailscale 库哈希均已与同批构建清单交叉核验。

两份 APK 内的 JetBrainsMono Nerd Font Mono 解码后字节一致，SHA-256 为 `f01031f40e48dc29e1112e6b0b0450a2c6cd097f3f35cfff05c55cb311f8034c`。Flutter 以独立资源打包，Tauri 在 arm64 原生库中嵌入压缩资源；两边各核对了 34 份随字体分发的许可、声明和来源材料。不同手机上的字形显示仍待实测。

## 手机场景

| 场景 | 设备公钥匹配 sshd 认证 | 临时主机收到的输入 | 共享 PTY 119 × 40 | 证据 |
| --- | --- | --- | --- | --- |
| Flutter · 只读 | 通过 | 0 字节 | 6286 次，尺寸变化 0 次 | [场景记录](https://github.com/Luck9Star/herdr-pocket/actions/runs/42362291867/artifacts/13571026059) |
| Flutter · 受保护输入 | 通过 | 同一目标 1 + 9 字节 | 2481 次，尺寸变化 0 次 | [场景记录](https://github.com/Luck9Star/herdr-pocket/actions/runs/42362291867/artifacts/13570861525) |
| Tauri · 只读 | 通过 | 0 字节 | 829 次，尺寸变化 0 次 | [场景记录](https://github.com/Luck9Star/herdr-pocket/actions/runs/42362291867/artifacts/13570885959) |
| Tauri · 受保护输入 | 通过 | 同一目标 1 + 9 字节 | 1198 次，尺寸变化 0 次 | [场景记录](https://github.com/Luck9Star/herdr-pocket/actions/runs/42362291867/artifacts/13570373693) |

配对由一次性夹具主机确认，手机审查响应并使用应用自己的设备签名。两种 GUI 均显示 full 和 delta，停止观察后保留陈旧状态。Tauri 新配对表单在选定终端前和观察期间均报告看板 fresh。受保护输入场景分别执行草稿粘贴取消、追加和显式发送，独立接收端在取消与追加后均仅保留先前的 1 字节。主机侧确认测试公钥已撤销，临时进程及密钥已清理。

## 修复与复验

首轮 `d56ca78` 的 Tauri 模拟器两场景通过。Flutter 因粘贴预览和测试目标的类型问题在安装前失败；Tauri 的 arm64 打包前有两项 Node 22 Unicode 测试失败，两份 arm64 包均未产出。修复保留实际 Unicode provider 和字形／列宽断言，测试在加载 provider 时使用浏览器的字节解码路径。[首轮 CI](https://github.com/Luck9Star/herdr-pocket/actions/runs/42360984554) · [原始修复说明](39-mobile-paired-dashboard.md)

修订批 Flutter analyzer 通过，常规套件 340 项通过、1 项环境限定用例跳过，组合字符专项 10 项通过；被跳过的 Flutter GUI／SSH 用例已在独立 Linux 夹具上执行并通过。Tauri JavaScript 215 项通过，共享 Rust 传输 101 项库测试和 1 项命令行测试通过。[手机系统粘贴](38-mobile-system-paste.md) · [终端选区与复制](37-mobile-terminal-selection.md)

## 手机复测步骤

1. 在一次性测试主机和测试设备上建立主机资料，对照用户名、SSH 主机指纹和会话。手机创建设备专属公钥，主机 helper 核对设备指纹并确认授权。手机导入响应，再主动连接。
2. 从看板选择一个 pane，核对所属会话和终端身份。让测试程序产生新输出，确认持续出现更新。隐藏标签，再主动恢复，核对目标和新的完整画面；改变本地视口后核对远端共享 PTY 尺寸。
3. 选择草稿模式，输入 `Pocket`，在测试剪贴板放入“测”。先取消一次，再追加一次，在显式发送前核对远端没有收到草稿。发送时核对目标和 9 个 UTF-8 字节。断线或发送结果未知时保留草稿、重新核验，不重放。
4. 停止观察，退出测试应用，撤销这次测试配对。下阶段优先在同一部 arm64 手机上比较两套 GUI 的中文 IME、键盘伸缩、触控选区、相机扫码及恢复，再补真实三网并发与 iOS 设备数据。据此收敛 Penpot 和框架选型。
