# 项目许可证决策提案与逐产物发行审查

日期：**2026-11-10**（2026-11-11 拍板）  
源码基线：`feat/mobile-feature-batch-0011` (`dd02595` / 当前提交)  
前置依据：[`docs/17-license-and-distribution-review.md`](17-license-and-distribution-review.md) · [`docs/04-roadmap.md:118`](04-roadmap.md) · [`docs/56-project-status-and-handoff.md:26`](56-project-status-and-handoff.md) · [`README.md`](../README.md) · [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)

> **决定（2026-11-11）**：维护者拍板采用 **GPL-3.0-or-later**，根目录 `LICENSE` 已写入（gnu.org 权威全文，SHA-256 前缀 `3972dc97`）。本页以下内容保留为决策依据与逐产物审查记录。

---

## 1. 提案目的与决策现状

### 1.1 现状与决策分工
根据 `docs/56-project-status-and-handoff.md:26` 记录：**“仓库根目录尚无项目许可证，逐产物依赖清单和正式分发审查尚未完成”**。`README.md` 与 `docs/05-product-design.md:184` 明确记录了用户的核心开源诉求：
> **“公开开源且希望衍生改动继续开源；五端目标、手机优先桌面紧随；具体许可证按已定开源立场进行依赖与分发审查后确定，不把调查工作转交用户选型。”**

`docs/17` 作为本项工作的专门技术设计文档，给出了**“优先建议 GPL-3.0-or-later，AGPL-3.0-or-later 保留为备选”**的倾向性意见，但明确指出**“本页尚未作最终许可决策，未自动创建根目录 LICENSE，交由维护者拍板”**。

因此，**当前许可证问题的状态为：技术审查已闭环，决策方案已就绪，最终许可证待用户/维护者正式拍板**。本文件作为承接 `docs/58` 之后的正式交付件，系统呈现审查证据、逐产物清单、合规边界与推荐结论，供维护者一锤定音。

---

## 2. 依赖树中的法律边界与传染性深度评估

针对项目依赖树中可能限制客户端分发或反向约束原创代码的关键组件，本次进行了基于实际锁文件、上游源码提交与全文扫描的深度排查：

### 2.1 ZeroTier 依赖与许可状态（已彻底消除侵权与专有传染风险）
1. **`libzt` fork (Change Date 转换机制生效)**：
   - 上游来源：`Ylarod/libzt@7e5d0f99a2de81c45faa28e44289bcd19d933bf2`。
   - 其许可文件 `LICENSE.txt` 明确规定为 Business Source License 1.1 (BSL 1.1)，并指定：
     - `Change Date: 2026-01-01`
     - `Change License: Apache License version 2.0`
   - **审查定论**：今日日期为 **2026-11-10**，已逾越转换日期（2026-01-01）。根据 BSL 1.1 核心授权条款，原 BSL 限制全部终止，该固定版本代码已**无条件自动转为 Apache-2.0 许可**。先前受关注的 BSL 商业使用限制、SaaS 禁止条款不再生效。
2. **`ZeroTierOne` core (MPL-2.0 与 Secondary License 兼容性)**：
   - 上游来源：`zerotier/ZeroTierOne@fc5c3ec22090b5b2a0f274e863651fe9ca489bf4` (1.16.2)。
   - 核心代码（`node/` 与 `osdep/`）采用 Mozilla Public License 2.0 (MPL-2.0)。
   - **Exhibit B 逐文件排查**：对构建工具链实际编译的 49 个 C++ 文件（`node/*.cpp` 及 `osdep/{OSUtils,PortMapper}.cpp`）执行全文扫描，**45 个源文件带有标准 MPL-2.0 头，4 个密码算法文件为 Public Domain（`ECC.cpp`、`Poly1305.cpp`、`SHA512.cpp`、`Salsa20.cpp`），全部 49 个文件均未附带 Exhibit B（即没有任何一处声明 `Incompatible With Secondary Licenses`）**。
   - **衍生与组合结论**：根据 MPL-2.0 §3.3，由于未声明 Exhibit B，MPL-2.0 代码在与其他代码组合构成 Larger Work 时，允许整个 Larger Work 依 Secondary License（包括 GPLv2/GPLv3/LGPLv2.1/LGPLv3/AGPLv3）分发，只需保持 MPL-2.0 代码自身的修改以 Source Code Form 提供。
