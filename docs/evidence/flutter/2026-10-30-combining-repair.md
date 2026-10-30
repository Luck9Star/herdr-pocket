# terminal_view 0.5.0 组合重音实验补丁

2026-10-30。当前是固定来源的候选补丁，未改变默认依赖，也没有选择 UI 框架。Ubuntu 与 macOS 云端绘制回归已通过，来源、修复范围和实际验证边界见下文。

## 来源与修复范围

- [pub registry](https://pub.dev/api/packages/terminal_view) 当日最新仍为 `0.5.0`，发布时间 `2026-10-14T20:07:05.918443Z`。
- [官方 0.5.0 archive](https://pub.dev/api/archives/terminal_view-0.5.0.tar.gz) SHA256：`5f8cf2e999b9b98224430b7ef2a32d378062073fa4e566f1f52d89ac9d9ac9cf`，本轮重新下载并核验。
- [上游当前 head](https://github.com/Termphin/terminal_view/commit/29c3c0893bd8ca3a10ec4535cdf23728358e9426) 的 `painter.dart` 与 archive 完全同 SHA256 `3d482e223a21ec62cb690006b46178c1c58b7a95ff5747d13479dfa82af00258`；未发现已经发布的修复，不直接升级候选。
- Context7 `library terminal_view` 仍只返回不相关库；没有冒用这些条目作接口证据。此次依据上述固定官方源码，并沿 graph 找出 painter、光标与选区调用路径。

补丁文件：`validation/flutter/patches/terminal_view-0.5.0-combining.patch`；SHA256 `2d0fb1d7283b034eb8161651f5c1cee0343df2877ebd6863e6639782ad8e5833`。`patches/manifest.json` 同时固定两个文件的修改前后 hash、MIT 许可证与 archive 来源。

1. `painter.dart` 的 ASCII 批处理在首单元或后续单元有 combined suffix 时结束批次，转入已有完整 grapheme cell 绘制路径。普通 ASCII 仍走批处理。
2. 光标和选区覆盖颜色绘制复用同一 grapheme 方法；`render.dart` 为真实 buffer 单元传入 combined。光标若显示 overlay cell，不借用底层 buffer 的 suffix。
3. 不改 parser、字符存储、列宽、SGR 内容、输入文本或共享 fixture；不将输入预组合。NFC 仅用作测试图像参照。没有修改系统 pub cache 或用户原工程。

## 隔离集成

`candidate.py apply --destination APP` 只接受 CI `RUNNER_TEMP` 内、带 `ci.py prepare` 标记的新工程；核验 archive、patch 与每个修改文件前后 hash，再写独立 `pubspec_overrides.yaml` 指向 `candidate/terminal_view`。上游 LICENSE/NOTICE 留在候选目录，并附在候选包 artifact。

首次 `flutter pub get` 后执行 `candidate.py verify-lock --destination APP`；除 terminal_view 改成显式 path 来源外，每一个 transitive dependency block 必须与已提交基线 lock 相同。独立工作流保存候选 lock，五端构建消费同一 lock 并 enforce；默认基线工作流继续保留原始失败。

## 验证安排与边界

新增 9 项真实绘制回归：分解重音对 NFC 同字体字形与位置；ASCII 邻接；宽 CJK 邻接；SGR 粗体红色与 inverse；普通 ASCII 对独立 Flutter TextPainter；缓存录制后单独收到重音；实际 TerminalView 的聚焦 block cursor 和选区前景覆画。另重跑原有 6 项 gate/模拟 IME 测试和原始真实 painter 诊断。

所有用例保留输入与 buffer 原码点/列宽，并输出实际图像。CJK 邻接用例只证明该 test-engine 的两参考布局一致，不证明 CJK fallback 具体字形正确；可能使用相同缺字方框。原生系统剪贴板、设备 IME、触控、性能、复杂 emoji/全部 grapheme 和全 Unicode 支持仍未验证。此次不会启动 GUI 应用。

已执行：Python 脚本语法检查；4 项路径/覆盖拒绝、archive hash 拒绝和 transitive lock 漂移拒绝测试通过；在私有临时目录完成官方 archive 的真实补丁应用，修改后文件 hash 全部匹配，原 lock 字节未变。没有本地 Flutter SDK，因此不把这些检查称为 Dart 编译或绘制通过。

## 实测结果：Ubuntu 与 macOS 无界面绘制通过

[候选运行 40993758160](https://github.com/Luck9Star/herdr-pocket/actions/runs/40993758160)，源码 `e216eb1db83e562cbff5c128cc9eedcc293203cf`：Ubuntu 的 archive/patch/锁检查、分析、原有6测试、原始真实painter诊断以及9项新增回归全部通过；macOS云runner使用相同候选锁再次运行原诊断与9回归，也全部通过。9回归包含10组图像比较（缓存用例比较两帧）。五端包构建结果需另外判断。

- [Ubuntu 原始报告与校验](repair-e216eb1/ubuntu/verification.json)：原始诊断 base=138、marked=169 非透明像素；所有 NFC/独立 TextPainter 图像比较一致，原码点与列宽保持，光标/选区各有59个白底和6个黑字像素。
- [macOS 原始报告与校验](repair-e216eb1/macos/verification.json)：base=155、marked=193；10组比较同样一致，光标/选区各有49个白底和7个黑字像素。跨操作系统抗锯齿不同，不要求两OS的PNG完全相同。
- Ubuntu candidate 组合PNG SHA256 `58ec65d6fbb0bab48b413fde40388f9dd3f078b014853f673d69177414141662`；原始未修复PNG `0faf2a8446a0c0b62d0f4442048367910242f99f14c06aa5b22ca1f42ff74cd7` 保留。已人工查看 candidate 重音与光标图片，没有打开GUI App。
- candidate lock SHA256 `8061fdb6e4fb277952fe6b987de4740fac7bc9db7532e6feeba78e6e08eb9ba0`。除 terminal_view 的显式 path 来源外，所有**package blocks**与基线一致；SDK footer 的 Flutter 最低约束从 `>=3.19.0` 变成 `>=3.18.0-18.0.pre.54`。实际使用的 Flutter 仍精确固定3.47.9，候选package自身pubspec没有修改。这是pub重新解析path override后观察到的锁文件元数据差异；未查明内部聚合原因，不声称整个lock只有单一差异。

2026-10-30 Context7 查询官方 Dart 文档确认 [dependency override 会更新锁中的来源](https://dart.dev/tools/pub/dependencies#dependency-overrides)、[Flutter SDK 约束定义](https://dart.dev/tools/pub/pubspec#flutter-sdk-constraints)。后续manifest已收窄措辞为packages-only，并显式保留SDK footer比较；原始下载manifest保持原样，独立verification说明上述差异。

Windows首轮在补丁应用后的文件hash检查失败，尚未执行构建：继承的 `core.autocrlf=true` 导致 git apply 输出 CRLF。在本机私有临时目录复现相同779处CRLF后，归一化hash正好等于预期，确认是材料化脚本问题。修复为仅在该次git调用加 `-c core.autocrlf=false -c core.eol=lf`，不修改任何全局配置、补丁或已验证绘制代码；新增真实Git回归后5项脚本测试通过。Windows修复效果仍以随后CI结果为准。

已下载并核验 [e216eb1 macOS候选包](https://github.com/Luck9Star/herdr-pocket/actions/runs/40993758160/artifacts/12950213273)：archive SHA256 `c20d9377ea277f16f66ad29467613735ee403853d0ca853e50fdf347ff31c502` 与manifest一致；含App可执行文件、候选来源与上游LICENSE/NOTICE。仅检查archive，没有启动、安装或做本机GUI smoke。[下载核验](repair-e216eb1/macos-download-verification.json)

Windows材料化修复提交 `c27535d3ed7174ad7b722d9e086ee59e9db11f5d` 的[复跑 40994503435](https://github.com/Luck9Star/herdr-pocket/actions/runs/40994503435)已通过Windows归档/补丁hash核验及完整构建；Ubuntu常规与绘制回归、Mac无界面回归也再次通过。[该次candidate manifest](repair-e216eb1/candidate-manifest-c27535d.json)真实包含package-only比较与SDK footer差异，补丁hash及候选lock hash均未变。其余包以对应job最终结果为准。

最终复跑已全部结束：[40994503435 / c27535d](https://github.com/Luck9Star/herdr-pocket/actions/runs/40994503435) 的 Ubuntu补丁与测试gate、macOS无界面绘制检查以及 **iOS unsigned、Android、Windows、macOS、Linux 五个候选构建全部成功**。八个artifact（含锁、两份绘制证据及五端包）已由API确认存在、未过期；[完整job及下载链接](repair-e216eb1/final-c27535d-ci.json)。这些通过项不扩展为手机IME/触控、真实GUI重新验收、完整Unicode或远端链路通过。
