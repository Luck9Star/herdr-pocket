# 首批空首页与接入选择

产品变更覆盖默认空首页 `home` 和连接方式 `choose`。冻结设计为 `79deef0e9c03425f368966e32ff1f1d399a3ac02`。两壳用各自修复前的产品提交取同尺寸画面。Flutter 基线为 `7847b3438848202d25d06f6ad3daeafb0036eb97`，修后为 `af408c398eecdf0d3c5a870687383b603982c6b1`。Tauri 基线为 `7fd481f0c99819170963414497be6ae1f00f99c5`，UI 提交为 `57744fec10ed69e8b7b31de6774ee79762e9968f`，修后证据含 `2043d76a0019a96ecb50a40d657385f7c1cfec0b` 的安全区接入。

采用 390×844（47/34 pt）与 320×640（24/24 pt），DPR 1。Flutter 用 3.47.9 Widget 引擎注入安全区和字体运行产品页面。Tauri 用 Playwright 1.62.1 驱动 WebKit 26.5，由 IPC 夹具和 CSS 注入提供测量环境。本批首页和选择仅验证入口操作。回环 SSH 与 Tauri 模拟传输过程见[前测报告](../baseline/README.md)。

两壳在常规字号下实际点击添加、直达普通 SSH、选择普通 SSH 与 herdr 接入。修后返回操作可回到看板。字形由截图目视核对。Flutter 原版添加进入设备配对，表中两张配对图保留实际去向，该版本没有选择页。每个视口状态的两个系统外框由夹具模拟，未计入应用锚点结果。

| 壳 | 视口 | 状态 | 修前达标 / 超差 / 缺少 | 修后达标 / 超差 / 缺少 | 修后最大偏差 | 修前图片 | 修后图片 |
| --- | ---: | --- | ---: | ---: | ---: | --- | --- |
| Flutter | 390 | `home` | 0 / 7 / 2 | 9 / 0 / 0 | 2 pt | [修前](screens/flutter-before-home-390.png) | [修后](screens/flutter-after-home-390.png) |
| Flutter | 390 | `choose` | 0 / 0 / 4 | 4 / 0 / 0 | 0.5 pt | [旧添加动作实际进入配对](screens/flutter-before-pairing-390.png) | [修后](screens/flutter-after-choose-390.png) |
| Flutter | 320 | `home` | 0 / 7 / 2 | 9 / 0 / 0 | 2 pt | [修前](screens/flutter-before-home-320.png) | [修后](screens/flutter-after-home-320.png) |
| Flutter | 320 | `choose` | 0 / 0 / 4 | 4 / 0 / 0 | 0.5 pt | [旧添加动作实际进入配对](screens/flutter-before-pairing-320.png) | [修后](screens/flutter-after-choose-320.png) |
| Tauri | 390 | `home` | 0 / 8 / 1 | 9 / 0 / 0 | 0 pt | [修前](screens/tauri-before-home-390.png) | [修后](screens/tauri-after-home-390.png) |
| Tauri | 390 | `choose` | 0 / 2 / 2 | 4 / 0 / 0 | 1 pt | [修前](screens/tauri-before-choose-390.png) | [修后](screens/tauri-after-choose-390.png) |
| Tauri | 320 | `home` | 0 / 8 / 1 | 9 / 0 / 0 | 0 pt | [修前](screens/tauri-before-home-320.png) | [修后](screens/tauri-after-home-320.png) |
| Tauri | 320 | `choose` | 0 / 2 / 2 | 4 / 0 / 0 | 1 pt | [修前](screens/tauri-before-choose-320.png) | [修后](screens/tauri-after-choose-320.png) |

[差值、中心命中与源几何摘要](matrix.json) · [图片尺寸与来源 SHA256](screens.json)。几何摘要保留计算所用源 JSON 的 SHA256。逐锚数据用画板锚点统一命名，和源探针输出的文件结构有区别。PNG 保留原像素数据，移除 EXIF 和文本元数据。图片清单分别记录源与归档 SHA256。画板未重复收录，可由[冻结生成源](../../../penpot/direct-ssh-mobile.mjs)生成。

Flutter 另以 320×640、200% 字号观察[首页](screens/flutter-after-home-320-200.png)、[选择页](screens/flutter-after-choose-320-200.png)与[滚动后的选择页](screens/flutter-after-choose-320-200-scrolled.png)。两张选择卡中心可命中，普通 SSH 路径完成实点。该首页静态帧的直达按钮中心未命中，未将其算为高字号通过。另有既有下游配对页 Column 底部溢出 4 pt，属于独立待修。高字号观察和配对页诊断均未计入上述 52 项。

Tauri 安全区桥使用所属窗口与当前 WebView 布局，保留已消费后的合法零值。浏览器验证了 CSS 环境值、仅原生结果、合法零、回退、横屏及 Android 隔离分支。原生 iOS SDK 编译和系统画面的结论应来自对应设备作业。

主审另用同一 Flutter 修后源码执行 `validation/flutter/tool/direct_ssh_fixture_runner.py`，两组分别通过 32 项和 2 项。受控回环服务端独立核对密码认证、PTY 与输入、换钥拒绝停在认证前、加密私钥认证。此项适用于本地 Widget 加受控真实回环，原生设备及加密私钥与轮换的组合仍需单独验证。源记录 SHA256 为 `01c32dbc996a3d2fd8de9bd7af0a5f40c8800c715add9b3eef411c7ae1e9185e`。

[15 状态前测](../baseline/README.md)继续记录其余 13 个状态的未达标锚点和待修状态。