3. **`ZeroTierOne` nonfree 目录（零污染保证）**：
   - 上游 `nonfree/` 目录属于 Source-Available 专有协议（严格禁止商业使用）。
   - **隔离审查**：经核对 `validation/native/tool/android_zerotier.py`、`zerotier_macos.py` 与 `CMakeLists.txt`，构建系统以精确白名单枚举编译单元，全局显式定义 `-DZTS_DISABLE_CENTRAL_API=1`，**完全未包含 `nonfree/` 目录下的任何源码文件**。

### 2.2 EasyTier 依赖（LGPL-3.0 边界与重链接义务）
1. **EasyTier 核心代码**：
   - 上游来源：`EasyTier/EasyTier@728ba94b5029240add6204eed591f22e4e039e6b`，全套核心采用 `LGPL-3.0-or-later`。
2. **Heeler bridge 与本项目 portable-stream**：
   - `native/easytier` 与本项目 `validation/native/portable-stream` 明确采用 `LGPL-3.0-or-later`。
3. **分发边界与合规要求**：
   - 在 Android 及其他目标中，EasyTier 库被编译为独立的共享动态库 `libheeler_easytier.so`，两套 GUI 宿主分别通过平台动态加载（Android 的 `System.loadLibrary("heeler_easytier")`）或 C ABI 动态链接进行调用。
   - **若客户端选用 GPL-3.0-or-later**：根据 LGPL-3.0 §2(b) 及 §4，Combined Work 可以直接作为整体按 GPL-3.0 分发，此时 GPL-3.0 自动满足 LGPLv3 对下游权利的保护要求，不存在许可冲突。
   - **若客户端选用宽松许可（如 MIT/Apache）**：则必须严格满足 LGPL-3.0 §4(d) 与 §4(e) 的要求，为用户提供重新链接（Relink）或替换该动态库的机制与“安装信息（Installation Information）”。这在具有代码签名强约束的平台（如 iOS）上会带来极大的合规审查复杂度。

### 2.3 russh 0.65.0 本地候选补丁（Apache-2.0 §4 合规）
- 本项目在 `validation/vendor/russh-0.65.0/` 内维护了包含针对 `src/client/mod.rs` 本地 Close 索引释放修复的 90 个文件完整官方包。
- 官方归档缺少根 LICENSE 文件，本项目在同级补齐了规范的 `russh-0.65.0-LICENSE-APACHE`（SHA-256：`cfc7749b…`）与 `RUSSH-NOTICE.md`。
- 补丁及验证脚本 `verify-russh.py` 均完整开源，完全满足 Apache-2.0 §4(b)“保留显著修改说明”与保留原版权声明的要求。

### 2.4 终端字体与图标资产（独立资产随包分发，不受代码许可覆盖）
- 字体 `JetBrainsMonoNerdFontMono-Regular.ttf`（SHA-256：`f01031f4…`）底层为 SIL Open Font License 1.1 (OFL-1.1)。
- 根据 OFL-1.1 §1 与 §5，字体允许作为普通软件包的一部分捆绑分发，且不因宿主软件的许可（GPL/MIT等）而改变自身许可。字体不能被单独售卖，修改名称需注意 RFN。
- 字体所含全部 17 份第三方授权文件与 13 份生成来源记录已集中保存在 `validation/shared/fonts/`，两壳打包流程已具备随包校验能力。

---

## 3. 项目开源许可证候选方案对比

结合用户明确授权原则：**“公开开源且希望衍生改动继续开源”**，以下系统比选三组方案：

