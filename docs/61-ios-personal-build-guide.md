# 61 · iOS 个人编译与 TestFlight 路径指南

回答设计清单「iOS 平台接入」项的第一个问题：**能否用个人 Apple 账号自己编译安装到 iPhone，或走 TestFlight**。本文只做判定与操作指南；签名与分发属账号决策，本文不改动任何签名配置。盘点时间 2026-11-10，仓库 HEAD `7535573`。

## 1. 结论速览

| 路径 | 账号要求 | Flutter 壳 | Tauri 壳 | 结论 |
| --- | --- | --- | --- | --- |
| A. 个人免费 Apple ID 本地编译（Xcode 侧载） | 任意 Apple ID | 可行 | 可行 | **两条壳都可在本机走通**，前提是先装完整 Xcode（本机当前只有 CommandLineTools）；产物 7 天有效期、每账号最多 3 个 app 侧载 |
| B. Apple Developer Program（$99/年）+ TestFlight | 付费开发者账号 | 可行 | 可行 | 标准流程；CI 签名需把证书/描述文件放入 Secrets（本文只描述方案不实施） |
| C. Ad Hoc 直发 `.ipa` | 付费开发者账号 | 可行 | 可行 | 免费账号**不支持**；付费账号可注册设备后直发，额度以开发者账户页面为准 |

当前代码状态：两壳的 iOS 工程都能在本地一条命令生成，Swift bridge（配对扫码 / 设备密钥 / 配置文档）在两壳的生成路径中均已接线，**不存在阻塞性的代码缺口**。真正的门槛按顺序是：本机装 Xcode → Apple ID 登录 Xcode → 真机冒烟验证（Keychain 真实调用目前为 0，见 §6）。

## 2. 现状盘点（2026-11-10 核实）

### 2.1 本机（用户的 Mac，Darwin 27.2）

- `xcode-select -p` → `/Library/Developer/CommandLineTools`：**只有命令行工具，无完整 Xcode**，`xcodebuild -version` 直接报错。当前本机既不能真机构建也不能模拟器构建（CLT 不含 iOS SDK 与模拟器 runtime）。
- `security find-identity -v -p codesigning` → 0 个签名身份：未登录任何 Apple 开发者账号，属正常状态，装好 Xcode 并登录后会自动出现个人签名身份。

### 2.2 CI 产物（run 42802131744，runner Xcode 16.4）

| 产物 | 形态 | 架构 | 签名 | 可否装机 |
| --- | --- | --- | --- | --- |
| `tauri-ios-simulator-*` 内 `herdr-pocket-tauri-probe.app.zip` | `.app` 打 zip | aarch64-**sim**（模拟器） | unsigned-test-only | 否：模拟器架构装不上真机，也未签名 |
| `flutter-candidate-ios-*` 内 `flutter-ios-debug.tar.gz` | `build/ios/iphoneos/Runner.app` 打 tar.gz | **iphoneos（真机 arm64）** | 未签名 | 否：架构对但缺签名与描述文件；manifest 自述「iOS unsigned, not installable on device」（`validation/flutter/tool/ci.py:310`） |

结论：CI 产物都不能直接装手机。Flutter 的 iphoneos 包说明**编译链路已通到真机架构，只差签名**——个人账号在 Xcode 里重新构建并自动签名即可闭环。

### 2.3 两壳 iOS 工程的生成方式（关键事实）

两壳的 iOS Xcode 工程**都不入库**，均在构建时生成；bridge 源码以仓库共享 Swift 文件为准，生成时自动接线，无需手工改 Xcode 工程：

