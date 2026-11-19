# Flutter 桌面普通 SSH 活动会话

## 三宽实测

基线 `ed01711a7aceff878a314c35e8fa7db85fe40f19` 的真实桌面活动页能接通并主动断开，活动页没有桌面侧栏入口。基线保存三张实际可到达的终端原图。修复后保存三宽各四张图，覆盖活动终端、活动看板、活动网络和活动设置。 [基线原图](before/) · [修复原图](after/)

| 客户区 | 侧栏默认 | 终端旧矩形 | 终端新矩形 |
| --- | ---: | --- | --- |
| 1440×900 | 224pt | `[0,120,1440,740]` | `[264,120,1136,764]` |
| 980×780 | 224pt | `[0,120,980,620]` | `[264,120,676,644]` |
| 700×900 | 64pt | `[0,120,700,740]` | `[104,120,556,764]` |

坐标依次为 `[x,y,宽,高]`。实际量测覆盖冻结四状态的 126 个锚点，最大偏差 2pt，来自空看板卡内两个按钮的边框偏差。滚动轨矩形从实际 `RawScrollbar` 的渲染矩形、厚度和 padding 推导，滑块长度随真实回滚行数变化。 [逐点记录](geometry.json) · [冻结 SVG 生成源](../../../design/penpot/direct-ssh-desktop.mjs)

## 会话和页面行为

- 三个尺寸各真实发起一次认证、打开一个 PTY、收到一次 stdin EOF。测试在真实回环输出中滚动后点击看板、网络、设置，逐次回到原终端，核对同一终端对象、滚动位置和输入焦点。整个测试每个连接只收到返回后手动键入的一个 `Q`，并在终端读到回显。实际点击断开并返回看板，均看到“本机已断开”。 [Widget 运行日志](after/widgets.log) · [SSH 对端日志](after/peer.log)
- 测试还点开网络新增并取消、保存终端字号及进入真实配置迁移。700pt 可在 64pt 与 224pt 间切换。真实保存的主机名称可在展开栏读到，在线标签仍绑定原会话。设置里的系统返回回到原终端，桌面活动终端保持到显式断开。
- 目录和网络 Widget 用例 20 项通过，覆盖失败后重新读取、旧读取晚到、成功恢复已存网络，以及跨宽度保持编辑稿。涉及 SSH、跨宽与受影响 320／390 手机控件的相关回归共 47 项通过，4 项按条件跳过。 [目录与网络日志](checks/catalog-widget.log) · [相关回归日志](checks/responsive-widget.log)

量测在 macOS 主机上使用 Flutter 3.47.9 headless widget renderer、1× 比例、Arial Unicode／内置终端字体，桌面画面用 Linux Widget 平台。SSH 走实际 Paramiko 回环。Native macOS／Linux／Windows 窗口、原生系统辅助功能树及手机真机另行验证。

## 从干净检出复跑

从仓库根目录使用 Flutter 3.47.9、Node ≥20 和 macOS Arial Unicode 字体。

```sh
evidence="$PWD/docs/evidence/flutter-ordinary-live-layout-20261120"
work="$(mktemp -d)"
python3 validation/flutter/tool/ci.py prepare --destination "$work/app"
(cd "$work/app" && flutter pub get)
node design/penpot/direct-ssh-desktop.mjs "$work/desktop.svg" "$work/design"
python3 -m venv "$work/venv"
"$work/venv/bin/python" -m pip install 'paramiko==4.0.0'
"$work/venv/bin/python" "$evidence/run-evidence.py" "$work/app" "$work/design/geometry.json" "$work/pixels" --verify
(cd "$evidence" && shasum -a 256 -c SHA256SUMS)
```

应报告 `AUTH=3, PTY=3, EOF=3, INPUT=3, PNG=12`。对基线使用该脚本时省略 `--verify`，输出三张活动终端图。
