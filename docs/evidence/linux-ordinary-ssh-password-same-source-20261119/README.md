# Linux 普通 SSH 密码：PR #30 同源证据（2026-11-19）

两份原始 ZIP 来自同一产品源码 `0c3490677d43f345b99c1721968ae9567b7933f1`，未经修改。官方运行和作业均为 completed/success；产物元数据的源码、运行编号及字节数与下表一致。

| 客户端 | 官方运行 / 作业 | Artifact ID | ZIP 字节 | ZIP SHA-256 |
| --- | --- | --- | ---: | --- |
| Flutter | [44547617392 / 135642343507](https://github.com/Luck9Star/herdr-pocket/actions/runs/44547617392/job/135642343507) | 14541273788 | 26648 | `8703ec296604fe78c75e6d49873ce269238c2a1075921538fefea59ef5eb0c5e` |
| Tauri | [44547606686 / 135642303678](https://github.com/Luck9Star/herdr-pocket/actions/runs/44547606686/job/135642303678) | 14539694362 | 43689 | `3c89a0c0ae852490932887b6839724e9f3a309e9ceb6270c22253f1f64ed88a3` |

| 客户端 | `ordinary-terminal.png` SHA-256 | `result.json` SHA-256 |
| --- | --- | --- |
| Flutter | `46af672c5fde0492bc7b8052c2de1cb138433465d76eadcf859f073dcf7baa27` | `2bd26230eec4f4bf57d28ed9c8f028fc617dfba3d32f8275f22556503e69c10a` |
| Tauri | `545a94127bf33e1e033617620eca879bee7f0c8214946bb37e877097c9afc567` | `d302e7f235e4f30d4f73e58bbdbc93e9e75e4999b2f3cc2ece936fdb0df6c8ce` |

核对结果：ZIP 成员 CRC 均通过，成员与独立 OCR 使用的解包文件逐字节一致，PNG 摘要与结果文件一致。独立 OCR 对两张图均报告终端序列及预期回环目标可见。两端服务端账本均为 A/A：首次探测 0 次认证；第二次 1 次认证成功、1 次 PTY、1 次 shell，输入 9 字节、输出 102 字节，最终 `peer_eof`。两次连接均关闭；结果文件列出的进程、监听器、临时凭据及目录等清理项均为真。

范围：受控 Linux 原生窗口与隔离回环 SSH；Flutter 使用测试输入和 Xvfb 像素，Tauri 使用原生 WebKitGTK WebDriver 视口。不是物理设备、物理输入法或真实跨网验证。这是新「本机已断开」结果文案发布之前的验收，不能抵充新产品的结果卡与返回首页验收。