- **Tauri 壳**：CI 执行 `npm run tauri -- ios init --ci` 生成 `src-tauri/gen/apple`（`gen/` 被 gitignore，`validation/tauri/src-tauri/` 实测确认）；`npm run tauri -- ios build --debug --target aarch64-sim --no-sign --archive-only --ci`（`.github/workflows/tauri-validation.yml:95-96`）。Swift bridge 由 Cargo build script 从仓库共享源生成静态 Swift 包链入工程（`validation/tauri/src-tauri/build.rs:84-85` 引用 `validation/tauri/ios/PocketKeyBridge.swift`、`PocketPlugin.swift` 等；`validation/tauri/README.md:86` 明确「无需修改生成的 Xcode 工程」）。相机用途说明在 `validation/tauri/src-tauri/Info.ios.plist`（NSCameraUsageDescription）。bundle identifier 为 `dev.herdrpocket.tauriprobe`（`validation/tauri/src-tauri/tauri.conf.json`）。
- **Flutter 壳**：无 `ios/` 目录入库；`validation/flutter/tool/ci.py prepare` 先 `flutter create --platforms=android,ios,macos,windows,linux`（`ci.py:38`），再把共享 Swift 桥（`validation/pairing/native/apple/DeviceKeys.swift`、`validation/flutter/native/apple/DeviceKeyChannel.swift` 等、`validation/pairing/native/camera/apple/PairScanner.swift`）追加进 `ios/Runner/AppDelegate.swift` 并注册 channel（`ci.py:105-118`），同时向 `ios/Runner/Info.plist` 写入相机权限文案（`ci.py:119-121`）。Flutter SDK 锁定 3.47.9（`ci.py:23-24`）。CI 构建命令为 `flutter build ios --debug --no-codesign`（`.github/workflows/flutter-validation.yml:115`）。
- `ci.py` 的 `bootstrap` 子命令（克隆锁定版 Flutter SDK）是 CI-only（`ci.py:340-341`）；**`prepare` 子命令本地可直接用**，无 CI 限制，且拒绝覆盖已存在目录（`ci.py:36`）。

### 2.4 功能现状边界（照实声明）

- **三网 native 不在 iOS 包内**：Tailscale / EasyTier / ZeroTier 库目前只进 Android 包，构建库未接入任何 GUI 打包路径（`docs/17-license-and-distribution-review.md:16`）；五端矩阵中 iOS 三网全部「未做」（`docs/05-product-design.md` §8 回填表）。iOS 包当前只有 russh 传输链路，无组网能力。
- **Keychain 真实调用数为 0**：两壳的 iOS 设备密钥后端（CryptoKit Ed25519 + `WhenUnlockedThisDeviceOnly` Keychain）只做过内存替身测试，系统 Keychain 从未被真实调用，真机未验（`docs/56-project-status-and-handoff.md:69`；`docs/05` §8 iOS「安全凭据存储」格）。
- **iOS GUI 从未在任何设备/模拟器上运行过**（`docs/05` §8「设备运行：未做」）。

## 3. 路径 A：个人免费 Apple ID 本地编译（推荐先用这条）

### 3.1 免费账号的限制（先知道再动手）

- App 签名 **7 天有效期**，过期后 app 无法启动，需重新构建安装；每 Apple ID 同时最多 **3 个 app** 侧载；个人 Team 每 7 天最多注册 10 个 App ID（本项目 2 个 app，无碍）。
- **不能**使用 TestFlight、Ad Hoc、App Store 分发；不能申请大部分 entitlements（本项目当前不需要任何特殊 capability，无碍）。
- 首次安装后需在 iPhone「设置 → 通用 → VPN 与设备管理」里信任该开发者证书。

### 3.2 一次性环境准备（本机当前缺的就是这一步）

1. 从 App Store 安装完整 Xcode（约 15GB+ 磁盘；本文不做品牌/版本强约束，CI 用 Xcode 16.4 可作参照）。
2. `sudo xcode-select -s /Applications/Xcode.app`，然后 `xcodebuild -version` 能出版本号即就绪。
3. 打开 Xcode → Settings → Accounts → 添加个人 Apple ID（免费即可）。添加后在 Team 下拉里会出现「Your Name (Personal Team)」。
4. 用数据线把 iPhone 连到 Mac，iPhone 上信任该电脑。

### 3.3 Flutter 壳步骤（可照做）

