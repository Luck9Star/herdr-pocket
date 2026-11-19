# Tauri 普通 SSH 入口布局验证

基线 `0b2fc1d9437598a84cda671371c707577b326957`。本批完成桌面空看板、连接方式选择与真实侧栏展开/收起；普通 SSH 的首次目标、指纹和认证桌面页面仍使用旧版布局。所有图片是 Playwright WebKit 26.5 原始 CSS 像素截图；通过环回 HTTP 和合成 Tauri IPC 正常点击导航，不建立真实 SSH。`before/` 是基线，`after/` 为本批实现；JSON 保留所列截图状态、动作、IPC 与原始测量，省略未归档截图的状态。`mobile-before/` 是本批首次桌面 CSS 改动后的移动观察，移动样式与基线相同；其 JSON 中旧 `sourceSha` 是脚本默认值，不是被测构建身份。

| 桌面宽度 | 侧栏 | 空卡 x,y,w,h | 选择 SSH x,y,w,h |
| --- | --- | --- | --- |
| 700 | 64 | 104,78,556,268 | 104,124,556,100 |
| 900 / 959 | 64 | 104,78,560,268 | 104,124,560,100 |
| 960 / 980 / 1440 | 224 | 264,78,560,268 | 264,124,560,100 |

700、980、1440 宽的设计锚点与这两组测量完全一致；另测 900、959、960 证明默认 960 断点。侧栏按钮自身为 44×44，六个宽度都实际点击一次展开或收起，再点击恢复；路由按钮宽度比稿小 1px，其余列出的锚点差 0。700 展开后空间收窄，卡片按可用宽度变为 396px。此前断开、返回和受控非空看板入口仍经过实际点击；非空看板观察在 `populated-980x780/`，该目录使用合成主机记录。

仍需后续完成桌面首次目标、指纹、选密码：例如 1440 首次目标 host 实测 `[260,277.8125,452,46]`，设计 `[264,134,560,48]`；首次核对卡和认证选项当前使用旧桌面结构，未达到冻结稿。侧栏在进入旧目标页后也回到原导航，不能把本批称作完整桌面流程的布局验收。首页标题沿用现有“主机与会话”，设计为“看板”；按钮沿用现有“普通 SSH”，设计为“普通 SSH 终端”。

移动首次核对及密码页分别在 390×844、320×640 测试，模拟顶部安全区 47px、24px：目标卡、指纹卡、确认按钮、密码框和连接按钮与稿差 0px，返回按钮差 1px。指纹实际文字宽度不是外层行框宽度；外层行框 y 差 1px、高差 1px。使用 `setViewportSize` 模拟键盘打开时的缩短视口并聚焦、滚动及恢复：320 宽缩到 402 高后滚动 78px，恢复高度后回到滚动 0；390 宽缩到 553 高后滚动保持 0。该过程不是原生键盘、系统安全区或真机验证，不能证明键盘动画、IME 和设备遮挡行为。

在依赖完整的临时副本执行 `npm test`：705/705；`npm run build` 通过。当前工作树未安装完整依赖，此结果不代表当前目录原地运行通过。此前原生设备或模拟器证据见项目已有文档，本次浏览器模拟不替代它们。

## 复验

使用与本次版本相同的已构建 Tauri `dist` 和 Playwright 1.62.1。以下从仓库根目录执行，所有依赖和一次性测试私钥均留在新建临时目录：

```sh
PRODUCT_DIST="$(pwd)/validation/tauri/dist"
EVIDENCE_DIR="$(pwd)/docs/evidence/tauri-ordinary-entry-layout-20261120"
REPLAY_DIR="$(mktemp -d)"
mkdir -p "$REPLAY_DIR/fixture"
cp "$EVIDENCE_DIR/desktop-replay.mjs" "$EVIDENCE_DIR/mobile-replay.mjs" "$REPLAY_DIR/"
cp "$EVIDENCE_DIR/fixture/host.pub" "$REPLAY_DIR/fixture/"
ssh-keygen -q -t rsa -N '' -f "$REPLAY_DIR/fixture/client"
cd "$REPLAY_DIR"
npm install --no-save playwright@1.62.1
npx playwright install webkit
FEEDBACK_PRODUCT_DIST="$PRODUCT_DIST" FEEDBACK_EVIDENCE=desktop-output FEEDBACK_PRODUCT_SHA=local node desktop-replay.mjs
FEEDBACK_PRODUCT_DIST="$PRODUCT_DIST" FEEDBACK_EVIDENCE=mobile-output FEEDBACK_PRODUCT_SHA=local node mobile-replay.mjs
```

移动脚本明确注入模拟安全区、调整 viewport；它不调用原生键盘。fixture 公钥为虚构记录，不保存任何私钥，也不触碰 SSH 授权文件。
