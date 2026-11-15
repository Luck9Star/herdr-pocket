# 双壳共享的 Linux 测试 fixture

[独立工作流](../../.github/workflows/android-dual-overlay-fixtures.yml)并行构建受保护输入 herdr 与固定源码的 EasyTier peer、Tailscale testcontrol/DERP fixture，再验证并组装供两个 Android QA 作业复用的单个工件。它只在显式 QA 分支或调用方工作流中运行；构建阶段不启动网络节点。最终目录恰好包含 `herdr`、`peer`、`ts-fixture` 三个 Linux x86_64 ELF 和 `manifest.json`，不包含临时私钥、身份状态、授权 URL、SSH 配置或运行日志。下载重放作业再从 GitHub 重新下载并检查。

调用工作流暴露 `hostSource`、`artifactId` 和 GitHub 外层 `artifactDigest`。跨工作流消费时应记录并固定这三者，按工件 ID 下载并核对外层 digest，再在独立 checkout **对应的 hostSource** 中运行：

```sh
python3 validation/remote-harness/dual_overlay_shared_bundle.py verify \
  --bundle "$downloaded_host_bundle" --source-sha "$host_source" --restore-executable
```

验证会核对 checkout HEAD、manifest 固定来源、相关材料和三个 ELF 的 SHA256、架构及精确文件集合；成功后才恢复执行位。Flutter/Tauri 的 `nativeSource`（例如当前网络修复 `93ca6cd`）与各自 `uiSource`、`runnerSource` 应分别记录；它们无需与 `hostSource` 字面相同，但必须各自有来源与兼容性证据。不要把该包的 hash 当作 GitHub 外层 artifact digest，或把同源当成同二进制。

本机快速检查 `python3 -m unittest discover -s validation/remote-harness -p test_dual_overlay_shared_bundle.py -v` 使用合成小 ELF 头，只验证来源与损坏反例。它不运行真实 fixture、Android App 或 overlay。正式设备流程仍须逐次创建和销毁自己的临时 SSH 身份、两个 herdr 目标、TS 控制面与网络节点；共享包不得包含这些运行资料。双方向 Linux 验收通过前，不应把该构建工件描述为产品接壳或设备通过。
