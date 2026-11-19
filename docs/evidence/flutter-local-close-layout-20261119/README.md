# Flutter 普通 SSH 断开后返回首页：桌面布局证据

## 范围与来源

- 基线：`122f82e4ad5640567bacdae886dd8224963cd05c`。
- 设计：`design/penpot/direct-ssh-desktop.svg` 中 `returned-1440`、`returned-980`、`returned-700`。
- `screen-before/` 原样复制自主审目录 `/tmp/herdr-ssh-retire-parent.plLqcjpR/screen-before`，不是本批重新生成；`geometry-parent-before.json` 是主审原始几何结果。
- `screen-after/` 由本批候选源码在 `/tmp/herdr-returned-dashboard-r20/flutter-device` 中生成。两阶段均使用 macOS Flutter 3.47.9 widget renderer、逻辑像素比例 1、真实 Paramiko loopback SSH，并通过 widget 点击断开和返回首页；没有使用假页面、假 state 截图或修改主审 QA 档案。
- 本批 after 运行还执行了新增几何和导航断言，结果为 `17 passed, 2 skipped`；见 `screen-after/widgets.log`。

## 复现命令

```sh
cd /tmp/herdr-returned-dashboard-r20
/tmp/herdr-flutter-ordinary-venv/bin/python runner.py
```

该 runner 启动主审的 `direct_ssh_fixture.py`，设置 `HERDR_DIRECT_SSH_FIXTURE_PORT` 和 `HERDR_OUTCOME_PIXELS`，然后运行：

```sh
/Users/yangyitian/flutter-3.47.9/bin/flutter test --no-pub --reporter expanded \
  test/parent_real_ssh_pixels_test.dart \
  test/direct_ssh_desktop_return_test.dart \
  test/direct_ssh_return_widget_test.dart
```

## 几何结果

`geometry.json` 同时记录 before/after。after 的三个必闭锚点均达到 0pt 偏差：

| 宽度 | `home-ssh-closed` before | `home-ssh-closed` after / 目标 |
| --- | --- | --- |
| 1440 | `[240,100,1184,44]` | `[264,62,560,44]` |
| 980 | `[240,100,724,44]` | `[264,62,560,44]` |
| 700 | `[24,72,652,44]` | `[104,62,556,44]` |

after 空主机卡也均为 0pt 偏差：1440/980 为 `[264,122,560,268]`，700 为 `[104,122,556,268]`。侧栏实测 1440/980 为 224px，700 为 64px。`direct_ssh_desktop_return_test.dart` 另外断言标题 y=16、内部按钮 y=266/326，并实际点击看板/终端/网络/设置导航。

## 文件

- `screen-before/`、`screen-after/`：1440、980、700、390、320 的 active/result/home 原始 PNG，以及 widget/SSH fixture 日志。
- `ocr-before.json`、`ocr-after.json`：macOS Vision 对三种桌面宽度 home 原图的 OCR 结果。after 均识别到“看板”“本机已断开”“添加主机”“普通 SSH 终端”等核心文案；窄侧栏图标没有强行伪造文字 OCR。
- `geometry.json`：本批 before/after 对照和通过状态。
- `geometry-parent-before.json`：主审原始几何档案，保留用于追溯。
- `SHA256SUMS`：本目录全部证据文件的 SHA-256（不含清单自身）。
