# 许可证与分发审查

2026-11-06；源码基线 `8daf1bcb081903cb0c4fe3c8982c346b315200d3`。本页供维护者决定项目许可和准备发行材料，尚未作最终许可决策或法律合规保证。审查以实际锁文件、构建／打包脚本、已有声明及固定上游原文为依据；没有下载、安装或验收本批 GUI 成品，没有读取真实凭据，没有等待或改写进行中的 CI 结论。

**当前可继续进行隔离验证和发行准备，但“public”尚不等于本项目已完成开源授权；现有材料也不足以宣布任一 GUI 或三网完整版已完成分发审查。**两 GUI 的主要终端／SSH 组件未发现已证实的 GPLv3 阻断；有待闭合的是完整依赖和平台运行库清单、随包声明、字体 glyph 归属汇总、三网对应源码／链接材料，以及手机分发条款。

本页继承[技术评估](06-technology-evaluation.md)、[验证范围](09-prototype-validation.md)、[实验修复](10-blocker-repair.md)和 [ADR-0006](adr/0006-three-overlay-providers.md)的证据边界。用户希望衍生改动持续开源；下文建议供选择，未自动创建 `LICENSE`，也未将第三方代码改标为项目许可。

## 1. 当前公开和分发范围

| 对象 | 本轮确认 | 发行判断与缺口 |
| --- | --- | --- |
| 仓库原创源码／文档 | 根目录没有项目 `LICENSE`；`publish = false`、`private: true`、`publish_to: none` 是包发布设置，不是版权许可 | 需由有权许可者确定原创代码范围、许可证和贡献规则。已有第三方文件继续适用各自许可。GitHub 的公开可查看／fork 权利不等于获得通用再分发和衍生许可，见 [GitHub 官方说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository) |
| Flutter GUI 测试包 | 固定 Flutter、Dart lock；候选可注入有 hash 的 terminal_view 补丁；打包收集四份 Dart SSH 许可、候选终端 LICENSE/NOTICE 与共享字体材料 | 这是已有打包行为；尚无完整 Flutter engine／Dart／全部传递包／平台原生库的逐产物许可清单，也未在本轮检查最终包内的完整声明 |
| Tauri GUI 测试包 | npm／Rust lock、字体共享目录被收集；Android 三份 crypto／QR 声明有包内 hash 检查 | 脚本未建立 xterm、Tauri、russh、ring、所有传递依赖的统一声明／源码入口。lock 本身不含全部许可义务，不能代替声明包 |
| 三网 native 探针与补丁 | 固定来源、补丁和离线验证已有材料；构建库未接入现有两 GUI 的依赖／打包路径 | 不能以此宣称 GUI 已分发三网 SDK。将来加入任何 native 库时，须按实际链接图重新审查；不能直接套用 Heeler 的 iOS 发行包说明 |
| herdr 主机端／测试工具 | GUI 连接远端 herdr；CI 中还有上游 herdr 与可选输入扩展 fixture | 远端协议交互不等于 GUI 包含 herdr。若另发 helper、改造后的 herdr binary 或整套测试工具，须列为独立产物，保留对应来源、补丁、许可和依赖；不由 GUI 清单自动覆盖 |

公开测试 artifact 也是对外提供副本；“实验”“debug”不取消第三方声明义务。反过来，未通过手机运行验收也不能据此推断许可证冲突。工程验收与发行材料分别记录。

## 2. 两 GUI 实际终端、SSH 与 crypto

### Flutter 路线

