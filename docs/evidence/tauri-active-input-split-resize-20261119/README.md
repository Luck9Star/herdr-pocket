# Tauri D2 收窄与回宽时保留逐键焦点

基线 `44d7838e53020cc306ffbef9030c08c740a89381` 在 700 像素窗口确实暂停 A，但 B 的逐键编辑器在焦时跳过整页渲染，界面仍显示两个面板，收纳说明缺失。临时移除焦点守卫后，两个引擎都显示正确的一栏，但 B 的原输入框失焦，后续按键未发出。

修复 `a065fc0a689ec3784d10e7266abfc1f0dc45b2c0` 保留 B 已挂载的编辑器，只更新分屏布局及副面板。WebKit 26.5 和 Chromium 151.0.7922.34 的同一条测试确认以下结果。[脱敏报告](report.json) · [哈希清单](SHA256SUMS)

- 从 1440 收窄到 700 只发一次暂停 A。页面只显示 B 及收纳说明，B 保有同一个可编辑的 xterm 输入框、DOM 焦点和原输入租约。
- 回到 1440 只恢复同一个 A，先显示恢复中，确认同一目标的新完整帧后进入只读观察。B 在左、A 在右，面板坐标和宽度分别保持 265／560 和 839／560 像素。
- 测试分别在收窄前、窄窗中和回宽后按一次键。三个受理事件都属于原 B，A 收到零输入。窗口变化新增零输入、零授权切换、零重连和零 PTY resize 命令。
- 点击返回看板暂停两侧，再返回同一组标签并仅主动恢复 B，A 在下一次回宽后仍暂停。窄窗里才开启 B 的逐键输入再回宽，也保留该编辑器的焦点和输入资格。
- 新增的 [Node 回归](../../../validation/tauri/test/desktop-split.test.mjs) 在基线因窄窗仍有两栏而失败，修复后的前端全套 687 项通过。

浏览器运行生产前端和真实 xterm，以普通页面操作、浏览器键盘事件和视口变化驱动。原生 IPC 由隔离夹具提供。此次没有扩展原生窗口、SSH 网络和系统输入法的验收范围。

| 引擎 | 原版窄窗 700×1200 | 修复窄窗 700×1200 | 回宽后 A 新帧 1440×1200 | 手动暂停后回宽 1440×1200 |
| --- | --- | --- | --- | --- |
| WebKit | [原图](webkit-before-narrow.png) | [原图](webkit-after-narrow.png) | [原图](webkit-after-wide-new-full.png) | [原图](webkit-after-wide-manual-pause.png) |
| Chromium | [原图](chromium-before-narrow.png) | [原图](chromium-after-narrow.png) | [原图](chromium-after-wide-new-full.png) | [原图](chromium-after-wide-manual-pause.png) |

## 复跑

从包含本证据目录的仓库根运行。使用 Node.js 22.12 或更高版本。本次使用 Node.js 24.22.2 和 Playwright 1.62.1。下面把指定源码、构建产物和浏览器依赖放在临时目录中。

```sh
probe="$PWD/docs/evidence/tauri-active-input-split-resize-20261119/probe.mjs"
source_sha=a065fc0a689ec3784d10e7266abfc1f0dc45b2c0
scratch="$(mktemp -d)"
git archive "$source_sha" validation/tauri validation/shared validation/vendor \
  validation/remote-harness/theme-prompt-measurement.js | tar -xf - -C "$scratch"
npm ci --prefix "$scratch/validation/tauri"
npm run build --prefix "$scratch/validation/tauri" -- --outDir "$scratch/site"
npm install --prefix "$scratch/tools" --no-audit --no-fund playwright@1.62.1
"$scratch/tools/node_modules/.bin/playwright" install chromium webkit

for engine in chromium webkit; do
  HERDR_D2_SITE="$scratch/site" \
  HERDR_D2_OUTPUT="$scratch/$engine" \
  HERDR_D2_SOURCE_SHA="$source_sha" \
  HERDR_D2_BROWSER="$engine" \
  HERDR_D2_PLAYWRIGHT_MODULE="$scratch/tools/node_modules/playwright/index.mjs" \
  node "$probe"
done
```

两次的 `report.json` 应为 `passed: true`，浏览器原图在各自的 `shots/`。如需使用已安装的浏览器启动器，给对应命令设置 `HERDR_D2_EXECUTABLE`。换用基线 SHA 并重新构建时，探针仍会写出报告，预期在主用例发现窄窗保留两栏并以非零码退出。
