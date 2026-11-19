# 桌面分屏窗口变化验收

2026-11-19，Flutter 的 [D2 窄桌面与窗口变化](08-ui-design-plan.md#3-首轮画板与状态清单)在正常主机工作台完成 Widget 回归。收窄时保留活动终端与输入焦点，暂停另一侧。拉宽后恢复原来的左右位置，副侧显示旧画面并标为已暂停。Ubuntu 官方作业已在 Flutter Widget 中验证两条真实 OpenSSH/herdr 回环的分屏、焦点和输入隔离。macOS 无界面回环也已复验，macOS 原生窗口内两条真实连接的分屏与窗口变化仍待验收。

## Flutter 窗口与键盘回归

在 macOS arm64 运行 Flutter 3.47.9（`c197ca5199e9ee5661e865596c9c07294dfab51c`）。从主机工作台入口打开两个独立标签，走审查、连接与分屏。观察帧和输入回执由合成适配器提供。

| 逻辑宽度 | 原版 `aecd0d7` | 修复版 `3ff4d23` |
| --- | --- | --- |
| 1440，初始 | 两侧可见，B 在左，A 在右 | 相同。两侧各自持有目标与终端画面 |
| 1184 | 224 的侧栏之外仍有 960 的工作区，入口和分屏均可用 | 相同。回归断言入口仍可命中，两侧同时可见 |
| 1183 | 只剩一侧，侧栏仍提供分屏入口 | 侧栏保留，工作区只剩 959。分屏入口收起，副侧暂停并出现空间不足提示 |
| 700 | 只剩活动侧，已丢失分屏关系 | 标签条可返回主机列表，可取消并排。活动侧继续显示，副侧状态保留 |
| 1440，再次拉宽 | 仍只剩活动侧 | B 回到左侧并标为已暂停，A 回到右侧并保有输入资格 |

- 用 Tab、Shift+Tab、Enter 到达并激活面板按钮。已主动启用逐键输入的一侧再次经历 700 → 1440 时，Flutter 的实际焦点节点保持同一对象。只有选中侧拥有输入资格。
- 恢复后的副侧保留原终端与最后一帧。显式点恢复后，旧观察轮次的完整帧仍被拒绝。原目标的新完整帧到达后才替换旧画面，输入模式仍需主动选择。取消并排、明确切换标签或资料停用后，拉宽不会重开旧分屏。
- 合成适配器只收到两次主动输入，A、B 各 1 字节。窗口变化、旧侧迟到输入和焦点切换后的测试输入均未增加写入。两侧各连接一次，观察网格保持 80×24，终端组件的 `autoResize` 为 `false`。这轮没有采样真实远端 PTY。
- 同一 Widget 用例在原版复现临界假入口和回宽丢失副侧，并触发语义树和 ScrollController 断言。修复版完整 Flutter 套 607 通过、23 跳过、0 失败，analyzer 无问题。[Widget 用例](../validation/flutter/test/host_split_widget_test.dart) · [分屏状态用例](../validation/flutter/test/host_tabs_test.dart) · [验证记录](evidence/desktop-split-resize-20261119/widget-verification.json)

### 同尺寸截图

每对 PNG 来自同一 Widget 用例的直接截帧，像素比为 1。归档去掉 `sBIT` 和 `sRGB` 辅助块，保留原 `IDAT`，未裁切或重采样。逐张核对了宽高和解码后的 RGBA 字节。验证记录同时保留原始 PNG、归档 PNG 和 RGBA 的 SHA-256。[验证记录](evidence/desktop-split-resize-20261119/widget-verification.json) · [归档 SHA-256](evidence/desktop-split-resize-20261119/SHA256SUMS)

| 场景 | 尺寸 | 原版 | 修复版 |
| --- | --- | --- | --- |
| 初始分屏 | 1440×900 | [原版初始分屏](evidence/desktop-split-resize-20261119/before-1440-start.png) | [修复版初始分屏](evidence/desktop-split-resize-20261119/after-1440-start.png) |
| 临界收窄 | 1183×900 | [原版临界入口](evidence/desktop-split-resize-20261119/before-1183-critical.png) | [修复版收纳提示](evidence/desktop-split-resize-20261119/after-1183-critical.png) |
| 窄窗 | 700×900 | [原版窄窗](evidence/desktop-split-resize-20261119/before-700-narrow.png) | [修复版窄窗与取消并排](evidence/desktop-split-resize-20261119/after-700-narrow.png) |
| 再次拉宽 | 1440×900 | [原版仍为单栏](evidence/desktop-split-resize-20261119/before-1440-return.png) | [原位恢复并标为暂停](evidence/desktop-split-resize-20261119/after-1440-return.png) |

### 重跑 Flutter 用例

从含修复提交的仓库根目录执行。将锁定的 Flutter 3.47.9 加入 `PATH`。`--offline` 使用本机 Pub 缓存，首次准备依赖时用 `flutter pub get`。

```sh
flutter --version
run=$(mktemp -d /tmp/herdr-d2.XXXXXX)
mkdir "$run/after-png" "$run/before-png"
python3 validation/flutter/tool/ci.py prepare --destination "$run/after-app"
(
  cd "$run/after-app" &&
    flutter pub get --offline &&
    HERDR_SPLIT_CAPTURE="$run/after-png" flutter test --no-pub --reporter expanded &&
    flutter analyze --no-pub
)

cp -R "$run/after-app" "$run/before-app"
baseline=aecd0d753533ac6019b9ffaa630c2197d9256880
for file in host_catalog_page.dart host_tabs.dart remote_page.dart; do
  git show "$baseline:validation/flutter/lib/$file" > "$run/before-app/lib/$file"
done
(
  cd "$run/before-app" &&
    HERDR_SPLIT_CAPTURE="$run/before-png" flutter test --no-pub \
      test/host_split_widget_test.dart --reporter expanded
)
```

最后一个命令预期退出 1。断言的实际值 `(true, false)` 分别表示原版在 1183 仍有分屏入口、回到 1440 未找回副侧，预期值为 `(false, true)`。归档检查可从仓库根目录执行下列命令。

```sh
(
  cd docs/evidence/desktop-split-resize-20261119 &&
    shasum -a 256 -c SHA256SUMS
)
image=docs/evidence/desktop-split-resize-20261119/after-1440-return.png
ffmpeg -v error -i "$image" -frames:v 1 -pix_fmt rgba -f hash -hash sha256 -
```

最后一行输出与 `widget-verification.json` 中该图的 `rgbaSha256` 比对。

## macOS 真实双回环

同日在 macOS arm64 以普通用户运行两套独立的回环 OpenSSH/herdr，每套使用独立主机公钥、临时设备身份和授权。两个主机指纹均经独立核对，交叉请求、交叉响应和交叉设备 SSH 认证均被拒。两个已认证会话同时存活，每侧仅接受自己的设备连接，并收到准确的 10 字节。运行后两条会话和自建服务均关闭，捕获程序停止，临时授权撤销，临时凭据已移除。

设备私钥来自测试用 `MemoryKeyStore`。配对请求未签名，设备持有证明来自真实 OpenSSH 公钥认证。报告中的 `et` 和 `ts` 是两个回环夹具的标签。此次运行未打开 GUI，平台密钥库、受保护输入和实际组网仍需对应验收。[双回环脚本](../validation/remote-harness/paired_dual_demo.py) · [脱敏报告](evidence/dual-overlay-20261115/macos-two-paired-hosts.json)

本次首跑和独立复验的输出均与已归档报告逐字节一致，SHA-256 为 `141c51f6d543b74332101fe06140b034e45e123ad5c1f44c221925df25d56e01`。本机 herdr 0.9.5 二进制与报告字段及官方 `herdr-macos-aarch64` 资产的 SHA-256 相同，均为 `fb77c2232a05a8035421382c894392f4174e4e38a18e48af3dd0290157c3a7e2`。[官方发布](https://github.com/herdrdev/herdr/releases/tag/v0.9.5) · [官方资产元数据](https://api.github.com/repos/herdrdev/herdr/releases/tags/v0.9.5)

复验使用系统 OpenSSH、`uv` 和 [固定 Python 依赖](../validation/pairing/requirements.txt)。首次准备依赖时省略 `--offline`。以下命令先核对本机可执行文件的 SHA，再运行夹具。

```sh
herdr_bin=$(command -v herdr)
herdr_digest=fb77c2232a05a8035421382c894392f4174e4e38a18e48af3dd0290157c3a7e2
pair_run=$(mktemp -d /tmp/herdr-d2-macos-pair.XXXXXX)
printf '%s  %s\n' "$herdr_digest" "$herdr_bin" | shasum -a 256 -c &&
  uv run --no-project --offline --with-requirements validation/pairing/requirements.txt \
    python validation/remote-harness/paired_dual_demo.py \
      --herdr "$herdr_bin" --output "$pair_run/report.json" &&
  shasum -a 256 "$pair_run/report.json" &&
  cmp "$pair_run/report.json" docs/evidence/dual-overlay-20261115/macos-two-paired-hosts.json
```


## Ubuntu 官方 Flutter 双 SSH 验证

两次作业使用 `67c5263fbbf1a6bd947c940c5f7ceb4bd160b80d`、Ubuntu 24.04 x86_64、Flutter Widget 的 1440×1000 视口和两套真实回环 OpenSSH/herdr。签名器、目录和输入日志使用测试后端。原始 ZIP 与 Actions 摘要、各内部文件 SHA256 已核对。

| 模式 | 两侧服务端收字节 | 两侧 PTY 采样 | 运行与归档 |
| --- | --- | --- | --- |
| stock，只观察 | `[0,0]` | 518／513 次，均保持 119×40 | [作业 44459182939](https://github.com/Luck9Star/herdr-pocket/actions/runs/44459182939/job/135341525126) · [正式工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44459182939/artifacts/14498758741) · [脱敏摘要与 SHA256](evidence/desktop-split-resize-20261119/s06-stock-official.json) |
| guarded，明确启用受保护输入 | `[9,1]` | 558／552 次，均保持 119×40 | [作业 44459280773](https://github.com/Luck9Star/herdr-pocket/actions/runs/44459280773/job/135343613484) · [正式工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44459280773/artifacts/14499861389) · [脱敏摘要与 SHA256](evidence/desktop-split-resize-20261119/s06-guarded-official.json) |

两侧各连一次，使用各自的认证设备身份。相同 pane ID 解析为不同终端，两个面板各自显示并推进观察帧。只有选中侧获得输入资格，切换焦点不会恢复此前的输入模式，迟到输入被拒。服务端按目标核对实际字节。两个远端 PTY 在 50 ms 采样中观察到 0 次尺寸变化。两条观察停止、临时授权撤销、受控进程和密钥清理均通过。

两次均观察到 `OpenSSH_9.6p1 Ubuntu-3ubuntu13.20, OpenSSL 3.0.13 30 Jan 2024`。stock 的 Ubuntu 镜像为 `20261116.133.1`，guarded 为 `20261111.127.1`。两案验证固定 Widget 视口内的真实连接，D2 的收窄和恢复仍由上述独立 Widget 回归覆盖。macOS 原生窗口、两条真实连接中的窗口宽度往返、系统输入法组词、平台密钥库和真实跨网仍待验收。

## 已有 S06 运行范围

| 运行 | 验证范围 |
| --- | --- |
| 2026-11-15 Flutter，Ubuntu，`beee7ca` | 真实 Flutter Widget 引擎，两条真实隔离 SSH/herdr 观察。stock 收到 0/0 字节，guarded 收到 9/1 字节。签名器、目录和输入日志为测试后端。[stock manifest](evidence/design-parity-20261115/flutter-s06-stock-43672254449.json) · [guarded manifest](evidence/design-parity-20261115/flutter-s06-guarded-43672256984.json) |
| 2026-11-15 Tauri，Ubuntu，`042c80f` | 原生 GTK WebView，两条真实隔离 SSH/herdr 观察。stock 收到 0/0 字节，guarded 收到 9/1 字节。身份为进程内测试实现。[stock manifest](evidence/design-parity-20261115/tauri-s06-stock-43676588247.json) · [guarded manifest](evidence/design-parity-20261115/tauri-s06-guarded-43676590579.json) |
| 2026-11-19 macOS 双回环 | 有两套真实配对、独立 OpenSSH 认证、各 10 字节和清理。运行入口是无界面夹具。[脱敏报告](evidence/dual-overlay-20261115/macos-two-paired-hosts.json) |
| 2026-11-19 Flutter D2，`3ff4d23` | Widget 验证窗口阈值、分屏位置、暂停和恢复、键盘焦点及输入隔离，使用合成适配器。[验证记录](evidence/desktop-split-resize-20261119/widget-verification.json) |

历史 S06 的连接、字节和 PTY 采样见[原验收记录](63-design-parity-and-direct-ssh.md#s06-双侧界面与真实回环验收)。macOS 原生窗口需要在同一次运行中验证两条真实连接、窗口来回变化、键盘切换和服务端 PTY 与输入计数。[S06 隔离运行入口](../validation/remote-harness/README-s06-real-ssh.md)
