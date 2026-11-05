# 手机配对与设备密钥契约实验

2026-11-05 更新：Android 设备密钥四方法已接入两壳；Flutter 的 Apple bridge、独立相机入口与一次性 POSIX helper 已有实现。有关当前 GUI 的运行证据与缺项，见[手机配对工作台](../../docs/14-mobile-pairing-workbench.md)与[Android signer](native/android/README.md)。下文保留 10 月 30 日离线实验的范围。

2026-10-30。这里完成**可执行的离线公开请求 → 临时 helper 授权 → 手机响应绑定 → 等待连通／取消／过期／重复／撤销状态契约**。Python reference 使用固定 `cryptography 46.0.3` 生成独立 Ed25519 key，并以成熟 OpenSSH parser 验证公钥；不是手机 App 已接线的实现。没有调用 SSH、相机、真实主机授权文件、系统 Keychain 或 overlay 身份，也没有运行服务。产品授权流程不构成本次真实主机写入授权。

## 运行与隔离边界

```sh
python3 -m venv /tmp/herdr-pairing-validation-venv
/tmp/herdr-pairing-validation-venv/bin/python -m pip install -r validation/pairing/requirements.txt
/tmp/herdr-pairing-validation-venv/bin/python -m unittest discover -s validation/pairing -v
python3 -m unittest discover -s validation/helper -v
/tmp/herdr-pairing-validation-venv/bin/python validation/pairing/demo.py --demo
/tmp/herdr-pairing-validation-venv/bin/python validation/pairing/demo.py --demo --confirm-fixture 'AUTHORIZE FIXTURE'
```

CLI 不接受任意路径、账号、host、公私钥或请求文件；每次运行创建全新 private 临时 fixture。默认demo先展示 `preview` 的fixture账号／手机指纹／拟议变更，没有确认不写授权；确认只写 `FixtureStore` 自己创建的 `authorization.fixture`，退出即销毁。demo 的撤销是隔离情景，不会撤销真实设备。私钥仅存在临时进程内存，既不序列化到 fixture，也不打印或上传；Python／Swift 的托管内存不保证所有历史副本可靠清零。

已执行记录见[本地证据](../../docs/evidence/pairing/README.md)。[工作流](../../.github/workflows/pairing-validation.yml)可在云端运行契约、Apple compile/memory probe、iOS simulator typecheck 与 Android API35 编译；已在 [run 41061177628](../../docs/evidence/mobile-observe/41061177628/README.md) 的 `c276c95` 源码上三job通过：Ubuntu/Mac各21项配对与15项helper检查、Apple内存probe/iOS simulator typecheck、Android API35编译；这些都不等于系统设备存储运行。本机不安装完整 Android／iOS SDK。

## v2 wire 与两个 GUI 的接线点

[JSON Schema](protocol-v2.schema.json)与[公开 fixtures](fixtures/)共用以下约束：UTF-8 JSON ≤2048 bytes、只允许平面对象、严格字段白名单、拒绝重复 key／控制字符／未知类型与版本、严格整数时间、有效期 ≤600 秒，必须 `issued_at <= now < expires_at`。`public_key` 只允许规范单行 `ssh-ed25519 <base64>`，拒绝选项、注释、换行；fingerprint 是 OpenSSH wire blob 的 SHA256。schema 不能表达时钟、TTL、重复字段和密码学解析，必须同时执行 `decode` 的语义检查。

公开 fixture 使用虚拟时钟：request 在100、authorized 在101、revoked 在900；不得用它们当当前有效请求。fixture 公钥随机生成后丢弃对应私钥，不对应用户设备身份。响应只绑定请求，没有签名、bearer secret、来源证明或自动 trusted-host 状态。

| 对象 | 字段 |
| --- | --- |
| request | `version=2`, `type=pairing-public-key-request`, `request_id`（随机32hex）, `device`, `public_key`, `account`, `host_key`（预期SSH host公钥的SHA256指纹）, `issued_at`, `expires_at` |
| response | `version=2`, `type=pairing-binding-response`, 同一 `request_id/account/host_key`, `fingerprint`（手机公钥）, `issued_at`, `expires_at`, `status=authorized|revoked`, `authorization_added` |

`authorization_added=false` 表示此前相同公钥已经存在，helper 没有新增它；其撤销返回手工处理，不谎称删除其他人管理的旧授权。`true` 也只说明当前 fixture 中确实新增，不能从未认证响应推出真实主机已授权。

兼容关系：旧 [helper v1](../helper/README.md)及其 wire 类型维持不变，新协议有意升为 v2，不能把 v2 JSON 交给旧 v1 parser。`FixturePairingHost` 先执行成熟公钥解析和 v2 校验，再调用旧 `FixtureStore.authorize(request_id, public_key)` 的同名字段；文件追加／receipt 所有权／原子失败语义复用旧实现。没有生产主机账号／home／UID 解析、跨进程消耗状态、并发写锁或断电恢复，因此没有生产“一次性 helper”承诺。

两 GUI 可接到 `PendingPairing` 的等价模型：

1. 调用本机 key store 的 `create → public`；保留**本机** handle，展示公钥与指纹。应用 UI／QR／导入导出均无私钥字段，不迁移 handle 到另一设备。
2. 用户审查预期 SSH 账号与 host 指纹后创建 request；只显示／传递公开请求，不暗含手机回传网络。主机操作者通过已有可信访问方式取得请求，核对账号／手机指纹并显式确认后返回 response。
3. 响应先校验版本、请求ID、手机指纹、账号、预期host指纹与期限；用户另行核验可信来源后才可 `accept(..., source_reviewed=True)`。响应绑定不产生主机信任、route、overlay入网或网络连接。
4. UI 显示 `authorized-unverified`。只有用户主动连接才 `connect(explicit=True)`，取得 generation；SSH adapter 必须先以同一预期host公钥实际 pin 验证、再认证手机私钥，成功后才报告 `connection_result(generation, pinned_ssh_authenticated=True)`。该布尔事件是测试 seam；本包未实际完成 SSH。
5. 网络／认证失败事件转为 `waiting-connectivity`，不会自动重试、重新申请key或发送输入。取消使 generation 失效；迟到成功不能覆盖取消或新的尝试。

