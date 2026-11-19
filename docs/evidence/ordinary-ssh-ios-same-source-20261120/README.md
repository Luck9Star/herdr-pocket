# 普通 SSH：同源 iOS 模拟器证据

源码均为 `c5aa64a0c9703d0494f5694ec0028018f7f2a0b8`，证据来自真实应用、iOS 模拟器和隔离 loopback SSH 对端。Flutter 使用 iOS 26.2 / iPhone 11 模拟器，Tauri 使用 iOS 26.2 / iPhone 17 Pro Max 模拟器；不等同物理 iPhone、物理输入法或公网服务器验收。四个 ZIP 是官方脱敏 Actions 工件，不含原始 XCTest / AX 日志。

| 路线和场景 | 结果与交互 | 截图 |
| --- | --- | --- |
| Flutter 普通密码 | 通过；确认指纹后连接，终端正常文字提交和远端回显，键盘开合及看板/网络/设置返回同一终端后断开。 | 终端截图与 OCR；连接前脱敏截图。 |
| Flutter 密码换钥 | 通过；新 key 在认证前拒绝，取消保留旧信任，重新探测并明确确认后连接。 | 新旧指纹审查截图；终端截图与 OCR。 |
| Flutter 加密私钥 | 通过；私钥由粘贴输入，错误口令本地拒绝，正确口令后公钥认证、终端文字提交、远端回显并断开。 | 终端截图与 OCR。 |
| Flutter 加密私钥换钥 | 通过；粘贴私钥，换钥拒绝、取消及重新确认后公钥认证，终端文字提交、回显并断开。 | 新旧指纹审查截图；终端截图与 OCR。 |
| Tauri 普通密码与密码换钥 | 通过；原生点击、输入、指纹确认、真实终端和回环对端闭环。 | 各终端截图与 OCR；换钥审查截图。 |
| Tauri 加密私钥手输 | **未通过**；到口令阶段触发保密门禁，触发节点尚未分类。无认证。 | 本次失败工件只有结果 JSON。 |

Flutter 终端文字提交是模拟器内的真实产品输入路径和回环服务器接收，不证明物理键盘或系统输入法；私钥采用粘贴而非逐字符手输。审查截图供设计核对，终端截图及其 OCR 用于目标和回显证据，两者用途不同。Tauri 两个旧入口断点在本次通过案例中未复现，不能由此确定旧失败的原因。

## 归档和校验

- Flutter 普通、密码换钥及加密私钥：[官方脱敏 ZIP](flutter-ios-ordinary-rotation-encrypted.zip)，Actions 运行 `44584233340`，artifact `14561986773`。
- Flutter 加密私钥换钥：[官方脱敏 ZIP](flutter-ios-encrypted-rotation.zip)，Actions 运行 `44584305176`，artifact `14563751286`。
- Tauri 普通及换钥：[复用已归档 ZIP](../tauri-ios-native-entry-20261120/ordinary-key-change-r2.zip)，运行 `44583882651`，artifact `14562341236`。
- Tauri 加密手输失败：[复用已归档 ZIP](../tauri-ios-native-entry-20261120/encrypted-manual-r2.zip)，运行 `44583969020`，artifact `14559684499`；[逐案说明](../tauri-ios-native-entry-20261120/README.md)。

在本目录执行 `shasum -a 256 -c SHA256SUMS` 校验四份 ZIP。每个 ZIP 的 `result.json` 记录各阶段、peer 和清理状态；截图及 OCR 文件的哈希在结果 JSON 中。
