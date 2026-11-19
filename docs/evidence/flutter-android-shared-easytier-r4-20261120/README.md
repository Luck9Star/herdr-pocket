# Flutter Android 共享 EasyTier 双主机 R4

R4 在 GitHub Actions 的 API 35 x86_64 模拟器上完成了 APK 构建、两个独立主机的配对和首帧观察。发布 `shared_a_released` 时，B 在原终端上显示了新增帧。服务器始终未确认 A 的 SSH 正常关闭，验收以 `shared_peer_close_unconfirmed` 结束。[R4 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44564557536/job/135702641587) · [Actions 工件 14552570649](https://github.com/Luck9Star/herdr-pocket/actions/runs/44564557536/artifacts/14552570649)

- UI/验收驱动 `0d22d9f8c9169b7bd4c117ef73dc86a0b0850235`，测试专用原生构建 `547106ea172dfd055c3bf9fdb2f4e2a27c9ff2f8`，宿主构建 `5404adfb3c86f5174edda38f1d0c63c8d81996c5`。
- A、B 分别只有一个获准的 SSH 会话。关闭 A 后，A 的 39 次采样均显示原会话仍活跃、关闭未知。B 的 40 次采样均显示原会话仍活跃。两侧都没有新增会话或输入字节。
- 每个 EasyTier 对端累计接收一个 overlay 流、拨接一个回环 SSH 连接。运行未进入 B 关闭及用户主动停止节点的检查点。清理阶段的计数和资源移除结果不能用于证明运行中 A、B 的正常关闭顺序。
- 判定失败时 Flutter 测试进程仍在运行，安装拷贝的哈希复验未执行。随后 Flutter 测试进程、两个 reverse 映射、转发基线、应用包和独占宿主资源均完成清理。源产物未上传原始日志。

仓库保留 [官方 ZIP 原字节](r4-actions-14552570649.zip) 和 [按检查点汇总的 JSON](summary.json)。ZIP 内仅含 `manifest.json`，外层 SHA-256 与 Actions 元数据匹配。[SHA256SUMS](SHA256SUMS)

```sh
shasum -a 256 -c SHA256SUMS
unzip -p r4-actions-14552570649.zip manifest.json
```
