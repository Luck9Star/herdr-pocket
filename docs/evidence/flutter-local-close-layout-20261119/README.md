# Flutter 普通 SSH 返回布局与跨宽度导航

## 证据来源

- [`screen-before/`](screen-before/) 是主审历史 **after** 采集 `ba03d22374a465d4fd09c10c393cac2a9cc45e5c` 的 15 张原图和当次日志。历史运行目录的 45 个 Flutter 生产文件逐字节匹配基线 `122f82e4ad5640567bacdae886dd8224963cd05c`，两者的 `validation/flutter/lib` 树均为 `c08fca340578a05459a619f60095df274ee93de5`。15 张 PNG 的 SHA-256 均匹配主审历史 after 清单。
- [`screen-after/`](screen-after/) 在本提交的生产源码上重新运行。两批都实际点击连接、断开及“返回首页”，使用 macOS Flutter 3.47.9 widget renderer、1× 像素比、Arial Unicode 和内置图标／终端字体。基线使用组合重音候选终端依赖，本次使用 `ci.py prepare` 默认的参考终端依赖。对照矩形由 widget 测量，PNG SHA-256 用于检验原图完整性。前后各 5 个用例、5 次 Paramiko 密码认证、5 个 PTY。
- 原始 PNG 以宽度和阶段命名。尺寸为 1440×900、980×780、700×900、390×844、320×640，每组包含 `active` 活动终端、`result` 断开反馈、`home` 返回看板。PNG 和 [before OCR](ocr-before.json)、[after OCR](ocr-after.json) 均来自所列采集；OCR 是 macOS Vision 识别结果。Widget 测试核对文案和可点击性，画面范围是 headless Flutter widget renderer。

## 三个关键位置

以下坐标以左上角为原点，依次为 `[x, y, 宽, 高]`。设计稿的桌面宽度见 [普通 SSH 桌面 SVG](../../../design/penpot/direct-ssh-desktop.svg) 中的 `returned-1440`、`returned-980`、`returned-700`。完整预期、实测和偏差见 [geometry.json](geometry.json)。

| 宽度 | 断开反馈卡 | 返回首页按钮 | 返回后首页反馈 before → after |
| ---: | --- | --- | --- |
| 1440 | `[264,76,560,66]` | `[264,452,560,48]` | `[240,100,1184,44]` → `[264,62,560,44]` |
| 980 | `[264,76,560,66]` | `[264,452,560,48]` | `[240,100,724,44]` → `[264,62,560,44]` |
| 700 | `[104,76,556,66]` | `[104,452,556,48]` | `[24,72,652,44]` → `[104,62,556,44]` |
| 390 | `[24,123,342,66]` | `[24,499,342,48]` | `[24,119,342,44]` → `[24,119,342,44]` |
| 320 | `[16,100,288,66]` | `[16,476,288,48]` | `[16,96,288,44]` → `[16,96,288,44]` |

断开反馈卡和返回按钮前后坐标一致。修复后 5 个尺寸的 15 个关键位置偏差均为 0pt，容差为 2pt。1440／980 的侧栏是 224pt。700 的默认侧栏是 64pt，44×44pt 菜单按钮可将其展开到 224pt，再收回到 64pt。实测展开后可从连接方式页接通，点断开并返回，首页反馈可见，普通 SSH 入口可点击。

## 跨宽度和侧栏回归

- [回归前](navigation/bc7903a-widgets.log)在 `bc7903a709a44ae4e73090b7437f62098a5bda11` 复现。700 与 980 开始连接，缩至 390 后点击终端中的看板，无法回到看板。390 开始的用例通过。
- [回归后](navigation/final-widgets.log)三个起始宽度均通过。缩窄后点击看板和网络，再从终端入口返回，含横跨 700 与 960 两个断点的路径。重进使用原页面与终端对象，真实回环合计 [3 次认证与 3 个 PTY](navigation/final-peer.log)。用例还覆盖桌面系统返回和活动桌面 SSH 页退出。
- [相关回归](navigation/related-widgets.log)共 35 项通过、4 项按用例条件跳过。包含 700 展开侧栏后断开返回，以及两个已保存主机的标签仍然保留，展开／收起不改变当前终端和输入焦点。

## 从干净检出复跑

使用 PATH 中的 Flutter 3.47.9。渲染 PNG 需 macOS 上的 `/System/Library/Fonts/Supplemental/Arial Unicode.ttf`。跨宽度导航测试无需该字体。命令从本提交所在仓库的根目录执行，并使用独立临时目录。

```sh
evidence="$PWD/docs/evidence/flutter-local-close-layout-20261119"
work="$(mktemp -d)"
python3 validation/flutter/tool/ci.py prepare --destination "$work/app"
(cd "$work/app" && flutter pub get)
python3 -m venv "$work/venv"
"$work/venv/bin/python" -m pip install 'paramiko==4.0.0'

"$work/venv/bin/python" "$evidence/run-evidence.py" "$work/app" "$work/navigation" --navigation
"$work/venv/bin/python" "$evidence/run-evidence.py" "$work/app" "$work/screen-after"
(cd "$work/app" && flutter test --no-pub test/host_split_widget_test.dart)
(cd "$evidence" && shasum -a 256 -c SHA256SUMS)
```

导航命令应报告 `AUTH=3, PTY=3, PNG=0`。截图命令应报告 `AUTH=5, PTY=5, PNG=15`，并把三处关键位置写入 `widgets.log`。哈希清单校验仓库内的原图、摘要、脚本和日志。