| 事件 | 状态／授权语义 |
| --- | --- |
| 新请求 | `awaiting-host` / `unknown` |
| 已审查且匹配的授权响应 | `authorized-unverified` / `authorized` |
| 主动连接、网络失败、再次主动连接成功 | `connecting → waiting-connectivity → connecting → paired` |
| 取消 | `cancelled`，已记载的授权仍保留，主机可能已添加而手机尚未知时继续显示需主机核查／清理 |
| 待响应请求到期 | `expired`，不移除主机长期授权；已接收的授权不因QR到期自动失效 |
| 重复完成响应／已撤销请求再次授权 | 拒绝；仅当前内存实例保留消耗／tombstone，不跨重启承诺一次性 |
| 显式主机撤销并审查绑定撤销响应 | `revoked` / `revoked`，禁止再次连接；撤销响应可在原请求到期后另有600秒导入期 |

拒绝的响应不消耗当前待处理请求。实际主机指纹变化必须重新独立审查，不能由响应或导入直接替换。取消／到期后仍可按原request ID在主机清理；若手机没有收到过授权响应，其授权状态是unknown，不能据此断言主机未写入。此时仍可审查并接收绑定当前请求的撤销响应，转为revoked并保留消耗标记；错配、未审查来源、重复撤销与后续重新授权均拒绝。

## 设备安全存储：现实路径与已验证范围

App-facing稳定接口是 `create()→localHandle`、`public(handle)→OpenSSH public`、`sign(handle, boundedPayload)→signature`、`delete(handle)`。没有私钥导出／导入 API。locked、unavailable、invalidated、missing一律拒绝，不落明文兜底、不静默重建身份；删除本机key不等于撤销主机授权。仅在native内部允许seed读取，GUI跨语言bridge只映射这四个操作。Python `MemoryKeyStore` 测试这些失败路径，不能证明原生保护。

**iOS 路径**：`CryptoKit.Curve25519.Signing.PrivateKey` 生成／签名 Ed25519；32-byte raw seed 作为 Keychain generic-password 存放，限定 service/account、`kSecAttrSynchronizable=false`、`WhenUnlockedThisDeviceOnly`，不迁移到其他设备；读操作 `LAContext.interactionNotAllowed`，锁定／权限错误直接失败。Apple 公开 Secure Enclave 路径仅P-256，不能把此 Ed25519 seed说成Secure Enclave不可导出key。签名时seed出现在应用内存，Keychain保护的是静态存储。当前策略为解锁可用，不额外声称每次签名有生物识别确认。[Apple Keychain可访问性](https://developer.apple.com/documentation/security/ksecattraccessiblewhenunlockedthisdeviceonly)、[Secure Enclave限制](https://developer.apple.com/documentation/security/protecting-keys-with-the-secure-enclave)、[CryptoKit Ed25519](https://developer.apple.com/documentation/cryptokit/curve25519/signing/privatekey)

[Swift实现](native/apple/DeviceKeys.swift)已在Mac真实编译，`MemoryStoreProbe`只注入内存backend执行CryptoKit签名／验证、锁定拒绝、删除后拒绝；系统backend编译但**未实例化／未调用**。没有本机系统keychain写入。iOS simulator typecheck已在上述云端job通过；签名安装、设备Keychain、锁屏、备份恢复、entitlement与SSH signer集成均未验证；Mac内存probe不能替代它们。

**Android 路径**：不假设系统标准 provider 的Ed25519就能在AndroidKeyStore硬件中签名。采用native内成熟Ed25519库生成／签名，seed由AndroidKeyStore生成的AES-256-GCM key封装；固定61-byte envelope（版本1+12-byte随机IV+32-byte密文+16-byte tag），AAD绑定本机handle，密文只存App `noBackupFilesDir`。解封只在native受限callback中签名，尽快清理临时seed，GUI不接触seed。Keystore的AES key不可导出不等于Ed25519私钥永不进应用内存；硬件等级须实际检查KeyInfo，不作默认硬件承诺。[Android Keystore官方能力](https://developer.android.com/privacy-and-security/keystore)

[Java封装桥](native/android/AndroidSeedEnvelope.java)只覆盖AES封装／解封／删除和missing拒绝，未实现Android Ed25519库选择／生成／SSH签名／原子envelope保存，未接入GUI。它显式拒绝API<35：Android官方记录API31–34的`setUnlockedDeviceRequired`问题，API35起修复；这只是最小验证基线，不是产品最低Android版本决定。没有在本机编译或执行Android bridge，云端API35编译已通过；锁屏／失效／重装／备份／硬件KeyInfo及GCM篡改拒绝的设备行为仍待验证。[API与已知限制](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec.Builder#setUnlockedDeviceRequired(boolean))

成熟库固定版本及来源见[sources](sources.json)。固定依赖只是复验基线，不表示依赖安全审计或原生产品已验收。下一步应在具备授权的测试设备上将两GUI映射到native四方法接口，使用新生成测试身份完成SSH signer与Keychain/Keystore运行验证；本轮不索取真实设备凭据或向真实主机授权。
