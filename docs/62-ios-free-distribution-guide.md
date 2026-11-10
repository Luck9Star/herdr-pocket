# 62 · iOS 免费互联网测试分发指南（AltStore / SideStore）

回答「**不花钱、不上 App Store，怎么把包装到（自己或测试者的）iPhone 上**」。与 `docs/61` 互补：61 讲本机 Xcode 编译，本文讲免编译的互联网分发路径。盘点时间 2026-11-10，仓库 HEAD `c2ce3d3`。本文不改动任何 workflow/CI 配置。

## 1. 方式矩阵（先给结论）

| 方式 | 费用 | 设备范围 | 有效期 | 是否需电脑常驻 | 对本项目适配度 |
| --- | --- | --- | --- | --- | --- |
| **AltStore / SideStore（推荐）** | 免费 | 仅签名人自己的设备（各设备各签各的） | 7 天/次，自动续签 | AltStore 需一台同 WiFi 的 Mac/PC 跑 AltServer；SideStore 首装后无需 | **高**：Release 已有可直接重签的 `.ipa`（§3） |
| TestFlight | $99/年（Apple Developer Program） | 内部 100 人 + 外部 10,000 人 | 每 build 90 天 | 否 | 高，但要付费账号 + Beta 审核 + 许可证复评（`docs/61` §4） |
| Ad Hoc OTA（itms-services 直链） | $99/年 | 仅注册过 UDID 的设备（额度有限） | 随描述文件（约 1 年，未确认精确值） | 否（出包需 Mac） | 中：小圈子可用，每加设备要重出描述文件（`docs/61` §5） |
| 企业证书（In-House） | $299/年（企业计划） | 理论上企业员工 | 随证书 | 否 | **不建议**：对非企业员工分发违反 Apple ToS，证书可被随时吊销，法律与稳定性双风险 |
| PWA（网页壳） | 免费 | 任意浏览器 | — | 否 | **不成立**：SSH 依赖原始 TCP 套接字（dartssh2 走 `dart:io` Socket），浏览器沙箱没有；设备密钥依赖 Keychain 级别的安全存储，浏览器只给 IndexedDB。两者都无法用 Web 等价物替换而不改变信任模型（密钥经第三方中转） |

## 2. AltStore 路线（免费，推荐）

**原理一句话**：AltStore/SideStore 用**你自己的免费 Apple ID** 给 app 重新签名后安装——不是绕过签名，而是把「个人签名」这件事自动化（签名限制与 `docs/61` §3.1 完全相同）。

### 2.1 前置选择