| 方案 | 拟定主许可证 | 与用户核心意图的匹配度 | 依赖兼容性与技术实现 | 分发合规与应用商店风险 | 推荐结论 |
| --- | --- | --- | --- | --- | --- |
| **方案 A<br>(推荐方案)** | **GPL-3.0-or-later** | **极高**<br>彻底保证下游在分发修改版客户端或桌面包时，必须向使用者完全开源其改动；杜绝他人闭源二次打包与商业套壳。 | **完美兼容**<br>- 吸收 Apache-2.0、MIT、BSD、ISC 等所有主要宽松库；<br>- 自然衔接 EasyTier 的 LGPL-3.0-or-later；<br>- 合法利用 MPL-2.0 §3.3 Secondary License 路径合并 ZeroTier 核心。 | **中（可控）**<br>- 源码与自编译分发完全顺畅；<br>- 测试 APK / 桌面安装器无阻碍；<br>- iOS App Store 需评估 FSF 与 Apple 协议的长期兼容实践（已有 VLC、Signal、Wire 等成功先例）。 | **强烈推荐（首选）** |
| **方案 B<br>(严格网络隔离)** | **AGPL-3.0-or-later** | **偏高，但超出了客户端定位**<br>§13 要求只要通过网络交互就必须向远端提供对应源码。 | **技术上可行，但界限极度模糊**<br>易引发使用者恐慌：是否客户端连接远端 herdr 会导致远端原版 herdr 或用户运行的服务端逻辑也被“传染”开源？ | **偏高**<br>应用商店与下游生态对 AGPL 客户端审查更严苛，且本项目本质是前端客户端，并非 SaaS 托管服务。 | **不推荐**（过度设计，产生不必要的协议争议） |
| **方案 C<br>(宽松许可)** | **Apache-2.0 或 MIT** | **不匹配**<br>完全违背了用户“希望衍生改动继续开源”的初始授权指令，允许下游厂商随意修改后闭源发布商用包。 | **复杂且被动**<br>由于含有 LGPL-3.0-or-later 模块（EasyTier），必须为整个客户端建立繁重的 LGPL §4(d) 动态替换和安装信息豁免材料，徒增合规成本。 | **低（但失去开源保护目的）** | **明确否决**（违反用户指示与防套壳初衷） |

---

## 4. 推荐方案、依据与风险矩阵

### 4.1 核心推荐结论
**建议维护者正式确定选定方案 A：`GNU General Public License v3.0 or later` (GPL-3.0-or-later) 作为 herdr-pocket 原创客户端代码与文档的主许可证。**

### 4.2 推荐依据
1. **契合用户最高意志**：满足“衍生改动继续开源”的核心要求，确保社区、商业公司对该客户端的任何二开或重新打包分发行为都必须对最终用户开放源码，有效防御恶意套壳与闭源分发。
2. **打通全链路依赖法律边界**：
   - 完美承接 EasyTier 和 portable-stream 的 `LGPL-3.0-or-later`，使整个客户端作为一个完整的 Combined Work 具备统一的强保护伞，下游无法剥离保护。
   - 依据 ASF（Apache 软件基金会）官方结论，Apache-2.0 代码完全兼容 GPLv3，可安全作为子模块编入 GPLv3 最终作品。
   - 依据 Mozilla 官方 FAQ Q14，无 Exhibit B 的 MPL-2.0 代码在并入 GPLv3 作品时合法满足 Secondary License 条款。
3. **界限清晰，不越界干扰远端服务端**：GPL-3.0-or-later 的约束发生在“分发（Convey）副本”环节，纯粹运行 SSH 协议与远端 herdr、Tailscale/ZeroTier 节点交互，绝不会使远端 host 上的原生 herdr 或业务系统被传染。

### 4.3 风险与防范矩阵
- **风险 1：iOS 渠道与 Apple App Store 条款摩擦**
  - *分析*：Apple 开发者协议中的使用限制与 GPLv3 §6 关于“安装信息（Installation Information）”与自由再分发权存在理论讨论。
  - *防范*：在实际提交 App Store 前，维护者若需要可在客户端版权声明中附加 GPLv3 认可的“附加权限（Additional Permissions under GPLv3 §7）”声明，豁免通过 Apple 官方应用商店分发的签名限制（如 VLC iOS 采用的豁免条款），或保留 TestFlight / 侧载测试渠道优先分发。
