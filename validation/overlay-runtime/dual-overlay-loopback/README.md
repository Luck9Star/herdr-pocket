# 双网络 herdr 隔离验收

这是可选的 Linux 验收程序，不是产品新入口。`.github/workflows/dual-overlay-herdr-validation.yml` 为显式 opt-in 分支构建固定 EasyTier 和 Tailscale 候选，以及已核对来源的 herdr 受保护输入夹具；在仅启用 `lo` 的独立 network namespace 中运行。两套临时 OpenSSH 主机密钥、客户端密钥、独立 herdr socket 和 pane 全部由该次运行生成。

同一 `OverlayRuntime` 分别启动两个 provider profile。Tailscale 登录须先证明状态不返回 URL 且不能拨号，明确开始登录后由仅限私有 stdin 的临时控制面批准，再以产品 `OverlayDialer` 访问各自真实 peer。两侧先取得可输入的 full 帧与匹配输入回执，再从实际画面读取固定应答；分别新建两次会话，依次停止 EasyTier 或 Tailscale；被停一侧的旧输入必须被拒绝，另一侧仍须获得下一次输入回执和画面，两侧观察任务须可 join。两个 pane 独立记录实际输入，必须逐字节等于预期，任何多余/重放字节均失败。

在两侧可观察后，交叉 provider 目标和存活的系统 loopback SSH 地址必须被拒绝；这些不同地址的检查**不证明重叠虚拟地址**。本实验也不证明真实 tailnet/物理网络、移动设备、平台保险库或 GUI。manifest 只包含源码和程序哈希、固定错误类别、布尔值及资源计数，不含私钥、输入字节、授权 URL、SSH 日志或目标身份。失败也应保留失败结论；准备、namespace、两个 provider 和输入扩展缺一不可，不启用 synthetic fallback。

本机只读编译和独立夹具回归：

```sh
cargo +1.96.0 test --manifest-path validation/overlay-runtime/dual-overlay-loopback/Cargo.toml --features fixture --locked
python3 -m unittest discover -s validation/remote-harness -p test_dual_overlay_loopback.py -v
```

`fixture` 特性仅用于编译和单元测试；执行入口会拒绝它。真实实验须用 `real` 同时链接两份真实候选库，并由上面的工作流准备和清理隔离环境。没有 Linux namespace 的本机测试不应记录为双网通过。
