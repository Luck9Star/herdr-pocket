# 手机配置导入影响预览

2026-11-20，在 390×844 的手机视口复核「设置 → 配置导入 → 解密并预览 → 逐条选择」。选中「替换」后，预览应指出所选冲突会影响的连接或工作台标签。新增、保留和未选条目不应带入其他标签。两端只验证到预览，观察是否发生配置写入或发送终端输入。M1-05 的系统文件提供方、在用连接实际停止、自动重试停止和真机仍待逐端验证。 [路线图](../../04-roadmap.md) · [历史 macOS 系统选择器实测](../../18-mobile-network-profiles.md)

## 来源与原图

原图的基线均为 `8a38ada164fbaa631a61cc1c78cfb849222ff61f`。Tauri 原图候选为 `c7cfd0c1060bbd9ff2c88d2640351078a0a46122`，Flutter 为 `bf84aebf535daab7860747acc482b43165617044`（从 `fc30c02` 经 `e8874c7` 修订）。组合提交 `4c3bf8f00770b8bca33d035d9dc25a675578ae48` 来自 #46 后主线 `794220e`，它的 Tauri 前端及测试、Flutter 产品 Dart 和本项 Widget 测试与各自候选一致。原图按各自原始来源记录。

| 层级 | 同状态画面 | 改前 | 改后 |
| --- | --- | --- | --- |
| Flutter Widget / 390×844 | A 选替换，B 未选，未勾确认。滚到影响预览。 | [基线溢出原图](flutter/before/a-replace.png) | [完整替换动作和受影响标签](flutter/after/a-replace.png) |
| Flutter Widget / 320×740 | 同样选 A 替换。滚到已选下拉项，核对文字和箭头。 | [控件溢出原图](flutter/320x740/before/a-replace-control.png) | [完整文案和箭头](flutter/320x740/after/a-replace-control.png) |
| Tauri 前端 / WebKit | Alpha 选替换，Beta 选新增。在相同视口滚到影响区。 | [笼统关闭提醒](tauri/before-webkit-390x844/shots/alpha-replace.png) | [活动连接和两个受影响标签](tauri/after-webkit-390x844/shots/alpha-replace.png) |

Tauri 另有只影响连接的画面。合成原生 IPC 报告 Gamma 有活动连接，工作台没有对应标签。选替换后仍显示将停止 Gamma 的连接，并明确当前没有受影响的工作台标签。 [Gamma 原图](tauri/after-webkit-390x844/shots/native-owner-only.png)

## Flutter Widget 复验

固定 Flutter 3.47.9，以 390×844、DPR 1 渲染正式看板和设置。测试从「加密迁移」入口选择文件，输入口令并运行产品解密，读取真实加密的合成档案。档案交付通过测试通道返回，主机、标签、存储和设备身份使用隔离夹具。系统选择器、在用 SSH 和真机需要各自另验。

基线选 A 或 B 的替换动作时，旧控件在 390×844 均向右溢出 4.5 px，在 320×740 均溢出 75 px。中间版 `e8874c7` 消除了框架溢出异常，390×844 的选中项末尾「留）」仍被裁掉。测宽回归记录长文案占 274.55 px，可用 270 px。最终版把动作缩为「替换全部冲突」，每条冲突说明单独写明停用资料并保留本机身份，或移除未配对资料。

A 选替换时只有 A 的两个标签，A 改为保留时没有受影响标签，B 选替换时只出现 B 的标签。每个尺寸各跑一个基线负例和一个候选用例。两份基线保留 Flutter 的溢出失败，两份候选通过。候选各三次滚动后点中下拉箭头和选项，选中项文字及箭头全部可见。审核期间主机资料写入和设备签名均为 0。 [390×844 原始测量](flutter/comparison.json) · [320×740 原始测量](flutter/comparison-320x740.json)

