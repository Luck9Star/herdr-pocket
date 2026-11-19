# Flutter Android 双网身份入口复验

2026-11-20 在 API 35 x86_64 Android 模拟器上复验 Flutter 的 Tailscale（TS）与 EasyTier（ET）双网。两个顺序分别运行，每次从应用进入网络页、通过身份入口、显式完成 TS 授权并配对不同主机，再按指定顺序停网。两台受控对端提供实际 SSH 审计，使用隔离控制面和测试专用 `adb reverse`。

## 三轮设备结果

| 轮次和客户端源码 | 先停 ET | 先停 TS | 设备原件 |
| --- | --- | --- | --- |
| R2 `aed169c` | 通过，TS 原会话继续收到第二字节，最后两端关闭。 | 在 `ts_identity_open` 提前退出，`device_test_exited_early`。尚未到达身份加载检查点，两个对端均为 0 条批准会话、0 字节输入。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44579499859/job/135755986206) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44579499859/artifacts/14557999356) · [原 ZIP](r2-actions-14557999356.zip) |
| R3 `ce1c8b1` | 通过。 | 通过。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44585708517/job/135777927119) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44585708517/artifacts/14561826753) · [原 ZIP](r3-actions-14561826753.zip) |
| 默认分支基线复验 `ebc3c34` | 通过。 | 通过。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44589479663/job/135791272955) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44589479663/artifacts/14563338860) · [原 ZIP](main-r1-actions-14563338860.zip) |

完整客户端 SHA、工件字节数、ZIP 和内层 `manifest.json` 的 SHA-256 见[脱敏摘要](summary.json)。三轮固定原生库 `547106ea172dfd055c3bf9fdb2f4e2a27c9ff2f8` 和宿主构建 `5404adfb3c86f5174edda38f1d0c63c8d81996c5`。宿主 ZIP 为工件 `14171011473`，哈希见摘要。

## 客户端、SSH 和清理

成功方向的客户端报告均确认已审查的两个目标、双端更新和回显标记。幸存端恢复后在原终端收到新全量帧，被停端标签退役。应用完成初次输入、幸存端续输与最后一次停网。

| 停网顺序 | 第一次停用后 | 第二次停用后 |
| --- | --- | --- |
| ET → TS | ET 原会话关闭，保留精确 1 字节 `E`。TS 原会话仍活跃，精确收到 `Tt`。 | 双方原会话均关闭。 |
| TS → ET | TS 原会话关闭，保留精确 1 字节 `T`。ET 原会话仍活跃，精确收到 `Ee`。 | 双方原会话均关闭。 |

通过的方向各有 ET、TS 一条获批 SSH 会话，序号始终为 1，基线后各自的新增会话数为 0。字节由受控对端按预期逐阶段核对，脱敏报告保留精确匹配和值计数。每次方向的环境清理单独核验，包括 Flutter 测试进程退出、应用包移除、三条 reverse 映射移除、forward 恢复基线、转发器与控制器停止、宿主 namespace 和临时文件清理。R2 中提前退出的方向也通过了这些清理检查。

## 入口修正与本机回归

R2 遗留的脱敏记录只定位到 Tailscale 身份入口及测试提前退出，具体触发原因未知。R3 与 `ebc3c34` 的两份验收代码逐字节一致。复验提交从默认分支 `8a8311d` 基线出发，只更改 Flutter 验收驱动及回归测试。驱动在当前网络页找对应配置的可点标题，按需展开，再单击当前路由里已启用的身份按钮。身份创建仍由显式审查和单独确认触发。[修正提交](https://github.com/Luck9Star/herdr-pocket/commit/ebc3c346bbcd8aa09bed3e2f73f350cb6a45b072)

Flutter 3.47.9 本机分析通过，独立临时壳复跑 107 项网络定向测试，其中包含 3 项身份入口 Widget 用例。Python 驱动的 42 项测试也通过。覆盖 320 宽的窄屏首次入场、390 宽的配置已展开、身份按钮禁用且无触摸或写入，以及显式确认后才创建。Widget 使用受控身份存储和运行时夹具。

## 复核原件

原 ZIP 保持 Actions 字节，检验摘要与 GitHub 工件元数据一致，每个 ZIP 只包含一份脱敏 `manifest.json`。[ZIP 校验值](SHA256SUMS) · [固定验收工作流](../../../.github/workflows/flutter-android-dual-overlay.yml)

```sh
shasum -a 256 -c SHA256SUMS
for archive in *-actions-*.zip; do
  unzip -t "$archive"
  unzip -p "$archive" manifest.json | shasum -a 256
done
```

覆盖范围限 Flutter Android 模拟器、隔离 TS/ET、受控的实际 SSH 和测试输入。实体手机、真实跨网、用户生产网络、Tauri 此版本和其他 provider 组合均须单独验收。
