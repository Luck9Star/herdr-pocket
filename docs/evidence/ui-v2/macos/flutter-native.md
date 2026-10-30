# Flutter v2：Mac 原生候选复验

2026-10-30，Mac17,3 / arm64 / macOS 26.6.2 (25G83)。实际运行 [candidate run41014495508](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014495508) 的 [Mac artifact12959725176](https://github.com/Luck9Star/herdr-pocket/actions/runs/41014495508/artifacts/12959725176)，源码 `7daa8a2341a0bc4270a962c3cc9aeb4906084b8f`。归档 SHA256：`d42e80030399bd64708862ee0e6a0f78ca756904479b61ac044c0e0c9125f758`；候选补丁、fixture/font/tokens 来源见[下载核验](../../flutter/v2-20261030/macos-package-verification.json)。

CUA 从解包后的 `.app` 启动，无本机 Flutter SDK、签名更改或系统安全设置变更。初始截图 1600×1256，zoom 后截图 5120×2640（均含标题栏）；这次只做功能复验，没有与 Tauri 使用严格相同内容区视口，不用于性能排名。

| 已执行操作 | 实际结果 |
| --- | --- |
| 初次打开及 zoom | 新版浅色应用壳、靛蓝操作色、深色终端；默认观察。宽屏出现主机侧栏，终端仍标 80×24 |
| 显式逐键 → 辅助 Ctrl+C | 本地 sink 1，UTF8 `03` |
| 注入未知 → 请求新 full | 新画面到达后仍显示“发送结果待核实”，本地接收保持 1 |
| 点击锁定的 Ctrl+C | 状态和接收计数不变；没有重放 |
| 人工核实 | 回到观察，需要重新明确选择输入方式 |
| 草稿逐键输入 `test` → 预览 → 确认 | 预览目标 demo-ts/session-a/pane-1；sink 增至 2，UTF8 `74657374`，无追加回车 |
| 分屏 → 选择 B → 请求 full | A 变非活动，只有 B 为输入焦点；B 本地接收 0，新画面到达后保持观察；两 pane 均 80×24 |

保存[未知状态 AX](flutter-native-unknown-ax.txt)、[草稿字节 AX](flutter-native-bytes-ax.txt)、[分屏 AX](flutter-native-split-ax.txt)与[分屏截图](flutter-native-split.png)。zoom 后 fixture 的 Marks 行可见重音，正式绘制比较仍以 Ubuntu/macOS headless 的逐像素回归证据为准，未逐格检查所有 Unicode。

CUA `paste('echo 中文')` 尝试未在草稿字段生效，预览为空，因此取消，改用实际逐键输入完成上述 ASCII 草稿检查。没有把这次自动化粘贴失败归因于产品实现，也不把中文粘贴／IME 标通过。macOS AX 部分图标按钮没有名称、禁用状态未明确暴露；可访问性仍需改进及辅助技术实测。

完成后 Cmd+Q 退出；进程查询确认 Flutter 与 Tauri 测试 App 均已结束，1421 / 4400 / 4401 / 4402 无监听。保留用户原 Penpot 编辑页。手机触控、真实输入法、GUI 的真实 SSH/herdr 与三网络连接仍未验证。
