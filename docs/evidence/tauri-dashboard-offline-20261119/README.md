# Tauri 看板离线降级浏览器复验

2026-11-19，M1-06。修前使用当时的 `main` 提交 `d5d56951dc1e6650bf56d8cba8db3b3cfaebd245`，修后使用它与修复提交 `22493cd701dd83cf2137f47735add889eb2cb537` 生成的预演合并树 `d89b2d273aa52eadee7da4babb4559df16f85e5b`。两边均构建 Tauri 生产前端，使用 Vite 8.3.5。原报告的 `sourceSHA` 分别记录为 `before` 和 `after`，对应上述两棵源码。

| 浏览器 | 修前 | 修后 |
| --- | --- | --- |
| Chromium 151.0.7922.34 | [原图](chromium-before.png) · [原报告](chromium-before-report.json) | [原图](chromium-after.png) · [原报告](chromium-after-report.json) |
| WebKit 26.5 | [原图](webkit-before.png) · [原报告](webkit-before-report.json) | [原图](webkit-after.png) · [原报告](webkit-after-report.json) |

从看板新建系统直连标签，核对并连接选择的窗格，开启逐键输入。Playwright 网络仿真触发浏览器的 `offline` 和 `online` 事件，两者均记录 `isTrusted: true`。期间夹具送来旧连接的迟到快照。四张 1440 × 1000 原图均拍于恢复网络之后、主动重连之前，展示观察和输入状态。主机看板的受阻计数与同步时间见原报告。

- 修前仍显示当前快照，迟到回调将受阻数从 1 改为 0，取消调用为 0。
- 修后保留陈旧快照、原同步时间和受阻数 1，拒绝迟到快照，取消调用为 1，输入锁定。恢复网络后观察调用仍为 1，主动重新核对并连接后才显示新快照。两边的输入和远端 resize 调用均为 0。

验收覆盖实际浏览器事件到生产页面的状态变化，Tauri IPC 和远端数据由夹具提供。原生 WebView、真实 SSH 断网及真机组合验收仍待验证。 [原件 SHA-256](SHA256SUMS)

## 复跑正常入口回归

在含修复的源码上使用 Node.js 22.12.0 或更高版本，从仓库根目录执行。用例应通过，并核对原连接取消和新快照恢复。 [正常入口测试](../../../validation/tauri/test/direct-dashboard-gui.test.mjs)

```sh
cd validation/tauri
npm ci
node --test --test-name-pattern='saved system-route workspace' test/direct-dashboard-gui.test.mjs
```

从本证据目录执行 `shasum -a 256 -c SHA256SUMS` 核对归档原件。
