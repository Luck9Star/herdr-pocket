# Tauri 普通 SSH：本机关停与桌面活动页

产品源码基线 `e719ddf136397ad7a6796ae1f66558f240ecd388`，本批 UI 移植提交 `dde0ca4`。后者 9 个 Tauri 前端及测试文件完整取自 `f440c36611ab89b35bf7762044532ce600f2c34b`。`source-SHA256SUMS` 只描述冻结提交 `dde0ca4` 的九文件，后续 HEAD 已含回执竞态修复；应在该提交的独立导出中校验，见下方命令。需要整体复用是因为活动页与真实侧栏、桌面分步认证、手机同文件样式及共享网络读取状态相互依赖；没有移动 Rust、Flutter、原生驱动或工作流。

这是 Playwright WebKit 26.5、真实产品前端和 xterm、回环 HTTP 与受控合成 Tauri IPC 的测量，**不是实际 SSH、原生 WebView、手机真机或真实键盘证据**。320×640、390×844 分别注入 24px、47px 顶部模拟安全区，不代表设备实测安全区。页面 `DPR=1`，坐标为 CSS px，对照冻结设计 logical pt。

## 桌面活动页对照

| 尺寸 | 中间版 e719ddf：断开按钮 | 移植后：断开按钮 | 移植后：真实终端容器 |
| --- | --- | --- | --- |
| 1440×900 | 349.61,868.81,81.61,44 | 1324,4,76,44 | 264,120,1136,764 |
| 980×780 | 119.61,683.81,81.61,44 | 864,4,76,44 | 264,120,676,644 |
| 700×900 | 109.61,803.81,81.61,44 | 584,4,76,44 | 104,120,556,764 |

1440 中间版按钮底部超出视口约 12.8px，初始四边中点命中为 `[true,true,true,false]`。同机同尺寸当前 main `9eab3ba` 结果相同，说明这是既有问题；完整版 `483251b` 的按钮为 `[1324,4,76,44]`、四边可命中。三份原图和实测 JSON 在 `before/`；新图在 `routes/`。移植后上表九项和冻结稿相差 0，按钮四边可命中；各非自然退出场景实际点击距底边 2px 的位置。终端填满剩余宽度并可滚动，并未通过压缩终端修复按钮。

## 关闭结果与再连接

五尺寸分别运行正常本机关闭、关闭时收到远端 exit 状态、远端自然 exit、无状态 exit、本机关闭失败、关闭 pending 六场景，共 30 项。除自然退出由受控事件触发外均实点断开；各场景实点返回首页，检查凭据字段清空和结果状态。pending 返回首页先显示处理中，模拟完成后才显示本机已断开。无远端状态的 exit 只显示本机断开，不声称远端报告；失败显示可能仍在，不能用模拟失败推断真实传输释放。

| viewport | 普通结果卡 / 返回按钮 | 明确远端报告结果卡 / 返回按钮 |
| --- | --- | --- |
| 320×640 | 16,100,288,66 / 16,476,288,48 | 16,100,288,84 / 16,494,288,48 |
| 390×844 | 24,123,342,66 / 24,499,342,48 | 24,123,342,66 / 24,499,342,48 |
| 700×900 | 104,76,556,66 / 104,452,556,48 | 同左 |
| 980×780、1440×900 | 264,76,560,66 / 264,452,560,48 | 同左 |

有冻结画板的结果卡、主机、用户名、端口、探测按钮、返回按钮及返回首页卡的所有矩形最大差为 0；pending 无冻结画板，只报告行为。各测量和对应原始截图在 `outcomes/`。25 个成功关闭的场景随后实际从首页建立新的合成会话，再向旧回调注入迟到 exit：新会话仍活动、未出现旧结果、无额外写入和误关闭，随后显式断开第二会话。失败场景不假设旧资源已释放，不进行此再连接断言。

## 会话与网络路由

`terminal-replay.mjs` 复用 `f440c36` 已验的参数化入口：三桌面、两手机、长目标、已有主机、已有网络配置和读取失败共 9 项通过。真实 xterm 滚动后经看板、网络、设置往返，验证同一 xterm 和可见行保留、无额外连接、无额外输入；随后显式输入 `hp-once` 并断开。网络空态、新建/管理、已有配置和不可读均为合成数据，不读取或更改真实网络。每个场景的 JSON 和选定原图在 `routes/`；JSON 中未归档截图的哈希仅用于该次临时运行。

`npm-test-integrated.log` 为 709/709，`npm-build-integrated.log` 为构建通过。一次初始测试因临时副本漏取 `validation/remote-harness/theme-prompt-measurement.js` 出现 708/709；补齐同基线依赖后重跑得到所归档的 709/709。设计生成器 SHA-256：桌面 `c14896bbddaef94e46a92b562fca9f9a21b0515c72ea295bd88f54f652f621d0`；手机 `5e38aa1dd6567af3cdd2ed3dfb577ce01414b1b58f535891ff6197bbfb73f313`。

## 冻结九文件校验

从仓库根目录执行；不要拿后续 HEAD 的文件与历史清单直接比较：

```sh
REPO_PATH="$PWD"
FROZEN_DIR="$(mktemp -d)"
git archive dde0ca4 validation/tauri/index.html validation/tauri/src validation/tauri/test | tar -x -C "$FROZEN_DIR"
(cd "$FROZEN_DIR" && shasum -a 256 -c "$REPO_PATH/docs/evidence/tauri-local-close-main-20261120/source-SHA256SUMS")
```

[后续回执竞态红绿、受影响 WebKit 图与 f442 原生工件来源](race-followup/README.md) 单独记录；新 UI 与 Linux 驱动合并候选的云端复验尚在进行。

## 复验

从干净仓库根目录执行；需能安装锁定依赖和 Playwright 1.62.1。所有构建、夹具和结果留在新临时目录，主机公钥为测试数据，无私钥：

```sh
REPO_PATH="$PWD"
EVIDENCE_PATH="$REPO_PATH/docs/evidence/tauri-local-close-main-20261120"
RUN_DIR="$(mktemp -d)"
mkdir -p "$RUN_DIR/source" "$RUN_DIR/replay/fixture"
git archive dde0ca4 validation/tauri validation/shared validation/vendor validation/remote-harness | tar -x -C "$RUN_DIR/source"
cp "$EVIDENCE_PATH/replay.mjs" "$EVIDENCE_PATH/terminal-replay.mjs" "$EVIDENCE_PATH/design-anchors.json" "$RUN_DIR/replay/"
cp "$EVIDENCE_PATH/fixture/host.pub" "$RUN_DIR/replay/fixture/"
(cd "$RUN_DIR/source/validation/tauri" && npm ci && npm test && npm run build)
cd "$RUN_DIR/replay"
npm install --no-save playwright@1.62.1
npx playwright install webkit
PRODUCT_DIST="$RUN_DIR/source/validation/tauri/dist" OUTPUT_DIR="$RUN_DIR/outcomes" node replay.mjs
FEEDBACK_PRODUCT_DIST="$RUN_DIR/source/validation/tauri/dist" FEEDBACK_EVIDENCE="$RUN_DIR/routes" node terminal-replay.mjs
```

在本目录执行 `shasum -a 256 -c SHA256SUMS` 校验归档；原生层检查应在同源构建上独立运行，不能把本浏览器截图当作设备证据。
