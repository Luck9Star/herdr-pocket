# Third-Party Notices / 第三方许可证与权利声明

本文件汇总 **herdr-pocket** 仓库当前代码基线所引用、依赖、包含或衍生的所有第三方开源组件、公共领域代码、图标与字体资产声明。

最后更新时间：**2026-11-10**  
源码基线提交：`feat/mobile-feature-batch-0011`

> **重要说明**：
> 1. 本文件为本项目构建与分发准备所需的第三方声明汇总，不构成对本项目整体许可证的单方替代。
> 2. 原创客户端代码的具体许可证选定方案详见 [`docs/59-license-decision-proposal.md`](docs/59-license-decision-proposal.md) 提案，目前待维护者正式拍板。
> 3. 第三方组件继续保留其各自的原始许可与版权归属，任何第三方代码不得被重新标示为项目自身的专有许可或统一替代许可。

---

## 目录

1. [概览与产物划分](#1-概览与产物划分)
2. [Flutter 壳产物依赖 (Dart & Flutter SDK)](#2-flutter-壳产物依赖-dart--flutter-sdk)
3. [Tauri 壳前端依赖 (npm & Web)](#3-tauri-壳前端依赖-npm--web)
4. [Rust 运行时与传输层依赖 (Cargo)](#4-rust-运行时与传输层依赖-cargo)
5. [三网络 Native 候选组件与运行时 (ZeroTier / EasyTier / Tailscale)](#5-三网络-native-候选组件与运行时-zerotier--easytier--tailscale)
6. [原生补丁归属与衍生条款审查](#6-原生补丁归属与衍生条款审查)
7. [Android 原生凭据与扫码组件](#7-android-原生凭据与扫码组件)
8. [终端字体与图标资产 (JetBrains Mono + Nerd Fonts)](#8-终端字体与图标资产-jetbrains-mono--nerd-fonts)
9. [主机端辅助配对工具 (Python Helper)](#9-主机端辅助配对工具-python-helper)
10. [主要开源许可证全文索引](#10-主要开源许可证全文索引)

---

## 1. 概览与产物划分

本项目包含多个独立的构建目标与分发产物。第三方许可义务按其被包含、链接或调用的实际产物分别生效：

| 产物标识 | 形态与目标 | 核心第三方组成 | 主要适用许可族 |
| --- | --- | --- | --- |
| **Flutter 壳** | 移动端 GUI (APK / iOS 候选) | Flutter SDK (BSD-3), Dart 生态包 (MIT/BSD/Apache), terminal_view 候选补丁 (MIT), FONT-NOTICES 字体资产 | BSD-3-Clause, MIT, Apache-2.0, OFL-1.1, CC-BY-4.0 |
| **Tauri 壳** | 桌面端及 Android GUI | @xterm/xterm (MIT), Tauri core/API (MIT/Apache), Rust 传输库 (Apache/MIT/BSD), FONT-NOTICES 字体资产 | MIT, Apache-2.0, BSD-3-Clause, MPL-2.0, OFL-1.1 |
| **共享传输层 (transport-rust)** | Rust 静态/动态库 | russh 0.65.0 (Apache-2.0 候选补丁), ring 0.17.14 (Apache-2.0 AND ISC), tokio (MIT), serde (MIT/Apache) | Apache-2.0, MIT, ISC, BSD-3-Clause |
| **三网络 Native 候选库** | 独立编译的 `.so` / 动态库 | libzt (BSL 1.1 → Apache-2.0), ZeroTierOne core (MPL-2.0 / Public Domain), lwIP (BSD-3), EasyTier (LGPL-3.0+), tsnet (BSD-3) | MPL-2.0, LGPL-3.0-or-later, BSD-3-Clause, Apache-2.0 |
| **Android 辅助原生组件** | AAR / JAR 依赖 | Bouncy Castle Ed25519 (MIT), ZXing Android Embedded (Apache-2.0), ZXing Core (Apache-2.0) | MIT, Apache-2.0 |
| **主机端配对工具 (Helper)** | 独立 Python CLI 工具 | cryptography (Apache-2.0 OR BSD-3-Clause), cffi (MIT-0), pycparser (BSD-3-Clause), qrcode (BSD-3-Clause) | Apache-2.0, BSD-3-Clause, MIT-0 |
| **共享终端字体** | TTF 嵌入资产 | JetBrains Mono (OFL-1.1), Nerd Fonts glyphs (MIT, OFL-1.1, Apache-2.0, CC-BY-4.0, Unlicense) | OFL-1.1, MIT, CC-BY-4.0, Apache-2.0, Unlicense |

---

## 2. Flutter 壳产物依赖 (Dart & Flutter SDK)

来源依据：`validation/flutter/pubspec.lock`（锁定 SHA-256：`58f7cc3fd81236889bda05d601c92119e4904085404792e966df9ca6ccda4f51`）及 pub.dev 官方归档。

| 组件名 | 锁定版本 | 来源 URL | 许可证标识 | 依赖性质 | 用途说明 |
| --- | --- | --- | --- | --- | --- |
| **Flutter SDK** | 3.47.9 / `c197ca5` | https://github.com/flutter/flutter | BSD-3-Clause | 基础框架 | 移动 GUI 宿主、widget 体系与平台通道 |
| **Dart SDK** | >=3.11.0 <4.0.0 | https://dart.dev | BSD-3-Clause | 基础运行时 | 语言核心库与 VM 运行时 |
| **terminal_view** | 0.5.0 | https://pub.dev/packages/terminal_view | MIT | 直接生产 | 移动终端虚拟终端解析与渲染器（含组合重音/IME 候选补丁） |
| **dartssh2** | 4.1.0 | https://pub.dev/packages/dartssh2 | MIT | 直接生产 | SSH2 客户端协议实现（主机通信与端口转发） |
| **pointycastle** | 4.0.0 | https://pub.dev/packages/pointycastle | Bouncy Castle (MIT 式) / LGPL-3.0 / MPL-2.0 | 直接生产 | 密码算法库（用于 dartssh2 密钥交换与加密，见下文详述） |
| **pinenacl** | 0.6.0 | https://pub.dev/packages/pinenacl | MIT | 传递生产 | TweetNaCl Dart 移植（用于 Ed25519 签名与加解密） |
| **asn1lib** | 1.5.8 | https://pub.dev/packages/asn1lib | BSD-3-Clause | 传递生产 | ASN.1 编码/解码器（用于 SSH 密钥格式解析） |
| **convert** | 3.1.2 | https://pub.dev/packages/convert | BSD-3-Clause | 传递生产 | 字符编码与数据转换工具库 |
| **meta** | 1.19.0 | https://pub.dev/packages/meta | BSD-3-Clause | 传递生产 | 语言注解元数据（@immutable 等） |
| **quiver** | 3.2.2 | https://pub.dev/packages/quiver | Apache-2.0 | 传递生产 | Google 常用工具集合（缓存、集合扩展） |
| **equatable** | 2.1.0 | https://pub.dev/packages/equatable | MIT | 传递生产 | 值对象相等性判定 |
| **zmodem** | 0.0.6 | https://pub.dev/packages/zmodem | MIT | 传递生产 | ZMODEM 文件传输协议解析器 |
| **characters** | 1.4.1 | https://pub.dev/packages/characters | BSD-3-Clause | 传递生产 | Unicode 字形簇（Grapheme cluster）分割 |
| **collection** | 1.19.1 | https://pub.dev/packages/collection | BSD-3-Clause | 传递生产 | 常用集合工具与比较器 |
| **material_color_utilities** | 0.13.0 | https://pub.dev/packages/material_color_utilities | Apache-2.0 | 传递生产 | Material 3 调色板与色彩方案计算 |
| **typed_data** | 1.4.0 | https://pub.dev/packages/typed_data | BSD-3-Clause | 传递生产 | 高性能类型化数据缓冲区 |
| **vector_math** | 2.4.4 | https://pub.dev/packages/vector_math | BSD-3-Clause | 传递生产 | 2D/3D 变换矩阵与几何计算 |
| **path** | 1.9.1 | https://pub.dev/packages/path | BSD-3-Clause | 传递生产 | 跨平台文件路径操作 |
| **async** | 2.13.1 | https://pub.dev/packages/async | BSD-3-Clause | 传递开发/测试 | 异步工具集（Stream 增强、CancelableOperation） |
| **boolean_selector** | 2.1.2 | https://pub.dev/packages/boolean_selector | BSD-3-Clause | 传递开发/测试 | 测试平台条件选择器语法解析 |
| **clock** | 1.1.3 | https://pub.dev/packages/clock | Apache-2.0 | 传递开发/测试 | 可插拔时钟接口（用于时间相关测试） |
| **fake_async** | 1.3.3 | https://pub.dev/packages/fake_async | Apache-2.0 | 传递开发/测试 | 确定性时间快进测试工具 |
| **flutter_test** | 0.0.0 (SDK) | https://github.com/flutter/flutter | BSD-3-Clause | 直接开发 | Flutter widget 测试框架 |
| **leak_tracker** | 11.0.2 | https://pub.dev/packages/leak_tracker | BSD-3-Clause | 传递开发/测试 | 内存泄漏监测工具 |
| **leak_tracker_flutter_testing** | 3.0.10 | https://pub.dev/packages/leak_tracker_flutter_testing | BSD-3-Clause | 传递开发/测试 | Flutter 测试用泄漏检测断言 |
| **leak_tracker_testing** | 3.0.2 | https://pub.dev/packages/leak_tracker_testing | BSD-3-Clause | 传递开发/测试 | 基础单元测试泄漏检测工具 |
| **matcher** | 0.12.20 | https://pub.dev/packages/matcher | BSD-3-Clause | 传递开发/测试 | 单元测试断言匹配器体系 |
| **source_span** | 1.10.2 | https://pub.dev/packages/source_span | BSD-3-Clause | 传递开发/测试 | 源码位置高亮与错误定位 |
| **stack_trace** | 1.12.2 | https://pub.dev/packages/stack_trace | BSD-3-Clause | 传递开发/测试 | 堆栈跟踪解析与符号化格式化 |
| **stream_channel** | 2.1.4 | https://pub.dev/packages/stream_channel | BSD-3-Clause | 传递开发/测试 | 双向 Stream 通道抽象 |
| **string_scanner** | 1.4.1 | https://pub.dev/packages/string_scanner | BSD-3-Clause | 传递开发/测试 | 字符流扫描器 |
| **term_glyph** | 1.2.2 | https://pub.dev/packages/term_glyph | BSD-3-Clause | 传递开发/测试 | 终端字符符号集（ASCII / Unicode 回退） |
| **test_api** | 0.7.12 | https://pub.dev/packages/test_api | BSD-3-Clause | 传递开发/测试 | 测试用例定义 API |
| **vm_service** | 15.4.0 | https://pub.dev/packages/vm_service | BSD-3-Clause | 传递开发/测试 | Dart VM 开发者服务与协议客户端 |

> **特别说明：Pointy Castle 的复合许可结构**：
> `pointycastle 4.0.0` 官方发布 tarball（SHA-256：`92aa3841d083cc4b0f4709b5c74fd6409a3e6ba833ffc7dc6a8fee096366acf5`）包含以下许可材料：
> 1. 根目录 `LICENSE` 为 Bouncy Castle 官方授权（MIT-style，版权归 The Legion of the Bouncy Castle Inc.）；
> 2. `licenses/LICENSE-BouncyCastle.html` 内嵌 HTML 注释注明项目自身采用 `LGPL 3 and MPL 2.0` 双许可；
> 3. `licenses/LICENSE-scrypt.txt` 为 Colin Percival 的 scrypt 衍生代码采用 Apache-2.0 许可。
> 本项目已将其归纳于随包声明中（`validation/flutter/licenses/pointycastle-4.0.0-LICENSE`）。

---

## 3. Tauri 壳前端依赖 (npm & Web)

来源依据：`validation/tauri/package.json` 与 `validation/tauri/package-lock.json`（锁定 SHA-256：`7c2babe5db5a4b60687f2cdef95d6fa1a196a0c229f4e6a2bd46e469e4bd6d05`）。

### 3.1 生产依赖 (直接编译并打包进入最终 Web/UI 产物)

| 组件名 | 锁定版本 | 来源 URL | 许可证标识 | 随包声明文件位置 |
| --- | --- | --- | --- | --- |
| **@tauri-apps/api** | 2.12.4 | https://github.com/tauri-apps/tauri | Apache-2.0 OR MIT | 包内及安装器声明 |
| **@xterm/xterm** | 6.0.0 | https://github.com/xtermjs/xterm.js | MIT | `dist/js-notices/xterm-LICENSE` |
| **@xterm/addon-unicode-graphemes** | 0.4.0 | https://github.com/xtermjs/xterm.js | MIT | `dist/js-notices/xterm-addon-unicode-graphemes-LICENSE` |

### 3.2 开发与构建工具依赖 (仅在构建时运行，不作为 JS 运行时分发)

| 类别/组件族 | 版本范围 | 许可证标识 | 包含组件说明 |
| --- | --- | --- | --- |
| **@tauri-apps/cli 及其多平台预编译包** | 2.12.4 | Apache-2.0 OR MIT | darwin-arm64, darwin-x64, linux-arm64, linux-x64, win32-x64 等平台 CLI 二进制 |
| **Vite** | 8.3.5 | MIT | 现代化前端构建与热重载工具 |
| **rolldown 及平台绑定** | 1.2.16 | MIT | 高性能 Rust-based JavaScript 打包器 |
| **lightningcss 及平台绑定** | 1.33.0 | MPL-2.0 | 高性能 CSS 解析器与压缩器（仅构建工具链，不随包分发源码） |
| **postcss** | 8.5.32 | MIT | CSS 语法转换工具 |
| **nanoid** | 3.3.20 | MIT | 唯一 ID 生成器 |
| **picocolors / picomatch** | 1.1.1 / 4.0.7 | ISC / MIT | 终端颜色与通配符匹配 |
| **fdir / tinyglobby** | 6.5.0 / 0.2.17 | MIT | 目录递归扫描工具 |
| **fsevents** | 2.3.3 | MIT | macOS 文件系统事件监听 |
| **detect-libc** | 2.1.2 | Apache-2.0 | C 运行库类型侦测 |
| **source-map-js** | 1.2.2 | BSD-3-Clause | Source map 解析与处理 |
| **@oxc-project/types** | 0.156.0 | MIT | JS/TS AST 类型定义 |

---

## 4. Rust 运行时与传输层依赖 (Cargo)

来源依据：
- `validation/tauri/src-tauri/Cargo.lock`（517 条 package，SHA-256：`f767c2fa6f32a173b7ec3404c91088572661e3a6af89a6ac85955c55c24b6c84`）
- `validation/transport-rust/Cargo.lock`（231 条 package，SHA-256：`4a07e8eb34acf45f0c8c6b0bd5146799300e6289c3f0f93a4541fde03e526870`）
- `validation/flutter-network-runtime/Cargo.lock`（232 条 package，SHA-256：`e261ad5d70ac1451d00403a215bec37742ed046c5a4986dcb769c943cb61518c`）
- `validation/ssh/Cargo.lock`（181 条 package，SHA-256：`a773978d92f52f111527d75769f943922cf508b3bd9a62c507313eab01b6aeaf`）

### 4.1 核心直接依赖 (Direct Dependencies)

| 组件名 | 锁定版本 | 来源与管理方式 | 许可证标识 | 涉及产物 | 用途说明 |
| --- | --- | --- | --- | --- | --- |
| **russh** | 0.65.0 | path 依赖 (`validation/vendor/russh-0.65.0`)，源自 crates.io 归档 | Apache-2.0 | Tauri 壳、传输层、Flutter 网络运行时、SSH 探针 | 纯 Rust SSH 客户端核心协议实现（含本地 Close 修复补丁） |
| **ring** | 0.17.14 | crates.io 锁定 | Apache-2.0 AND ISC | 共享传输层、Tauri 壳、Flutter 运行时 | 密码学基础设施（BoringSSL 衍生与纯 Rust 实现） |
| **tokio** | 1.54.1 | crates.io 锁定 | MIT | 全 Rust 模块 | 异步 I/O 驱动与多线程调度执行器 |
| **serde / serde_json** | 1.0.229 / 1.0.154 | crates.io 锁定 | MIT OR Apache-2.0 | 全 Rust 模块 | 数据结构序列化与反序列化框架 |
| **zeroize** | 1.9.1 | crates.io 锁定 | Apache-2.0 OR MIT | 全 Rust 模块 | 内存中敏感凭据与私钥的安全清零擦除 |
| **base64ct** | 1.8.3 | crates.io 锁定 | Apache-2.0 OR MIT | 共享传输层、Android/iOS 目标 | 常数时间 Base64 编码解码 |
| **url** | 2.5.8 | crates.io 锁定 | MIT OR Apache-2.0 | Tauri 壳、传输层、Flutter 运行时 | URL 解析与规范化处理 |
| **jni** | 0.21.1 | crates.io 锁定 | MIT/Apache-2.0 | Android 网络源、Flutter 运行时 | Java Native Interface 原生绑定桥 |
| **libc** | 0.2.191 | crates.io 锁定 | MIT OR Apache-2.0 | 全系统平台桥接 | 原生操作系统系统调用抽象 |
| **tauri / tauri-build** | 2.12.5 / 2.7.4 | crates.io 锁定 | Apache-2.0 OR MIT | Tauri 壳 | Tauri 应用运行时、IPC 桥与构建时代码生成 |
| **tauri-utils** | 2.10.2 | crates.io 锁定 | Apache-2.0 OR MIT | Tauri 壳 (macOS build) | Tauri 架构通用工具与配置处理 |

### 4.2 需特别关注的传递依赖分类审查 (Notable Transitive Crates)

Cargo 依赖树中解析出多项非单一 MIT/Apache 的许可证条目，分类审查结论如下：

1. **MPL-2.0 依赖 (弱 Copyleft，按文件级隔离)**：
   - 包含组件：`cssparser 0.37.0`、`cssparser-macros 0.7.1`、`selectors 0.38.0`、`dtoa-short 0.3.5`、`option-ext 0.2.0`。
   - 依赖链路：由 `tauri` 的 WebView 辅助组件（如 `dom_query`、`dirs-sys`）间接引入。
   - 条款审查：经核查，这些 crate 未附带 Exhibit B（即**未声明** `Incompatible With Secondary Licenses`）。在 MPL-2.0 §3.3 条款下，它们允许作为 Larger Work 的一部分并入 GPLv3/AGPLv3 作品，前提是其自身的 MPL-2.0 源码形式（或修改）继续保留并按 MPL-2.0 可获得。
2. **Unicode-3.0 依赖**：
   - 包含组件：`icu_collections 2.4.0`、`icu_locale_core 2.4.0`、`icu_normalizer 2.4.0`、`icu_normalizer_data 2.4.0`、`icu_properties 2.4.0`、`icu_properties_data 2.4.0`、`icu_provider 2.4.0`、`litemap 0.8.3`、`potential_utf 0.1.6`、`tinystr 0.8.5`、`writeable 0.6.4`、`yoke 0.8.4`、`zerofrom 0.1.8`、`zerotrie 0.2.5`、`zerovec 0.11.9` 等 18 个 ICU4X 组件。
   - 依赖链路：由国际化文本处理与 URL/IDNA 规范化链引入。
   - 条款审查：Unicode-3.0 属于宽松许可（类似 BSD/MIT），允许在保留版权声明的前提下自由分发与组合。
3. **复合许可 ring 0.17.14 (Apache-2.0 AND ISC)**：
   - 条款审查：manifest 明确为 **Apache-2.0 AND ISC**。crate 根内附带 `LICENSE`、`LICENSE-BoringSSL`、`LICENSE-other-bits` 以及 once_cell 的 MIT/Apache 头。分发时必须完整附带这四份版权与许可文本。
4. **Zlib 许可依赖**：
   - 包含组件：`zlib-rs 0.6.8`、`foldhash 0.2.0`、`tinyvec 1.13.3`、`objc2-* 0.3.2` 族。
   - 条款审查：Zlib 属于标准宽松许可，完全兼容主流宽松与强 Copyleft 许可证。
5. **0BSD / CC0 公有领域贡献**：
   - 包含组件：`adler2 2.0.1` (0BSD OR MIT OR Apache-2.0)、`dunce 1.0.5` (CC0-1.0 OR MIT-0 OR Apache-2.0)。
   - 条款审查：公有领域贡献或极宽免责，无任何再分发附加限制。

---

## 5. 三网络 Native 候选组件与运行时 (ZeroTier / EasyTier / Tailscale)

来源依据：`validation/native/sources.json`、`zerotier-runtime-source.json`、`zerotier-candidate.json`、`tailscale-runtime-source.json`、`managed-source-audit.json`。

| 原生组件/子模块 | 固定版本 / Commit | 来源 Repository | 原始许可证 | 在本仓库的构建方式与产物 | 许可证与衍生合规结论 |
| --- | --- | --- | --- | --- | --- |
| **libzt (fork)** | `7e5d0f99a2de81c45faa28e44289bcd19d933bf2` | https://github.com/Ylarod/libzt | BSL 1.1 (Change Date **2026-01-01**; Change License **Apache-2.0**) | 编译为 `libhp_zerotier.so` | **已满足转换条件**：BSL 1.1 条款在 2026-01-01 之后自动转为 Apache-2.0。不再受 BSL 商业使用与 SaaS 限制 |
| **ZeroTierOne (core)** | `fc5c3ec22090b5b2a0f274e863651fe9ca489bf4` (1.16.2) | https://github.com/zerotier/ZeroTierOne | **MPL-2.0** (node/, osdep/) 及 Public Domain (ECC, Salsa20, SHA512, Poly1305) | 参与静态编译进 `libhp_zerotier.so` | **核心代码采用 MPL-2.0**，经逐文件全文核验，编译的 49 个源文件中无一附带 Exhibit B。MPL 要求提供修改后的 Source Code Form；本项目完全公开补丁 |
| **ZeroTierOne (nonfree)** | 同上提交 | 同上 | **SOURCE-AVAILABLE** (严格禁止商业使用) | **静态严格排除**：构建工具链显式不包含 `nonfree/` 目录，并禁用 Central API（`-DZTS_DISABLE_CENTRAL_API=1`） | **未引入**：该非自由源码未进入任何构建输出，不构成侵入风险 |
| **lwIP** | `32708c0a8b140efb545cc35101ee5fdeca6d6489` | https://github.com/joseph-henry/lwip | BSD-3-Clause | 协议栈代码静态编译进 `libhp_zerotier.so` | 宽松许可，需保留瑞典计算机科学研究所版权声明 |
| **lwip-contrib** | `4fd612c9c72dfcd1db6618bd59c1a17d9f5b55f8` | https://github.com/joseph-henry/lwip-contrib | BSD-3-Clause / MIT | 平台 port（`sys_arch.c`）静态编译进 `libhp_zerotier.so` | 宽松许可，保留对应文件头版权声明 |
| **miniupnpc (嵌入)** | 2.0 (in ZeroTierOne) | Thomas Bernard | BSD-3-Clause | 静态编译进 `libhp_zerotier.so` | 宽松许可，保留 Thomas Bernard 版权与三条款声明 |
| **libnatpmp (嵌入)** | 20150527 (in ZeroTierOne) | Thomas Bernard | BSD-3-Clause | 静态编译进 `libhp_zerotier.so` | 宽松许可，保留 Thomas Bernard 版权与三条款声明 |
| **concurrentqueue** | 2013-2016 (in libzt) | Cameron Desrochers | Simplified BSD (BSD-2-Clause) | 单头文件包含 | 宽松许可，保留 Cameron Desrochers 版权声明 |
| **prometheus-cpp-lite** | 1.0 (in ZeroTierOne) | biaks (ianiskr) | MIT | 头文件包含 | 宽松许可，保留 biaks 版权声明 |
| **EasyTier (core)** | `728ba94b5029240add6204eed591f22e4e039e6b` | https://github.com/EasyTier/EasyTier | **LGPL-3.0-or-later** | 由 Heeler bridge 编译为独立的 `libheeler_easytier.so` | **强 Copyleft/库级隔离**：详见下节与提案。EasyTier 修改必须以 LGPL-3.0 继续提供对应源码 |
| **heeler-overlay-natives (bridge)** | `6a2817fc02aeb552df251d9478753c22fd4738bb` | https://github.com/Ylarod/heeler-overlay-natives | **LGPL-3.0-or-later** (native/easytier) / Apache-2.0 (glue) | 编译为 `libheeler_easytier.so` | C ABI 导出层；本仓库保留其 LGPL-3.0-or-later 边界，并在独立 `.so` 边界分发 |
| **portable-stream** | 0.1.0 | 本仓库原创与扩展 (`validation/native/portable-stream`) | **LGPL-3.0-or-later** | Rust 库，提供统一 handle 字节流抽象与 managed-node 生命周期 | 继承 Heeler 的 LGPL 授权，明确标为 LGPL-3.0-or-later，全部代码已开源于本仓库 |
| **Tailscale (tsnet)** | v1.104.1 / `9a522a9786` | https://github.com/tailscale/tailscale | **BSD-3-Clause** | Go `c-shared` 编译为 `libhp_tailscale.so` | 宽松代码许可。需保留 Tailscale Inc. 版权声明。需注意代码许可**不授予** Tailscale 商标权或云端服务访问权 |

---

## 6. 原生补丁归属与衍生条款审查

本项目对上游原生库打入了若干修复与适配补丁。依开源审查原则，逐项记录其涉及文件、原作者、原许可及衍生作品属性：

| 补丁路径与文件名 | 修改涉及的上游文件 | 上游仓库与版本 | 上游原许可 | 是否触发强制传染/条款要求 | 本项目处理与依据 |
| --- | --- | --- | --- | --- | --- |
| `validation/native/candidates/zerotier/patches/0005-native-safety.patch` | `ZeroTierSockets.h`, `Controls.cpp`, `Events.cpp/hpp`, `NodeService.cpp/hpp`, `VirtualTap.cpp/hpp`, 新增 `HpEventOwnership.hpp` 等 | `Ylarod/libzt` (Change Date 后的 Apache-2.0) | Apache-2.0 | Apache-2.0 §4(b)：修改过的文件必须带有显著的修改说明 | **已合规**：补丁文件头均保留清晰修改说明与原作者版权，未移除原有版权声明 |
| `validation/native/candidates/zerotier/patches/0006-strict-offline-identity.patch` | `ext/ZeroTierOne/node/ECC.hpp`, `Identity.cpp`, `NodeService.cpp` | `ZeroTierOne` (1.16.2) & `libzt` | MPL-2.0 (`Identity.cpp`) / Public Domain (`ECC.hpp`) / Apache-2.0 | MPL-2.0 §3.1：对 Covered Software 的修改属于 Modifications，必须以 Source Code Form 提供 | **已合规**：补丁以源码 patch 形式公开于仓库中，且无 Exhibit B 限制 |
| `validation/native/candidates/zerotier/patches/0007-defined-ecc-shifts.patch` | `ext/ZeroTierOne/node/ECC.cpp` | `ZeroTierOne` (1.16.2) | **Public Domain** (原作者 Matthew Dempsky / D. J. Bernstein / Adam Ierymenko) | 公共领域代码，无 Copyleft 传染性 | **已合规**：消除有符号负移位未定义行为，完全公开算术依据，保留原 Public Domain 声明头 |
| `validation/native/candidates/zerotier/patches/0008-streams-and-hp-boundary.patch` | `ext/lwip/src/api/sockets.c`, `core/netif.c`, `core/tcp.c`, `core/tcp_in.c`, `core/tcp_out.c`, `include/lwip/ip.h`, `netif.h`, `priv/sockets_priv.h`, `tcp_priv.h`; `src/HpBoundRoutes.cpp`, `HpBoundSockets.cpp`, `NodeService.cpp/hpp` | `joseph-henry/lwip` (BSD-3) & `Ylarod/libzt` (Apache-2.0) | BSD-3-Clause (`lwip`) / Apache-2.0 (`libzt`) | BSD-3 需保留版权声明；Apache 需保留修改声明；均无 Copyleft 传染性 | **已合规**：经三轮并发死锁与生命周期独立安全评审定稿（SHA-256：`ba4654f9…`），补丁完全公开 |
| `validation/native/candidates/zerotier/patches/0009-closed-port-rst.patch` | `ext/lwip/src/core/tcp_in.c`, `core/tcp_out.c` | `joseph-henry/lwip` (BSD-3) | BSD-3-Clause | BSD-3 宽松许可，无传染性 | **已合规**：针对关闭端口发送 RST 的标准行为修复，源码公开 |
| `validation/native/patches/0001-portable-stream-handles.patch` | `native/easytier/Cargo.toml`, `include/heeler_easytier.h`, `src/lib.rs` | `Ylarod/heeler-overlay-natives` (commit `6a2817f`) | **LGPL-3.0-or-later** | **LGPL-3.0-or-later 约束**：对库自身的修改属于库的衍生作品，修改必须以 LGPL-3.0-or-later 开源 | **已合规**：补丁直接以开源补丁归档，且本项目配套的 `portable-stream` 明确标为 `LGPL-3.0-or-later` |
| `validation/native/patches/0002-tsnet-explicit-auth.patch` | `tsnet/tsnet.go` | `tailscale.com` (v1.104.1) | BSD-3-Clause | BSD-3 宽松许可，保留原版权，无传染性 | **已合规**：关闭 ambient 凭据解析的嵌入式 opt-in 接口，源码公开 |
| `validation/flutter/patches/terminal_view-0.5.0-combining.patch` | `lib/src/ui/painter.dart`, `ui/render.dart`, `core/buffer/buffer.dart` | `terminal_view` (0.5.0) | MIT (fork of xterm.dart MIT) | MIT 宽松许可，要求保留 MIT LICENSE 和 NOTICE | **已合规**：保留上游 LICENSE 和 NOTICE，补丁 SHA-256 记录于 `manifest.json`，两文件随包分发 |
| `validation/flutter/patches/terminal_view-0.5.0-ime-observation.patch` | `lib/src/terminal_view.dart`, `ui/custom_text_edit.dart` | `terminal_view` (0.5.0) | MIT | MIT 宽松许可 | **已合规**：候选 IME 观测探针，源码公开 |
| `validation/vendor/russh-0.65.0-local-close.patch` | `src/client/mod.rs` | `russh` (0.65.0, Pierre-Étienne Meunier) | Apache-2.0 | Apache-2.0 §4(b)：修改必须带有显著说明 | **已合规**：附带完整的 `RUSSH-NOTICE.md` 说明本地 Close 索引收敛修复，源码公开 |

---

## 7. Android 原生凭据与扫码组件

来源依据：`validation/pairing/sources.json`、`validation/pairing/native/camera/sources.json` 及 Android 打包脚本校验器 `android_notices.py`。

| 组件名与 Maven 坐标 | 锁定版本 / SHA-256 | 来源 Repository / 官方仓库 | 许可证标识 | 随包资产与验证方式 | 用途说明 |
| --- | --- | --- | --- | --- | --- |
| **Bouncy Castle Ed25519**<br>`org.bouncycastle:bcprov-jdk18on` | 1.86<br>JAR SHA: `2af190b300cbb0b35e248ccf5f4a06b6072030aeb3da7a98ec73abe5b4cb371f` | https://github.com/bcgit/bc-java/tree/r1rv86 | **MIT** (Bouncy Castle License) | APK `assets/BOUNCY-CASTLE-LICENSE.md`<br>CI 中强制逐字节哈希核对 | Android 离线 Ed25519 密钥生成与签名验证 |
| **ZXing Android Embedded**<br>`com.journeyapps:zxing-android-embedded` | 4.3.0<br>AAR SHA: `4ab03353127c34e55cbb80fbc9a34031decbcfb1ec5e8f991944d2d494621a33` | https://github.com/journeyapps/zxing-android-embedded/tree/v4.3.0 | **Apache-2.0** | APK `assets/QR-NOTICE.txt`<br>CI 中强制逐字节哈希核对 | Android 扫码 Activity 封装与相机权限边界管理 |
| **ZXing Core**<br>`com.google.zxing:core` | 3.5.3<br>JAR SHA: `8d8064c1636fdaef7189dd9055c7d59950a8940a12f2293956446ec3c109fd82` | https://github.com/zxing/zxing/tree/zxing-3.5.3 | **Apache-2.0** | APK `assets/ZXING-APACHE-2.0.txt`<br>CI 中强制逐字节哈希核对 | 二维码核心解码矩阵运算 |

---

## 8. 终端字体与图标资产 (JetBrains Mono + Nerd Fonts)

来源依据：`validation/shared/fonts/FONT-NOTICES.md`、`font-sources.json`（checkedAt：`2026-11-06`）。  
字体文件：`JetBrainsMonoNerdFontMono-Regular.ttf`，SHA-256：`f01031f40e48dc29e1112e6b0b0450a2c6cd097f3f35cfff05c55cb311f8034c`。  
基础版本：Nerd Fonts **3.4.0**（commit `fa7b859994228a9c8759f99c55a8d31ee92a1b5e`），底层为 JetBrains Mono **2.304**。

本项目完整保留了 17 份上游许可文件全文（位于 `validation/shared/fonts/licenses/`）和 13 份生成来源记录（位于 `validation/shared/fonts/source-notes/`）。字体作为独立资产随包捆绑分发，不被主项目许可证改标。

| 图标/字体子集 | 来源版本与作者 | 目的码位范围与字符数 | 许可证 | 随包声明与合规状态 |
| --- | --- | --- | --- | --- |
| **JetBrains Mono (主字体)** | 2.304; The JetBrains Mono Project Authors | 基础字母/拉丁/数字/常用标点 | **OFL-1.1** | `LICENSE-JetBrainsMono.txt`；未声明 RFN；允许随软件捆绑分发 |
| **Nerd Fonts 聚合工作** | 3.4.0; Ryan L McIntyre & contributors | 字体补丁与合成逻辑 | **MIT / OFL-1.1** | `LICENSE-Nerd-Fonts.txt` 保留总许可 |
| **Font Logos (Linux 标志)** | 1.3.0; Lukas W (`e92426e2…`) | `U+F300`–`U+F381` (130) | **Unlicense** (公有领域贡献) | `LICENSE-Font-Logos-Unlicense.txt` 全文已收集；字节对照与 2016-03-10 授权提交已追溯；品牌商标归属各公司 |
| **Font Awesome (Free)** | 6.5.1.custom; Fonticons, Inc. | `U+ED00`–`U+F2FF` (1,487) | **CC-BY-4.0** (SVG) / **OFL-1.1** / **MIT** | `LICENSE-Font-Awesome-Free-6.5.1.txt` 与 `LICENSE-Font-Awesome-Free-vendored.txt` 双份保留 |
| **Font Awesome Extension** | v.0.0.3; André Luiz Gava (`09d80249…`) | `U+E200`–`U+E2A9` (170) | **MIT** | `LICENSE-Font-Awesome-Extension-MIT.txt` 全文已收集，字体字节与 tag 逐字节一致 |
| **Material Design Icons** | Pictogrammers / Templarian | `U+F0001`–`U+F1AF0` (6,896) | **Apache-2.0** | `LICENSE-Material-Design-Icons.txt` 与 `LICENSE-Apache-2.0.txt` 全文已收集；逐图标例外待核 |
| **Octicons** | 18.3.0.custom; GitHub Inc. | `U+F400`–`U+F533` 等 (310) | **MIT** | `LICENSE-Octicons-MIT.txt` 全文已收集 |
| **Codicons** | 0.0.35; Microsoft Corporation | `U+EA60`–`U+EC1E` (439) | **CC-BY-4.0** | `LICENSE-Codicons-CC-BY-4.0.txt` 全文已收集；不可使用 VS Code 专有商标 |
| **Devicons** | 2.16.0; konpa (`6910f050…`) | `U+E700`–`U+E8EF` (496) | **MIT** | `LICENSE-Devicon-2.16.0-MIT.txt` 全文已收集 |
| **Powerline Symbols** | 1.000; Kim Silkebækken | `U+E0A0`–`U+E0A2`, `U+E0B0`–`U+E0B3` (7) | **MIT-style** | `LICENSE-Powerline-Symbols-MIT.txt` 全文已收集 |
| **Powerline Extra Symbols** | 1.200; Ryan L McIntyre | `U+E0A3`, `U+E0B4`–`U+E0C8` 等 (34) | **MIT** | `LICENSE-Powerline-Extra-MIT.txt` 全文已收集 |
| **Pomicons** | 1.001; Gabriele Lana | `U+E000`–`U+E00A` (11) | **OFL-1.1** (RFN "Pomicons") | `LICENSE-Pomicons-OFL-1.1.txt` 全文已收集；派生字体未占用其 RFN |
| **Weather Icons** | 1.100; Erik Flowers & Lukas Bischoff | `U+E300`–`U+E3EB` (228) | **OFL-1.1** | `LICENSE-Weather-Icons-OFL-1.1.txt` 全文已收集；版权占位符待上游明确 |
| **IEC Power Symbols** | 1.0; Joe Loughry (`4c79c6a8…`) | `U+23FB`–`U+23FE`, `U+2B58` (5) | **MIT** | `LICENSE-IEC-Power-Symbols-MIT.txt` 全文已收集；与 vendor OTF 逐字节匹配 |
| **Hack (extraglyphs 派生)** | Hack 3.003; Source Foundry Authors / Bitstream | `U+276C`–`U+2771`, `U+EE00`–`U+EE0B` 等 (18) | **MIT / Bitstream Vera / DejaVu PD** | `LICENSE-Hack-MIT-Bitstream-Vera.txt` 全文已收集 |
| **Seti-UI + Custom (参考)** | 0.8.1; Jesse Weed | `U+E5FA`–`U+E6FF` (191) | **MIT** (参考) | `LICENSE-Seti-0.8.1-MIT.txt` 已作为参考收集；逐 SVG 历史导入版本映射待核 |
| **Vorillaz Devicons (参考)** | 2026 MIT 授权声明; Vorillaz | 包含于 Devicons 集合 | **MIT** (参考) | `LICENSE-Vorillaz-Devicons-reference-MIT.txt` 已作为参考收集；历史子集映射待核 |

---

## 9. 主机端辅助配对工具 (Python Helper)

来源依据：`helper/requirements.txt` 及 PyPI 官方元数据。该工具为独立运行的 POSIX 辅助 CLI，不作为移动/桌面客户端的随包依赖。

| Python 包名 | 锁定版本 | PyPI 来源 URL | 许可证标识 | 用途说明 |
| --- | --- | --- | --- | --- |
| **cryptography** | 46.0.3 | https://pypi.org/project/cryptography/46.0.3/ | **Apache-2.0 OR BSD-3-Clause** | SSH Host Key 读取、Ed25519 签名验证与配对回执签名 |
| **cffi** | 2.1.1 | https://pypi.org/project/cffi/2.1.1/ | **MIT-0** | Python C 外语法接口（cryptography 底层绑定） |
| **pycparser** | 3.12 | https://pypi.org/project/pycparser/3.12/ | **BSD-3-Clause** | 纯 Python C 语言解析器 |
| **qrcode** | 8.2 | https://pypi.org/project/qrcode/8.2/ | **BSD-3-Clause** (含 pyqrnative MIT 衍生) | 生成终端/SVG 配对二维码（支持手机扫码连接） |

---

## 10. 主要开源许可证全文索引

为便于离线查阅与满足分发保留义务，各主要开源许可证全文可参阅本仓库以下固定文件：

1. **Apache License, Version 2.0**:
   - `validation/vendor/russh-0.65.0-LICENSE-APACHE`（SHA-256：`cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`）
   - `validation/shared/fonts/licenses/LICENSE-Apache-2.0.txt`
   - `validation/pairing/native/camera/android/notices/ZXING-APACHE-2.0.txt`
2. **GNU Lesser General Public License, Version 3.0 (LGPLv3)**:
   - `validation/native/portable-stream/LICENSE`（SHA-256：`e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118`）
3. **GNU General Public License, Version 3.0 (GPLv3)**:
   - `validation/native/portable-stream/COPYING-GPL-3.0`（SHA-256：`3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986`）
4. **SIL Open Font License 1.1 (OFL-1.1)**:
   - `validation/shared/fonts/LICENSE-JetBrainsMono.txt`（SHA-256：`30f0c136e3c88e422d0791acd97238870f9054a9729bc34cf2ff0d4ed8cac4ad`）
   - `validation/shared/fonts/licenses/LICENSE-Pomicons-OFL-1.1.txt`
   - `validation/shared/fonts/licenses/LICENSE-Weather-Icons-OFL-1.1.txt`
5. **Creative Commons Attribution 4.0 International (CC-BY-4.0)**:
   - `validation/shared/fonts/licenses/LICENSE-Codicons-CC-BY-4.0.txt`（SHA-256：`d6239afa918961b465b07bf7411cbe34ff6685854f58553db7966f4881a0211f`）
6. **The Unlicense (Public Domain Dedication)**:
   - `validation/shared/fonts/licenses/LICENSE-Font-Logos-Unlicense.txt`（SHA-256：`88d9b4eb60579c191ec391ca04c16130572d7eedc4a86daa58bf28c6e14c9bcd`）
7. **Bouncy Castle License (MIT-style)**:
   - `validation/pairing/native/android/notices/BOUNCY-CASTLE-LICENSE.md`（SHA-256：`0e01f1549c9022f406392ac2947d32223b7c2e977d21ea2f8c182fdeb4dae5fd`）
   - `validation/flutter/licenses/pointycastle-4.0.0-LICENSE`（SHA-256：`3a7bb295473da049a1c6edd2f8c41b9e526a4e80f200c0200cc5600b2634df3f`）
8. **MIT License (xterm, dartssh2, terminal_view, etc.)**:
   - `validation/flutter/licenses/dartssh2-4.1.0-LICENSE`（SHA-256：`465afc358e3c3520109a7fd728d333e3101c71ad32d143181313bf406232808b`）
   - `validation/flutter/licenses/pinenacl-0.6.0-LICENSE`（SHA-256：`14cd126a80ee0e99ebd6e46ac5b8c7f929fecdcb1a01b8a0542552ea1f96589e`）
   - `validation/shared/fonts/LICENSE-Nerd-Fonts.txt`（SHA-256：`1f6ad4edae6479aaace3112ede5279a23284ae54b2a34db66357aef5f64df160`）
9. **BSD 3-Clause License (asn1lib, Tailscale, lwIP)**:
   - `validation/flutter/licenses/asn1lib-1.5.8-LICENSE`（SHA-256：`b0db8d3a93ea33f852d2b6dfa9c38fc57d33a51c31b47ca528df6d02700f2a42`）
   - `validation/shared/fonts/licenses/LICENSE-Hack-MIT-Bitstream-Vera.txt`
