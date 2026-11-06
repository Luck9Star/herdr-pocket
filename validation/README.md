# herdr-pocket 验证入口

2026-11-06 两个 Android API 35 的正式 GUI 路径都通过设备签名、主机看板与持续观察。[最新两份 APK、SHA 和实际运行记录](../docs/15-mobile-gui-validation.md)。

2026-11-05 手机工作台已接入 GUI 配对审查、设备签名、主机目录、多标签与持续观察。当前实现、两份 Android 基线包、失败及尚待实测的项目见[手机配对工作台](../docs/14-mobile-pairing-workbench.md)。

2026-10-30 看板、持续观察、配对与设备密钥结果及测试包见 [M1b 记录](../docs/13-mobile-dashboard-observe.md)。Penpot v2 视觉基线见 [UI v2 记录](../docs/11-ui-v2-integration.md)。下方前阶段测试包保留各自源码版本，不能当作新版已验收。

> 修复测试请先看[最新候选与验收记录](../docs/10-blocker-repair.md)。原baseline包保留原结果；带组合重音修复的是本项目experimental-patched候选，并非官方terminal_view发布，也不代表已经选定UI框架。

2026-10-30：这是并行验证区，不是首版应用。Flutter 与 Tauri 都是候选，未根据原型或编译成功提前选型。

- [实际交付、CI链接、五端／三网矩阵与阻断](../docs/09-prototype-validation.md)
- [Penpot 可点击原型及覆盖](../design/README.md)
- [共享fixture、字体、SHA与设备测试步骤](shared/README.md)
- [Flutter + terminal_view](flutter/README.md)
- [Tauri + xterm.js + Rust](tauri/README.md)
- [三网络原生可行性探针](native/README.md)
- [隔离SSH协议探针](ssh/README.md)
- [一次性helper的临时fixture验证](helper/README.md)
- [配对 v2 与设备密钥契约、原生桥](pairing/README.md)
- [同目标真实 SSH 持续观察对照](remote-harness/README.md)

从doc13当前或doc09历史Actions run下载测试artifact，按随包manifest和SHA256SUMS核验源码、版本与内容。只在明确标注的平台运行；iOS simulator并非iPhone签名包。不要为本验证在本机安装完整SDK，也不要把真实密钥、组网身份或用户授权文件交给fixture壳。

比较时使用相同设备/OS、字体文件、80×24 fixture、视口与负载。先记录正确性，再记性能；CUA注入、模拟IME测试、原生启动、真实输入法与远端链路分开记录。每一项没有设备证据就填“未验证”，不把单端结果外推其他端。结果未知不重放，布局不隐式调整远端PTY。

当前用户可用环境为云端与本机 Mac；手机、Windows/Linux设备和iOS签名尚不可用，不把缺项视为已通过。Android两份真实测试APK和SHA在[下载入口](../docs/09-prototype-validation.md#8-已核验的-android-下载入口)，可留待有设备时验证。Tauri iOS为unsigned simulator包，Flutter iOS为unsigned device app，均不是可直接分发的签名IPA。
