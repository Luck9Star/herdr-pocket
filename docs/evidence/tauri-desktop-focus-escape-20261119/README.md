# Tauri 桌面终端用键盘退出逐键输入

[D1 快捷键和焦点轮转](../../08-ui-design-plan.md#3-首轮画板与状态清单)涉及本地导航，并受[快捷键不得意外发送](../../05-product-design.md#7-产品验收)的验收约束。本次验证使用已有的 `Ctrl+Shift+F6`。主机工作台从正常入口打开两个测试标签并分屏，B 显式开启逐键输入。真实键 `x` 先向 B 提交一个字节，确认接收计数有效。窗口经历 1440 → 700 → 1440，回宽时仍由同一个 B 的 xterm 编辑节点持有焦点。

| 版本 | 按下退出快捷键 | 测试对端收到的输入 |
| --- | --- | --- |
| 修前 | 浏览器的 `HTMLCollection` 没有 `filter`。焦点留在 B 的 xterm，逐键输入仍启用 | A 为 0。B 先收到 `x`，又收到 7 字节 xterm 序列 `1b 5b 31 37 3b 36 7e` |
| 修后 | 浏览器消费快捷键，焦点移到 A 的「设为输入焦点」按钮。B 从逐键输入降回观察，当前选中的终端仍是 B | A 为 0，B 只收到此前的 `x` |

修后在 Chromium 用 Tab、Shift+Tab 回到 A 的按钮。WebKit 默认 Shift+Tab 到达 B 的草稿框，再使用该环境的 Option+Tab 到达 A 的按钮。两种浏览器都在实际聚焦按钮后用 Enter 明确选中 A，两侧继续观察，字节数保持 A 0／B 1。两条模拟连接各建立一次。按键均由浏览器键盘接口产生，报告记录 `isTrusted`、焦点、模式和每笔模拟 IPC 字节。

[Chromium 修前](chromium-before.json) · [Chromium 修后](chromium-after.json) · [WebKit 修前](webkit-before.json) · [WebKit 修后](webkit-after.json) · [校验清单](SHA256SUMS)

[Chromium 修前原图](chromium-before.png) · [Chromium 修后原图](chromium-after.png)。两张均为 1440 × 1200、DPR 1，在按下快捷键后截取，画面滚动位置随焦点变化。字节数和输入模式以机器报告为准。

## 范围与复跑

macOS arm64，Node 24.22.2，Playwright 1.60.0，Chromium 148.0.7778.96 和 WebKit 26.4。运行 Tauri 生产前端与 xterm，host、fingerprint、SSH 对端及输入回执均由隔离 IPC 提供。本次未运行原生 Tauri 窗口、真实 SSH 或 PTY。

[探针](browser-probe.mjs)使用 [既有构建脚本](../tauri-desktop-split-resume-20261119/prepare.sh)归档并构建基线 `44d7838e53020cc306ffbef9030c08c740a89381`。将探针复制到临时构建目录运行。修后以同一基线构建，仅换入修复后的 `validation/tauri/src/key-router.js` 并重建 `site/`。四份报告的 `routerSha256` 可用于核对源码。可用 `HERDR_D2_PLAYWRIGHT_MODULE` 指定 Playwright 启动模块，`HERDR_D2_BROWSER=chromium` 选择 Chromium，`HERDR_WEBKIT_EXECUTABLE` 指定已有 WebKit，`HERDR_SCREENSHOT=1` 保存原图。修前探针写下报告并返回 1。

## 主机与终端标签快捷键

独立浏览器复现使用基线 `44d7838e53020cc306ffbef9030c08c740a89381`，修后只替换 `navButtons()` 的集合转换。当前组合在 `0aa046dbf105f35020d5a408119363d9ea1ce774` 上应用同一个修改。两份修后源码之间，生产差异只有先前保留的 `panels()` 焦点退出修复。

在工作台的「返回主机看板」按钮持有焦点时，Chromium 148 和 WebKit 26.4 的真实键盘事件都复现相同故障。原来的按钮点击正常，四个快捷键因 `HTMLCollection.filter` 抛错，事件未被消费。修后无浏览器错误，应用消费了四个事件。

| 按键 | 修后选择 |
| --- | --- |
| Ctrl+1 | 终端 A（`w1:p1 / term_a001`） |
| Ctrl+Tab | 终端 B（`w1:p2 / term_b002`） |
| Ctrl+Shift+Tab | 终端 A |
| Alt+1 | 主机 A |

普通 Tab 在修前和修后均未被应用消费，也未改变选中的终端。两个目标都未收到输入。对组合源码另用 WebKit 复查四个导航键，用 Chromium 复查 `Ctrl+Shift+F6` 退出逐键输入。退出案例只收到有意发给 B 的 `x`，没有额外输入。逐键输入或其他文本编辑器聚焦时，四个导航键仍沿用既有传递规则。上述为浏览器按键和模拟 IPC 证据。

[Chromium 导航修前](nav-chromium-before.json) · [Chromium 导航修后](nav-chromium-after.json) · [WebKit 导航修前](nav-webkit-before.json) · [WebKit 导航修后](nav-webkit-after.json) · [导航校验清单](SHA256SUMS-nav)