- **风险 2：误将第三方代码整体改标**
  - *防范*：在主 LICENSE 和随包说明中明确列出《第三方专有/独立许可证声明》，严格声明第三方代码（MIT、Apache、OFL 字体等）继续适用其原始授权，GPL-3.0 仅适用于本项目团队拥有版权的原创代码与整体组合。

---

## 5. 逐产物第三方依赖与许可清单

详见根目录已正式落地的 [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。为满足发行审查标准，此处汇总其统计元数据：

### 5.1 依赖按产物与许可证分布统计

| 目标产物 | 依赖总数 (去重) | 主要许可证分布 | 来源锁文件依据 |
| --- | --- | --- | --- |
| **Flutter 壳 (Dart)** | 34 个直接/传递包 | BSD-3-Clause (22), MIT (6), Apache-2.0 (4), 复合/BouncyCastle (1: pointycastle), Flutter SDK (1) | `validation/flutter/pubspec.lock` |
| **Tauri 壳 (npm)** | 55 个 (生产 3, 开发 52) | 生产：Apache-2.0 OR MIT (1), MIT (2)；开发：MIT (35), Apache-2.0 (3), MPL-2.0 (13), ISC (1), BSD-3 (1) | `validation/tauri/package-lock.json` |
| **Tauri 壳 (Rust 宿主)** | 517 个 crates | MIT/Apache (388), Unicode-3.0 (18), Zlib族 (15), MPL-2.0 (5), BSD-3 (5), ISC/环 (2), 未确认/目标特定 (148) | `validation/tauri/src-tauri/Cargo.lock` |
| **共享传输层 (transport-rust)** | 231 个 crates | MIT/Apache (158), Unicode-3.0 (18), BSD-3 (3), ISC/环 (2), 未确认/目标特定 (34), 本地 (4) | `validation/transport-rust/Cargo.lock` |
| **Flutter 网络运行时** | 232 个 crates | 与 transport-rust 基本一致，增加 `jni 0.21.1` (MIT/Apache) 与平台绑定 | `validation/flutter-network-runtime/Cargo.lock` |
| **三网络 Native 候选库** | 5 个子工程与原生库 | BSL 1.1 → Apache-2.0 (libzt), MPL-2.0 (ZeroTierOne core), BSD-3 (lwIP/tsnet), LGPL-3.0+ (EasyTier) | `validation/native/sources.json` 等 4 个来源 JSON |
| **Android 原生辅助库** | 3 个 Maven artifact | MIT (Bouncy Castle 1.86), Apache-2.0 (ZXing Embedded 4.3.0, ZXing Core 3.5.3) | `validation/pairing/sources.json` 等 |
| **主机端配对工具 (Helper)** | 4 个 Python 包 | Apache-2.0 OR BSD-3-Clause (cryptography), MIT-0 (cffi), BSD-3-Clause (pycparser, qrcode) | `helper/requirements.txt` |
| **终端字体与图标资产** | 1 个 TTF (含 17 个子集) | OFL-1.1 (JetBrains Mono 等 3), MIT (7), CC-BY-4.0 (2), Apache-2.0 (1), Unlicense (1), PD (1) | `validation/shared/fonts/font-sources.json` |

---

## 6. 原生补丁归属与衍生条款审查

本仓库对第三方原生库的所有改动全部以独立 `.patch` 文件或独立子目录形式显式管理，逐项审查结论如下：

| 补丁文件名 | 目标上游仓库与版本 | 上游原许可 | 修改性质与代码规模 | 触发的条款与本项目合规措施 |
| --- | --- | --- | --- | --- |
| `0005-native-safety.patch` | `Ylarod/libzt` (Change Date 后的 Apache-2.0) | Apache-2.0 | 有界事件队列、所有权 RAII 管理与驱动退出（44 KB） | **Apache-2.0 §4(b)**：要求带有修改声明。补丁内完整保留原版权并标注修改记录。 |
| `0006-strict-offline-identity.patch` | `ZeroTierOne` (1.16.2) / `libzt` | MPL-2.0 (`Identity.cpp`) / Apache-2.0 | 严格离线公私钥对生成与内存敏感值擦除（3.4 KB） | **MPL-2.0 §3.1**：修改属于 Modifications，必须以源码形式提供。补丁完全公开于源码树。 |
| `0007-defined-ecc-shifts.patch` | `ZeroTierOne` (1.16.2 `node/ECC.cpp`) | **Public Domain** (原作者 Matthew Dempsky / DJB) | 修复 28 处有符号数负数移位未定义行为（3.8 KB） | **Public Domain**：无著作权限制。补丁保留了上游原作者的公共领域声明。 |
| `0008-streams-and-hp-boundary.patch` | `lwip` (32708c) & `libzt` | BSD-3-Clause (`lwip`) / Apache-2.0 (`libzt`) | lwIP 流生命周期绑定与并发安全隔离（42 KB） | **BSD-3 / Apache-2.0**：均要求保留原版权声明与修改说明。已通过三轮独立安全评审入档。 |
| `0009-closed-port-rst.patch` | `lwip` (32708c `tcp_in.c` / `tcp_out.c`) | BSD-3-Clause | 针对关闭端口发送 RST 的标准协议栈行为补充（1.8 KB） | **BSD-3-Clause**：保留原始瑞典计算机科学研究所版权声明，补丁完全公开。 |
| `0001-portable-stream-handles.patch` | `heeler-overlay-natives` (`native/easytier`) | **LGPL-3.0-or-later** | 将 OS 描述符改为 `uint64_t` 句柄抽象，消除跨平台阻断（25 KB） | **LGPL-3.0 §2**：对库本身的修改必须遵循 LGPL-3.0-or-later 开源。补丁与配套 Rust 库均完整开源。 |
| `0002-tsnet-explicit-auth.patch` | `tailscale.com` (v1.104.1) | BSD-3-Clause | 禁用 ambient 凭据与自动发现的嵌入式受控入口（2.9 KB） | **BSD-3-Clause**：保留 Tailscale 原始版权与三条款免责声明。 |
| `terminal_view-0.5.0-combining.patch` | `terminal_view` (0.5.0, Termphin) | MIT (源自 xterm.dart MIT) | 终端组合重音字符与选择器修复（候选补丁） | **MIT**：保留 Termphin 与 xuty 原始版权；随包提供上游 LICENSE 和 NOTICE。 |
| `terminal_view-0.5.0-ime-observation.patch` | `terminal_view` (0.5.0) | MIT | 针对移动端输入法的观测探针 | **MIT**：保留上游版权，源码公开。 |
| `russh-0.65.0-local-close.patch` | `russh` (0.65.0, Pierre-Étienne Meunier) | Apache-2.0 | 本地关闭通道时收敛 client sender 索引（3.1 KB） | **Apache-2.0 §4(b)**：随包附带 `RUSSH-NOTICE.md` 说明修改内容与上下文，附带完整 Apache 全文。 |

---

## 7. 字体声明与未确认项 (Pending Items)

依据 `validation/shared/fonts/font-sources.json` 记录，字体归属绝大部分已闭合（含 Font Logos 1.3.0 的 Unlicense 授权追溯），目前明确登记的 6 项待确认事项如下：

| 编号 | 涉及项目与码位范围 | 现状说明与已查证文件 | 为什么当前标为“待核” (Pending) | 后续闭合条件 |
| --- | --- | --- | --- | --- |
| **PEND-0** | Seti-UI + Custom<br>(`U+E5FA`–`U+E6FF`, 191 字符) | 仓库已收集 Jesse Weed 的 2014 MIT 许可（`licenses/LICENSE-Seti-0.8.1-MIT.txt`）及 `svgs-README.txt`。 | 上游 Nerd Fonts 将其与自制 custom 图标混合生成 `original-source.otf`。固定 MIT 文本来自 Seti v0.8.1，尚无法做到逐个图标一一映射到历史具体 commit 的贡献者。 | 维持当前声明；作为参考许可随包交付，标注其包含部分 custom 图标。 |
| **PEND-1** | Vorillaz legacy Devicons<br>(包含于 Devicons 集合中) | 仓库已收集 `licenses/LICENSE-Vorillaz-Devicons-reference-MIT.txt` 及来源说明。 | 上游 Nerd 描述其来自 `1.8.0` 之后的开发分支，并自称 `1.8.1`（非官方真实 release），该 MIT 文本本身缺少作者具体版权行。 | 在正式分发前核对上游 release 归属，维持当前参考归属声明。 |
| **PEND-2** | Weather Icons<br>(`U+E300`–`U+E3EB`, 228 字符) | 仓库已收集 `licenses/LICENSE-Weather-Icons-OFL-1.1.txt`，源字体明确字体部分为 OFL-1.1。 | 上游 vendored OFL 文本中的版权年份和 RFN 字段存在原作者遗留的占位符（如 `<dates>`, `<Reserved Font Name>`），本项目不擅自代其填写虚构内容。 | 维持原样保留上游带占位符的真实文件，以嵌入的作者（Erik Flowers 等）信息为准。 |
| **PEND-3** | Box Drawing 条件分支<br>(`U+2500`–`U+259F`, 160 字符) | 仓库已收集 Hack MIT/Bitstream Vera 许可（`licenses/LICENSE-Hack-MIT-Bitstream-Vera.txt`）。 | Nerd patcher 对制表符存在条件分支逻辑，仅凭当前 TTF cmap 映射无法 100% 证明该 160 个轮廓究竟全部继承自 JetBrains Mono 还是部分被 extraglyphs 覆盖。 | 需通过字体编辑工具对比轮廓点坐标确认；目前双重保留两份许可，合规无阻断。 |
| **PEND-4** | Material Design Icons 逐图标例外<br>(`U+F0001`–`U+F1AF0`, 6,896 字符) | 仓库已收集集合声明 `LICENSE-Material-Design-Icons.txt` 及 `LICENSE-Apache-2.0.txt`。 | Pictogrammers 集合声明指出极少数特定品牌/合作图标可能附带第三方原始作者说明，集合声明本身不是逐图标的展开表。 | 不影响整体 Apache-2.0 分发；后续若需商业商标深度排查再按品牌筛查。 |
| **PEND-5** | 原生包内随包资产自动化校验 | 共享 Python 校验器 `android_notices.py` 已验证 3 份 Android 资产，Tauri `js_notices.py` 已校验 2 份 JS 资产。 | 完整多平台最终发布包（包含全部 17 份字体授权文件和 Rust notices）的包内自动化比对机制尚未接入每次 CI release 流水线。 | 在正式签名/发布流水线中接入最终完整包内容扫描。 |

---

## 8. 构建工具链与校验和索引

本项目的构建与验证依赖严格锁定的多语言工具链，避免隐式升级导致的编译器/运行时法律与技术漂移：

### 8.1 编译器与 SDK 锁定基线

| 工具链组件 | 锁定版本 / 镜像标识 | 依据文件 | 说明与约束 |
| --- | --- | --- | --- |
| **Flutter SDK** | **3.47.9** (`c197ca5199e9ee5661e865596c9c07294dfab51c`) | `docs/17:25`, `docs/57:147`, CI configs | 严格要求回前台 `paused→hidden→inactive→resumed` 生命周期转态 |
| **Dart SDK** | 3.13.7 (随 Flutter 3.47.9 绑定，约束 `>=3.11.0 <4.0.0`) | `pubspec.lock:268` | 语言规范与核心运行时 |
| **Rust 工具链** | **1.95.0** (Native 库) / **1.96.0** (Tauri/Transport/SSH) | CI workflows (`rustup install 1.95.0/1.96.0`) | 1.95 用于 Heeler/EasyTier 兼容，1.96 用于 Rust 2024 edition |
| **Node.js** | **22.22.2** (CI) / `>=22.12.0` (engines) | `package.json:7`, CI workflows | 前端构建与测试运行时 |
| **Go 编译器** | **1.27.1** / **1.27.3** | `validation/native/sources.json`, CI | 编译 Tailscale tsnet `c-shared` 原生库 |
| **Google Protoc** | **36.2** (Linux/Darwin/Windows 独立哈希) | `validation/native/sources.json` | EasyTier protobuf 协议代码生成 |
| **Android NDK** | **28.2.13676358** | CI workflows (`ndk;28.2.13676358`) | arm64-v8a 原生库交叉编译工具链 |
| **Android SDK / API** | **platforms;android-35**, **build-tools;35.0.0** | CI workflows | Android 15 (API 35) 目标平台与构建工具 |
| **Java / JDK** | **17.0.18+8** (Temurin / setup-java v4) | CI workflows | Gradle 构建与 Android DEX/AAR 编译 |

### 8.2 关键锁定文件校验和索引 (SHA-256)

以下为当前工作副本的精确哈希，作为本审查交付件的物料基准：

```
58f7cc3fd81236889bda05d601c92119e4904085404792e966df9ca6ccda4f51  validation/flutter/pubspec.lock
7c2babe5db5a4b60687f2cdef95d6fa1a196a0c229f4e6a2bd46e469e4bd6d05  validation/tauri/package-lock.json
f767c2fa6f32a173b7ec3404c91088572661e3a6af89a6ac85955c55c24b6c84  validation/tauri/src-tauri/Cargo.lock
4a07e8eb34acf45f0c8c6b0bd5146799300e6289c3f0f93a4541fde03e526870  validation/transport-rust/Cargo.lock
e261ad5d70ac1451d00403a215bec37742ed046c5a4986dcb769c943cb61518c  validation/flutter-network-runtime/Cargo.lock
a773978d92f52f111527d75769f943922cf508b3bd9a62c507313eab01b6aeaf  validation/ssh/Cargo.lock
12bf1a7f0f0bd221958043b8079a9571c9f62d9892bbbfe151b85b3cc2b80637  validation/android-network-source/Cargo.lock
1bf3b49be1d54a61d1a0bf9e308ac2154ed0e44dbf85d141094076afd681bada  validation/native/portable-stream/Cargo.lock
8aa1e0d2c32735ab14ffb6cf4cfc98a07bba049d68dd6d1f13192e47b2e02b3a  validation/overlay-runtime/Cargo.lock
684d2fced643a9234e308dcbc988fd44670517080caf05cc46ae9eea9610e94b  validation/native/sources.json
d81461c86b93d33e919aee0354fde4501b7fbaf58cca48b208b30c077cef4bf4  validation/native/zerotier-candidate.json
3ee0f42d20f1e27f744d8f8d85dce1ebb5cd982cd3abd32b48b0c9c98259cad3  validation/flutter/patches/manifest.json
f01031f40e48dc29e1112e6b0b0450a2c6cd097f3f35cfff05c55cb311f8034c  validation/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf
0dd7b286ab499ce131e6c60cab8afaf146487da5b3e6f8916aaa2d4efd531739  validation/shared/fonts/FONT-NOTICES.md
c51ec2056b07a181819eeeb496681255f7ca470ff566946157c7b33393d40dbf  validation/shared/fonts/font-sources.json
```

---

## 9. 维护者决策建议与下一步操作指引

### 9.1 当前决策项
请维护者审阅本提案并确认选择：
- **[推荐选定] 批准方案 A (GPL-3.0-or-later)**：将正式的 GNU General Public License v3.0 全文写入仓库根目录 `LICENSE`，并为原创代码添加标准头部声明。
- **[备选方案] 选择方案 B (AGPL-3.0-or-later)**：如维护者预期未来客户端可能整体转化为多租户 Web 托管服务且要求云服务也必须开源，则落地 AGPLv3。

### 9.2 决策生效后的落地步骤
1. 用户选定后，创建根目录 `LICENSE` 文件（复制自 FSF 官方 GPLv3 全文，如 `validation/native/portable-stream/COPYING-GPL-3.0`）。
2. 在 `README.md` 的开源发布门槛章节回填主许可证链接。
3. 在 CI 发布构建中，将 `THIRD_PARTY_NOTICES.md`、`LICENSE` 以及字体/Rust notices 打包进发布归档中，完成逐产物许可证审查的闭环。
