# Flutter R23 认证锚点补测

2026-11-19，Flutter 在产品提交 `26d8abfcd25d78fa22d5ead31e58bc39cb6e34ca` 上补量原 R23 缺失的 18 项，两档各 9 项。原 R23 的 140 项与本次 18 项合计覆盖 158 项，属于不同采样，原始几何与图片保留不变。原 R23 README 在本次补测前的 SHA256 为 `4c248efaafcc02f49d0920f4a5b64a6773648c6ee629a3f0defd1f0a2764e56c`，原版本可从 Git 历史复核；为反映本次索引更新，原校验表仅调整 README 项。冻结画板仍为 `79deef0e9c03425f368966e32ff1f1d399a3ac02`，设计几何 SHA256 为 `7577391ebeb70e1c50a388a478dacd4eb2834b1b1cee248361860c7ef3bec848`。

[逐项矩形与中心命中](anchors.json)记录原始矩形、设计期望值和差值，18 项最大单分量偏差为 0 pt。按照原 R23 口径，Flutter AppBar 原始矩形包含顶部安全区，比较时扣除安全区；提示和页头属于非交互几何，不能将中心命中解释为可操作按钮。保旧和重探的返回按钮均为 44×44 pt 且中心命中。两档视口分别为 320×640、安全区上／下 24／24 pt，以及 390×844、安全区 47／34 pt，DPR 1，字体缩放 1。Flutter Widget 使用 SFNS、中文回退 PingFangSC 和等宽 ProbeNerd；[字体哈希](font-hashes.txt)用于识别输入，字体本身不随证据分发。

| 状态 | 320×640 | 390×844 |
| --- | --- | --- |
| 首次核对 | [截图](screens/flutter-before-320-trust.png) | [截图](screens/flutter-before-390-trust.png) |
| 密码认证 | [截图](screens/flutter-before-320-password.png) | [截图](screens/flutter-before-390-password.png) |
| 私钥认证 | [截图](screens/flutter-before-320-private-key.png) | [截图](screens/flutter-before-390-private-key.png) |
| 换钥阻断 | [截图](screens/flutter-before-320-key-changed.png) | [截图](screens/flutter-before-390-key-changed.png) |
| 保留旧信任 | [截图](screens/flutter-before-320-previous-trust.png) | [截图](screens/flutter-before-390-previous-trust.png) |
| 显式重探 | [截图](screens/flutter-before-320-recheck.png) | [截图](screens/flutter-before-390-recheck.png) |

截图来自正常入口和独立本地 SSH 回环，地址、账号与指纹均为一次性合成公开值；密码、私钥及口令字段为空，或已在换钥阻断时清空。320 pt 私钥截图的底部提示仅部分露出，不作为整页可读性证据。[截图清单](screens.json)保存源图与归档图各自 SHA256 和解码像素 SHA256；归档去除 PNG 文本及 EXIF 元数据，逐图校验解码像素、色彩模式和尺寸与源图相同。原始截图采样与 [4 份原始矩形数据](visual-before-320.json)同次；[换钥 320](rotation-before-320.json)、[首次核对 390](visual-before-390.json)、[换钥 390](rotation-before-390.json)分别保存其他数据。

独立回环先确认旧指纹，再触发服务端换钥，验证连接被阻断、取消保留旧信任及显式重探后显示新指纹。定向测试提交 `e69d92bcd7dc8b3b37a3c2410fa51faa8487139c` 的[两尺寸复跑日志](persistent-verified.txt)通过，并断言换钥期间没有认证或 PTY；该次复跑与上表原截图为两次独立运行。

从本目录运行 `shasum -a 256 -c SHA256SUMS`。复跑需按 [docs/72](../../../72-mobile-ssh-auth-snapshot.md)准备隔离 Flutter 工程，并提供安装 Paramiko 的 Python 和上述字体目录；将下列路径替换为本机实际位置：

```sh
HERDR_FIXTURE_PYTHON=/path/to/fixture-python \
HERDR_AUTH_ANCHOR_FONT_DIR=/path/to/fonts \
flutter test --no-pub test/direct_ssh_auth_anchors_test.dart --reporter expanded
```

未设置夹具或字体变量时测试会跳过，不能计为通过。结果属于 Widget 和本机回环证据，不代表原生键盘、实体设备或外部网络验证。
