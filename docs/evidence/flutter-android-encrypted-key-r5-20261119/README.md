# Flutter Android 加密私钥 R5 证据

2026-11-19，[运行 44479715559，作业 135408718366](https://github.com/Luck9Star/herdr-pocket/actions/runs/44479715559/job/135408718366)使用提交 `36a9228df84e344ff9f9f4b4e2fecd92dd177246`，在受控 Android API 35 x86_64 模拟器上完成独立的加密 OpenSSH Ed25519 私钥用例。它与普通密码及主机换钥案例是不同运行，不能据此宣称 R5 同时重跑了换钥。

[原始 Actions ZIP，工件 14508621605](https://github.com/Luck9Star/herdr-pocket/actions/runs/44479715559/artifacts/14508621605) 的 API `digest` 和本地下载 SHA256 均为 `b796cc238e1775384c836242d3212ec8d03c1d024267a43462fcaf3bd178199f`；ZIP 内 11 项 CRC 均通过。原始工件由 GitHub 管理保留期限。这里保留原始 [result.json](result.json)、[双图 OCR 结果](ordinary-screen-proof.json)，以及通过公开截图门禁的 [Flutter 图](connected.png)和 [设备原图](connected-device.png)。原图均为 1080×2340 RGBA，PNG 仅有 sRGB 元数据，画面是公开合成词及临时回环目标；未保存私钥或口令画面。两图字节与 ZIP 原图一致，未裁剪或重新编码。校验值见 [SHA256SUMS](SHA256SUMS)。

[结果](result.json)显示从首页进入并显式确认指纹；检查点 `review` 和错误口令后的 `rejected` 均只有第 1 条探测连接，认证、PTY、shell 和输入计数均为 0，该连接已关闭。随后第 2 条连接使用临时公钥成功认证一次，PTY 和 shell 请求各一次；服务端收到 9 字节输入、输出 102 字节，确认回显标记并在驱动退出前关闭会话。设备结果同时记录遮罩口令、错误口令本地拒绝、真实终端、正常文本输入提交、点击断开及凭据、剪贴板和私有输入清空。普通终端两张原图均由 Tesseract 5.3.4 在首次尝试确认标记与合成词序列；图片哈希与 OCR 结果一致。截图证明终端可见内容，认证计数来自独立服务端记录。

`reverse`、应用包、专属 forward、fixture、临时密钥和 Flutter 工具进程的清理状态均为真；前三项另有 `verified` 检查。`physicalImeVerified=false`：测试使用 Flutter 测试文本输入，不代表物理键盘或系统中文输入法已验证；亦未验证实体设备、跨网或五平台。

## 前四次尝试

| 批次 | 源码与作业 | 可证明的停点 |
| --- | --- | --- |
| R1 | `77657d8f6529b81c01f2bb1a56e07e4cbf54339b` · [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44464721538/job/135359634901) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44464721538/artifacts/14501787227) | 错口令前后零认证；正确密钥已有一次认证、PTY 和 shell，欢迎输出 24 字节，但终端输入为 0，失败阶段记为 `encrypted_connect`。当时此阶段还包含后续终端动作，不能据此定位确切断言。 |
| R2 | `97e4566555c8ebdfe66a6805b6bde00d6c42090d` · [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44469065783/job/135373829103) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44469065783/artifacts/14505030853) | `await_driver_exit` 超时，零 SSH 连接和公开检查点；reverse、应用包、forward 三项清理未证明。旧日志无法区分构建、安装或测试启动卡点。 |
| R3 | `78ee06e1e4fc7022ac2ed72ce13f14aa867f7a95` · [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44474314090/job/135391043281) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44474314090/artifacts/14506541079) | 预构建、设备、私有凭据交付、指纹核验和错误口令拒绝完成；第二次连接阶段失败，仅有第 1 条零认证探测连接，清理通过。 |
| R4 | `6e90feda20031f23cb5d006b0df594db23c244db` · [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44477132258/job/135400294950) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44477132258/artifacts/14506802812) | 第二次连接控件 `enabled=true`、`hit=true`，最终 `unstable`；仅一条零认证探测连接，清理通过。受控 Widget 红测显示 0.3 pt 连续位移即可使旧的矩形严格相等门槛超时，但不能反推出 R4 实机位移来源。 |

R5 在测试驱动中仅对第二次连接采用跨两帧相同屏幕点命中同一启用按钮、点前再次核对后单击；并未改变产品认证逻辑。相对 `2bd6dc83ce3e40a6ac34232078f3214163c04bba`，源码差异为 Flutter Android 工作流、两份 integration 入口/步骤、一份 Widget 测试及 Android 远程驱动与其测试，未改产品 `lib`、iOS 专属文件或 Tauri；共用步骤文件也被 iOS 导入，但新点击路径仅由此 Android 加密单案启用，R5 不构成 iOS 复验。原有服务器计数、OCR、断开及清理门槛仍适用。
