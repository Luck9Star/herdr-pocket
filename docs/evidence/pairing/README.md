# 配对与设备密钥：2026-10-30 本地证据

本目录只包含合成公开fixture、摘要与测试结果。对应[实现与限制](../../../validation/pairing/README.md)、[固定来源](../../../validation/pairing/sources.json)、[工作流](../../../.github/workflows/pairing-validation.yml)。本轮没有提交／推送或触发云端job。

- Python reference **21项隔离测试通过**：[contract日志](local-contract-tests.txt)。真实生成临时内存Ed25519 key，成熟库OpenSSH解析／签名验证通过；授权仅写自建临时fixture。覆盖UTF-8 wire（拒绝UTF-16／32与BOM）、来源审查、目标错配、期限、重复、取消／迟到结果、等待连通、未知授权在取消／到期后接收撤销，以及预先存在key保护。连接成功只是状态测试事件，不是SSH实测。
- 原helper **15项回归通过**：[helper日志](local-helper-tests.txt)。未修改旧helper实现，v2 adapter复用其临时存储／receipt／原子写语义。
- Swift后端以warnings-as-errors **真实编译通过**，只执行CryptoKit内存backend的签名验证／locked拒绝／删除后拒绝：[memory probe](apple-memory-double.json)。系统Keychain backend没有实例化或调用，没有写系统keychain。此结果不能称iOS Keychain或Secure Enclave实测。
- [无确认demo](default-demo.json)无写入；[显式fixture确认demo](confirmed-demo.json)经授权未验证→等待连通→取消→撤销，撤销后fixture恢复为空。没有SSH连接或真实host授权。

[manifest](manifest.json)记录base源码SHA与未提交新增源码的逐文件hash；[SHA256SUMS](SHA256SUMS)覆盖本目录证据。依赖和编译器实际版本另存。公开QR request/response fixture是虚拟时钟材料，不是实时有效请求；无私钥、真实凭据或设备身份。

**尚未执行**：Android bridge编译／Keystore运行、iOS target编译／Keychain运行、相机扫码、手机设备安装／锁屏／备份恢复、两GUI安全存储接线、生产helper实际UID/home／锁／崩溃恢复、真实SSH私钥持有验证及三网络连通。新增workflow的存在不改变这些未验证格。