```bash
# 锁定版 Flutter SDK（与 CI 同源：validation/flutter/tool/ci.py:23-24）
git clone --depth 1 --branch 3.47.9 https://github.com/flutter/flutter.git ~/flutter-3.47.9
export PATH="$HOME/flutter-3.47.9/bin:$PATH"
# shortcut: prepare 依赖 AppDelegate 模板 marker（ci.py:111），其他版本可能模板漂移导致拒绝

# 生成含 bridge 接线的 iOS 工程（与 CI 同一入口，本地可用）
cd <仓库>/validation/flutter
python3 tool/ci.py prepare --destination /tmp/herdr-flutter-ios
cd /tmp/herdr-flutter-ios
flutter pub get

# Xcode 签名并运行
open ios/Runner.xcworkspace
# Xcode: 选 Runner target → Signing & Capabilities → Team 选 Personal Team
#        顶部设备选自己的 iPhone → Cmd+R
```

说明：也可不进 Xcode，直接 `flutter run -d <iphone-id>`，但自动签名首次配置在 Xcode 里做最稳。产物 bundle id 为 `dev.herdr.herdrFlutterProbe`（`flutter create --org=dev.herdr --project-name=herdr_flutter_probe` 推导），个人 Team 下 Xcode 会自动注册该 App ID，无需改。

### 3.4 Tauri 壳步骤（可照做）

```bash
sudo xcode-select -s /Applications/Xcode.app   # 若尚未切换
rustup target add aarch64-apple-ios            # CI 只装了 -sim（tauri-validation.yml:63），真机需补
cd <仓库>/validation/tauri
npm ci
npm run tauri -- ios init                      # 生成 src-tauri/gen/apple 的 Xcode 工程（本地首次）

open src-tauri/gen/apple                      # 打开其中的 .xcodeproj / .xcworkspace
# Xcode: 主 target → Signing & Capabilities → Team 选 Personal Team → 选 iPhone → Cmd+R
```

说明：Swift bridge 由 build script 自动链入（§2.3），**不要手工往生成的工程里加文件**；`tauri.conf.json` 的 identifier `dev.herdrpocket.tauriprobe` 可直接用，也可按需改。如偏好 CLI，`npm run tauri -- ios build --debug`（不带 `--no-sign`）配合 Xcode 已配置的签名也可出真机包，但首次配置仍建议走 Xcode。

### 3.5 路径 A 首跑验收点

真机首跑本身就是项目台账里的未验项，建议按序确认：

1. app 能安装、能启动（签名信任流程走通）。
2. 首次触发扫码时弹出相机权限对话框（`Info.ios.plist` 的 NSCameraUsageDescription 生效）。
3. **Keychain 首次真实调用**：设备密钥写入/读取 `WhenUnlockedThisDeviceOnly` 后，锁屏状态下签名操作是否按预期被拒（这是替身测试覆盖不了的系统行为，`docs/56:69`）。
4. 锁屏/杀进程后重进，配对状态是否恢复。

## 4. 路径 B：Apple Developer Program（$99/年）+ TestFlight

### 4.1 前置条件

1. 加入 Apple Developer Program（年费以官网为准）。
2. App Store Connect 创建 App，注册 bundle id（两壳各一个）。
3. 生成分发证书与描述文件（TestFlight 用 App Store 分发证书；CI 无人值守构建推荐 App Store Connect API key）。

### 4.2 分发规则

- TestFlight **内部测试**最多 100 人（App Store Connect 用户角色），build 无需 Beta 审核；**外部测试**最多 10,000 人，每个 App 首个 build 需通过 Beta App Review。
- 每个 build 上架后 **90 天**有效，过期需重新提交。
- 未提交 App Store 的正式审查不因 TestFlight 而发生，但 Beta 审核对公测 build 生效。

### 4.3 CI 签名方案（只描述，不实施）