| 工具 | 首装 | 续签 | 适合 |
| --- | --- | --- | --- |
| [AltStore](https://altstore.io) | 需一台 Mac/PC 装 AltServer，经数据线或同 WiFi 首装 | AltServer 与 iPhone **同 WiFi** 时后台自动续签（手机端可查下次续签时间） | 家里有常开电脑 |
| [SideStore](https://sidestore.io) | 同样需要一次电脑侧载（或借另一台已装的设备） | **设备端自续签**，装好后无需电脑（依赖设备上的 WireGuard 配置与 pairing 文件） | 不想常开电脑 |

### 2.2 步骤（以 AltStore 为例，可照做）

1. 电脑装 AltServer（macOS 菜单栏应用），iPhone 数据线连接后从 AltServer 菜单「Install AltStore」到手机。
2. 手机上打开 AltStore，登录**你自己的 Apple ID**（免费账号即可；会向 Apple 注册个人开发证书）。
3. 获取 app 包：从 Release 下载 `herdr-pocket-flutter-ios-unsigned-v0.1.0.ipa`（§3），在 AltStore「+」里选择该文件本地安装；也可自建/添加源（source）后从源里装，实现升级提醒。
4. 首次安装后在 iPhone「设置 → 通用 → VPN 与设备管理」里信任你的开发者证书，app 才能启动。

### 2.3 限制（如实写）

- 每次签名 **7 天有效**，需按 §2.1 的方式续签；超期 app 打不开，续签即恢复（数据不丢，§4）。
- 每 Apple ID 同时最多 **3 个 app** 侧载。
- 个人 Team 每 7 天最多注册 10 个 App ID（本项目两个壳各占 1 个，无碍）。
- 免费 Apple ID 在中国大陆区能否完成 AltStore 登录注册流程：**未确认**，遇到问题可换区账号尝试。

## 3. 我们的产物现状（2026-11-10 核实）

### 3.1 Flutter 壳：Release 已有可重签 `.ipa`

Release v0.1.0 资产 `herdr-pocket-flutter-ios-unsigned-v0.1.0.ipa`（36,078,428 字节，SHA256 见 `SHA256SUMS-v0.1.0.txt`）由 CI run 42802131744 的真机产物封装：CI 构建 `flutter build ios --debug --no-codesign`（`.github/workflows/flutter-validation.yml:115`）出的 `build/ios/iphoneos/Runner.app`（真机 arm64，未签名）按标准 `Payload/Runner.app` 结构打成 ipa。用它注意三点：

- **debug 构建**：包含 `Runner.debug.dylib`、`__preview.dylib`，体积偏大属预期；运行性能与正式 release 构建有差距，测试定位问题时要记住这点。
- **签名兼容性反而顺**：包本身未签名、不含 entitlements；AltStore 重签时注入个人 development entitlements（天然带 `get-task-allow`），与 debug 构建的调试需求一致——不会出现「debug 包被分发签名拒绝装」的矛盾。反过来说，这个包**不能**用于 App Store/TestFlight 渠道（那要求 release 构建且 `get-task-allow=false`）。
- bundle id 固定为 `dev.herdr.herdrFlutterProbe`（`ci.py` create 参数推导），AltStore 升级走同 id 覆盖安装。

### 3.2 Tauri 壳：Release 现已有同款可重签 `.ipa`

在 CI run 42878187512 中，通过 commit `d9e9588` 新增的 `aarch64-apple-ios` 真机构建作业，Release v0.1.0 现已补充上架 `herdr-pocket-tauri-ios-unsigned-v0.1.0.ipa`（24.1 MB，SHA256 见 `SHA256SUMS-v0.1.0.txt`）：
- 由真实真机架构 `aarch64` 未签名构建（`.github/workflows/tauri-validation.yml:98`）出的 `herdr-pocket-tauri-probe.app` 按标准 `Payload/` 结构打包；
- bundle id 为 `dev.herdrpocket.tauriprobe`；
- 使用方法与 Flutter 壳完全一致：下载后直接在 AltStore / SideStore 中「+」重签安装。双壳在 iOS 设备上可同时安装、独立共存。

## 4. 升级与有效期注意

- 7 天未续签：app 图标仍在，但打开即被系统拦下。让手机与 AltServer 同 WiFi（或 SideStore 手动触发）重新续签即恢复，**应用数据不丢**。
- 升级装新版本：下载新的 `.ipa` 在 AltStore 里覆盖安装（同 bundle id `dev.herdr.herdrFlutterProbe`），数据与配置保留；不要先删再装（会清数据）。
- 换 Apple ID 重签视为不同签名者，需删旧装新，数据不保留。

## 5. 何时值得花 $99（与 TestFlight 的对比）

免费路线的成本是「7 天续签 + 每设备手工签」，仅适合**签名人自己的设备**（测试者也各自签各自的）。出现以下任一情况时，TestFlight（`docs/61` §4）才划算：

- 测试者超过三五人，或包含非技术人员——每人都装 AltServer 不现实；
- 需要稳定 90 天有效的 build、正式的反馈收集渠道；
- 已决定走向公开分发（TestFlight 是 App Store 前置形态）。

在那之前，AltStore/SideStore + Release 上的未签名 `.ipa` 是零成本闭环：下载、重签、装机、自动续签，全程无需 Mac 参与（SideStore 场景）。

## 相关文档

- `docs/61-ios-personal-build-guide.md`：本机 Xcode 编译路径（路径 A/B/C）、免费账号限制细则、真机首跑验收点
