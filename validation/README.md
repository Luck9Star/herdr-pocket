# herdr-pocket 验证入口

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

从doc09实际Actions run下载测试artifact，按随包manifest和SHA256SUMS核验源码、版本与内容。只在明确标注的平台运行；iOS simulator并非iPhone签名包。不要为本验证在本机安装完整SDK，也不要把真实密钥、组网身份或用户授权文件交给fixture壳。

比较时使用相同设备/OS、字体文件、80×24 fixture、视口与负载。先记录正确性，再记性能；CUA注入、模拟IME测试、原生启动、真实输入法与远端链路分开记录。每一项没有设备证据就填“未验证”，不把单端结果外推其他端。结果未知不重放，布局不隐式调整远端PTY。

当前用户可用环境为云端与本机 Mac；手机、Windows/Linux设备和iOS签名尚不可用，不把缺项视为已通过。Android两份真实测试APK和SHA在[下载入口](../docs/09-prototype-validation.md#8-已核验的-android-下载入口)，可留待有设备时验证。Tauri iOS为unsigned simulator包，Flutter iOS为unsigned device app，均不是可直接分发的签名IPA。
