# ADR-0001 · 单栈 Flutter，而不是双原生或纯 PWA

状态：已接受（2026-10-29）

## 背景

需求是「iOS 与 Android 同一套体验」+「App 内自带内网穿透」。既有实现里：Heeler 是 Swift（iOS only）、tuan3w 是 Flutter、benkraus 是 React Native、Collie/Ovis 是 PWA。

## 决策

用 Flutter 单栈，一套 UI + 一套协议层；原生代码只出现在 overlay 绑定（FFI）。

## 理由

1. `dartssh2` 4.x 已支持 `direct-streamlocal` → 不需要主机装 socat/python 就能直连 herdr socket，与 Heeler 同级。
2. `herdr terminal session observe` 提供 NDJSON 终端帧 → 协议层不需要逆向二进制协议，Flutter 侧工作量大幅下降。
3. xterm3 / terminal_view 在移动端够用（113 MiB/s 纯 ASCII），先不背上 libghostty 的跨端包袱。
4. 三个 overlay 库（Go / C++ / Rust）都能通过 FFI 接，Flutter 的 FFI + isolate 模型与"阻塞原生调用"天然合得来。

## 备选与为什么不选

- **React Native**：benkraus 已验证可行，但终端要两端各写原生模块，overlay 走 TurboModule，总工作量更高。
- **双原生 + 共享 Rust core**：质量天花板最高（iOS 用 libghostty），但两套 UI ≈ 双倍工期；留作终端体验不达标时的升级路径。
- **纯 PWA**：结构上做不到 in-app overlay，且实时终端要么轮询要么自造帧协议。

## 后果

- 终端性能上限低于 libghostty；若压测不过，需要把终端层替换为平台原生视图（局部返工，不影响协议层与 overlay 层）。
- 需要自己写三个 overlay 的 Dart FFI 绑定与 isolate 桥（Heeler 没有可直接复用的 Dart 产物）。
