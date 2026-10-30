# Flutter 终端验证壳

2026-10-30：最小 **本地 fixture 验证壳**，不是可连接 herdr 的产品。实际编译结果以 [Flutter Actions](https://github.com/Luck9Star/herdr-pocket/actions/workflows/flutter-validation.yml) 对应提交为准；真机字体、IME、选择、性能、真实 SSH 与三网络均未验证。

## 固定输入与边界

- Flutter **3.47.9**，源码提交 `c197ca5199e9ee5661e865596c9c07294dfab51c`；终端 `terminal_view: 0.5.0`，MIT。
- 两路线共用 [`../shared/fixture.json`](../shared/fixture.json)、同一 TTF 与 4096-byte 负载块；80×24 cells、14px 字号。手机视口 390×844，桌面 1440×900；同设备和系统字体回退仍须人工记录。
- 输入接收端只有本地有界字节记录器。UTF-8 hex 是“已交给本地 sink”，不是 SSH 已发送或命令已完成。
- 每个焦点/模式 epoch 重建终端输入连接，并重新显示 fixture full，以阻止旧 IME 回调进入新焦点。**因此当前壳不保留模式切换前的滚动历史**；这是需要真实流接入后消除的验证壳限制，不是产品设计。
- `autoResize: false` 且没有远端 resize 入口；窗口/键盘变化只改变可见空间。
- 输出队列上限 65536 bytes；溢出丢弃本轮观察并等待显式新 full，不带损坏画面继续输入。负载消费计量为解析器提交，不代表 GPU 完成绘制，不能据此比较整 App 性能。
- 本壳不读取 SSH 配置、凭据、私钥，不建立网络，不修改主机授权。

## 云端构建

工作流先在 Ubuntu 上生成临时平台工程、解析一次依赖锁并运行 analyze/tests，再让五端构建任务下载**同一个 lock**并使用 `--enforce-lockfile`。应用 `pubspec.lock` 已从 run 40982743142 取回并核对 terminal_view 归档 hash 后落库；构建脚本使用该锁并 `--enforce-lockfile`。锁 SHA256 为 `5b3979bec9c6487bb79f9bba82e66908fe735248923aeced14568cb101c9fa99`。首轮错误模板锁已排除，见来源记录。

平台脚手架只在 runner 临时目录生成，未将完整 SDK/平台模板安装到本机。`ci.py bootstrap` 在非 GitHub Actions 环境拒绝执行。

| 产物 | 安装/验证范围 |
| --- | --- |
| Android debug APK | 开发签名，仅测试；下载安装后才能确认设备运行 |
| iOS device `.app` | `--no-codesign` 编译产物，**不能直接安装真机**；还缺签名与实际设备 |
| macOS debug `.app` | 测试构建；未公证，实际启动和门禁提示待验 |
| Windows Debug 目录 | 需对应运行时，启动待验 |
| Linux debug bundle | 需 GTK 及目标 ABI 环境，启动待验 |

每个包附源提交、Flutter 提交、fixture/lock/产物 SHA256 与范围说明。Apple/Linux 使用 tar 保留 framework 符号链接与执行位。不会发布 release、合并 main 或提交商店。

已具备 SDK 的开发环境可手动复跑（没有 SDK 时直接使用 Actions）：

```sh
python3 validation/flutter/tool/ci.py prepare --destination /tmp/herdr-flutter-probe
cd /tmp/herdr-flutter-probe
flutter pub get
flutter analyze
flutter test
flutter run
```

目标目录必须不存在，脚本拒绝覆盖。重新跑用新的临时路径。

## 同设备人工测试

1. 下载相同源提交两路线产物，记录设备、系统、字体 SHA、输入法/键盘、视口。查看默认观察，输入键不得增加 sink 计数。
2. 点击“逐键”，使用真实中文输入法组合/取消/提交；组合期间 sink 不增，提交后 UTF-8 只出现一次。依次输入共享 `inputCases`，比较 hex。
3. 测试 Esc、Tab、方向、Ctrl-C/D、回车、硬件组合键。当前仅记录字节；vim/top 等真实 TUI 待 SSH 链路接入后测试。
4. 长按拖选、复制选区；点击“粘贴”或 Ctrl/Cmd-V，确认预览、取消和发送；草稿发送不额外加回车。手机键盘展开/收起，检查 80×24 契约未改变。
5. 中文组合期间切换标签/焦点/模式，提交不得进入新目标。宽度 ≥960 可开启本地分屏；窄窗只显示当前目标。
6. 隐藏后返回，输入保持禁用，点击“获取新 full”再显式逐键。注入未知/断线，恢复后先人工核实，确认 sink 计数没有自动增加。
7. 跑“1 MiB paced”；再注入“慢消费者 / 溢出”，确认 peak ≤65536 且恢复前不可输入。结果记录到共享矩阵，分别记构建、安装、运行和设备测试。

## 尚未具备

真实 SSH host-key/session 绑定与 herdr observe、三网络原生桥、真机性能采样、手机配对及加密迁移都没有被这个 fixture 壳实现。它们不能因本壳编译或单元测试通过而改为“已验证”。`terminal_view` 的 Unicode 宽度表、emoji grapheme、SGR 支持与系统 fallback 需运行同 fixture 后判定；没有预先认定其优于 xterm.js。
# 组合字符渲染诊断

Mac GUI smoke 发现分解重音 `e\u0301 A\u030a n\u0303` 看起来只有基字符。固定 `terminal_view 0.5.0` 源码中 buffer 将零宽字符存入 `getCombined`，`getText` 保留它们；`TerminalPainter._paintLineForeground` 的 ASCII 批处理却只采集基字符，未检查/传递 combined。新增 `diagnostic/combining_render_test.dart` 用同一字体、真实 buffer 和 painter 写入输入/复制 API codepoints、cursorX、两张 PNG 与像素对照 JSON，直接验证该假设。

诊断在独立 `render-characterization` CI job 中运行；可见重音与基字符像素相同时 job 必须失败，不能称字符正确性通过。五端包构建不依赖此诊断 job，便于继续设备比较。源码检查/目视现象不替代 CI 诊断结果；该诊断也不等价于原生剪贴板或系统 IME 验证。尚未对上游做补丁或改换终端引擎。
