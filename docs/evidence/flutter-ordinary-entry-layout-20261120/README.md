# Flutter 普通 SSH 桌面入口布局

## 证据范围

- 基线是 `99f73f35793fc8117b61bf2482f38e9fe771173d`。[before](before/) 保存 1440×900、980×780、700×900 三尺寸下选择、目标、目标聚焦、核对、密码、已有私钥原图及量测。实际从看板点“添加主机”，走普通 SSH 入口和 Paramiko 回环探测。两次采集均未点击认证连接，SSH 日志没有账户认证或 PTY。
- [chooser-after](chooser-after/) 保存选择接入方式页的 3 张新原图和本批完整量测日志。冻结 [SVG 生成源](../../../design/penpot/direct-ssh-desktop.mjs) 生成 geometry，比较实际控件矩形。30 个锚点均在 2pt 内，最大偏差 0.5pt。Widget 测试实际点击四个导航目标、返回按钮和三档侧栏展开／收起。默认侧栏为 224／224／64pt，选择卡为 560／560／556pt。
- 量测环境为 macOS Flutter 3.47.9 widget renderer、1× 像素比、Arial Unicode 和内置图标／终端字体。原图来自真实 widget 截图。此处验证接入方式页面和四个可点击的本地导航入口，桌面活动会话入口及终端内容独立验证。

## 复跑

从仓库根目录使用 Flutter 3.47.9、Node ≥20 和 macOS 系统 Arial Unicode 字体。脚本把源码和素材带到独立临时工程。

```sh
evidence="$PWD/docs/evidence/flutter-ordinary-entry-layout-20261120"
work="$(mktemp -d)"
python3 validation/flutter/tool/ci.py prepare --destination "$work/app"
(cd "$work/app" && flutter pub get)
node design/penpot/direct-ssh-desktop.mjs "$work/desktop.svg" "$work/design"
python3 -m venv "$work/venv"
"$work/venv/bin/python" -m pip install 'paramiko==4.0.0'
"$work/venv/bin/python" "$evidence/run-evidence.py" "$work/app" "$work/design/geometry.json" "$work/pixels" --verify choose
(cd "$evidence" && shasum -a 256 -c SHA256SUMS)
```

脚本应报告 `AUTH=0, PTY=0, PNG=18`。选择页锚点以 `ANCHOR choose-` 开头。要只量测已有实现的差距，运行同一脚本并省略 `--verify`。
