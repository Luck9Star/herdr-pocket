# Tauri v2：Mac 原生包复验

2026-10-30，Mac17,3 / arm64 / macOS 26.6.2 (25G83)。GitHub Actions [41014249412](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014249412)，源码 `224d143f1a545fc64257f6cc46a2ba177c675237`，下载 [Mac artifact 12958494516](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014249412/artifacts/12958494516)。父代理独立重算 App ZIP SHA256：`ab123527b9f57ca89e9a07aba549af0fc1d40499fc1f7b9f7946108f28625c67`。包的 15 份文件及 fixture/font/tokens 核验见[包记录](../../tauri/v2-20261030-ci/macos-package-verification.json)。

通过 CUA 从已解包路径启动实际 `.app`，界面 URL 为 `tauri://localhost`，不是浏览器预览。窗口截图 2880×1800 px（含标题栏）；没有将其当作精确内容区视口或性能对照。没有安装 SDK、修改签名或系统安全配置。

| 已执行操作 | 实际结果 |
| --- | --- |
| 初次打开 | 靛蓝／浅色应用壳与深色终端；默认观察，辅助输入禁用 |
| 显式逐键 → 辅助 Ctrl+C | 本地捕获一次 `03` |
| 注入未知 → 新全量 | 三模式与辅助键仍禁用；只有人工核实入口可用，没有新增输入记录 |
| 人工核实 | 回到观察，仍需明确选择输入模式 |
| 草稿粘贴 `echo 中文` → 预览 → 确认 | 目标 A / session-fixture / pane-a；一次 11 bytes `65 63 68 6f 20 e4 b8 ad e6 96 87`，无追加回车 |
| 原生 1 MiB 负载 | 二进制 Channel 完成 1048576 bytes；最终待消费 0/65536。显示 361 ms，仅一次功能观察，不作性能排名 |
| 分屏 → 选择 B 焦点 | A/B 各自显示相同 fixture，只有 B 活动；模式保持观察，输入目标显示 B |

原始 [AX 状态与诊断字节](tauri-native-ax.txt.gz)和[原生分屏截图](tauri-native-split.png)已保存。图中组合重音可见，但未逐格测量完整 Unicode；CUA paste 不代表真人中文 IME，未验证手机触控、系统剪贴板完整流程或真实 SSH／overlay。

结束后 Cmd+Q 退出；随后 `ps -axo pid=,comm=` 对两款测试应用名称精确筛选，无运行进程。未关闭其他用户应用。
