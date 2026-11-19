# 桌面分屏窗口变化验收

2026-11-19，Flutter 的 [D2 窄桌面与窗口变化](08-ui-design-plan.md#3-首轮画板与状态清单)在正常主机工作台完成 Widget 回归。收窄时保留活动终端与输入焦点，暂停另一侧。拉宽后恢复原来的左右位置：**因窗口收窄而被暂停、此前仍在实时观察的副侧自动恢复只读观察**，等待同一目标的新完整帧；手动暂停或从未观察的面板不自动恢复。早期版本（`3ff4d23`）拉宽后副侧一律显示旧画面并标为已暂停，须手动恢复，此为历史行为。Ubuntu 官方作业已在 Flutter Widget 中验证两条真实 OpenSSH/herdr 回环的分屏、焦点和输入隔离。macOS 无界面回环也已复验。macOS 原生双连接的分屏与窗口变化在当前环境下未验证。详见[macOS 原生窗口签名限制](#macos-原生窗口签名限制)。

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
- 【历史，`3ff4d23`】恢复后的副侧保留原终端与最后一帧。显式点恢复后，旧观察轮次的完整帧仍被拒绝。原目标的新完整帧到达后才替换旧画面，输入模式仍需主动选择。取消并排、明确切换标签或资料停用后，拉宽不会重开旧分屏。当前版本（`c9410f9`）中拉宽即自动恢复观察资格，迟帧拒绝与输入资格规则不变，见下节。
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

## 回宽自动恢复（`028072e`、`c9410f9`）

同日在同一 Widget 用例上以红绿闭环验证两轮主复核反例。Widget 用例使用**合成适配器**提供观察帧与输入回执；窄宽序列驱动的正是真实 Widget 树与真实分屏状态机。固定 1440 视口的 Ubuntu 官方作业（见下）验证的是固定窗口下的真实远端连接，不能验证窗口拖拽窄宽——真实远端下的窄宽自动恢复目前待 macOS 原生窗口验收（R5 作业 44475250370 的 pairA host 回读失败，未通过）。

- 反例一（红绿）：副侧已手动暂停时，新的窄宽周期不得赋予自动恢复资格；手动恢复入口必须仍可用。旧资格判定（`!viewPaused && live`）在该反例下通过，但反例二暴露缺口。
- 反例二（红绿，先红 `Expected 3, Actual 2`）：副侧收窄→拉宽已自动恢复（`live=false`，等新完整帧）→**不发任何帧**再次收窄→再拉宽。旧判定在第二次收窄时丢失资格，面板永远停留旧画面。`c9410f9` 将资格改为 `!viewPaused && (live || observationEpoch > 0)`：等新帧的已恢复观察保留布局资格；手动暂停（`viewPaused=true`）与从未观察（`observationEpoch==0`）仍无资格。
- 双次来回断言最终拉宽后同一目标自动恢复（`resumes==3`）、零新增远端输入、无重连。迟帧拒绝既有断言覆盖：旧 generation 帧、旧 epoch 完整帧均拒绝，仅新 epoch 帧生效。
- 单用例通过；完整 Flutter 套 **607 通过、23 跳过、0 失败**；独立工程 `flutter analyze --no-pub` 无问题（工程 `lib/`、`test/` 与 `c9410f9` 逐文件一致后运行，[运行摘要](evidence/desktop-split-resize-20261119/r2-c9410f9-widget-run-summary.json)，原始控制台日志因 `*.log` 通配不入库，摘要与原件逐项核对）。`remote_adapter.dart` 的 `resumeObservation` 注释已同步两壳新契约（显式用户动作或布局拉宽其自身暂停的观察）。
- Ubuntu 官方 stock/guarded 作业在 `c9410f9` 复验固定视口真实连接通过，见[下节](#ubuntu-官方-flutter-双-ssh-验证)。

### 回宽两态截图（`c9410f9`）

两张均为 1440×900、像素比 1 的直接截帧，同一用例同一运行先后捕获，未裁切或重采样。

| 场景 | 画面 | SHA-256 |
| --- | --- | --- |
| 拉宽后等待新帧 | 副侧原位恢复、显示暂停前的旧帧，等待新完整帧 | [图](evidence/desktop-split-resize-20261119/r2-c9410f9-restored-waiting.png) `3ea390b7b6f4e7a23e3f81ef4460200fdf32d811c1068b722fec88ef1f3905a4` |
| 新完整帧已到 | 同一目标的新 epoch 帧替换旧画面，恢复只读观察 | [图](evidence/desktop-split-resize-20261119/r2-c9410f9-auto-new-full.png) `8cc554da338919d508479f8b3996fe37de234155bd2e31686ad1803302c02081` |

`3ff4d23` 首轮修前/修后原图与日志已存 [r2-3ff4d23-originals/](evidence/desktop-split-resize-20261119/r2-3ff4d23-originals/)（old 为 `aecd0d7` 基线，new 为 `3ff4d23`），全部哈希见 [SHA256SUMS-r2](evidence/desktop-split-resize-20261119/SHA256SUMS-r2)。

### 重跑回宽自动恢复用例

从 `c9410f9` 仓库根目录执行；依赖固定方式与上文「重跑 Flutter 用例」相同（先 `flutter pub get --offline`）。截图直出依赖用例内 `HERDR_SPLIT_CAPTURE` 钩子；「新完整帧已到」一张需在临时副本的 `expect(bResumed, isNot(same(bTerminal)));` 行后补一行 `await capture('auto-new-full');`（本仓不保留该插桩，永久用例止于状态断言）。

```sh
run2=$(mktemp -d /tmp/herdr-d2-r2.XXXXXX)
python3 validation/flutter/tool/ci.py prepare --destination "$run2/app"
cp -R validation/flutter/lib "$run2/app/lib" && cp -R validation/flutter/test "$run2/app/test"
(
  cd "$run2/app" &&
    flutter pub get --offline &&
    HERDR_SPLIT_CAPTURE="$run2/out" flutter test test/host_split_widget_test.dart --no-pub &&
    flutter analyze --no-pub
)
ls "$run2/out"   # wide / critical / narrow / restored 四帧
```

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


## macOS 原生窗口签名限制

**未验证 — 环境受限。** 2026-11-19 的 Flutter stock 托管 macOS arm64 作业停在第一台主机的设备身份创建阶段，尚未取得公开配对请求，也未到达主机授权、双 SSH 实窗、分屏或窗口变化。上述无界面双回环独立记录。

两次作业均在原生窗口完成第一台主机的公开资料预览、明确填表和逐项回读，覆盖端口、账号、命名会话、连接路径和主机公钥，并核对完整指纹。复核复选框经一次实际点击从未勾选变为已勾选，同一创建按钮随即切换到启用外观。驱动随后执行一次创建操作。[R10 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44494129879/job/135456886644) · [R11 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44498417528/job/135471493490)

| 作业来源 | 创建后的原生观察 | 原始工件 |
| --- | --- | --- |
| R10，`2e38d94e41d3144faebd951b343af7da644e292d` | 到达 `keyA`，同窗找不到「复制当前公开请求」。结果未知。 | [原始 ZIP](evidence/macos-s06-signing-20261119/mac-s06-r10.zip) · [Actions 工件 14514054134](https://github.com/Luck9Star/herdr-pocket/actions/runs/44494129879/artifacts/14514054134) |
| R11，`643ec9d46f82bf3c15f5a8bb79a39fff60eabc70` | 产品报告设备身份创建结果未知，记为 `deviceCreationUnknown`。工件只记录这一阶段，未取得底层 `OSStatus`。本轮专用 AppKit 通道已释放。 | [原始 ZIP](evidence/macos-s06-signing-20261119/mac-s06-r11.zip) · [Actions 工件 14517390000](https://github.com/Luck9Star/herdr-pocket/actions/runs/44498417528/artifacts/14517390000) |

R11 读取了本轮实际构建应用的签名与 entitlement。应用为 ad hoc 签名，未发现团队标识、应用标识、Keychain 访问组、应用组或 provisioning profile。当前构建缺少产品所需的 Data Protection Keychain 签名访问组。产品用 `kSecUseDataProtectionKeychain` 调用 `SecItemAdd`，Apple 规定该钥匙串的访问组由代码签名 entitlement 决定，并由 provisioning profile 授权。[产品密钥存储源码](../validation/pairing/native/apple/DeviceKeys.swift#L20-L38) · [原生错误返回源码](../validation/flutter/native/apple/DeviceKeyChannel.swift#L22-L34) · [Apple TN3137](https://developer.apple.com/documentation/technotes/tn3137-on-mac-keychains)

两份 ZIP 各只含 Actions 脱敏结果 `result.json`。校验后可直接读取原件。[SHA-256 清单](evidence/macos-s06-signing-20261119/SHA256SUMS)

```sh
cd docs/evidence/macos-s06-signing-20261119
shasum -a 256 -c SHA256SUMS
unzip -p mac-s06-r10.zip result.json
unzip -p mac-s06-r11.zip result.json
```

按仅使用现有环境的决定，本轮到此归档。恢复验收需要在正确签名的 macOS 登录环境中运行同一产品的 Data Protection Keychain 路径，随后在同一次原生窗口运行中完成两条真实配对连接、键盘切换、窗口收窄与回宽、服务端 PTY 和输入计数及清理。若扩展环境，签名与钥匙串授权由用户掌控。

## Ubuntu 官方 Flutter 双 SSH 验证

两次作业使用 `67c5263fbbf1a6bd947c940c5f7ceb4bd160b80d`、Ubuntu 24.04 x86_64、Flutter Widget 的 1440×1000 视口和两套真实回环 OpenSSH/herdr。签名器、目录和输入日志使用测试后端。原始 ZIP 与 Actions 摘要、各内部文件 SHA256 已核对。

| 模式 | 两侧服务端收字节 | 两侧 PTY 采样 | 运行与归档 |
| --- | --- | --- | --- |
| stock，只观察 | `[0,0]` | 518／513 次，均保持 119×40 | [作业 44459182939](https://github.com/Luck9Star/herdr-pocket/actions/runs/44459182939/job/135341525126) · [正式工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44459182939/artifacts/14498758741) · [脱敏摘要与 SHA256](evidence/desktop-split-resize-20261119/s06-stock-official.json) |
| guarded，明确启用受保护输入 | `[9,1]` | 558／552 次，均保持 119×40 | [作业 44459280773](https://github.com/Luck9Star/herdr-pocket/actions/runs/44459280773/job/135343613484) · [正式工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44459280773/artifacts/14499861389) · [脱敏摘要与 SHA256](evidence/desktop-split-resize-20261119/s06-guarded-official.json) |

两侧各连一次，使用各自的认证设备身份。相同 pane ID 解析为不同终端，两个面板各自显示并推进观察帧。只有选中侧获得输入资格，切换焦点不会恢复此前的输入模式，迟到输入被拒。服务端按目标核对实际字节。两个远端 PTY 在 50 ms 采样中观察到 0 次尺寸变化。两条观察停止、临时授权撤销、受控进程和密钥清理均通过。

两次均观察到 `OpenSSH_9.6p1 Ubuntu-3ubuntu13.20, OpenSSL 3.0.13 30 Jan 2024`。stock 的 Ubuntu 镜像为 `20261116.133.1`，guarded 为 `20261111.127.1`。两案验证固定 Widget 视口内的真实连接，D2 的收窄和恢复仍由上述独立 Widget 回归覆盖。macOS 原生窗口、两条真实连接中的窗口宽度往返、系统输入法组词、平台密钥库和真实跨网仍待验收。

### `c9410f9` 复验

`c9410f96703041113414b31eb4bf5de98f3bbc57` 上的固定 1440×1000 Widget 视口复验通过，同一套断言与清理检查全部满足。作业产物 ZIP 与其内部 `SHA256SUMS` 均已核对，`sourceSHA` 等于 `c9410f9`。

| 模式 | 两侧服务端收字节 | 两侧 PTY 采样 | 运行与归档 |
| --- | --- | --- | --- |
| stock，只观察 | `[0,0]`，`exactRemoteBytes` 为真 | 帧数 7/10、增量 5/9，`119×40` 保持，0 次尺寸变化 | [作业 44475116460](https://github.com/Luck9Star/herdr-pocket/actions/runs/44475116460/job/135393668921) · ZIP `968a736c6f37e03158d1169c2c5fd6f9a5a026519371b5645a82674707dc26fe` · [脱敏 manifest](evidence/desktop-split-resize-20261119/s06-stock-c941-official.json) |
| guarded，明确启用受保护输入 | `[9,1]`，`exactRemoteBytes` 为真 | 帧数 12/15、增量 10/14，`119×40` 保持，0 次尺寸变化 | [作业 44475148214](https://github.com/Luck9Star/herdr-pocket/actions/runs/44475148214/job/135395559119) · ZIP `d22f63d6d3a8d4ca5d91f3ff0f149417a924dfd705bdbcf2f91fa941015c01b2` · [脱敏 manifest](evidence/desktop-split-resize-20261119/s06-guarded-c941-official.json) |

原始 ZIP 不入库，上列 SHA-256 供比对；两个脱敏 manifest（含 `sourceSHA`、两侧字节、帧计数、PTY 记录与清理结果）已归档并列入 `SHA256SUMS-r2`。

## 已有 S06 运行范围

| 运行 | 验证范围 |
| --- | --- |
| 2026-11-15 Flutter，Ubuntu，`beee7ca` | 真实 Flutter Widget 引擎，两条真实隔离 SSH/herdr 观察。stock 收到 0/0 字节，guarded 收到 9/1 字节。签名器、目录和输入日志为测试后端。[stock manifest](evidence/design-parity-20261115/flutter-s06-stock-43672254449.json) · [guarded manifest](evidence/design-parity-20261115/flutter-s06-guarded-43672256984.json) |
| 2026-11-15 Tauri，Ubuntu，`042c80f` | 原生 GTK WebView，两条真实隔离 SSH/herdr 观察。stock 收到 0/0 字节，guarded 收到 9/1 字节。身份为进程内测试实现。[stock manifest](evidence/design-parity-20261115/tauri-s06-stock-43676588247.json) · [guarded manifest](evidence/design-parity-20261115/tauri-s06-guarded-43676590579.json) |
| 2026-11-19 macOS 双回环 | 有两套真实配对、独立 OpenSSH 认证、各 10 字节和清理。运行入口是无界面夹具。[脱敏报告](evidence/dual-overlay-20261115/macos-two-paired-hosts.json) |
| 2026-11-19 Flutter D2，`3ff4d23` | Widget 验证窗口阈值、分屏位置、暂停和恢复、键盘焦点及输入隔离，使用合成适配器。[验证记录](evidence/desktop-split-resize-20261119/widget-verification.json) |
| 2026-11-19 Flutter D2 回宽自动恢复，`c9410f9` | Widget 红绿验证两轮复核反例：布局暂停的活跃观察拉宽自动恢复、等新帧期间资格保持、手动暂停与从未观察不自动；合成适配器。[运行摘要](evidence/desktop-split-resize-20261119/r2-c9410f9-widget-run-summary.json) |
| 2026-11-19 同源 `c5aa64a` 双端 guarded | 同一提交并行 Flutter Widget 与 Tauri 原生 GTK 两条真实 SSH/herdr 回环：两端 [9,1] 字节、[1,1] 认证、共享 PTY 0 resize、清理全过；Tauri 另含 guarded 直接输入/Esc/窗口往返探针。[证据](evidence/s06-same-source-20261120/README.md) |

历史 S06 的连接、字节和 PTY 采样见[原验收记录](63-design-parity-and-direct-ssh.md#s06-双侧界面与真实回环验收)。macOS 原生窗口需要在同一次运行中验证两条真实连接、窗口来回变化、键盘切换和服务端 PTY 与输入计数。[S06 隔离运行入口](../validation/remote-harness/README-s06-real-ssh.md)

## Flutter 分屏关闭焦点主机

**通过 — Ubuntu 24.04 隔离回环 Widget。** 2026-11-19，R3 stock 在 `2cd636f40b07928d31b1f487c653dbd0dbe4f380` 先从正常首页打开两条真实 SSH/herdr 观察，再关闭焦点 A。B 仍用原连接在同一终端推进画面，未自动启用输入。主动停止 B 后，对端确认两条连接均已关闭，驱动退出后再查一致。两侧各连接 1 次、收到 0/0 字节。[stock 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44517427428/job/135536975870)

同源 guarded 使用隔离受保护输入扩展，两端实际收到 9/1 字节，绑定正确，两视图主动停止并等待本地取消完成。两种模式的 PTY 均保持 119 × 40，观察到 0 次 resize。临时授权、进程和密钥清理均通过。关闭 A 后 B 推进与退出前独立对端关闭确认由 stock 用例覆盖。[guarded 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44518193618/job/135542178535)

R1 未确认最终关闭。R2 云端通过，本机显式等待取消时仍复现 `network_transport_failed`。R3 修正关闭顺序后，本机真实回环连续通过 5/5。归档基线与 R3 的 Flutter 产品树一致，主代理对该共享适配器的 M3-05 独立复跑也通过。此处覆盖固定 Widget 视口和隔离回环，原生窗口、窗口宽度往返、物理输入法及真实网络提供方仍待验证。[两个官方 ZIP、SHA-256 与本机复验](evidence/flutter-desktop-shared-host-close-20261119/README.md)

## Tauri 分屏键盘退出与窗口变化

**Guarded R12 单次通过（Ubuntu 24.04 原生 GTK，两条真实回环 SSH）。** 2026-11-20，原生窗口经历 1440→700→1440，B 三次采样均保留原编辑器和焦点，A 因布局暂停并在回宽后以同一目标的新完整帧恢复只读。可信退出组合键只消费一次。随后通过界面依次关闭 A、B，A 关闭时 B 仍在线。退出驱动前两侧各认证一次、各有合格关闭记录、均无 reset，原 socket 均已消失。首键对端字节为 0／1，最终为 9／1，两个远端 PTY 均无尺寸变化。手动暂停仍由下文 stock R7 独立覆盖，其他平台及手机真机仍需对应验收。[R12 原 ZIP、阶段证据与 SHA-256](evidence/tauri-gtk-guarded-r12-20261120/README.md)

**D1 逐键退出通过（Ubuntu 24.04 原生 GTK，固定宽屏，隔离 SSH/herdr）。** 2026-11-19，guarded R6 在 `c14af9d0bec0a5451318378bf5abaf1c94fd25b9` 上从首页配对两条连接。B 收到明确输入的 1 字节后，真实 WebDriver 键盘按下一次 `Ctrl+Shift+F6`。焦点移到 A 原有的「设为输入焦点」按钮，当前选中的终端保持 B，B 退出逐键输入，两侧均处于只读观察，原目标和连接保留。随后 A 明确发送一次草稿，SSH 对端最终收到 9／1 字节，退出驱动前两条连接均已关闭。guarded R7 在 `5e50a4d` 的固定 1440 × 1200 原生窗口复验通过，六项退出断言、9／1 字节及两条原 SSH 的关闭均独立核对。[guarded R6 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44524014037/job/135562342657) · [原件、六项断言与复核方法](evidence/tauri-gtk-focus-resize-r6-20261119/README.md) · [guarded R7 原件](evidence/tauri-gtk-focus-resize-r7-20261119/README.md#guarded-原生逐键退出) · [guarded R7 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44533705204/job/135596416871)

**D2 逐键期间收窄与回宽通过（WebKit 和 Chromium，受控 IPC）。** 1440 → 700 → 1440 时，B 保留原 xterm 编辑器、DOM 焦点及输入资格。A 因布局暂停，回宽后等待同一目标的新完整帧，再恢复只读观察。手动暂停的 A 在回宽后仍保持暂停。两种浏览器都运行生产前端和 xterm，连接、输入受理与帧由夹具提供。[D2 原图、报告与复跑](evidence/tauri-active-input-split-resize-20261119/README.md) · [D1 浏览器修前后](evidence/tauri-desktop-focus-escape-20261119/README.md)

**D2 stock R7 通过（Ubuntu 24.04 原生 GTK，两条真实回环 SSH，只读观察）。** 窗口与视口同为 1440 × 1200 → 700 × 1200 → 1440 × 1200。收窄仅显示原 B，原 A 暂停。回宽恢复原来的左右位置，A 用同一目标的新完整帧恢复，两侧画面推进。B 一直是应用选中的终端。DOM 焦点采样依次在 B 面板和两次面板外。[stock R7 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44533698168/job/135593449788) · [原件和窗口证据](evidence/tauri-gtk-focus-resize-r7-20261119/README.md#stock-原生窗口与双-ssh)

驱动实际点击「返回主机看板」与「终端」，两侧手动暂停在第二轮窄宽往返中保持，旧画面不推进。显式选中 A 后点击「恢复观察」，仅 A 收到新完整帧，B 继续暂停。两侧各认证一次、各收到零字节，分别在驱动退出前关闭。两个远端 PTY 均保持 119 × 40，采样均未观察到尺寸变化，临时授权、进程与密钥已清理。[R7 门槛和修前／修后原图](evidence/tauri-gtk-focus-resize-r7-20261119/README.md#修前与修后的原图)

R6 在手动离页后能确认两侧暂停，返回时 A 被读为断开，B 仍暂停。受控 IPC 的 Chromium 和 WebKit 复现了过期帧确认误取消原连接。`5e50a4d` 按当前连接和观察周期处理帧确认，迟到结果不影响保留的连接，当前周期的确认失败仍会断开。[R6 断点](evidence/tauri-gtk-focus-resize-r6-20261119/README.md#stock-窗口往返与手动暂停断点) · [R7 修复与复跑](evidence/tauri-gtk-focus-resize-r7-20261119/README.md#修复范围与复跑)

**Guarded R8–R10 均未完成原生 GTK 逐键窗口往返。** R8 停在等待首键到达服务端，缺少独立的逐侧字节记录。R9 在 B 的原编辑器确认可信首键和匹配回执，SSH 对端 A／B 收到 0／1 字节，随后在收窄时失焦。R10 安置了独占 Xvfb 的指针，B 原编辑器收到可信 `keydown`，A／B 对端均收到 0 字节，停在首键阶段，尚未收窄。R10 的窗口焦点保持、原观察恢复与手动暂停由本地 WebKitGTK 组件对照覆盖，连接与输入受理来自隔离 IPC 夹具。[三轮原 ZIP、SHA-256 与组件对照](evidence/tauri-gtk-guarded-r8-r10-20261119/README.md)

**Guarded R11 完成逐键窗口往返，停在对端关闭核验。** 原生 GTK 作业确认 B 的可信首键和回执，SSH 对端 A／B 收到 0／1 字节。按冻结驱动的执行顺序，随后通过了原编辑器保持、A 只读恢复、退出逐键及输入隔离检查。两标签已移除，工作台隐藏，退出驱动前未确认两条原 SSH 均已关闭。R11 工件未留逐侧关闭数据，也未单独落盘窗口往返和组合键样本。[R11 原 ZIP、SHA-256 与断点](evidence/tauri-gtk-guarded-r11-20261119/README.md)
