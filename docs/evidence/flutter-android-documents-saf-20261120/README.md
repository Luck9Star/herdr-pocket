# Flutter Android 配置迁移 · 系统文件选择器验收

2026-11-20，Flutter 的 R7 在 Android API 35 x86_64 模拟器通过字号偏好导出与审查导入。运行完成 19 个检查点，五次打开系统 DocumentsUI，并在用户确认后把字号从 13 恢复为 19。覆盖范围为 [M1-05](../../04-roadmap.md) 中的字号迁移。

## R7 验收

| 操作 | 验收结果 |
| --- | --- |
| 初始字号设为 19，打开选择器后取消 | 应用报告取消，无预览，宿主确认系统测试目录为空，应用目录文件字节不变。 |
| 保存加密档案，改为字号 13 | 宿主从系统选择器写入的文件读取 126 字节，并用独立 Python 解密器确认 v2 载荷只含字号 19，主机和网络列表均为空。宿主另读到应用目录字号为 13。 |
| 选择原档案并输入错误口令 | 应用明确拒绝且无预览。宿主确认目录文件字节仍与字号 13 的对照一致。 |
| 选择篡改档案 | 宿主核验设备文件恰有一字节改动、原档案未变，并用独立解密器确认篡改被拒。系统选择器选择篡改件后，应用同样拒绝且无预览，目录文件字节不变。 |
| 使用正确口令预览 | UI 确认档案字号 19、当前 13，偏好与审查选项均未勾选，应用按钮禁用。宿主确认此时目录文件字节不变。 |
| 勾选字号和审查，确认一次 | 宿主在当前目录仍等于对照时只放行一次应用动作。应用读回字号 19，宿主另读目录文件确认恢复且写入已发生。 |
| 清理 | 应用包、系统测试目录、临时 UI 层级和 Flutter 工具四项清理均确认。独占模拟器正常退出，ADB 中对应序列消失。 |

宿主的判定器读取真实设备文件，用 Python AES-GCM 解析导出档案，独立约束目录状态、检查点顺序和单次确认。应用的 UI 状态和宿主字节检查都必须通过。目录保持不变按各检查点的字节相等判定，工件无逐次文件 I/O 记录。官方 ZIP 保留脱敏的运行报告和文件摘要，原配置文件与口令仅在运行时使用。本次归档复核了官方 ZIP、报告及检查代码，本地单元测试使用独立合成档案。[宿主判定器](../../../validation/remote-harness/flutter_android_documents_oracle.py) · [系统选择器驱动](../../../validation/remote-harness/flutter_android_documents_device.py) · [Flutter UI 检查点](../../../validation/remote-harness/flutter_android_documents_device_test.dart)

R7 验证的是 Flutter 测试监听入口实际安装的 APK。宿主包与设备读取的 APK 均为 93,730,678 字节且摘要相同。预构建 APK 的独立摘要另记。环境固定为 Flutter 3.47.9、Android Emulator 37.2.13（build 16740729）、API 35 `google_apis` x86_64 rev 9。导出阶段观测到本应用键盘并用系统返回键收起，三次导入阶段均观测为已隐藏。[官方作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44663450045/job/136046961081) · [官方工件 14596982282](https://github.com/Luck9Star/herdr-pocket/actions/runs/44663450045/artifacts/14596982282) · [脱敏索引](official-index.json)

工件无设备截图。结果覆盖本机字号偏好、受管模拟器系统文件选择器与清理。实体设备、其他文件提供方、主机及网络秘密迁移、活动连接替换、跨网、读屏和物理 IME 仍需单独验收。

## 早期断点

| 轮次与源码 | 最后边界 | 官方来源 |
| --- | --- | --- |
| R4 `f91c31ee` | `app_ready` 的安装摘要校验报 `installed_hash_mismatch`，零选择器检查点通过。模拟器正常关停，应用及临时项的四类清理在该报告未确认。 | [作业 136022521406](https://github.com/Luck9Star/herdr-pocket/actions/runs/44656082590/job/136022521406) · [工件 14594355431](https://github.com/Luck9Star/herdr-pocket/actions/runs/44656082590/artifacts/14594355431) |
| R5 `a0bf5ce0` | 安装摘要已匹配。打开第三次选择器并返回应用，到 `hide_wrong` 时无法证实系统 IME 已显示，错口令拒绝还未完成。 | [作业 136030340149](https://github.com/Luck9Star/herdr-pocket/actions/runs/44658430687/job/136030340149) · [工件 14595450173](https://github.com/Luck9Star/herdr-pocket/actions/runs/44658430687/artifacts/14595450173) |
| R6 `02d0ae7f` | 已完成错口令拒绝。第四次选择器未确认损坏文件行，止于 `tampered_picker/open_file_row`。未得到应用的篡改拒绝结果。 | [作业 136041152625](https://github.com/Luck9Star/herdr-pocket/actions/runs/44661678588/job/136041152625) · [工件 14595888745](https://github.com/Luck9Star/herdr-pocket/actions/runs/44661678588/artifacts/14595888745) |

R7 允许在已核验的前台应用、焦点归属和键盘隐藏条件下继续；发布损坏件时回读设备文件，比较长度、唯一改动字节及原档案摘要，再通知系统扫描。R4–R6 各次作业仍保留失败结论。[R7 修复](https://github.com/Luck9Star/herdr-pocket/commit/a71571e605c6850e8b6da2ecc9299714a6eb9a08)

## 同里程碑的独立验证

Tauri Linux 的官方 GTK/Xvfb 新结果覆盖活动连接的正式文件导入。R4 `5a85d585` 与 #55 合入历史中的复验 `ab6ef070` 均通过。导入替换 A 后保留旧标签最后画面和禁用连接状态，B 在原 SSH 连接显示新帧。两条真实回环 SSH 均关闭，终端输入为零。两份 ZIP 的内层各 11 项哈希已核对。[R4 作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44649668455/job/136001096650) · [#55 集成复验作业](https://github.com/Luck9Star/herdr-pocket/actions/runs/44653580682/job/136014197833) · [GTK R4 归档与原图](../config-import-retained-tabs-20261120/README.md#tauri-linux-m1-05-官方云-r4run-44649668455正式通过)

## 校验与复跑

在本目录核对索引和原件。GitHub CLI 需有工件读取权限，原件下载受保留期限制。

```sh
set -eu
shasum -a 256 -c SHA256SUMS
zip=$(mktemp)
gh api repos/Luck9Star/herdr-pocket/actions/artifacts/14596982282/zip > "$zip"
unzip -t "$zip"
shasum -a 256 "$zip"
unzip -p "$zip" documents-public/flutter-documents-roundtrip.json | shasum -a 256
```

与 [索引](official-index.json)中的 ZIP 和报告摘要比较。历史 R7 源码为 `a71571e605c6850e8b6da2ecc9299714a6eb9a08`。云端复跑需要允许调度的现有 `codex/` 分支，先确认 `ref` 指向待验提交。

```sh
git ls-remote --exit-code origin "refs/heads/$ref"
gh workflow run direct-ssh-android.yml --ref "$ref" -f acceptance=documents-roundtrip
```

本地可从仓库根目录跑独立的档案与驱动守门测试。需先装 [Python 固定依赖](../../../validation/pairing/requirements.txt)。这两条命令使用合成档案和设备回执。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s validation/remote-harness -p 'test_flutter_android_documents*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s validation/remote-harness -p 'test_tauri_android_config_document.py' -v
```
