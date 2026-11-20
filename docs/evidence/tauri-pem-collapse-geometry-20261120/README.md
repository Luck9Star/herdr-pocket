# Tauri PEM 收起样式与同步聚焦证据（2026-11-20）

## 范围

本目录只归档 `validation/tauri` 产品前端在 Playwright WebKit 中的 DOM/CSS/焦点行为与同尺寸截图。它不证明原生 Tauri 窗口、iOS/macOS 原生软键盘、真实 SSH、真机或云端 CI 通过。

证据使用两个明确的 Git 源 ref：

- 修前：`65319ae6c750ce5b60c6cd19ef37557c95f4dd28`
- 当前：`8769fd50e6044d632a9427bd38c578a06dadd6fa`

证据目录中的 `probe-*.mjs` 来自包含本证据目录的最终归档，与产品 source ref 分开。两个 ref 均含 `validation/tauri/package.json` 与 `package-lock.json`。设计冻结来源为：

- `design/penpot/direct-ssh-pem-states/mobile/private-key-collapsed-390.svg`
- `design/penpot/direct-ssh-pem-states/desktop/private-key-collapsed-980.svg`

冻结 SVG 要求 390 按钮 `[24,351,342,84]`、文字中心 `x=195`；980 按钮 `[264,304,560,84]`、文字中心 `x=544`；双端 `rx=42`、文字色 `#4F46E5` 且居中。

## 从两个 source refs 复跑

在包含这两个产品提交和本证据提交的仓库中，从该证据提交检出后执行以下整段命令。需要 Node.js、npm、Git、tar 和 Playwright WebKit 所需的系统依赖与网络；本次使用 Playwright **1.62.1**、WebKit **26.5**。不同系统、字体或浏览器版本可能使 PNG 字节不同，须检查 JSON 和截图，不能仅凭哈希推断功能是否一致。命令安装固定版本及其 WebKit；如果已在本机安装相同版本及浏览器，可跳过安装并将 `PLAYWRIGHT_MODULE` 设为其 `index.mjs` 的绝对路径。

```sh
set -eu
repo=$(git rev-parse --show-toplevel)
tmp=$(mktemp -d)
evidence=docs/evidence/tauri-pem-collapse-geometry-20261120
mkdir -p "$tmp/before" "$tmp/after" "$tmp/evidence" "$tmp/out" "$tmp/pw"
git -C "$repo" archive 65319ae6c750ce5b60c6cd19ef37557c95f4dd28 \
  validation/tauri validation/shared validation/vendor | tar -x -C "$tmp/before"
git -C "$repo" archive 8769fd50e6044d632a9427bd38c578a06dadd6fa \
  validation/tauri validation/shared validation/vendor | tar -x -C "$tmp/after"
git -C "$repo" archive HEAD "$evidence" | tar -x -C "$tmp/evidence"
(cd "$tmp/before/validation/tauri" && npm ci && npm run build -- --outDir "$tmp/before-dist")
(cd "$tmp/after/validation/tauri" && npm ci && npm run build -- --outDir "$tmp/after-dist")
if [ -z "${PLAYWRIGHT_MODULE:-}" ]; then
  npm install --prefix "$tmp/pw" --no-save playwright@1.62.1
  "$tmp/pw/node_modules/.bin/playwright" install webkit
  PLAYWRIGHT_MODULE="$tmp/pw/node_modules/playwright/index.mjs"
fi
export PLAYWRIGHT_MODULE
node -e 'const p = require("node:path"); const v = require(p.join(p.dirname(process.env.PLAYWRIGHT_MODULE), "package.json")).version; if (v !== "1.62.1") throw Error(`Playwright ${v}, expected 1.62.1`);'
(
  cd "$tmp/out"
  R12_APP="$tmp/after-dist" R12_APP_SOURCE=8769fd50e6044d632a9427bd38c578a06dadd6fa \
    node "$tmp/evidence/$evidence/probe-geometry.mjs" .
  R12_APP="$tmp/before-dist" R12_APP_SOURCE=65319ae6c750ce5b60c6cd19ef37557c95f4dd28 \
    R12_VARIANT=baseline node "$tmp/evidence/$evidence/probe-behavior.mjs" .
  R12_APP="$tmp/after-dist" R12_APP_SOURCE=8769fd50e6044d632a9427bd38c578a06dadd6fa \
    R12_VARIANT=current node "$tmp/evidence/$evidence/probe-behavior.mjs" .
)
printf '复跑产物：%s/out\n归档证据：%s/evidence/%s\n' "$tmp" "$tmp" "$evidence"
```

