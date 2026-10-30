# terminal_view 0.5.0 组合重音实验补丁

2026-10-30。当前是固定来源的候选补丁，未改变默认依赖，也没有选择 UI 框架。云端结果取得前，下面仅说明实现、可追溯性和已执行的本地脚本检查。

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
