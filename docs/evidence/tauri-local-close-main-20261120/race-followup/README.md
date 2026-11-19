# 关闭与连接回执竞态补充

产品修复 `2f060341363462f4fb811d4555913029e2325fed`，其父提交为 `f4427b47e60647fc1b4dc6f9cd4dc47a7b445659`。仅普通 SSH UI 与定向测试变更；后续候选 `ea5dd709806a2745e25792921d3b5da07dcdb6c0` 又加入 Linux 驱动修正。**候选的同源原生云端复验进行中，本页旧工件不能证明该候选已通过。**

## 红绿与浏览器实测

日志仅去除行尾空格，测试内容不变。

- [红测输出](red.log)：关闭 pending 中端口 input 后收到失败回执，结果仍卡在 pending；连接打开中返回后，迟到会话虽关闭，页面仍停在认证步骤。
- [附加红测](navigation-red.log)：取消打开后旧命令尚未返回时，再次返回被拦截，无法沿可见路径前往网络或设置。
- [专项绿测](green.log) 8/8：关闭成功/失败、目标输入锁定、取消后离页与迟到成功/失败、旧会话只关闭一次、新连接和手动修改后重新探测；没有自动重放终端输入。完整 JS [717/717](full-test-summary.txt)，构建通过。

[矩形与 IPC 计数](measurements.json) 和 `images/` 记录三个尺寸、两条受影响路径的 WebKit 原始实测；选存 320、1440 两尺寸的原图。关闭路径实际点击断开、触发受控 input、回执失败并点击返回；打开路径实际点击返回，经可见导航进入网络，再交付迟到的合成打开结果。六案均通过。320×640 pending/失败卡为 `[16,100,288,66]`、返回为 `[16,476,288,48]`；390×844 为 `[24,123,342,66]` / `[24,499,342,48]`；1440×900 为 `[264,76,560,66]` / `[264,452,560,48]`。卡片和返回按钮与既有冻结锚点差 0。

DPR 1，320/390 顶部安全区分别注入 24/47 CSS px；截图和节点是真实 WebKit 前端，Tauri IPC、会话与关闭结果为合成夹具，不代表真实 SSH 或原生设备。`replay.patch` 是相对于父目录既有 `replay.mjs` 的最小执行入口改动，不另复制完整脚本。复跑时从仓库根目录：

```sh
REPO_PATH="$PWD"
EVIDENCE_PATH="$REPO_PATH/docs/evidence/tauri-local-close-main-20261120"
RUN_DIR="$(mktemp -d)"
mkdir -p "$RUN_DIR/source" "$RUN_DIR/replay/fixture"
git archive 2f06034 validation/tauri validation/shared validation/vendor validation/remote-harness | tar -x -C "$RUN_DIR/source"
cp "$EVIDENCE_PATH/replay.mjs" "$EVIDENCE_PATH/design-anchors.json" "$RUN_DIR/replay/"
cp "$EVIDENCE_PATH/fixture/host.pub" "$RUN_DIR/replay/fixture/"
(cd "$RUN_DIR/replay" && patch -p0 < "$EVIDENCE_PATH/race-followup/replay.patch")
(cd "$RUN_DIR/source/validation/tauri" && npm ci && npm test && npm run build)
cd "$RUN_DIR/replay"
npm install --no-save playwright@1.62.1
npx playwright install webkit
PRODUCT_DIST="$RUN_DIR/source/validation/tauri/dist" OUTPUT_DIR="$RUN_DIR/output" node replay.mjs
```

## f442 旧源码的原生工件

以下是公开工件原 ZIP 的 SHA-256 和 Actions 来源。只留字段白名单摘要 [native-baseline.json](native-baseline.json)，不重复发布 ZIP、原始日志、夹具认证数据或图像中的其他内容。

| 原生运行 | 公开工件 | 原 ZIP SHA-256 | 可证明范围 |
| --- | --- | --- | --- |
| [Linux 44597653045](https://github.com/Luck9Star/herdr-pocket/actions/runs/44597653045) | [14567286532](https://github.com/Luck9Star/herdr-pocket/actions/runs/44597653045/artifacts/14567286532) | `a300d405fe92f75213bc6248bd80540e8fd65f4f4c76751e86de515a2c178663` | GTK / Xvfb 实际应用、隔离 loopback SSH 密码；确认指纹、PTY/shell、输入回显、断开及清理。两条 peer 均关闭。 |
| [Android 44597651198](https://github.com/Luck9Star/herdr-pocket/actions/runs/44597651198) | [14565294360](https://github.com/Luck9Star/herdr-pocket/actions/runs/44597651198/artifacts/14565294360) | `4fd5898921f3d6d3a7610f16715cb6659cd875c2521f35bd80a499b3cba0e56a` | API 35 模拟器自有 WebView、隔离 loopback SSH；普通、换钥与已有加密私钥案例。CDP 文字输入不证明真实输入法组合。 |

原生工件内部均自报源码 `f4427b47…`，与本次新 UI 修复和 Linux 驱动合并候选不同；其服务端是自建回环，不代表公网 SSH 或物理手机。