- 把分发证书（P12 + 密码）与描述文件（或 App Store Connect API key）放入 GitHub Actions Secrets；在 macos-15 runner 上导入临时 keychain，构建后清理。
- Tauri 壳：`tauri ios build --export-method app-store-connect`（替换现有 `--no-sign --archive-only`，`.github/workflows/tauri-validation.yml:95-96`）。
- Flutter 壳：`flutter build ipa --export-options-plist <plist>`（替换现有 `--no-codesign`，`.github/workflows/flutter-validation.yml:115`）。
- 许可证前提：TestFlight 属 Apple 协议约束渠道，GPL/LGPL 义务（对应源码、声明、重链接材料）须按最终包依赖清单复评后才能上渠道（`docs/17-license-and-distribution-review.md:88` 的既有结论：不能泛称任何 iOS 分发必然允许或禁止）。

## 5. 路径 C：Ad Hoc 直发 `.ipa`

- 免费账号：**不支持**。
- 付费账号：在开发者账户注册测试设备（UDID）、生成 Ad Hoc 描述文件、`flutter build ipa --export-method ad-hoc` / `tauri ios build --export-method ad-hoc`，ipa 直接发人安装。设备注册额度有限（每账号每年上限，精确数字以开发者账户页面为准），每加设备需重出描述文件。适合小圈子、免 Beta 审核的内测；受众扩大前建议直接走 TestFlight。

## 6. 离「个人账号真机跑」还差什么（文件级清单）

| # | 缺口 | 位置/性质 | 动作 |
| --- | --- | --- | --- |
| 1 | 本机无完整 Xcode | 系统环境（`xcode-select -p` 指向 CLT） | 装 Xcode 并切换（§3.2），这是一切的前提 |
| 2 | Flutter 壳无本地 iOS 脚手架与本地指引 | `validation/flutter/`（ios/ 由 `ci.py prepare` 生成） | 按本文 §3.3 执行；`ci.py prepare` 本地可用，无代码缺口 |
| 3 | Tauri 真机 rust target 未装 | CI 只装 `aarch64-apple-ios-sim`（`tauri-validation.yml:63`） | 本地 `rustup target add aarch64-apple-ios`（§3.4） |
| 4 | 两壳无 Team/签名配置 | Xcode 交互式操作 | 非文件缺口；在 Xcode Signing & Capabilities 里选 Personal Team |
| 5 | bundle id 为探针占位 | `dev.herdrpocket.tauriprobe`（tauri.conf.json）、`dev.herdr.herdrFlutterProbe`（ci.py create 参数推导） | 个人账号可直接用；若要正式名再改 |
| 6 | Keychain 真实调用数为 0 | 台账 `docs/56:69` | 真机首跑按 §3.5 验收；发现问题回写台账 |
| 7 | CI 无签名产物 | 两条 workflow 的 `--no-sign`/`--no-codesign` | 属账号决策（路径 B/C），本文不实施 |

## 7. 风险与未验证项

- 本机尚未装 Xcode，本文 §3 步骤在本机**未实际执行过**，属基于已核实工程事实的操作指南；首跑问题回写本文。
- 免费账号 7 天重签对长期自用有摩擦；若自用频率高，付费账号的 development 直装（无 7 天限制）是中间档。
- iOS GUI 从未运行过：首跑可能在渲染、输入法、扫码以外的交互上暴露未知问题，属预期内的新证据，不构成回退理由。
- 三网能力在 iOS 上完全缺失（§2.4）；即便装上，当前 iOS 包也无法完成依赖组网的场景，只能验 SSH 直连链路。
- TestFlight/Ad Hoc 上渠道前须完成依赖与许可证复评（§4.3），未复评不得分发。

## 相关文档

- 平台矩阵与验收口径：`docs/05-product-design.md` §8
- 项目台账（iOS 各维度状态）：`docs/56-project-status-and-handoff.md`
- 构建分层与渠道边界：`docs/07-build-and-release.md`
- 分发与许可证审查：`docs/17-license-and-distribution-review.md`
- 两壳工程细节：`validation/flutter/README.md`、`validation/tauri/README.md`