先在归档证据目录运行 `shasum -a 256 -c SHA256SUMS` 检查归档完整性，再逐项对比复跑目录的 JSON 与 PNG。两次产品导出和最终证据导出均通过 `git -C "$repo"` 完成；构建输出位于独立的临时目录。JSON 中截图路径为相对输出目录的路径。

`probe-geometry.mjs` 与 `probe-behavior.mjs` 只通过可见的 `#home-open-ssh`、`#ssh-probe`、`#ssh-trust-confirm` 等真实控件点击；不会用 `evaluate` 点击隐藏入口、切换隐藏 DOM 或强制显示凭据区。凭据和主机指纹均为公开合成 fixture，合成 Tauri IPC 只用于本浏览器探针。

## 实测结果

本次用两个指定提交实际重跑；14 张 PNG 与前一版逐字节一致。`geometry.json` 对应当前 source ref，记录 WebKit 26.5 双尺寸：

- 390：`borderRadius=42px`、`rgb(79,70,229)`、居中，文字中心 195。
- 980：`borderRadius=42px`、`rgb(79,70,229)`、居中，文字中心 544。
- 目标/摘要/粘贴/口令/连接锚点偏差为 0。

`behavior-geometry-baseline.json` 对应修前 source ref。两个尺寸均从可点击的入口和指纹确认进入；填入草稿后点击口令框失焦，再点击仍可见的编辑框。修前失焦后私钥正文仍可见：

- `afterBlur.editorVisible=true`
- `afterBlur.summaryVisible=false`
- 对应原图 `pem-baseline-editor-visible-390.png` / `pem-baseline-editor-visible-980.png`
- 修前不是“旧黑字摘要”，旧版没有唯一摘要态。

`behavior-geometry-current.json` 对应当前 source ref：

- 两个尺寸均从可点击的入口和指纹确认进入，填入草稿后点击口令框失焦，再点击摘要重开。
- `afterBlur`：正文不可见且值为空，唯一摘要显示，焦点在口令框。
- `afterReopen`：摘要真实点击后编辑器恢复可见，`activeElement=ssh-key`。
- `afterPaste`：粘贴后重新折叠为唯一摘要，焦点在粘贴按钮。
- DOM 全文不含合成草稿或剪贴板值。

## 原图清单

- 修前：`pem-baseline-editor-visible-{390,980}.png`、`pem-baseline-reopen-{390,980}.png`、`pem-baseline-paste-{390,980}.png`
- 当前几何：`pem-collapsed-{390,980}.png`
- 当前行为：`pem-blur-current-{390,980}.png`、`pem-reopen-current-{390,980}.png`、`pem-final-current-{390,980}.png`

所有 PNG 均为 `deviceScaleFactor=1` 的原始尺寸，未经缩放或后期标注。

## 证据边界

- 首次归档曾把修前正文可见截图误称为旧摘要态，并在桌面探针里通过隐藏 DOM 绕过入口；本版已删除这些错误截图与绕行，改用可见指纹确认按钮后重新取证。
- 真实产品桌面入口与指纹确认在本次双尺寸 WebKit 探针中可完成；没有强行打开 `hidden` 控件。
- Swift 驱动的严格唯一摘要、重开软键盘、错误/正确口令回调序列属于另一批代码测试，不由本浏览器证据证明。
- 归档只用于说明样式、几何和 DOM 焦点；不得据此宣称原生流程或真机验收通过。
