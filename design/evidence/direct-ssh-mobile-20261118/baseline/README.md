# 15 状态产品前测

产品提交 `cdbb41ac5878ff93a88cbf0fcdb5088f9dc0473b`，集成基线 `f378e9a08085eb67487ce66aa339af58edac5016`。固定设计提交 `79deef0e9c03425f368966e32ff1f1d399a3ac02`。设计总览 SHA256 为 `f8931a5a7d5a93adb7a8dab622f68309a15901a900b3c07d8a9560786616bfab`，生成坐标 SHA256 为 `7577391ebeb70e1c50a388a478dacd4eb2834b1b1cee248361860c7ef3bec848`。坐标和画板可由[冻结生成源](../../../penpot/direct-ssh-mobile.mjs)重建。

两个引擎均为 390×844、DPR 1、模拟安全区上 47 / 下 34 pt。Flutter 3.47.9 Widget 引擎运行原产品组件，用独立回环 SSH 夹具测连接、核验、换钥、回显及断开。Tauri 为 WebKit 中的原产品 DOM、样式及 xterm，CSS 注入安全区，原生 IPC 由夹具提供。两壳键盘相关组使用模拟 Keyboard/VisualViewport inset，未取系统键盘图。被固定导航挡住的锚点按记录的截图滚动位置判定。

表中「可比」含能逐矩形比较的应用锚点。「缺少」含未测或没有同类结构。「系统模拟」只记录模拟区域。阈值按 x、y、宽、高各自的绝对偏差不超过 2 pt。

| 画板 | Flutter 可比（达标 / 超差） | Flutter 缺少 | Flutter 系统模拟 | Tauri 可比（达标 / 超差） | Tauri 缺少 | Tauri 系统模拟 | 逐锚记录 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `home` | 7（0 / 7） | 2 | 2 | 8（0 / 8） | 1 | 2 | [首页到返回](home-to-return.json) |
| `choose` | 0（0 / 0） | 4 | 2 | 2（0 / 2） | 2 | 2 | [首页到返回](home-to-return.json) |
| `target` | 6（1 / 5） | 0 | 2 | 4（0 / 4） | 2 | 2 | [首页到返回](home-to-return.json) |
| `target-focused` | 6（1 / 5） | 0 | 2 | 4（0 / 4） | 2 | 2 | [认证及终端](ssh-extended.json) |
| `trust` | 2（0 / 2） | 6 | 2 | 1（0 / 1） | 7 | 2 | [首页到返回](home-to-return.json) |
| `password` | 3（0 / 3） | 5 | 2 | 2（0 / 2） | 6 | 2 | [认证及终端](ssh-extended.json) |
| `private-key` | 5（0 / 5） | 5 | 2 | 3（0 / 3） | 7 | 2 | [认证及终端](ssh-extended.json) |
| `terminal-open` | 11（1 / 10） | 2 | 2 | 11（0 / 11） | 2 | 2 | [认证及终端](ssh-extended.json) |
| `terminal-closed` | 11（1 / 10） | 7 | 2 | 16（0 / 16） | 2 | 2 | [认证及终端](ssh-extended.json) |
| `settings-active` | 0（0 / 0） | 11 | 2 | 8（0 / 8） | 3 | 2 | [认证及终端](ssh-extended.json) |
| `disconnected` | 7（1 / 6） | 1 | 2 | 4（0 / 4） | 4 | 2 | [首页到返回](home-to-return.json) |
| `returned` | 7（0 / 7） | 3 | 2 | 8（0 / 8） | 2 | 2 | [首页到返回](home-to-return.json) |
| `key-changed` | 6（0 / 6） | 2 | 2 | 6（0 / 6） | 2 | 2 | [认证及终端](ssh-extended.json) |
| `previous-trust` | 7（1 / 6） | 0 | 2 | 4（0 / 4） | 3 | 2 | [认证及终端](ssh-extended.json) |
| `recheck-trust` | 2（0 / 2） | 6 | 2 | 1（0 / 1） | 7 | 2 | [认证及终端](ssh-extended.json) |
| 合计 | 80（6 / 74） | 54 | 30 | 82（0 / 82） | 52 | 30 | 328 项 |

可比应用锚点 162 项，6 项在阈值内、156 项超出阈值。另有 106 项缺少、60 项系统模拟。两份 JSON 保留原矩阵字节，字段包含状态、壳、锚点、目标与实际矩形、差值、中心命中与测量说明。原文件 SHA256 可由[归档校验和](../SHA256SUMS)复核。

普通 SSH 与 herdr 接入在原产品中均可达。Flutter 原添加动作一步进入设备配对，Tauri 原选择页仍用同排按钮。两壳的目标字段堆叠，首次核验和认证沿用弹窗或同页布局。模拟键盘展开时，两壳均有锚点超差。Tauri 设置往返保持同一会话，画面缺活动会话提示。Flutter 活动页未提供设置往返。完整状态与缺失项见上表所链接矩阵。

[首批对照](../first-batch/README.md)更新 `home` 和 `choose`。其余 13 张画板的差异和缺项仍待修复与复验。
