# #39／#40 合入前普通 SSH 原生证据

2026-11-20 核验六次 Actions 运行。Tauri 使用 `ea5dd709806a2745e25792921d3b5da07dcdb6c0`，Flutter 使用 `8be0a23b514469cd33707c30ecf578a7524207b1`。每次的目标作业和报告均通过，SSH 对端均为独占回环夹具。 [#39](https://github.com/Luck9Star/herdr-pocket/pull/39) · [#40](https://github.com/Luck9Star/herdr-pocket/pull/40)

| 客户端与环境 | 实际运行范围 | 原作业与工件 |
| --- | --- | --- |
| Tauri · Linux GTK / Xvfb | 密码。首条 A 仅探测，末条 A 一次认证、一次 PTY 和一次 shell，9 字节输入、102 字节输出。1440 × 1200 原视口回显通过 OCR；主动断开为 `peer_eof`，清空凭据、返回首页，五项清理通过。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44600935553/job/135831834733) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44600935553/artifacts/14567539745) |
| Flutter · Linux debug GTK / Xvfb | 密码。明确核对 A 后才认证，末次认证、PTY 和 shell 各一次，9 字节输入、102 字节输出。1920 × 1080 X11 原屏的应用区通过 OCR；主动断开为 `peer_eof`，凭据清空、返回首页，四项清理通过。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44601674208/job/135834441543) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44601674208/artifacts/14569155442) |
| Tauri · Android API 35 x86_64 Google APIs 模拟器 | 密码、密码换钥和独立加密私钥。普通案确认键盘开合与看板、网络、设置往返；普通和换钥的 ADB 系统原图通过回显顺序门。换钥取消保留 A，之后再核对 B；独立加密私钥案通过回显、断开、返回首页和五项清理。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44600936462/job/135831836282) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44600936462/artifacts/14569371319) |
| Flutter · Android API 35 x86_64 Google APIs 模拟器 | 密码与密码换钥。八个导航检查点沿同一原会话，提交前输入为零。换钥 A→B→B→B，前三次零认证，末次认证、PTY 和 shell 各一次，9 字节输入、102 字节输出。普通与换钥图通过发布门；对端在驱动退出前已关闭。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44601672495/job/135834431911) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44601672495/artifacts/14570246209) |
| Tauri · iOS 26.2，iPhone 17 Pro Max 模拟器 | 密码与密码换钥。XCTest 从添加主机进入表单，普通案完成八步导航。换钥 A→B→B→B，前三次零认证；末次与普通案各 9 字节输入、102 字节输出。1320 × 2868 回显图通过 OCR；两案主动断开，模拟器、夹具与私有文件清理通过。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44600895267/job/135831679520) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44600895267/artifacts/14570171432) |
| Flutter · iOS 26.2，iPhone 11 模拟器 | 密码、密码换钥和独立加密私钥。普通案八个导航点均沿原会话且提交前零输入。换钥前三次零认证；私钥错误口令在本机被拒、零认证，双向模式切换清空凭据且保留信任。三个成功会话各收到 9 字节并输出 102 字节，终端图通过发布门，驱动退出前已关闭。 | [作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44601625331/job/135834259606) · [工件](https://github.com/Luck9Star/herdr-pocket/actions/runs/44601625331/artifacts/14569332961) |

Tauri 的 #39 合并提交是 `994e6e4`，其被合入的 `9632b5c` 在测试提交后追加文档证据。Flutter 的 #40 合并提交是 `550acb6`，第二父提交即测试提交。与归档时的主线 `63d1148` 对比，`validation/tauri` 与 Tauri 测试提交相同，`validation/flutter` 的差异仅为 #42 的 Linux 集成测试。相关驱动和工作流也有后续改动，六份结果绑定各自实际运行的源码。Linux 两案只记录当时的密码基线，同源密码、私钥及换钥六格见 #42。实体手机、物理 IME、跨网与加密私钥换钥的组合均需对应的独立验收。 [#42 同源六格](../linux-ordinary-ssh-auth-matrix-20261120/README.md)

## 核验与复跑

[索引](official-index.json)记录官方 ZIP 字节数、SHA-256、原报告 SHA-256／CRC-32 和脱敏固定字段。原件体积与 GitHub 元数据逐一吻合，所有 ZIP 成员均通过 CRC。归档保留索引和核验程序，原 ZIP 和原图通过上表工件链接获取。

将原工件保存成 `<run>-<artifact>.zip`。下载仍在保留期时，可从仓库根目录用已认证的 GitHub CLI 重取并核验。

```sh
index=docs/evidence/ordinary-ssh-native-39-40-20261120
archives=$(mktemp -d)
jq -r '.runs[] | [.run, .artifact] | @tsv' "$index/official-index.json" |
  while read -r run artifact; do
    gh api "repos/Luck9Star/herdr-pocket/actions/artifacts/$artifact/zip" > "$archives/$run-$artifact.zip" || exit 1
  done
python3 "$index/verify_artifacts.py" "$archives" --github
```

复跑验收时，以索引中的完整源码 SHA 和分支前缀为准。Linux 用 [Paired GUI](../../../.github/workflows/paired-gui-validation.yml) 的 `linux_direct_ssh=password` 或 `flutter-password`。Android 用 [Tauri](../../../.github/workflows/tauri-android-direct-ssh.yml) `scenario=default` 和 [Flutter](../../../.github/workflows/direct-ssh-android.yml) `auth_case=standard`。iOS 使用 [普通 SSH iOS 模拟器作业](../../../.github/workflows/direct-ssh-ios.yml)，Tauri 与 Flutter 分别使用索引记录的 `tauri-only`、`flutter-only-encrypted-key` 分支前缀。
