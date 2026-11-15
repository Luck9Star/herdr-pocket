# Android 双网传输前置检查

`AndroidDualOverlayRelay` 在本次拥有的 Linux namespace 与宿主回环之间提供控制面、DERP、EasyTier 三条固定角色 TCP 通道。私有 0600 manifest 中记录 namespace、三个目标端口、对应 owner PID 和两个禁止转发的 SSH 端口；监听开始及每次连接前核验进程 UID、namespace 与精确的 loopback 监听。调用方以 `OwnedReverseMappings(relay)` 上下文为一次性 AVD 创建三条 `adb reverse --no-rebind`：设备侧端口保持 fixture 广告端口，宿主侧端口对应 relay。只删除本次确认创建且仍未被替换的映射；冲突或结果不确定时拒绝假报清理成功。

[API35 x86_64 模拟器测试 43727802535](https://github.com/Luck9Star/herdr-pocket/actions/runs/43727802535) / 工件 `14166423461` 的[原始脱敏结果](../../docs/evidence/dual-overlay-20261115/android-transport-43727802535.json)：三条设备 shell 合成回显通过，三条映射安装和精确删除均确认，relay、peer、临时目录、namespace 与独占模拟器均清理。工件外层 SHA256 `d9754da636b6a4f5a0f6b2ee34b804fcf4e00eccff7b0d86b638425ee93aa389`。

该检查未启动 Flutter/Tauri App，没有 SSH 端口、真实 Tailscale/EasyTier 控制面或 TLS，也不证明物理设备、应用信任链或双网会话。冲突、部分失败与归属不明情况由独立单元测试覆盖；实际双网验收须另验。
