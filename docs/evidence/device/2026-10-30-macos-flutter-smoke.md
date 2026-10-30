# macOS Flutter 原生包 smoke

2026-10-30，在与 Tauri 相同的 Mac17,3 / arm64 / macOS 26.6.2 (25G83) 上直接启动 CI 解包 App；没有装 SDK 或修改 OS 安全设置。

- [Actions 40983264890](https://github.com/Luck9Star/herdr-pocket/actions/runs/40983264890)，commit `c8d70abf45972a5e4d715117213916ba6df7f190`，macOS job 成功；该 run 的其他 job 需独立判断。
- archive SHA256 `67cbf812e2ac9d1db4a1c17cc3833baf87d4f936a115ebb2917b3de5832a07e4`。
- Flutter + terminal_view 0.5.0；fixture SHA256 `ad2eca3667445764d501ecb6ab53079232850c913626f433b167d1cdb97d7ab3`，font SHA256 `f01031f40e48dc29e1112e6b0b0450a2c6cd097f3f35cfff05c55cb311f8034c`。
- 初始窗口截图 1600×1256 px；通过 CUA 窗口拖拽调整至 2880×1800 px（含标题栏），与 Tauri 实测截图窗体尺寸一致。两者 80×24，同字体文件；Flutter 显示 14px。内容区布局不同，尚非逐个终端单元像素完全相等的性能基准。

## 实际观察

| 操作 | 结果 | 证明范围 |
| --- | --- | --- |
| 原生启动、加载 fixture、窗口放大 | 成功，终端 80×24 没有随窗口变化 | 本地渲染；没有远端 PTY |
| CUA pressKey a/b/c/Return | sink 4，最后 `0d`；再单键 x 为 sink 5 / `78` | 自动化键事件；不是人类物理键盘或中文 IME |
| 辅助 Ctrl-C | sink 6，`03` | 辅助按钮字节正确 |
| 1 MiB paced | UI完成；queue 0/65536、peak4096 | 仅解析提交，并非绘制完成或帧率测量；不能与 Tauri 1952ms直接比较 |
| 注入未知／断线 | 逐键／草稿入口和辅助键目视禁用；点击 Ctrl-C 后 sink不增加 | 本地失败注入 |
| 获取新 full | 仍默认观察且输入锁；人工核实后才能选草稿；没有增加 sink | 不自动重放 |
| 草稿 `test` | CUA单键产生文本，预览目标A；确认只增加一次 sink，UTF8 `74657374`，无CR | 一次提交、目标预览 |
| 标签 A→B→A | 切换显示旧画面/等待full，默认观察；B sink0。A 新full后预览仍有 `keepkeep` 草稿，sink7保留 | 独立草稿与恢复门控 |
| 组合字符显示 | 同fixture的 Marks 行目视疑似缺失组合重音；Tauri可见é/Å/ñ。已交候选作者核查 | 这是初次观察；后续源码定位见下文，确认候选版本渲染问题，原生复制仍未验证 |

自动化边界：CUA `paste` 到此 Flutter 草稿未成功；AX `setValue` 虽显示值变化，预览仍空，不能当真实编辑输入，也不能直接算产品缺陷。改用 `pressKey` 后草稿预览与提交正常。真实中文 IME、系统粘贴和终端选区复制尚未验证。Flutter AX 快照对目视禁用按钮未稳定返回 disabled 状态；需要后续读屏实测。

截图在本轮 CUA 工具会话图像中，尚未导出仓库图片。真实 SSH/herdr、三网络、手机输入、系统后台、交互式远端TUI均未验证。单macOS smoke不足以选定框架。

后续定位：作者发现 terminal_view 0.5.0 的 Buffer.writeChar(width0) 保留 combined，但 Painter._paintLineForeground 的 ASCII batch 只传基字符，忽略 combined；与本机显示一致，记录为该候选版本的渲染正确性失败，[真实painter诊断](../flutter/combining-ed35d84/combining-render.json)已在[run40985723032](https://github.com/Luck9Star/herdr-pocket/actions/runs/40985723032)失败复现：buffer和getText都保留原分解码点，cursorX=5；base/marked两图均138非透明像素且PNG完全相同。证明当前候选的ASCII批量绘制丢失组合重音效果，非输入／存储丢失。该测试是Flutter test engine内实际TerminalPainter，不冒充原生clipboard或IME。实际已用鼠标选择 Marks 行并出现可见选区，点击复制后浏览器桥clipboard读到空串，不能确认跨工具系统clipboard内容；因此原生复制功能和复制文本未判通过。

收尾：本次启动的测试 App 已通过 Cmd+Q 退出，随后按测试应用进程名与云产物目录精确检查，无运行进程；未关闭其他应用。
