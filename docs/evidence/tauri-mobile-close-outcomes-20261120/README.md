# Tauri 手机断开结果补充测量

产品与冻结设计基线为 `e392602e5d2bc15bc5ab5635b9d77b956ddca369`，其中产品源码与 `8628659fb4d8694bab364c36cefd36a27c06dfd0` 相同。本批没有发现超过 2pt 的指定布局差异或误导文案，因此没有修改产品 UI。`before/` 与 `after/` 是同一源码的两次独立测量，不是产品修复前后；后一次增加了边缘命中、设计锚点断言以及远端自然退出和无退出状态的反例。两次保留对应尺寸的原始截图与测量。

| 状态 | 390×844 反馈卡 | 390 返回 | 320×640 反馈卡 | 320 返回 |
| --- | --- | --- | --- | --- |
| 本机正常断开 | 24,123,342,66 | 24,499,342,48 | 16,100,288,66 | 16,476,288,48 |
| 有明确远端退出状态 | 24,123,342,66 | 24,499,342,48 | 16,100,288,84 | 16,494,288,48 |
| 本机关闭失败 | 24,123,342,66 | 24,499,342,48 | 16,100,288,66 | 16,476,288,48 |

表中为 x,y,w,h，单位为 CSS 像素；DPR 为 1，设计文件单位为 logical-point。六个结果页锚点（卡片、主机、用户名、端口、探测和返回）与对应冻结稿的最大差为 0；返回首页提示和空卡矩形也分别相符。待完成状态无对应冻结画板，单独记录而不作为设计对齐结论。390 与 320 浏览器测试分别注入 47px、24px 顶部模拟安全区；不代表系统实测安全区、系统键盘或原设备截图。

`after/` 的每个尺寸包括正常、关闭期间收到 `exitStatus=0`、远端自然退出、无状态的 exit、关闭失败和 pending 共六种场景。只有明确 exit 状态出现“远端已报告结束”；无状态 exit 只陈述本机已断开。失败文案及返回首页均不声称成功；pending 先返回首页显示正在断开，合成关闭完成后才更新为本机已断开。每个场景都从界面点击连接，记录一次合成探测、一次合成打开、一次合成关闭、零终端输入；自然退出由受控 peer 事件触发自动关闭，其余场景点击断开。关闭失败模拟抛错，不能由此证明真实传输已释放。

结果页的探测、返回按钮及活动终端断开按钮均检查四条边中点（距边 2px）的命中；断开与返回还实际点击左边缘。返回首页的“添加主机”和“普通 SSH”检查四边命中，没有为测试重复点击它们。`desktop/` 额外覆盖 1440×900、980×780、700×900 的相同六种状态，指定结果页与首页锚点最大差也为 0。JSON 记录每次点击后状态、四边命中和 IPC 计数；仅选定截图归档，未归档的截图名称仍可能出现在完整 JSON 中。

## 真实回环与证据边界

WebKit 截图使用真实前端、回环 HTTP 与受控合成 Tauri IPC；不连接真实 SSH，也不代表 Android/iOS 原生设备。作为独立传输层检查，使用相同源码的 Rust `direct_shell` 和每次新建的本地回环 SSH peer 运行：

- `cancellation_waits_for_the_authenticated_ssh_task`：一次已认证连接，确认本机取消等待 SSH 任务结束和夹具清理。
- `exit_events_only_include_evidence_sent_by_the_peer`：分别验证无报告、状态 0 和信号等独立 peer，只有实际收到的退出证据进入事件。
- `cancelled_shell_reports_only_consumed_exit_evidence_after_retirement`：分别核对关闭竞争期间已消费的退出证据与未消费报告，包含清理检查。

三项均通过，原始日志在 `logs/`；这些是**独立 Rust 传输层回环**，没有与浏览器截图串成一次端到端测试，也不能证明原生手机 UI。受控 IPC 的关闭失败同样不是 Rust 真实远端失败。完整临时前端副本 `npm test` 为 709/709、构建通过；原始日志同目录。没有访问用户 SSH 授权文件或真实网络身份。

`design-anchors.json` 从两份冻结设计生成器的上述四类画板提取；复跑脚本对照该快照并执行 ≤2pt 断言。来源 SHA-256：手机生成器 `5e38aa1dd6567af3cdd2ed3dfb577ce01414b1b58f535891ff6197bbfb73f313`，桌面生成器 `c14896bbddaef94e46a92b562fca9f9a21b0515c72ea295bd88f54f652f621d0`。`SHA256SUMS` 覆盖本目录记录、脚本、日志和截图；在本目录执行 `shasum -a 256 -c SHA256SUMS` 可校验。

## 复验

从仓库根目录运行；需要本地有基线提交及可安装 Playwright 1.62.1 的环境。构建和浏览器输出留在新临时目录，测试只使用目录内虚构公钥：

```sh
REPO_PATH="$PWD"
EVIDENCE_PATH="$REPO_PATH/docs/evidence/tauri-mobile-close-outcomes-20261120"
REPLAY_TEMP="$(mktemp -d)"
mkdir -p "$REPLAY_TEMP/source" "$REPLAY_TEMP/run/fixture"
git archive e392602e5d2bc15bc5ab5635b9d77b956ddca369 validation/tauri validation/shared validation/vendor | tar -x -C "$REPLAY_TEMP/source"
cp "$EVIDENCE_PATH/replay.mjs" "$EVIDENCE_PATH/design-anchors.json" "$REPLAY_TEMP/run/"
cp "$EVIDENCE_PATH/fixture/host.pub" "$REPLAY_TEMP/run/fixture/"
(cd "$REPLAY_TEMP/source/validation/tauri" && npm ci && npm run build)
cd "$REPLAY_TEMP/run"
npm install --no-save playwright@1.62.1
npx playwright install webkit
PRODUCT_DIST="$REPLAY_TEMP/source/validation/tauri/dist" OUTPUT_DIR="$REPLAY_TEMP/output" node replay.mjs
```

可分别以 `CARGO_TARGET_DIR="$(mktemp -d)" cargo test --locked --offline --manifest-path validation/transport-rust/Cargo.toml <上述测试名> -- --nocapture` 复跑 Rust 检查；需本机有锁定版本的离线 Cargo 依赖。浏览器与 Rust 两类结果应分别解释。