从仓库根目录运行。使用已安装依赖的 Flutter 3.47.9 工程缓存和 Python 3.12 或以上。原图使用 macOS Arial Unicode 与固定 Flutter SDK 的 MaterialIcons。字体和 SDK 摘要见报告。

```sh
repo=$(git rev-parse --show-toplevel)
lab=$(mktemp -d)
python3 "$repo/docs/evidence/config-import-impact-20261120/flutter/run_capture.py" \
  --repo "$repo" \
  --before 8a38ada164fbaa631a61cc1c78cfb849222ff61f \
  --after 4c3bf8f00770b8bca33d035d9dc25a675578ae48 \
  --sdk "${HERDR_FLUTTER_SDK:?请指定 Flutter 3.47.9 安装目录}" \
  --font "/System/Library/Fonts/Supplemental/Arial Unicode.ttf" \
  --output "$lab/flutter"
```

脚本会复测三个选项状态并在临时目录生成原图。复测较窄视口时加 `--width 320 --height 740` 并使用新输出目录。仓库保留 390×844 的影响区和 320×740 的下拉控件各一对原图，其他状态的测量与图像摘要保留在报告。 [生成脚本](flutter/run_capture.py) · [Widget 捕获测试](flutter/capture_test.dart)

## Tauri 浏览器复验

Playwright 1.62.1 用 WebKit 26.5 和 Chromium 151.0.7922.34 加载正式 Tauri 前端。测试从看板建立合成标签，打开设置中的配置迁移入口，选择合成文件并预览。文件读取、预览返回和工作台连接状态由合成 IPC 提供。这个层级覆盖浏览器触点和布局、标签与原生层连接摘要的呈现。系统选择器、真实解密、真实 SSH、移动 WebView 和真机需要各自另验。

每个引擎在改前和改后各执行 8 次触点点击，均命中应选单选项并选中。每组四个影响区状态均可滚动到达，没有确认应用或发送终端输入。改后按 Alpha 替换、Beta 替换、只替换 Gamma 和保留／新增分别断言；四个状态中记录的 16 个文本行全部可见，页面、预览和影响区的横向溢出均为 0。另有定向 Node 测试分别覆盖旧的单一活动主机字段和新的活动主机列表。 [四组测量和原报告](tauri/summary-390x844.json) · [原始浏览器探针](tauri/mobile-probe.mjs)

从仓库根目录在临时目录构建两个版本。以下使用组合提交作为候选；复跑原始 Tauri 对照时，可把候选改为上面的 `c7cfd0c` 全 SHA。使用 Node 22.12 或以上版本以及 Playwright 支持的系统。

```sh
repo=$(git rev-parse --show-toplevel)
lab=$(mktemp -d)
cp "$repo/docs/evidence/config-import-impact-20261120/tauri/mobile-probe.mjs" "$lab/"
npm install --prefix "$lab" --no-package-lock --ignore-scripts --no-save playwright@1.62.1
"$lab/node_modules/.bin/playwright" install chromium webkit

build_tauri() {
  variant=$1
  commit=$2
  mkdir "$lab/$variant"
  git -C "$repo" archive "$commit" validation/tauri validation/shared validation/vendor |
    tar -x -C "$lab/$variant"
  (
    cd "$lab/$variant/validation/tauri" || exit
    npm ci --ignore-scripts &&
      npm run build -- --outDir "$lab/$variant/site"
  )
}
build_tauri before 8a38ada164fbaa631a61cc1c78cfb849222ff61f || exit
build_tauri after 4c3bf8f00770b8bca33d035d9dc25a675578ae48 || exit
for engine in webkit chromium; do
  for variant in before after; do
    HERDR_D2_BROWSER="$engine" node "$lab/mobile-probe.mjs" "$variant" || exit
  done
done
```

每组会生成 `report.json` 和四张截图。仓库保留代表性的三张 WebKit 原图。从本目录运行 `shasum -a 256 -c SHA256SUMS` 可校验已归档的原图、报告和脚本。 [校验清单](SHA256SUMS)
