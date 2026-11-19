# Flutter 桌面分屏关闭焦点主机 R3

2026-11-19，Ubuntu 24.04 x86_64 在固定 1440 × 1000 Flutter Widget 视口内，使用同一受控回环 OpenSSH 端点下的两条真实 SSH 连接和两个命名 herdr 会话。两侧使用独立临时设备身份，匹配各自的稳定 terminal ID。签名器、目录和输入日志使用测试后端。

两次云运行的精确源码均为 `2cd636f40b07928d31b1f487c653dbd0dbe4f380`。归档基线 `f923cb10a25f90738f0e741cd9e2e27ecc3073ab` 的 Flutter 产品树同为 `15fe2c02ed0257f7cd0f659d78d051d6e3a8eb9a`，本用例的 Flutter 测试、回环驱动与对应 Python 验证测试一致。

| 模式 | 每侧连接数 | 帧 / 增量 A、B | 服务端输入 A、B | PTY 采样 A、B | 原件 |
| --- | --- | --- | --- | --- | --- |
| stock，原版 herdr 0.9.5 | 1、1 | 9/7、11/10 | 0、0 字节 | 385、381 次 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44517427428/job/135536975870) · [Actions 工件 14527150230](https://github.com/Luck9Star/herdr-pocket/actions/runs/44517427428/artifacts/14527150230) · [原 ZIP](stock-r3-actions-14527150230.zip) |
| guarded，隔离输入扩展 | 1、1 | 15/13、19/18 | 9、1 字节 | 686、676 次 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44518193618/job/135542178535) · [Actions 工件 14526921865](https://github.com/Luck9Star/herdr-pocket/actions/runs/44518193618/artifacts/14526921865) · [原 ZIP](guarded-r3-actions-14526921865.zip) |

两次均从正常首页配对并进入两侧观察，核对两份公钥由 sshd 独立认证、pane 和稳定 terminal 绑定、唯一输入焦点、换焦点后输入资格未自动恢复及迟到输入拒绝。PTY 每 50 ms 采样，四份记录均保持 119 × 40，观察到 0 次 resize。临时授权已经撤销，归本次运行所有的进程已停止，临时密钥已移除，未触及用户的授权文件。

## stock 关闭与两端确定状态

Widget 实际关闭当前焦点 A。独立对端读回 A 已关闭、B 尚未观察到关闭，随后 B 的同一 terminal 对象显示编号更高的新增量，连接代际及绑定保持原值，SSH 连接总数一直为 1。B 未自动获得输入资格。用户主动停止 B 后，驱动同时等待本地取消完成与对端确认，两侧在 Widget 驱动退出前都已关闭，退出后再次读回相同结果。

| 观察点 | A | B |
| --- | --- | --- |
| 关闭 A 后，取下一帧前 | 对端确认关闭 | 同一连接仍取得更新画面 |
| 主动停止 B 后，驱动退出前 | 对端确认关闭 | 对端确认关闭 |
| 驱动退出后 | 对端确认关闭 | 对端确认关闭 |

guarded 直接使用明确构建的隔离输入扩展，测试先向 B 发送一次按键、再在 A 确认一次草稿。两端收到的实际字节及目标均匹配。该分支在原视图分别主动停止两侧并等待适配器取消，关闭焦点 A 后 B 推进与独立对端关闭时间门由上面的 stock 运行覆盖。

## 历史收尾和本机复验

- R1 云端报告 A 关闭后 B 推进，但 B 最终关闭未在收尾窗口内得到确认，错误码为 `s06_stock_final_peer_close_unconfirmed`。原 ZIP SHA-256 为 `bd28c32af49c8e74a3fb2d0b3a309b4b4454f58654a367f6f6304a07df458839`。[R1 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44510307698/job/135512520224) · [R1 官方工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44510307698/artifacts/14523700539)
- R2 云端已确认两条对端关闭，原 ZIP SHA-256 为 `f2b980e6e125ec3678865fa00398c9837d8fb3e664b26962aac120099a4b0761`。以 R2 关闭顺序在本机加入阶段诊断时，B 的读侧等待在 `peer_eof` 超时，测试异步清理报告 `network_transport_failed`。把等待移入用例后明确捕获同一错误。[R2 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44514365750/job/135526414702) · [R2 官方工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44514365750/artifacts/14526045068)
- R3 修复先等待 SSH 通道的关闭交换，再半关闭写侧，读取持续到对端 EOF。同一取消尝试由重复调用共同等待。macOS 本机以 Widget、两个真实 stock herdr 会话和受控 OpenSSH 连续通过 5/5，每次均独立核对 A 关闭后 B 推进、两端在驱动退出前后关闭及 `[0,0]` 字节。本机源文件逐字节与 R3 相应提交核对。主代理另以归档基线共享适配器复跑 M3-05，除精确来源 SHA 外，脱敏字段与已归档结果逐项一致。M3-05 仅覆盖自身的 Widget 回环用例及合成 herdr RPC 和内存 journal。[本机 5 次复验摘要](local-stock-r3-summary.json) · [M3-05 同适配器原结果](m305-shared-adapter-f923cb1.json) · [M3-05 验收范围](../../24-target-input-recovery.md#m3-05-flutter-回环丢回执)

## 核对原件

两份 R3 ZIP 保留 Actions 原字节。外层 SHA-256 与 GitHub 元数据一致，内部 `SHA256SUMS` 中的 manifest、Flutter 锁文件、Rust 锁文件和远程契约均逐一匹配。归档无临时授权材料、密钥、输入原文或原始日志。尚未覆盖原生桌面窗口与窗口宽度往返、物理输入法、系统密钥库或真实网络提供方。[SHA256SUMS](SHA256SUMS) · [验收快照](../../74-desktop-split-resize.md#flutter-分屏关闭焦点主机)

```sh
shasum -a 256 -c SHA256SUMS
unzip -p stock-r3-actions-14527150230.zip manifest.json
unzip -p guarded-r3-actions-14526921865.zip manifest.json
```
