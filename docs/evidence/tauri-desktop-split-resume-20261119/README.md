# Tauri 桌面分屏回宽复验

2026-11-19。按 [D2](../../08-ui-design-plan.md#3-首轮画板与状态清单) 验收，回宽只自动恢复因收窄而暂停的副面板，原目标收到新完整画面后继续只读观察，输入焦点仍在原主面板。手动暂停继续要求主动恢复。

## 浏览器结果

实际运行 Tauri 生产前端和 xterm，使用模拟 Tauri IPC 与两个隔离合成目标。对照提交为修前 `c6b5e2e446ddbe77a92aea98c3d61c8a6f0839db` 和修后 `1c9e310b8b910c6a8c58091efb4acd0ef0857e6f`。四张为未裁切的浏览器原图，像素均为 1440 × 1000（DPR 1）。终端以页面内滚动方式进入视野。

| 浏览器 | 500 ms 暂停确认，快速回宽前 | 同条件修后 |
| --- | --- | --- |
| Chromium 151.0.7922.34 | [副面板仍暂停，旧帧](screens/chromium-before.png) | [副面板已恢复，新完整帧](screens/chromium-after.png) |
| WebKit 26.5 | [副面板仍暂停，旧帧](screens/webkit-before.png) | [副面板已恢复，新完整帧](screens/webkit-after.png) |

两浏览器均按 1440 → 700 → 1440 改变视口。快速用例在页面发出 `pause`、夹具尚未确认时拉宽。修前右侧重挂但保留旧帧，控制记录只有 `pause`。修后只发一次 `resume`，右侧确认同一 `w1:p1 / term_a001` 的新完整帧，左侧继续观察 `w1:p2 / term_b002` 并持有唯一输入焦点。宽度状态在前端通过模拟 IPC 验证，本次未覆盖 GTK、原生 macOS 窗口或 SSH 服务端的 PTY。

正常等待暂停确认的用例另行通过。窄窗仅显示左侧，暂停的右侧保留为标签。通过键盘切换到暂停标签后，只有主动按「恢复观察」才恢复。Chromium 使用 Tab／Enter，WebKit 使用 Option+Tab／Enter。独立的空白 HTML 对照中，WebKit 默认 Tab 会跳过原生按钮，Option+Tab 可到达。两浏览器修后全流程无输入或 resize IPC，并沿用两个 80 × 24 的原观察画布。[机器摘要及几何](verification.json)

[局部回归](../../../validation/tauri/test/desktop-d2-adaptation.test.mjs)另覆盖主动离开工作台后保持暂停、再次收窄、换焦点、关闭分屏或标签、目标变更，以及旧观察代的帧和被替换的终端。桌面定向测试 54 项、完整 Tauri 前端测试 677 项，均通过。

## 复跑

需要仓库内依赖已准备的 Tauri 前端、Node 24.22.2、Playwright 1.62.1 和已安装的 Chromium／WebKit。脚本用提交归档构建临时站点，在回环端口启动，不接触账号或远端主机。从仓库根目录运行。若 Playwright 安装在另一个目录，将 `HERDR_D2_PLAYWRIGHT_MODULE` 设为该安装的 `index.mjs` 路径。

```sh
evidence="$PWD/docs/evidence/tauri-desktop-split-resume-20261119"
run=$(mktemp -d)
sh "$evidence/prepare.sh" "$PWD" c6b5e2e446ddbe77a92aea98c3d61c8a6f0839db "$run/before"
sh "$evidence/prepare.sh" "$PWD" 1c9e310b8b910c6a8c58091efb4acd0ef0857e6f "$run/after"

for candidate in before after; do
  HERDR_D2_BROWSER=chromium node "$run/$candidate/browser-probe.mjs"
  HERDR_D2_TAB=Alt+Tab node "$run/$candidate/browser-probe.mjs"
  HERDR_D2_RAPID=1 HERDR_D2_BROWSER=chromium node "$run/$candidate/browser-probe.mjs"
  HERDR_D2_RAPID=1 HERDR_D2_TAB=Alt+Tab node "$run/$candidate/browser-probe.mjs"
done

(cd "$evidence" && shasum -a 256 -c SHA256SUMS)
```

两个修前快速用例预期退出 1，其余用例预期退出 0。每个用例在对应浏览器目录生成 `report.json` 和原始截图。
