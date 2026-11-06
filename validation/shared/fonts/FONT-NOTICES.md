# 字体来源与第三方声明材料

2026-11-06。适用资源仅为本目录 `JetBrainsMonoNerdFontMono-Regular.ttf`，SHA-256：

`f01031f40e48dc29e1112e6b0b0450a2c6cd097f3f35cfff05c55cb311f8034c`

本字体来自 **Nerd Fonts 3.4.0**，固定 commit [`fa7b859994228a9c8759f99c55a8d31ee92a1b5e`](https://github.com/ryanoasis/nerd-fonts/tree/fa7b859994228a9c8759f99c55a8d31ee92a1b5e)，底层是 **JetBrains Mono 2.304**。herdr-pocket 本轮没有改动字体文件、现有 JetBrains 许可或 Nerd Fonts 总许可。默认终端比较继续使用同一份字体字节。

本包补齐已取得的原许可、归属与修改说明；**状态是部分来源核验／声明收集，不是所有 glyph 均已完成权利审查或原生发行已完成**。剩余事项列在末尾及 [font-sources.json](font-sources.json) 的 `pending`。所有原文逐字节保存，含原始 BOM／CRLF；文件 SHA-256 和固定取得 URL 见清单。原许可优先于本说明中的摘要，字体及图标不会因项目选择 GPL／AGPL 而统一改标为该许可。

## 字体与 glyph 集合

依据固定 [`font-patcher`](https://github.com/ryanoasis/nerd-fonts/blob/fa7b859994228a9c8759f99c55a8d31ee92a1b5e/font-patcher) 的 `patch_set`（patcher 4.20.3）和现有 TTF 的非零 cmap 映射逐集合核对。下表的数量是各目的码位集合中存在的映射，**不是独立轮廓来源的逐 glyph 证明，也不能把不同集合相加当作字体总数**。尤其 box drawing 由条件逻辑决定是否覆盖，部分非 PUA 字符也可能来自基础字体。固定 patcher 的 Material legacy 被禁用，未引入任意 custom 字体；不把这些备选路径算作当前已用组件。

| 集合／来源 | 当前版本、作者或权利人 | 目的码位与映射数 | 原许可与修改／来源状态 |
| --- | --- | --- | --- |
| JetBrains Mono | 2.304；Copyright 2020 The JetBrains Mono Project Authors | 基础字母／标点／基础 Unicode | [OFL-1.1 原文](LICENSE-JetBrainsMono.txt)。该原文没有指定 RFN 名称；不虚构额外 RFN。由 Nerd Fonts 修补、命名与嵌入；本项目未再修改 |
| Nerd Fonts 原创与聚合工作 | 3.4.0；Ryan L McIntyre 及贡献者；[固定树](https://github.com/ryanoasis/nerd-fonts/tree/fa7b859994228a9c8759f99c55a8d31ee92a1b5e) | 见其各 glyph 集合 | [现有总许可](LICENSE-Nerd-Fonts.txt)，含其 MIT／OFL 声明；不能代替以下第三方文本 |
| Seti-UI + Custom | vendor `original-source.otf` name version 3.3.0；Seti 的 Jesse Weed 与 Nerd Fonts 贡献者；[生成来源说明](source-notes/svgs-README.txt) | E5FA–E6FF，191 | 固定 audit 标 MIT；保留 [Jesse Weed 2014 MIT](licenses/LICENSE-Seti-0.8.1-MIT.txt) 与 Nerd 总许可。该文本来自 Seti v0.8.1／`6c358eb9…`；**逐 SVG 历史导入版本／作者映射 pending**，不把该参考版本当作整个 custom 集的唯一来源 |
| Heavy Angle Brackets、Progress、条件性 Box Drawing | `extraglyphs.sfd` 为 Hack 3.003 派生容器；Copyright 2018 Source Foundry Authors／Copyright 2003 Bitstream, Inc. | 276C–2771：6；EE00–EE0B：12；2500–259F：160（box 来源分支 pending） | 保留同固定 Nerd tree 的 [Hack MIT／Bitstream Vera／DejaVu 公有领域说明全文](licenses/LICENSE-Hack-MIT-Bitstream-Vera.txt)，以及 Nerd 总许可。不能只看容器名称把本字体全部改称 Hack，也不能忽略其版权头 |
| Devicons | 2.16.0.custom；devicon v2.16.0 `6910f050…`；Copyright 2015 konpa；Nerd Fonts 生成／修补 | E700–E8EF，496 | [Devicon MIT](licenses/LICENSE-Devicon-2.16.0-MIT.txt)；[自定义生成说明](source-notes/glyphs-devicons-README.txt)、[修改 SVG 说明](source-notes/glyphs-devicons-fixed-README.txt)。另含少数 Vorillaz 旧集合，见下一项 |
| Vorillaz legacy Devicons 子集 | Nerd 作者称 default branch ahead of 1.8.0，并自称 1.8.1（**非真实 release**） | 包含于 Devicons，不另计 | [固定 Nerd 来源说明](source-notes/glyphs-devicons-vorillaz-README.txt)；[2026 MIT 原文参考](licenses/LICENSE-Vorillaz-Devicons-reference-MIT.txt)。**精确旧 SVG 子集与该授权的对应关系 pending**；该 MIT 文本本身无作者版权行，不能自行补成已确认的完整归属 |
| Powerline Symbols | vendor 1.000（约 2013）；Copyright 2013 Kim Silkebækken and other contributors | E0A0–E0A2、E0B0–E0B3，7 | [MIT 式许可原文](licenses/LICENSE-Powerline-Symbols-MIT.txt)；[Nerd 修改说明](source-notes/glyphs-powerline-symbols-README.txt)：E0B0／E0B2 增加 7% 边缘条 |
| Powerline Extra Symbols | vendor 自定义 1.200；Copyright 2016 Ryan L McIntyre | E0A3；E0B4–E0C8；E0CA；E0CC–E0D7；2630，共 34 | [MIT](licenses/LICENSE-Powerline-Extra-MIT.txt)；[固定修改记录](source-notes/glyphs-powerline-extra-README.txt)包含新增／简化图形、7% 边缘条、landing platform、版本变更 |
| Pomicons | 1.001；Copyright 2021 Gabriele Lana | E000–E00A，11 | [OFL-1.1](licenses/LICENSE-Pomicons-OFL-1.1.txt)，RFN **Pomicons**；保留归属；当前派生字体主名称未使用该 RFN |
| Font Awesome | 6.5.1.custom；Fonticons, Inc.；由 Nerd Fonts 从 release SVG 自定义生成 | ED00–F2FF，1,487 | SVG 图标来源 **CC-BY-4.0**；[固定生成说明](source-notes/glyphs-font-awesome-README.txt)、[Nerd 所带 Free 许可](licenses/LICENSE-Font-Awesome-Free-vendored.txt)、[实际 6.5.1 上游 Free 许可](licenses/LICENSE-Font-Awesome-Free-6.5.1.txt)；后者版权为 2023，Nerd 所带版本为 2022，二者均原样保留，不覆盖差异。完整 CC-BY-4.0 条款另见 [CC 原文](licenses/LICENSE-Codicons-CC-BY-4.0.txt)。Nerd 进行了选择、字体生成、缩放／排布与重编码，不能因最后容器是 OTF 就略过 SVG 归属；原 Free 文本另区分官方字体 OFL 和代码 MIT，含 RFN Font Awesome |
| Font Awesome Extension | tag v.0.0.3 `bbfbc8c7…`；TTF name version 1.0；Copyright 2017 André Luiz Gava | E200–E2A9，170 | [MIT 全文](licenses/LICENSE-Font-Awesome-Extension-MIT.txt)，固定授权 commit `09d80249…`。vendor 字体与 tag、该 MIT commit 的字体逐字节相同；Nerd 重编码 E000–E0A9 → E200–E2A9 |
| IEC Power Symbols | vendor name Version 1.0；Copyright 2013 Joe Loughry；上游 `4c79c6a8…` | 23FB–23FE、2B58，5 | [MIT 全文](licenses/LICENSE-IEC-Power-Symbols-MIT.txt)；vendor OTF 与该固定 MIT 来源的 OTF 逐字节相同 |
| Material Design Icons | vendor desktop custom font；固定说明最近获取日期 2022-10-06；Pictogrammers／Templarian 和各图标作者 | F0001–F1AF0，6,896 | [Pictogrammers 集合声明](licenses/LICENSE-Material-Design-Icons.txt)和 [Apache-2.0 全文](licenses/LICENSE-Apache-2.0.txt)；[Nerd 修改记录](source-notes/glyphs-materialdesign-README.txt)说明手修 F1522。集合声明明确有各自许可图标；**逐图标例外／作者 NOTICE 映射 pending**，不能将集合声明简写为所有素材无例外 |
| Weather Icons | vendor font 1.100；name 表设计者 Erik Flowers、Lukas Bischoff（v1 Art） | E300–E3EB，228 | [固定 OFL-1.1 原文](licenses/LICENSE-Weather-Icons-OFL-1.1.txt)；源字体 name 表明字体 OFL、代码 MIT、文档 CC-BY-3.0，不把后两者误加给字体。原 OFL 版权年份／RFN 栏有占位符，**精确信息待核**，未擅自填入 |
| Font Logos | 1.3.0；Copyright 2014–2024 Lukas W；上游 `e92426e2…` | F300–F381，130 | **[Unlicense 全文](licenses/LICENSE-Font-Logos-Unlicense.txt)**；实际 release 与 vendor 字体字节一致，详情见下节。Unlicense 不是“无许可”；其本身不强制署名 |
| Octicons | 18.3.0.custom；Copyright 2023 GitHub Inc.；Nerd Fonts 生成／重编码 | F400–F533（有缺口）、2665、26A1，共 310 | [MIT 全文](licenses/LICENSE-Octicons-MIT.txt)；固定 vendor name 表标 `v18.3.0.tar.gz; 3.4.0`；Nerd 选择与重编码、缩放／布局属于已说明的修改 |
| Codicons | 固定 README 0.0.35（vendor name 是生成工具的 Version 1.10）；Microsoft Corporation／vscode-codicons，Nerd Fonts 修补 | EA60–EC1E，439 | **[CC-BY-4.0 全文](licenses/LICENSE-Codicons-CC-BY-4.0.txt)**；[固定 README](source-notes/glyphs-codicons-README.txt)记载 EB40／EB41 手修。上游代码的 MIT 不能替代本次字体／图标 CC 许可 |

Nerd Fonts 的字体组合、重新编码、统一单格宽度、缩放及以上已列具体修补均发生在上游；herdr-pocket 本轮仅添加声明，不重编码、重新生成或编辑该 TTF。这里的归属不是任何作者／品牌对 herdr-pocket 的背书。

## Font Logos 的固定授权证据

- Nerd Fonts 固定 vendor `src/glyphs/font-logos.ttf`：48,592 bytes，SHA-256 `7f0b055275bb3710afee586519884f3e302ec295a2f4ff4158daacf437c49852`。
- 官方 [1.3.0 release zip](https://github.com/lukas-w/font-logos/releases/download/v1.3.0/font-logos-1.3.0.zip)：SHA-256 `53376d5496cfbc78035ca60f58791ba5b2bfec6a9e751ac521aace6acdacb012`；其中 `assets/font-logos.ttf` 与 vendor 逐字节相同。
- zip 中 LICENSE 与固定 `e92426e28ee5bbf4ca328b33e3a393b7a5045f01` [LICENSE](https://github.com/Lukas-W/font-logos/blob/e92426e28ee5bbf4ca328b33e3a393b7a5045f01/LICENSE)逐字节相同；本地全文 SHA-256 `88d9b4eb60579c191ec391ca04c16130572d7eedc4a86daa58bf28c6e14c9bcd`。
- 上游在 2016-03-10 的 [`0b10f1ca…`](https://github.com/Lukas-W/font-logos/commit/0b10f1ca42d323f27d0e41f2f38c695ff28f0eae)已加入 Unlicense，早于 Nerd 2024 年引入 1.3.0。历史 audit 中 `Unlicensed` 的词不能推翻这一原文。
- 版权／公有领域贡献声明与商标不同。固定 [原 README](source-notes/Font-Logos-1.3.0-README.txt)说明品牌图标是各权利人的商标，用来代表相应产品／公司；本字体许可不转让其商标，不表示得到品牌背书。

## 原文与校验清单

所有下列文件均直接保留上游原始字节。`font-sources.json` 记录每份固定原文 URL、完整 SHA-256、文件大小、原文／参考状态，以及实际检查过的 glyph 源字体元数据。`source-notes/` 的 `.txt` 是原 README／历史 audit 的数据副本，不是本仓库本地操作文档，其中相对图片／脚本链接仍按原上游路径解释。

| 原许可文件 | SHA-256 |
| --- | --- |
| [LICENSE-Codicons-CC-BY-4.0.txt](licenses/LICENSE-Codicons-CC-BY-4.0.txt) | `d6239afa918961b465b07bf7411cbe34ff6685854f58553db7966f4881a0211f` |
| [LICENSE-Font-Awesome-Free-vendored.txt](licenses/LICENSE-Font-Awesome-Free-vendored.txt) | `de784a808496d49f5f80dd9d1d6e9a51cff712cfbc339e7c25155631ae3cdb5d` |
| [LICENSE-Material-Design-Icons.txt](licenses/LICENSE-Material-Design-Icons.txt) | `3bae6305bcaa6d10219b999f65c342034c2d40b1c0e8567fa08605e73ccba829` |
| [LICENSE-Octicons-MIT.txt](licenses/LICENSE-Octicons-MIT.txt) | `4f886642f9e8d99eeadd484acdac011c3fde8a338faf52f5ca1408c13b9a9b63` |
| [LICENSE-Pomicons-OFL-1.1.txt](licenses/LICENSE-Pomicons-OFL-1.1.txt) | `cb4797a9745683f287c28833db596e9d68ec43082d59359b3a49c504f0f610ce` |
| [LICENSE-Powerline-Extra-MIT.txt](licenses/LICENSE-Powerline-Extra-MIT.txt) | `544307a58e6826c24145b2af1c3578b53e2e21ae0e6c67ab4c6abd544304d26a` |
| [LICENSE-Powerline-Symbols-MIT.txt](licenses/LICENSE-Powerline-Symbols-MIT.txt) | `46d5355e4734468135d8e4a30d0916292cc4df2b3ec30aa68c866f82497933be` |
| [LICENSE-Weather-Icons-OFL-1.1.txt](licenses/LICENSE-Weather-Icons-OFL-1.1.txt) | `69cdedc8a4f57a30d68e4f045af8b9cce0ec3b1a6e7eec1ad41737c894f26790` |
| [LICENSE-Hack-MIT-Bitstream-Vera.txt](licenses/LICENSE-Hack-MIT-Bitstream-Vera.txt) | `1f61bb7c790c59b4b0ecdf304628b94e42ae4c8020094a8c3da73381ab212623` |
| [LICENSE-Font-Logos-Unlicense.txt](licenses/LICENSE-Font-Logos-Unlicense.txt) | `88d9b4eb60579c191ec391ca04c16130572d7eedc4a86daa58bf28c6e14c9bcd` |
| [LICENSE-Devicon-2.16.0-MIT.txt](licenses/LICENSE-Devicon-2.16.0-MIT.txt) | `121194741d4a915b9f5890fdd6dd95121f9b1f816517c792358d72d7c838d664` |
| [LICENSE-IEC-Power-Symbols-MIT.txt](licenses/LICENSE-IEC-Power-Symbols-MIT.txt) | `11aef1cdf2d58d822e6857e2574870ccc59d4900052bf5c098e319d750e7ac3d` |
| [LICENSE-Font-Awesome-Extension-MIT.txt](licenses/LICENSE-Font-Awesome-Extension-MIT.txt) | `b47b15d771c4507a75ff65beca3a78168d6af4cca9b45177a1aa817139c64ba5` |
| [LICENSE-Seti-0.8.1-MIT.txt](licenses/LICENSE-Seti-0.8.1-MIT.txt) | `d4d2d888c6a0a220a7b0e2d6013cf37539b0e05ef937002b3b33bdb364575b88` |
| [LICENSE-Vorillaz-Devicons-reference-MIT.txt](licenses/LICENSE-Vorillaz-Devicons-reference-MIT.txt) | `508a77d2e7b51d98adeed32648ad124b7b30241a8e70b2e72c99f92d8e5874d1` |
| [LICENSE-Apache-2.0.txt](licenses/LICENSE-Apache-2.0.txt) | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |
| [LICENSE-Font-Awesome-Free-6.5.1.txt](licenses/LICENSE-Font-Awesome-Free-6.5.1.txt) | `0aa8f86525273b2efa4f40f4272a188e187704252170e979dc06879adf68d43c` |

已有两份许可的 SHA-256 保持：`LICENSE-JetBrainsMono.txt` 为 `30f0c136e3c88e422d0791acd97238870f9054a9729bc34cf2ff0d4ed8cac4ad`；`LICENSE-Nerd-Fonts.txt` 为 `1f6ad4edae6479aaace3112ede5279a23284ae54b2a34db66357aef5f64df160`。

## 明确保留的待办

1. 把 Seti／Nerd custom original 的逐 SVG 导入版本、作者与适用声明对应起来；现有 Seti 0.8.1 MIT 是固定参考，不是对所有混合来源的一揽子证明。
2. 将 Nerd 文档所述 Vorillaz 旧 default-branch 子集匹配到精确原始文件与授权。此处固定保留了 2026-04-18 加入的 MIT 文本，尚未证明它与早期 vendor 子集的对应；不据此声称无授权，也不据当前 grant 虚报历史映射完成。
3. 核实 Weather Icons 源 OFL 中占位的版权年份和 RFN；源字体已明确 OFL 和设计者，不能自行补造 RFN 名称。
4. 核实 box drawing 在此 release 构建中采用了基础字体还是条件性 Hack extra 路径；已经保守保留 Hack 完整声明，cmap 数量不证明覆盖发生。
5. 补齐 Material Design Icons 集合声明中所指的各图标例外／作者／NOTICE 对应，尤其不能从上游 root 的 Apache 标记反推所有外来图标已单独核验。
6. 主打包流程后续把本说明、`font-sources.json`、所有原文／支持材料纳入每个平台可获取的发行内容，更新共享哈希与 Flutter assets，并对最终包验证。**本次没有做这项接线，也没有运行／触发 CI 或下载工具链。**

这些 pending 是证据／发行材料范围说明，不是认定发生侵权或要求替换字体。字体字节保持不变时，本次补声明不改变现有渲染对照；若后续换字体，必须另行固定新文件和验收结果。
