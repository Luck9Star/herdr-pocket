# 网络目录重开时的旧空卡竞态

基线为 `ead4bcd14153af6f96233b9781339f28fcfa58ed`，修复为 `8628659fb4d8694bab364c36cefd36a27c06dfd0`。四张 PNG 是原始 Playwright WebKit 26.5 截图，均为 980×780 CSS 像素、DPR 1：

- `before/pending-resize.png`：旧版本读取仍未完成，980→590→980 后错误地再次显示可点击的旧空卡。
- `after/pending-resize.png`：修复后相同状态显示“正在读取网络配置…”，没有空卡和添加按钮。
- `after/fresh-empty.png`：当前读取成功并确认空目录后才显示空卡。
- `after/failed-resize.png`：旧请求迟到、当前请求失败并再次跨断点后，显示读取失败、状态未知，没有空卡。

旧空卡与新读取确认的空卡外观相同，因此 `before/pending-resize.png` 和 `after/fresh-empty.png` 的 SHA-256 相同；区别来自受控请求时序，不可从静态图单独判断。`original-geometry.json` 保存首次对照脚本的原始测量；基线文件的 `failed` 表示旧行为触发断言。`replay-geometry.json` 是本目录精简脚本的独立复跑结果；基线的 `baselineReproduced: true` 表示成功复现缺陷，并非旧版本通过修复检查。图像的 PNG 尺寸、摘要与复跑 JSON 的摘要已逐一比对。

本证据使用回环 HTTP、真实 WebKit 页面与受控合成 Tauri IPC。脚本只控制测试网络目录读取的等待、成功和失败顺序，通过界面按钮进入普通 SSH 和网络页；未直接改写页面可见状态。它不连接真实 SSH，不读取或更改用户真实网络资料，也不证明原生 WebView 或设备行为。测试期间只有一次合成 SSH 打开，没有终端写入或关闭。

## 完整性校验

在本目录运行 `shasum -a 256 -c SHA256SUMS`。清单覆盖截图、两套测量、复跑入口和本文；`../fixture/host.pub` 为父目录已归档的虚构公钥，清单同样核验它。

两版 `validation/tauri/src/network-ui.js` 的 Git 内容 SHA-256 分别为：

- `ead4bcd14153af6f96233b9781339f28fcfa58ed`：`76391780110077d0cb2eaf2060bd621c10295286c5de4970b8ff5c474380476c`
- `8628659fb4d8694bab364c36cefd36a27c06dfd0`：`4596a46c862ba935cc2571ed6cfab501196f28f72b20963a31f854e3e69b8738`

可在仓库根目录使用 `git show <完整提交 SHA>:validation/tauri/src/network-ui.js | shasum -a 256` 独立核对。

## 从 Git 复跑

以下在仓库根目录执行；需本地已存在上述两次提交，Node 满足项目版本要求，并可安装 Playwright 1.62.1 和 WebKit。所有依赖、构建和测试输出均在临时目录：

```sh
REPO_PATH="$PWD"
DOC_PATH="$REPO_PATH/docs/evidence/tauri-ordinary-terminal-layout-20261120/network-reload"
FIXTURE_PATH="$REPO_PATH/docs/evidence/tauri-ordinary-terminal-layout-20261120/fixture/host.pub"
REPLAY_TEMP="$(mktemp -d)"
mkdir -p "$REPLAY_TEMP/run"
cp "$DOC_PATH/replay.mjs" "$REPLAY_TEMP/run/"
cd "$REPLAY_TEMP/run"
npm install --no-save playwright@1.62.1
npx playwright install webkit
for spec in \
  'ead4bcd14153af6f96233b9781339f28fcfa58ed:before' \
  '8628659fb4d8694bab364c36cefd36a27c06dfd0:after'
do
  REF="${spec%%:*}"
  LABEL="${spec#*:}"
  mkdir -p "$REPLAY_TEMP/$LABEL"
  git -C "$REPO_PATH" archive "$REF" validation/tauri validation/shared validation/vendor | tar -x -C "$REPLAY_TEMP/$LABEL"
  (cd "$REPLAY_TEMP/$LABEL/validation/tauri" && npm ci && npm run build)
  if [ "$LABEL" = before ]; then
    PRODUCT_DIST="$REPLAY_TEMP/$LABEL/validation/tauri/dist" FIXTURE_PUB="$FIXTURE_PATH" OUTPUT_DIR="$REPLAY_TEMP/output-$LABEL" EXPECT_REPRO=1 node "$REPLAY_TEMP/run/replay.mjs"
  else
    PRODUCT_DIST="$REPLAY_TEMP/$LABEL/validation/tauri/dist" FIXTURE_PUB="$FIXTURE_PATH" OUTPUT_DIR="$REPLAY_TEMP/output-$LABEL" node "$REPLAY_TEMP/run/replay.mjs"
  fi
done
```

基线应复现旧卡；修复版应依次通过读取中、当前读取成功、迟到响应和失败保持未知的检查。截图由当次环境生成，字体或平台差异可能改变其文件摘要；仓库中原图以清单摘要为准。
