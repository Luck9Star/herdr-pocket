# Tauri 普通 SSH 断开结果布局验证

基线 `122f82e4ad5640567bacdae886dd8224963cd05c`，结果来自该基线加本次工作区改动。`before/` 是基线截图及测量，`final/` 是改动后的截图及测量；`cases/` 保存失败、待完成、非空看板等补充场景。图片均为 Playwright WebKit 26.5 原始 CSS 像素截图，非真机截图。每个 `geometry.json` 包含元素矩形、命中测试、点击与 IPC 记录，最终记录还含结果阶段及颜色。

测试使用完整生产前端构建、环回 HTTP 和合成 Tauri IPC；按实际界面操作连接、断开、返回。它不建立真实 SSH，也不证明原生进程或远端关闭。桌面 viewport 为 1440×900、980×780、700×900；移动 viewport 为 390×844、320×640。浏览器报告的原生安全区均为 0；移动场景分别通过测试样式注入 47px 和 24px 顶部安全区以对照设计。无注入时结果卡与返回按钮 y 均为 76/452，首页提示 y 为 72；因此这里不证明真实设备安全区或键盘行为。

| 尺寸 | 结果卡 x,y,w,h | 返回按钮 x,y,w,h | 首页结果 x,y,w,h |
| --- | --- | --- | --- |
| 1440×900 | 264,76,560,66 | 264,452,560,48 | 264,62,560,44 |
| 980×780 | 264,76,560,66 | 264,452,560,48 | 264,62,560,44 |
| 700×900 | 104,76,556,66 | 104,452,556,48 | 104,62,556,44 |
| 390×844 | 24,123,342,66 | 24,499,342,48 | 24,119,342,44 |
| 320×640 | 16,100,288,66 | 16,476,288,48 | 16,96,288,44 |

以上 15 个矩形与给定设计锚点差为 0 CSS px，满足 2px 容差。桌面字段、探测按钮以及空看板卡片也与提供的矩形对齐；移动测量包含上述模拟安全区。现有真实路由用于侧栏，700 宽使用 64px 图标栏，较宽时为 224px；设计中的侧栏折叠按钮尚无对应真实交互，因此没有伪造。桌面结果页只在断开结果和返回的空看板启用该布局；非空看板沿用现有布局。

失败采用 danger，pending 采用中性色，确认后采用品牌色；两处均根据结果 phase 而非翻译文字选择。`cases/700x900-password-choose-close-pending` 验证 pending 时先返回，首页仍显示正在断开，合成关闭完成后才显示本机已断开；失败和 `false` 返回也可返回首页。`cases/980x780-password-direct-close-confirmed` 用一条合成已存主机，真实点击验证返回后“添加主机”和“普通 SSH”入口均可进入；这是浏览器内合成目录，并非用户主机。

验证时完整临时副本 `npm test` 为 704/704，`npm run build` 通过；当前工作树缺少本地依赖，不能把该结果称为当前目录原地运行通过。除了被测源码和生成物，临时副本与仓库 Tauri 源码比较仅发现原有 macOS 图标文件不同；图标不参与 Web 构建。图像中的文本、图标与真实平台原生安全区仍需设计及真机验收。

## 复现说明

`replay.mjs` 覆盖五尺寸的确认和失败流程。以下示例在临时目录安装 Playwright 1.62.1 并创建一次性私钥；不改动本仓库的依赖，也不保存私钥到仓库。先在 Tauri 目录完成生产构建，将 `PRODUCT_DIST` 设置为其 `dist` 的绝对路径，然后从仓库根目录执行：

```sh
PRODUCT_DIST="$(pwd)/validation/tauri/dist"
EVIDENCE_DIR="$(pwd)/docs/evidence/tauri-local-close-layout-20261119"
REPLAY_DIR="$(mktemp -d)"
mkdir -p "$REPLAY_DIR/fixture"
cp "$EVIDENCE_DIR/replay.mjs" "$REPLAY_DIR/"
cp "$EVIDENCE_DIR/fixture/host.pub" "$REPLAY_DIR/fixture/"
ssh-keygen -q -t rsa -N '' -f "$REPLAY_DIR/fixture/client"
cd "$REPLAY_DIR"
npm install --no-save playwright@1.62.1
npx playwright install webkit
FEEDBACK_PRODUCT_DIST="$PRODUCT_DIST" FEEDBACK_PRODUCT_SHA="local-replay" node replay.mjs
```

`fixture/host.pub` 是虚构主机公钥。脚本使用环回服务器与合成 IPC，不访问 SSH 授权文件或网络身份。脚本中的移动测试注入模拟安全区；pending 和非空看板的原始截图与记录已保存，上述五尺寸复验入口不覆盖那两个附加场景。