- 固定 Flutter **3.47.9**／`c197ca5199e9ee5661e865596c9c07294dfab51c`，其 [LICENSE](https://github.com/flutter/flutter/blob/c197ca5199e9ee5661e865596c9c07294dfab51c/LICENSE) 为 BSD 三条款。该 root 许可不覆盖 engine、第三方 C/C++、Dart runtime 与生成工程的全部声明；需从实际 SDK／engine 构建输入和最终平台包汇总。
- `terminal_view 0.5.0` 官方[归档](https://pub.dev/api/archives/terminal_view-0.5.0.tar.gz) SHA-256 为 `5f8cf2e999b9b98224430b7ef2a32d378062073fa4e566f1f52d89ac9d9ac9cf`，与[补丁 manifest](../validation/flutter/patches/manifest.json)相同。本轮重新下载并验 hash：MIT LICENSE SHA-256 `fa9c766d83aeeaca6e8994be904afcc1940ece6b10cd9754919ee09bc0aa3530`，NOTICE SHA-256 `c307f60f6ada98062e4fd2634497e7e335741e09545f3caa54d48155621871a3`。NOTICE 明确源自 MIT 的 xterm.dart 4.0.0，保留原作者及 fork 归属。绘制补丁 SHA-256 `2d0fb1d7283b034eb8161651f5c1cee0343df2877ebd6863e6639782ad8e5833`；发布候选必须保留上游声明和本项目修改记录，不能只写“自研终端”。
- 实际 [pubspec](../validation/flutter/pubspec.yaml)直接使用 `dartssh2 4.1.0`、`pointycastle 4.0.0`；`pinenacl 0.6.0`、`asn1lib 1.5.8` 由锁固定。仓库已有[原许可和 hash 清单](../validation/flutter/remote-dependencies.json)：前 3 个为 MIT，asn1lib 为 BSD-3-Clause。本轮未重下这四个包，不把历史 hash 记录冒充本轮下载核验。
- `terminal_view` 的 `convert`、`meta`、`quiver`、`equatable`、`zmodem` 以及 Flutter／test 依赖仍须随实际图完整收集；四份 SSH 许可不能代表整个 pub lock 已审清。测试专用依赖与运行包依赖应在 SBOM 中分开，不能按 lock 所有条目都已链接处理。
- `xterm3 6.3.7` 是**未引入的备选**。本轮核对官方[归档](https://pub.dev/api/archives/xterm3-6.3.7.tar.gz) SHA-256 `dd3b79245e1d64a28e27e7d6a80187984d5125bc9632ec57e922446168f4a5fc`；其 NOTICE 为 AGPL-3.0-or-later，同时保留先前 MIT 作品声明。当前 MIT 候选不会因另一个 fork 的新许可自动变成 AGPL；若更换，必须重新审查实际组合、分发条款与终端验收，不能将现有补丁测试外推给它。

### Tauri／Rust 路线

| 实际锁定对象 | 核对结果 | 需要随发行物保留／补齐 |
| --- | --- | --- |
| Tauri core 2.12.5，build 2.7.4，utils 2.10.2；API／CLI 2.12.4 | MIT OR Apache-2.0；来源分别由 [Rust 清单](../validation/tauri/src-tauri/Cargo.toml)、[npm 清单](../validation/tauri/package.json)和各 lock 固定；[core 固定上游](https://github.com/tauri-apps/tauri/blob/tauri-v2.12.5/Cargo.toml) | 选用的许可分支、版权、所含 NOTICE、运行时与平台依赖清单；不能用 core 许可替全部 WebView／GUI 系统库背书 |
| `@xterm/xterm 6.0.0` | [固定版本 LICENSE](https://github.com/xtermjs/xterm.js/blob/6.0.0/LICENSE) 为 MIT；本地安装包文本与该项目作者归属一致 | 打包后的 minified JS 仍须保留或伴随 MIT 版权和许可；目前 package 脚本没有显式收集该文件 |
| `russh 0.65.0` | [固定 Cargo.toml](https://github.com/Eugeny/russh/blob/v0.65.0/russh/Cargo.toml) 为 Apache-2.0；本项目 [transport 清单](../validation/transport-rust/Cargo.toml)使用 `default-features = false`、`features = ["ring"]`，并显式固定 ring 0.17.14 | 不能照默认功能误报为已链接 aws-lc-rs；仍须逐目标检查 feature 合并后的实际图、SSH RustCrypto／ssh-key 传递包和来源声明 |
| `ring 0.17.14` | [官方 crate](https://static.crates.io/crates/ring/ring-0.17.14.crate) SHA-256 `a4689e6c2294d81e88dc6261c768b63bc4fcdb852be6d1352498b114f61383b7`，与两份 Rust lock 一致；manifest 是 **Apache-2.0 AND ISC**，不是二选一 | root LICENSE 还指向 `LICENSE-BoringSSL`、`LICENSE-other-bits`、once_cell 的 MIT／Apache 文本及源文件头。需收集实际对应声明，不能只放一份 Apache 文本或只写“MIT crypto” |
| Tokio 1.54.1、Serde 1.0.229、serde_json 1.0.154、base64ct 1.8.3、zeroize 1.9.1、libc 0.2.191 等 | 已锁，主干为 MIT／Apache／BSD 等许可；这是初步元数据核对 | Rust standard library、目标平台 crate 和 C／系统运行库仍须纳入逐包许可与实际分发边界 |

本机 registry 元数据抽查仅作缺口定位：transport lock 共 180 条 package，143 条 registry 包有本地 manifest、36 条 registry 包本地缺失；Tauri lock 共 515 条，344 条 registry 包有本地 manifest、168 条 registry 包缺失，其余为本地 path 包。**这些是 lock 条目和本地缓存覆盖率，不是运行时链接数，也不是全平台许可证扫描结果。**已见的非单一 MIT／Apache 类型包括 Tauri 传递包的 MPL-2.0（如 cssparser、selectors、option-ext）、Unicode-3.0，以及 ring 的复合许可。它们不能被省略，也不能仅据 SPDX 字段宣布兼容闭合；缺失包包括 Windows、Linux GUI、WASM 和 Android 目标项，需由每个平台实际构建补齐。

## 3. 三网真实候选与 LGPL／MPL 边界

本轮重读固定 [Heeler native README](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/README.md#licences) 与 [sources.lock](https://github.com/Ylarod/heeler-overlay-natives/blob/6a2817fc02aeb552df251d9478753c22fd4738bb/sources.lock)，没有改用当前 main。其 root／许多 glue 为 Apache-2.0，**不能覆盖 `native/easytier` 或每个子模块**。

| 路径 | 本项目真实候选／固定来源 | 可行性与未闭合材料 |
| --- | --- | --- |
| Tailscale | 当前探针直接 import `tailscale.com/tsnet v1.104.1`；[该版本 LICENSE](https://github.com/tailscale/tailscale/blob/v1.104.1/LICENSE) BSD-3-Clause。参考 libtailscale `d1dc45d039edb7759ecbee6ba2aea0c4bca884b8` [LICENSE](https://github.com/tailscale/libtailscale/blob/d1dc45d039edb7759ecbee6ba2aea0c4bca884b8/LICENSE) 同为 BSD-3-Clause，但不是当前 tsnet 探针已集成完整 binding 的证明 | 收集 Go standard library、实际 go.mod/go.sum 中链接模块、Go 原生输出及修改声明；单独使用云端服务还须核对对应服务条款，代码许可不授予服务账户或商标权 |
| EasyTier | 开发提交 `728ba94b5029240add6204eed591f22e4e039e6b`，不是已确认的 2.7.0 release；其 [LICENSE](https://github.com/EasyTier/EasyTier/blob/728ba94b5029240add6204eed591f22e4e039e6b/LICENSE) 是 LGPLv3。Heeler bridge 与本项目 [portable-stream](../validation/native/portable-stream/Cargo.toml)明确 LGPL-3.0-or-later；本地 portable 补丁 SHA-256 `c6cf73a5e26bab665c226f37c81d55671f801e84d67d340bd18dc670529b06a4` | Heeler crate 静态链接 EasyTier，本项目候选构成其修改来源；需 GPL＋LGPL 文本、显著库使用／修改声明、完整对应源码／补丁／Cargo lock／构建脚本及实际适用的重链接和安装材料。上游包的 iOS 重建说明不是本项目五端 GUI 的说明 |
| libzt | Ylarod fork `7e5d0f99a2de81c45faa28e44289bcd19d933bf2` [LICENSE.txt](https://github.com/Ylarod/libzt/blob/7e5d0f99a2de81c45faa28e44289bcd19d933bf2/LICENSE.txt)写明 Change Date **2026-01-01**、Change License Apache-2.0 | 按该固定版本条款，在本次日期已达到转换条件；此判断仅覆盖该许可的 Licensed Work，不能扩展到当前 libzt main、别的版本、全部子模块或商标 |
| ZeroTierOne core | libzt gitlink 固定 `fc5c3ec22090b5b2a0f274e863651fe9ca489bf4`／1.16.2；[root LICENSE](https://github.com/zerotier/ZeroTierOne/blob/fc5c3ec22090b5b2a0f274e863651fe9ca489bf4/LICENSE.txt)与 [MPL 文本](https://github.com/zerotier/ZeroTierOne/blob/fc5c3ec22090b5b2a0f274e863651fe9ca489bf4/LICENSE-MPL.txt)将 core 与 `nonfree/` 分开 | MPL 文件和修改需可取得 Source Code Form、许可及来源入口。MPL 与 GPL／AGPL 的 Secondary License 路径有条件，须检查实际文件无 Exhibit B 等排除，不能仅据 root MPL 文本认定全部文件可转许可，见 [Mozilla FAQ Q14](https://www.mozilla.org/en-US/MPL/2.0/FAQ/) |
| ZeroTierOne `nonfree/` | 同一 commit 的 [SOURCE-AVAILABLE LICENSE](https://github.com/zerotier/ZeroTierOne/blob/fc5c3ec22090b5b2a0f274e863651fe9ca489bf4/nonfree/LICENSE.md)另有限制 | 不能随意纳入 GPL／AGPL 产品。固定 libzt [CMakeLists](https://github.com/Ylarod/libzt/blob/7e5d0f99a2de81c45faa28e44289bcd19d933bf2/CMakeLists.txt)的 core source glob 指向 node、指定 osdep 与 ext，不包含 nonfree；本项目又禁用 Central API。此为静态构建范围证据，正式每目标须留完整编译单元／链接清单和自动拒绝 nonfree 检查，不能把 `ZTS_DISABLE_CENTRAL_API` 当成许可证开关 |
| lwIP 与其余 C/C++ 组件 | lwIP `32708c0a8b140efb545cc35101ee5fdeca6d6489` [COPYING](https://github.com/joseph-henry/lwip/blob/32708c0a8b140efb545cc35101ee5fdeca6d6489/COPYING)为 BSD 三条款；lwIP contrib `4fd612c9c72dfcd1db6618bd59c1a17d9f5b55f8` | 本轮 contrib root `COPYING` URL 为 404，需按实际采用文件头定位。MiniUPnPc、libnatpmp、LZ4、ConcurrentQueue、prometheus-cpp-lite 等按上游固定 README已有分件说明，但尚未在本项目按实际编译文件逐件复核、收集全文；不以一个 root COPYING 代替 |

LGPLv3 的 Combined Work 路径涉及允许修改库／为调试库修改而逆向、提供相应许可、适用的重新组合／重链接方式，以及适用时的 Installation Information。源码公开或把 `.so` 改名都不会自动完成这些要求。若选择 GPLv3 并按允许路径分发整个组合作品，仍须完整对应源码、构建和适用安装材料；不能把“项目也开源”当成略过分析的理由。原文见本仓库[LGPL](../validation/native/portable-stream/LICENSE)和 [GPLv3](../validation/native/portable-stream/COPYING-GPL-3.0)，固定上游 GPL 文本 hash `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986` 本轮与其来源锁核对。

## 4. 字体、二维码、Android crypto 和平台条款

### 已有明确许可，但材料需要按实际包闭合

- 字体是 Nerd Fonts **v3.4.0** 的 `JetBrainsMonoNerdFontMono-Regular.ttf`，底层 JetBrains Mono **2.304**；[fixture 和 SHA](../validation/shared/fixture.json)固定为 `f01031f40e48dc29e1112e6b0b0450a2c6cd097f3f35cfff05c55cb311f8034c`。已有 JetBrains OFL-1.1 与 Nerd Fonts 总许可；[固定字体目录 OFL](https://github.com/ryanoasis/nerd-fonts/blob/v3.4.0/patched-fonts/JetBrainsMono/Ligatures/Regular/OFL.txt)本轮与仓库副本核对。允许按条件随软件捆绑；字体保持其自身许可，不能改标为 GPL／AGPL，修改命名须检查实际 RFN，且不能单卖字体。
- Android Ed25519 使用 `org.bouncycastle:bcprov-jdk18on:1.86`，MIT；[固定官方原文](https://github.com/bcgit/bc-java/blob/r1rv86/LICENSE.html)与仓库 [notice](../validation/pairing/native/android/notices/BOUNCY-CASTLE-LICENSE.md)语义一致，后者为 Markdown 转写，不能拿 HTML hash 要求逐字相同。artifact hash 已记在 [sources](../validation/pairing/sources.json)。本轮核对许可证原文，没有重下载该 jar，也未证明硬件 Keystore 行为。
- Android 扫码是 `com.journeyapps:zxing-android-embedded:4.3.0` 和 `com.google.zxing:core:3.5.3`，两者 Apache-2.0；[固定 embedded COPYING](https://github.com/journeyapps/zxing-android-embedded/blob/v4.3.0/COPYING)、[ZXing LICENSE](https://github.com/zxing/zxing/blob/zxing-3.5.3/LICENSE)及 [artifact 来源](../validation/pairing/native/camera/sources.json)可追溯。仓库已有 QR 归属、Apache 全文和 BC MIT 文本，共享 [APK 检查器](../validation/shared/android_notices.py)要求各唯一一份、限长且内容 hash 与源一致。
- 上述 Android 检查只覆盖三份文件。Gradle 实际解析的 AndroidX、camera activity 依赖及其他 AAR／JAR 仍须完整汇总，不能称扫码与 Android 整体已审清。ZXing root LICENSE 另附 jai-imageio 许可，但 root 总清单不证明该模块实际被 core jar 链接；应按解析图／artifact 内容确定，避免漏报，也避免将未使用模块误报为所需权限。
- Apple 路径调用系统 CryptoKit／Security／AVFoundation，未据此认定随包带入独立开源 `swift-crypto`。使用系统 API 与再分发库是不同范围；Apple SDK、签名、安装和商店条款另外审查。系统 CJK／emoji fallback 同理，不因使用系统字体便宣称拥有其可拷贝再分发权。

### Font Logos 版权许可已追溯，字体声明仍需汇总

Nerd Fonts v3.4.0 的 [license-audit.md](https://github.com/ryanoasis/nerd-fonts/blob/fa7b859994228a9c8759f99c55a8d31ee92a1b5e/license-audit.md)将 Font Logos 写作 `Unlicensed`，**不能把该词直接解释为没有许可证**。该 audit 标注须结合对应固定版本的实际授权全文解释，下列来源已经追溯到具体 release。

| 追溯环节 | 本轮证据 |
| --- | --- |
| Nerd Fonts 固定版本 | v3.4.0 指向 `fa7b859994228a9c8759f99c55a8d31ee92a1b5e`；[vendor 文件](https://github.com/ryanoasis/nerd-fonts/blob/fa7b859994228a9c8759f99c55a8d31ee92a1b5e/src/glyphs/font-logos.ttf)实际为 `.ttf`，不是 `.otf`；name 表版本 **1.3.0**、归属 `Copyright (c) 2014-2024, Lukas W`、来源 URL 指向 Lukas-W/font-logos |
| vendor 更新来源 | [更新提交 2123aea](https://github.com/ryanoasis/nerd-fonts/commit/2123aea42031882eca629487ea694537141a6acf)明确升级 1.3.0；[修正提交 4ab9d898](https://github.com/ryanoasis/nerd-fonts/commit/4ab9d898d7c8dcba604d7b9b5e3377d222614948)说明重新从 Font Logos Release 获取，以补齐 River／F381 |
| 官方 release 的字节对照 | [font-logos-1.3.0.zip](https://github.com/lukas-w/font-logos/releases/download/v1.3.0/font-logos-1.3.0.zip) SHA-256 `53376d5496cfbc78035ca60f58791ba5b2bfec6a9e751ac521aace6acdacb012`；其中 `assets/font-logos.ttf` 为 48,592 bytes、SHA-256 `7f0b055275bb3710afee586519884f3e302ec295a2f4ff4158daacf437c49852`，与上述 Nerd vendor 文件逐字相同 |
| 该 release 的授权全文 | zip 内 `LICENSE` SHA-256 `88d9b4eb60579c191ec391ca04c16130572d7eedc4a86daa58bf28c6e14c9bcd`；与上游 v1.3.0 commit `e92426e28ee5bbf4ca328b33e3a393b7a5045f01` 的 [LICENSE 全文](https://github.com/Lukas-W/font-logos/blob/e92426e28ee5bbf4ca328b33e3a393b7a5045f01/LICENSE)一致，属于 **Unlicense**，含 public-domain dedication 及复制、修改、编译、销售、分发许可，适用于商业和非商业用途 |
| 声明时间 | [0b10f1ca](https://github.com/Lukas-W/font-logos/commit/0b10f1ca42d323f27d0e41f2f38c695ff28f0eae)在 **2016-03-10** 加入 Unlicense，早于上述 2024 年 vendor 更新；不是用现今 main 的新许可倒推旧字体 |

固定 [font-patcher](https://github.com/ryanoasis/nerd-fonts/blob/fa7b859994228a9c8759f99c55a8d31ee92a1b5e/font-patcher)把 Font Logos 映射到 U+F300–U+F381；当前客户端 TTF 的该 130 个码位都有非零 glyph 映射。因此这份来源／许可应进入字体归属清单；**对应版本具有明确版权授权，本项余下工作是发行来源／声明汇总，不要求删除或更换已验字体**。Unlicense 是明确的版权授权／公有领域贡献声明，不等于“未许可”。

版权许可与商标另行区分：该固定版本 [README](https://github.com/Lukas-W/font-logos/blob/e92426e28ee5bbf4ca328b33e3a393b7a5045f01/README.md)说明品牌图标属于各自权利人的商标，用来代表对应公司或产品。Unlicense 不应被理解为取得这些品牌的商标权或背书；终端渲染图标与把品牌用作本产品标识／营销是不同使用场景，本页未逐品牌审核后者。

最短修复是完善发行声明，而非改字体字节：在共享字体材料中加入上述固定 Font Logos Unlicense 全文和 provenance（Nerd commit、Font Logos 1.3.0 commit、zip／vendor hash、商标说明）；再建立统一 `FONT-NOTICES`／来源表，逐项收集本字体所含 Codicons／Font Awesome 的 CC-BY-4.0、Material Design Icons 的 Apache、MIT／OFL 来源及其适用归属／修改说明。Unlicense 本身不强制署名，这份全文和归属记录用于准确追溯，不能虚构它有额外署名条款。现有 JetBrains OFL 与 Nerd 总许可继续保留，两 GUI 的发行入口须能取得这些文本，并以包内／随包 hash 核验。只有字体文件本身改变时才需要更换 fixture hash 并重跑相关绘制验收；本轮仅修正文档判断，没有写入这些声明文件，也没有宣布其他 glyph 来源已逐件审清。

### 手机与桌面发行渠道尚未获结论

源码／本地重建、测试包直发、TestFlight、App Store、Google Play、桌面安装器不是同一个分发方案。GPL／AGPL 的下游权利、可能适用的安装信息，与实际签名／DRM／渠道附加条款必须对照；不能泛称所有商店必然允许，也不能泛称所有 iOS 分发必然禁止。Apple 官方明确以开发者账户接受的最新英文协议为准，见[当前协议入口](https://developer.apple.com/support/terms/)；本轮只检查公开入口，未读取任何账户协议或签名凭据。Windows 的 WebView2／VC runtime、Linux 的 GTK／WebKit 组件、Android 系统／SDK 与可能重分发的 runtime 也须按最终包列明。

密码功能的出口／进口分类和应用商店加密申报是另一项发行判断。此处未查明发行主体、地区、渠道与最终算法组合，不提供已豁免或无需申报的结论；不能由“ring／BC 是开源”替代该项。

## 5. GPLv3 与 AGPLv3 的条件性建议

**建议先把 GPL-3.0-or-later 作为原创客户端代码的优先候选，待下列材料闭合后决定；AGPL-3.0-or-later 保留为有明确网络交互衍生服务要求时的选择。**这符合“分发衍生改动继续开放”的方向，也避免仅因客户端会联网就把 AGPL 当成必选。该建议不代表用户已批准许可证，也不改变各依赖许可。

| 候选 | 与用户目标的对应 | 尚须确认 |
| --- | --- | --- |
| GPL-3.0-or-later | 对分发 covered 衍生／组合作品要求相应源码与同许可；私人修改通常不因未发布自动要求公开 | 不应承诺“任何改动都必须向全世界公开”。要明确原创代码／文档／设计资产边界、贡献来源、库链接图、对应源码与适用安装信息；原文与 [FSF GPLv3 指南](https://www.gnu.org/licenses/quick-guide-gplv3.html)可供逐项核对 |
| AGPL-3.0-or-later | 在 GPL 类分发要求外，§13 对修改后的程序与远程网络用户交互另设提供对应源码的义务 | 不能把任意 SSH 通信解释为远端 herdr 自动受本客户端 AGPL 约束，也不能据 AGPL 认定所有后端必须开源。未来若客户端逻辑衍生为托管服务，额外约束更贴合该目标；协议边界、组合关系与渠道须重新确认，见 [FSF GPLv3／AGPL 指南](https://www.gnu.org/licenses/quick-guide-gplv3.html) |

MIT／BSD／ISC／Apache 主干使这两种方向有继续评估的基础；Apache 官方明确说明其代码可进入 GPLv3 作品，这不等于第三方 Apache 源码自身被一律替换许可，见 [ASF 兼容说明](https://www.apache.org/licenses/GPL-compatibility)。LGPL 的来源条件、MPL Secondary License 条件、字体独立许可和其他资产都继续保留。GPLv3／AGPLv3 §13 的组合机制也不是把两个许可证名称互换；若未来使用 xterm3 AGPL，需要针对实际 combined work 再作结论。

**没有发现已核实的主要组件许可必然要求放弃五端／三网目标；也没有足够证据现在宣布完整产品可按 GPL 或 AGPL 无条件分发。**字体声明汇总、平台依赖覆盖与发行材料是当前实际缺口，不能靠选择更强 copyleft 自动修复。

## 6. 最短下一步与完成条件

1. **生成逐产物依赖清单。**每 GUI × 每目标平台导出实际 enabled features／解析依赖／原生编译单元／系统动态库和随包文件，区分构建工具、测试依赖、被链接代码、系统库。SBOM 至少关联源 commit、lock hash、目标 ABI、artifact hash、上游版本／commit、许可表达式、全文／NOTICE、修改和对应源码入口；清单缺项拒绝把该包标成已审清。
2. **先闭合现有 GUI 的声明与字体归属材料。**给两条包流程统一收集第三方文本与可见入口，覆盖 xterm、Flutter／engine、Dart、Rust／ring／Unicode／MPL 传递项及 Gradle 图；按本页已固定的 Font Logos Unlicense 来源补全文及 provenance，并补齐其他已使用 glyph 来源的适用声明；不将 audit 的 `Unlicensed` 误读为无许可。对已生成的 APK／App／安装器做包内和外附声明双重校验，而不是只检查工作目录存在文件。
3. **三网集成时补专用来源包。**保留 Heeler 原始来源锁、全部补丁和修改归属，核对 ZeroTier nonfree 排除／MPL 文件头，完整复制 lwIP contrib 等实际使用文件的许可。为每平台给出可实际复跑的对应源码、重链接或按选定 copyleft 路径所需的重建与安装说明，并用修改后的库验证该路径；没有 GUI 接线时不能预填通过。
4. **按选定渠道作最终选择。**原创权利和依赖闭合后，确定 GPL-3.0-or-later 或 AGPL-3.0-or-later，补根 LICENSE、范围说明、贡献规则和第三方排除项；同时对照真实渠道／账户协议和安装信息条件。正式发布前再固定最终源码与产物、完成必要签名和加密申报核查。本页本轮不代替此决策。

本轮文档核验范围：固定官方许可／归档重取、指定 hash 对比、现有声明和打包脚本静态审阅、锁文件／本地包元数据缺口统计、字体 cmap／vendor name 表只读检查、Font Logos 固定 release 字节与历史授权追溯、相对链接与空白检查。未运行 SDK 构建、未安装依赖、未改源码／工作流／许可证、未提交或发布；未执行的全量 SBOM、逐包许可扫描、商店／签名／真机核验均不报通过。

## 7. 本轮锁定快照

以下 SHA-256 仅标识本页所审输入，不能代替源码 commit、签名或最终产物 hash。后续依赖变化须重审相应条目。

| 输入 | SHA-256 |
| --- | --- |
| `validation/flutter/pubspec.lock` | `58f7cc3fd81236889bda05d601c92119e4904085404792e966df9ca6ccda4f51` |
| `validation/tauri/package-lock.json` | `44f29651818b66a0999fa8be850eae259a86c4144d98d797402b036115bfbece` |
| `validation/tauri/src-tauri/Cargo.lock` | `bdedab5ae2288e3b70dbd92aedf0de697279017099671f8f51da06777349f32d` |
| `validation/transport-rust/Cargo.lock` | `e380aa4977bde400421d67452b66cca6ac5cb5ec459ad4a7f7460ca90d147721` |
| `validation/native/sources.json` | `97c1181f296976088fec17452935ef8d3fa483e380128ca9d35b09ae9f8ef35a` |

## 8. 声明材料后续进展

上述审查固定在 `8daf1bc`。随后提交 `007e20d` 增加共享 `FONT-NOTICES.md`、`font-sources.json`、17 份上游许可全文和 13 份来源说明，共 32 份材料。原有 TTF 和两份字体许可的字节摘要沿用原版本。[字体声明](../validation/shared/fonts/FONT-NOTICES.md) · [来源及待核项](../validation/shared/fonts/font-sources.json)

Flutter `007e20d` APK 已逐字核对 35 份字体文件与仓库，含上述 32 份材料。Tauri 可下载包来自 `8daf1bc`，后续集中构建再验新增材料的随包状态。字体来源表仍有 6 项待核内容，平台解析依赖和完整发行材料继续按本页清单推进。[两包验证记录](16-mobile-input-and-config.md)
